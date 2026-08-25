"""Preview Open Graph de enlaces enviados en el chat.

El cliente no puede leer og:* por CORS; este endpoint los resuelve con SSRF básico.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

MAX_BYTES = 180_000
TIMEOUT = 3.5
MAX_REDIRECTS = 4
CACHE_TTL = 60 * 60 * 24
USER_AGENT = (
    'Mozilla/5.0 (compatible; MecanimovilPreview/1.0; +https://mecanimovil.cl)'
)

_BLOCKED_HOSTS = {
    'localhost',
    'localhost.localdomain',
    'metadata.google.internal',
}


class _OgParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: dict[str, str] = {}
        self.title = ''
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {k.lower(): (v or '') for k, v in attrs}
        if tag.lower() == 'meta':
            prop = (ad.get('property') or ad.get('name') or '').strip().lower()
            content = (ad.get('content') or '').strip()
            if prop in {
                'og:title',
                'og:description',
                'og:image',
                'og:site_name',
                'twitter:title',
                'twitter:description',
                'twitter:image',
            } and content and prop not in self.tags:
                self.tags[prop] = content[:500]
        if tag.lower() == 'title':
            self._in_title = True

    def handle_data(self, data: str) -> None:
        if self._in_title and len(self.title) < 300:
            self.title += data

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == 'title':
            self._in_title = False


def _ip_is_public(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _host_is_safe(hostname: str, resolve_dns: bool = True) -> bool:
    host = (hostname or '').strip().lower().rstrip('.')
    if not host or host in _BLOCKED_HOSTS:
        return False
    if host.endswith('.local') or host.endswith('.internal'):
        return False
    try:
        addr = ipaddress.ip_address(host)
        return _ip_is_public(addr)
    except ValueError:
        pass
    if not resolve_dns:
        return '.' in host
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if not _ip_is_public(addr):
            return False
    return True


def validate_preview_url(raw: str, resolve_dns: bool = True) -> str | None:
    candidate = (raw or '').strip()
    if not candidate or len(candidate) > 2000:
        return None
    parsed = urlparse(candidate)
    if parsed.scheme not in ('http', 'https'):
        return None
    if parsed.username or parsed.password:
        return None
    if not parsed.hostname or not _host_is_safe(parsed.hostname, resolve_dns=resolve_dns):
        return None
    return candidate


def _parse_html(html: str, base_url: str) -> dict:
    parser = _OgParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass
    title = (
        parser.tags.get('og:title')
        or parser.tags.get('twitter:title')
        or parser.title.strip()
        or ''
    )
    description = (
        parser.tags.get('og:description')
        or parser.tags.get('twitter:description')
        or ''
    )
    image = parser.tags.get('og:image') or parser.tags.get('twitter:image') or ''
    if image:
        image = urljoin(base_url, image)
        if not validate_preview_url(image, resolve_dns=False):
            image = ''
    site = parser.tags.get('og:site_name') or ''
    return {
        'title': title[:180],
        'description': description[:240],
        'image': image[:500],
        'site_name': site[:80],
    }


def fetch_link_preview(url: str) -> dict:
    safe = validate_preview_url(url)
    if not safe:
        raise ValueError('url_invalida')
    cache_key = 'chat_og:' + hashlib.sha256(safe.encode('utf-8')).hexdigest()[:40]
    cached = cache.get(cache_key)
    if cached:
        return cached

    current = safe
    html = ''
    final_url = safe
    session = requests.Session()
    session.headers.update({
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8',
    })
    try:
        for _ in range(MAX_REDIRECTS + 1):
            checked = validate_preview_url(current)
            if not checked:
                raise ValueError('url_invalida')
            resp = session.get(
                checked,
                timeout=TIMEOUT,
                allow_redirects=False,
                stream=True,
            )
            if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
                nxt = resp.headers.get('Location')
                resp.close()
                if not nxt:
                    break
                current = urljoin(checked, nxt)
                continue
            ctype = (resp.headers.get('Content-Type') or '').lower()
            if 'text/html' not in ctype and 'application/xhtml' not in ctype:
                resp.close()
                break
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_content(8192):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_BYTES:
                    chunks.append(chunk[: max(0, MAX_BYTES - (total - len(chunk)))])
                    break
                chunks.append(chunk)
            resp.close()
            html = b''.join(chunks).decode('utf-8', errors='ignore')
            final_url = str(resp.url or checked)
            break
    except requests.RequestException:
        logger.info('link_preview fetch failed url=%s', safe[:120])
        html = ''

    parsed = _parse_html(html, final_url) if html else {
        'title': '',
        'description': '',
        'image': '',
        'site_name': '',
    }
    payload = {
        'url': safe,
        'final_url': final_url,
        **parsed,
    }
    cache.set(cache_key, payload, CACHE_TTL)
    return payload
