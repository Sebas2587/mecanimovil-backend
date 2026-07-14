"""
Scraper de listados externos (MercadoLibre + Chileautos).
Adaptado desde experiments/marketplace-patente-search/scrape_marketplaces.py
"""
from __future__ import annotations

import hashlib
import logging
import random
import re
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from django.utils import timezone

logger = logging.getLogger(__name__)

ML_LISTADO = 'https://listado.mercadolibre.cl'
ML_CATEGORY_AUTOS = 'MLC1744'  # Autos, Camionetas y 4x4 (Chile)
DEFAULT_CHILEAUTOS = 'https://www.chileautos.cl'

# Tokens de trim/equipamiento que no sirven para buscar en marketplaces.
_MODELO_STOP = {
    'new', 'nuevo', 'nueva', 'aut', 'at', 'mt', 'manual', 'automatico', 'automático',
    '4x4', '4x2', '2wd', 'awd', 'fwd', 'rwd', 'gt', 'lx', 'ex', 'gl', 'gls', 'ltd',
    'sport', 'premium', 'full', 'base', 'diesel', 'bencina', 'hibrido', 'híbrido',
}


def _modelo_search_parts(marca: str, modelo: str) -> tuple[str, list[str]]:
    """
    Convierte 'New 6 Gt 2.5 Aut' → query 'Mazda 6' + tokens ['6'].
    Evita filtrar 100% de avisos por trim GetAPI que no aparece en títulos ML.
    """
    parts = [p for p in re.split(r'[\s/\-_]+', (modelo or '').strip()) if p]
    tokens: list[str] = []
    for p in parts:
        pl = p.casefold()
        if pl in _MODELO_STOP:
            continue
        if re.fullmatch(r'\d+(\.\d+)?', pl) and '.' in pl:
            # cilindrada 2.5 / 2.2
            continue
        if len(pl) < 1:
            continue
        tokens.append(p)
    primary = tokens[0] if tokens else (parts[0] if parts else '')
    query = re.sub(r'\s+', ' ', f'{marca} {primary}').strip()
    return query, [t.casefold() for t in tokens[:4]]


def _title_matches_segment(titulo: str, marca: str, modelo_tokens: list[str]) -> bool:
    t = (titulo or '').casefold()
    if marca.casefold() not in t:
        return False
    meaningful = [tok for tok in modelo_tokens if len(tok) >= 2 or tok.isdigit()]
    if not meaningful:
        return True
    return any(tok in t for tok in meaningful)


@dataclass
class ListingScraped:
    fuente: str
    external_id: str
    url: str
    titulo_raw: str
    precio: int
    year: int | None = None
    kilometraje: int | None = None
    region: str = ''
    marca_texto: str = ''
    modelo_texto: str = ''


@dataclass
class ScrapeResult:
    marca: str
    modelo: str
    year_bucket: int | None
    listings: list[ListingScraped] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    blocked_reason: str = ''


def _slug_url(s: str) -> str:
    s = unicodedata.normalize('NFD', s.strip().lower())
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return s or 'x'


def _parse_price(text: str) -> int | None:
    if not text:
        return None
    digits = re.sub(r'[^\d]', '', text)
    if not digits:
        return None
    val = int(digits)
    return val if val > 100_000 else None


def _parse_year_from_title(title: str) -> int | None:
    m = re.search(r'\b(19|20)\d{2}\b', title or '')
    if m:
        y = int(m.group(0))
        if 1980 <= y <= timezone.now().year + 1:
            return y
    return None


def _parse_km_from_title(title: str) -> int | None:
    m = re.search(r'(\d{1,3}(?:\.\d{3})*)\s*km', (title or '').lower())
    if m:
        km = int(re.sub(r'[^\d]', '', m.group(1)))
        return km if 0 < km < 2_000_000 else None
    return None


def _external_id_from_url(url: str, titulo: str, fuente: str) -> str:
    if url:
        m = re.search(r'MLC-(\d+)', url)
        if m:
            return m.group(1)
        m = re.search(r'/(\d{6,})', url)
        if m:
            return m.group(1)
    digest = hashlib.sha1(f'{fuente}:{titulo}'.encode()).hexdigest()[:16]
    return digest


def _jitter_sleep(min_s: float = 2.0, max_s: float = 6.0) -> None:
    time.sleep(random.uniform(min_s, max_s))


def _listings_from_ml_api_results(
    results: list[dict],
    marca: str,
    modelo_tokens: list[str],
) -> list[ListingScraped]:
    listings: list[ListingScraped] = []
    seen: set[str] = set()
    for item in results:
        titulo = (item.get('title') or '').strip()
        if not titulo or not _title_matches_segment(titulo, marca, modelo_tokens):
            continue
        price = item.get('price')
        try:
            precio = int(round(float(price)))
        except (TypeError, ValueError):
            continue
        if precio < 100_000:
            continue
        eid = str(item.get('id') or '').replace('MLC', '').lstrip('-') or _external_id_from_url(
            item.get('permalink') or '', titulo, 'mercadolibre'
        )
        if eid in seen:
            continue
        seen.add(eid)
        attrs = {a.get('id'): a.get('value_name') for a in (item.get('attributes') or []) if a.get('id')}
        year = None
        km = None
        try:
            if attrs.get('VEHICLE_YEAR'):
                year = int(re.sub(r'[^\d]', '', str(attrs['VEHICLE_YEAR'])) or 0) or None
        except ValueError:
            year = _parse_year_from_title(titulo)
        try:
            if attrs.get('KILOMETERS'):
                km = int(re.sub(r'[^\d]', '', str(attrs['KILOMETERS'])) or 0) or None
        except ValueError:
            km = _parse_km_from_title(titulo)
        listings.append(
            ListingScraped(
                fuente='mercadolibre',
                external_id=eid,
                url=(item.get('permalink') or '')[:512],
                titulo_raw=titulo,
                precio=precio,
                year=year or _parse_year_from_title(titulo),
                kilometraje=km or _parse_km_from_title(titulo),
                marca_texto=marca,
                modelo_texto=' '.join(modelo_tokens) if modelo_tokens else '',
            )
        )
    return listings


def _ml_access_token() -> str:
    try:
        from mecanimovilapp.apps.valoracion_mercado.services.ml_auth import (
            get_mercadolibre_access_token,
        )

        return get_mercadolibre_access_token()
    except Exception:
        import os

        return (os.environ.get('MERCADOLIBRE_ACCESS_TOKEN') or '').strip()


def _is_ml_security_challenge(title: str = '', body: str = '') -> bool:
    blob = f'{title} {body[:800]}'.casefold()
    return any(
        s in blob
        for s in (
            'seguridad — mercado libre',
            'seguridad - mercado libre',
            'security — mercado libre',
            'are you a human',
            'captcha',
            'unusual traffic',
            'access denied',
        )
    )


def scrape_mercadolibre_api(marca: str, modelo: str, limit: int = 50) -> tuple[list[ListingScraped], str]:
    """
    API ML. Retorna (listings, blocked_reason).

    Confirmado (jul-2026): desde abril 2025 ML deprecó la búsqueda general
    `/sites/{site}/search?q=...` para apps de terceros — devuelve 403
    'forbidden' incluso con un access_token OAuth válido y recién emitido
    por el propio dueño de la app (no es un tema de scope/expiración).
    Según su documentación oficial, ese endpoint no tiene reemplazo; solo
    sigue vivo `/users/{user_id}/items/search` para listados de un
    vendedor puntual que ya autorizó tu app — inútil para comparables de
    mercado. Se detecta ese 403-con-token para no reintentar en vano.
    """
    import requests

    query, modelo_tokens = _modelo_search_parts(marca, modelo)
    listings: list[ListingScraped] = []
    url = 'https://api.mercadolibre.com/sites/MLC/search'
    params = {
        'q': query,
        'category': ML_CATEGORY_AUTOS,
        'limit': min(limit, 50),
    }
    headers = {
        'Accept': 'application/json',
        'User-Agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ),
    }
    token = _ml_access_token()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        resp = requests.get(url, params=params, timeout=25, headers=headers)
        if resp.status_code == 403:
            if token:
                logger.warning(
                    'MercadoLibre API 403 con token OAuth válido: búsqueda '
                    'general deprecada por ML (abril 2025), sin reemplazo'
                )
                return listings, 'mercadolibre_search_discontinued'
            logger.info('MercadoLibre API 403 sin token OAuth')
            return listings, 'mercadolibre_no_oauth'
        resp.raise_for_status()
        results = resp.json().get('results') or []
    except Exception as exc:
        logger.warning('MercadoLibre API falló: %s', exc)
        return listings, ''

    listings = _listings_from_ml_api_results(results, marca, modelo_tokens)
    logger.info('MercadoLibre API: %s avisos para query=%r (auth=%s)', len(listings), query, bool(token))
    return listings, ''


def _scrape_ml_via_browser_api(page, query: str, marca: str, modelo_tokens: list[str]) -> list[ListingScraped]:
    """
    Llama a la API de ML desde el contexto del browser (cookies/UA reales).
    Desde datacenter suele seguir en 403; con Bearer token suele funcionar.
    """
    q = urllib.parse.quote(query)
    cat = ML_CATEGORY_AUTOS
    token = _ml_access_token()
    auth_js = f", 'Authorization': 'Bearer {token}'" if token else ''
    js = f"""
    async () => {{
      try {{
        const r = await fetch(
          'https://api.mercadolibre.com/sites/MLC/search?q={q}&category={cat}&limit=50',
          {{ headers: {{ 'Accept': 'application/json'{auth_js} }} }}
        );
        if (!r.ok) return {{ ok: false, status: r.status, results: [] }};
        const data = await r.json();
        return {{ ok: true, status: r.status, results: data.results || [] }};
      }} catch (e) {{
        return {{ ok: false, status: 0, results: [], error: String(e) }};
      }}
    }}
    """
    try:
        payload = page.evaluate(js)
    except Exception as exc:
        logger.warning('ML browser API evaluate falló: %s', exc)
        return []
    if not payload or not payload.get('ok'):
        logger.info(
            'ML browser API no OK status=%s error=%s',
            (payload or {}).get('status'),
            (payload or {}).get('error'),
        )
        return []
    results = payload.get('results') or []
    listings = _listings_from_ml_api_results(results, marca, modelo_tokens)
    logger.info('MercadoLibre browser-API: %s avisos para query=%r', len(listings), query)
    return listings


def _titulos_ml_playwright(page) -> list[tuple[str, str, str]]:
    """Retorna lista de (titulo, url, precio_text)."""
    from playwright.sync_api import TimeoutError as PWTimeout

    selectors = [
        'a.poly-component__title',
        '.poly-card a.poly-component__title',
        '.ui-search-item__title a',
        '.ui-search-item__group__element h3 a',
        "[data-testid='search-result'] a",
        'li.ui-search-layout__item a h2',
        'h2.ui-search-item__title',
    ]
    rows: list[tuple[str, str, str]] = []
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=4_000)
        except PWTimeout:
            continue
        for loc in page.locator(sel).all()[:40]:
            try:
                t = loc.inner_text().strip()
                href = loc.get_attribute('href') or ''
            except Exception:
                continue
            if t and len(t) > 5:
                rows.append((t, href, ''))
        if rows:
            break

    price_sel = '.andes-money-amount__fraction, .poly-price__current .andes-money-amount__fraction'
    prices = page.locator(price_sel).all()[:40]
    out: list[tuple[str, str, str]] = []
    for i, (t, href, _) in enumerate(rows):
        ptxt = ''
        if i < len(prices):
            try:
                ptxt = prices[i].inner_text().strip()
            except Exception:
                pass
        out.append((t, href, ptxt))
    return out


def scrape_mercadolibre(
    marca: str, modelo: str, headless: bool = True
) -> tuple[list[ListingScraped], str]:
    """
    Retorna (listings, blocked_reason).

    Confirmado (jul-2026) con un access_token OAuth recién autorizado por
    el dueño de la app: `/sites/MLC/search` devuelve 403 igual, porque ML
    deprecó la búsqueda general para terceros en abril 2025 y no tiene
    reemplazo. Ni el OAuth ni el HTML anónimo (muro "Seguridad") sirven —
    no tiene sentido lanzar Chromium en ninguno de esos casos: fallaría
    igual y solo consume tiempo del worker.
    """
    query, modelo_tokens = _modelo_search_parts(marca, modelo)
    api_listings, api_blocked = scrape_mercadolibre_api(marca, modelo)
    if api_listings:
        return api_listings, ''
    if api_blocked == 'mercadolibre_search_discontinued':
        return [], api_blocked

    if not _ml_access_token():
        return [], 'mercadolibre_no_oauth'

    # Con token pero la API falló (red/rate-limit): último intento vía browser,
    # reusando la sesión del token en el fetch (no HTML anónimo, que sigue muerto).
    listings: list[ListingScraped] = []
    rows: list[tuple[str, str, str]] = []
    used_url = ''
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning('playwright no instalado; omitiendo MercadoLibre HTML')
        return listings, ''

    slug = _slug_url(query)
    urls = [
        f'{ML_LISTADO}/{slug}_CategoryID_{ML_CATEGORY_AUTOS}',
    ]

    try:
        with sync_playwright() as p:
            launch_kwargs: dict[str, Any] = {
                'headless': headless,
                'args': ['--disable-blink-features=AutomationControlled', '--no-sandbox'],
            }
            proxy = _playwright_proxy()
            if proxy:
                launch_kwargs['proxy'] = {'server': proxy}

            browser = p.chromium.launch(**launch_kwargs)
            ctx = browser.new_context(
                locale='es-CL',
                user_agent=(
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                ),
                viewport={'width': 1366, 'height': 900},
            )
            page = ctx.new_page()
            page.set_default_timeout(12_000)

            browser_api = _scrape_ml_via_browser_api(page, query, marca, modelo_tokens)
            if browser_api:
                browser.close()
                return browser_api, ''

            for url in urls:
                used_url = url
                try:
                    page.goto(url, wait_until='domcontentloaded', timeout=15_000)
                except Exception as exc:
                    logger.info('ML goto falló %s: %s', url, exc)
                    continue
                page.wait_for_timeout(800)
                title = ''
                body_snip = ''
                try:
                    title = page.title()
                except Exception:
                    pass
                try:
                    body_snip = page.inner_text('body', timeout=2500)[:500]
                except Exception:
                    pass
                if _is_ml_security_challenge(title=title, body=body_snip):
                    logger.warning(
                        'ML anti-bot (Seguridad) url=%s title=%r — abortando HTML',
                        url,
                        title[:80],
                    )
                    browser.close()
                    return [], 'mercadolibre_antibot'
                rows = _titulos_ml_playwright(page)
                logger.info(
                    'ML HTML url=%s title=%r rows=%s',
                    url,
                    title[:80],
                    len(rows),
                )
                if rows:
                    break
            browser.close()
    except Exception as exc:
        logger.warning('MercadoLibre scrape falló: %s', exc)
        return listings, ''

    seen: set[str] = set()
    matched = 0
    for titulo, href, ptxt in rows:
        if not _title_matches_segment(titulo, marca, modelo_tokens):
            continue
        matched += 1
        precio = _parse_price(ptxt) or _parse_price(titulo)
        if not precio:
            continue
        eid = _external_id_from_url(href, titulo, 'mercadolibre')
        if eid in seen:
            continue
        seen.add(eid)
        listings.append(
            ListingScraped(
                fuente='mercadolibre',
                external_id=eid,
                url=href or used_url,
                titulo_raw=titulo,
                precio=precio,
                year=_parse_year_from_title(titulo),
                kilometraje=_parse_km_from_title(titulo),
                marca_texto=marca,
                modelo_texto=' '.join(modelo_tokens) if modelo_tokens else modelo,
            )
        )

    if not listings and rows:
        for titulo, href, ptxt in rows:
            if marca.casefold() not in titulo.casefold():
                continue
            precio = _parse_price(ptxt) or _parse_price(titulo)
            if not precio:
                continue
            eid = _external_id_from_url(href, titulo, 'mercadolibre')
            if eid in seen:
                continue
            seen.add(eid)
            listings.append(
                ListingScraped(
                    fuente='mercadolibre',
                    external_id=eid,
                    url=href or used_url,
                    titulo_raw=titulo,
                    precio=precio,
                    year=_parse_year_from_title(titulo),
                    kilometraje=_parse_km_from_title(titulo),
                    marca_texto=marca,
                    modelo_texto=modelo,
                )
            )
        logger.info(
            'ML soft-fallback: rows=%s matched_tokens=%s kept=%s query=%r',
            len(rows),
            matched,
            len(listings),
            query,
        )
    else:
        logger.info(
            'ML HTML final: rows=%s matched=%s listings=%s query=%r',
            len(rows),
            matched,
            len(listings),
            query,
        )
    return listings, ''


def _playwright_proxy() -> str:
    import os

    try:
        from django.conf import settings

        proxy = getattr(settings, 'PLAYWRIGHT_PROXY', '') or ''
        if proxy:
            return proxy.strip()
    except Exception:
        pass
    return (os.environ.get('PLAYWRIGHT_PROXY') or '').strip()


def scrape_chileautos(
    marca: str, modelo: str, headless: bool = True
) -> tuple[list[ListingScraped], str]:
    """Retorna (listings, blocked_reason)."""
    query, modelo_tokens = _modelo_search_parts(marca, modelo)
    base = DEFAULT_CHILEAUTOS.rstrip('/')
    slug_combo = _slug_url(query)
    q_enc = urllib.parse.quote(query)
    listings: list[ListingScraped] = []

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning('playwright no instalado; omitiendo Chileautos')
        return listings, ''

    urls = [
        f'{base}/vehiculos/buscar/?Keywords={q_enc}',
        f'{base}/vehiculos/autos-veh%C3%ADculo/{slug_combo}/',
    ]

    try:
        with sync_playwright() as p:
            launch_kwargs: dict[str, Any] = {
                'headless': headless,
                'args': ['--disable-blink-features=AutomationControlled', '--no-sandbox'],
            }
            proxy = _playwright_proxy()
            if proxy:
                launch_kwargs['proxy'] = {'server': proxy}

            browser = p.chromium.launch(**launch_kwargs)
            ctx = browser.new_context(
                locale='es-CL',
                user_agent=(
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                ),
                viewport={'width': 1366, 'height': 900},
            )
            page = ctx.new_page()
            page.set_default_timeout(18_000)
            titles: list[tuple[str, str]] = []
            for u in urls[:1]:
                try:
                    page.goto(u, wait_until='domcontentloaded', timeout=22_000)
                except Exception:
                    continue
                page.wait_for_timeout(1500)
                title = ''
                body_snip = ''
                try:
                    title = page.title()
                except Exception:
                    pass
                try:
                    body_snip = page.inner_text('body', timeout=2500)[:600]
                except Exception:
                    pass
                blob = f'{title} {body_snip}'.casefold()
                if any(
                    s in blob
                    for s in (
                        'datadome',
                        'captcha',
                        'access denied',
                        'please verify',
                        'are you a human',
                        'denied request',
                        'geo.captcha',
                    )
                ):
                    logger.warning('Chileautos anti-bot title=%r — abortando', title[:80])
                    browser.close()
                    return [], 'chileautos_antibot'
                for sel in (
                    'article h2 a',
                    'article h2',
                    "main a[href*='/vehiculos/']",
                    "[class*='listing'] a",
                    "[class*='Listing'] a",
                ):
                    loc = page.locator(sel)
                    try:
                        n = min(loc.count(), 40)
                    except Exception:
                        continue
                    for i in range(n):
                        try:
                            t = loc.nth(i).inner_text(timeout=1500).strip()
                            href = ''
                            if 'a' in sel:
                                href = loc.nth(i).get_attribute('href') or ''
                        except Exception:
                            continue
                        if len(t) > 10:
                            titles.append((t, href))
                    if titles:
                        break
                if titles:
                    break
            logger.info('Chileautos titles=%s query=%r', len(titles), query)
            browser.close()
    except Exception as exc:
        logger.warning('Chileautos scrape falló: %s', exc)
        return listings, ''

    if not titles:
        return [], 'chileautos_empty'

    seen: set[str] = set()
    for titulo, href in titles:
        if not _title_matches_segment(titulo, marca, modelo_tokens):
            if marca.casefold() not in titulo.casefold():
                continue
        precio = _parse_price(titulo)
        if not precio:
            continue
        eid = _external_id_from_url(href, titulo, 'chileautos')
        if eid in seen:
            continue
        seen.add(eid)
        listings.append(
            ListingScraped(
                fuente='chileautos',
                external_id=eid,
                url=href or urls[0],
                titulo_raw=titulo,
                precio=precio,
                year=_parse_year_from_title(titulo),
                kilometraje=_parse_km_from_title(titulo),
                marca_texto=marca,
                modelo_texto=' '.join(modelo_tokens) if modelo_tokens else modelo,
            )
        )
    logger.info('Chileautos listings=%s query=%r', len(listings), query)
    return listings, ''


def scrape_segmento(
    marca: str,
    modelo: str,
    year_bucket: int | None = None,
    on_progress=None,
) -> ScrapeResult:
    """
    Scrapea solo MercadoLibre (vía API OAuth).

    Chileautos queda deshabilitado por decisión de producto: su API oficial
    (Global Inventory Integration) es solo para publicar/leer el inventario
    propio de una automotora, no para buscar avisos de terceros, y su HTML
    público está protegido por DataDome. `scrape_chileautos` se deja
    implementada en este módulo por si se retoma más adelante (proxy
    anti-bot pagado o acceso especial de soporte@chileautos.cl).
    """
    result = ScrapeResult(marca=marca, modelo=modelo, year_bucket=year_bucket)
    headless = True

    def _progress(pct: int, message: str) -> None:
        if callable(on_progress):
            try:
                on_progress(pct, message)
            except Exception:
                pass

    try:
        _progress(20, 'Consultando MercadoLibre…')
        ml, blocked = scrape_mercadolibre(marca, modelo, headless=headless)
        result.listings = list(ml)
        if blocked:
            result.blocked_reason = blocked
            result.errors.append(blocked)
            logger.warning('scrape_segmento ML bloqueado: %s', blocked)
        logger.info(
            'scrape_segmento %s %s → ml=%s total=%s blocked=%s',
            marca,
            modelo,
            len(ml),
            len(result.listings),
            result.blocked_reason or '-',
        )
    except Exception as exc:
        result.errors.append(str(exc))
        logger.exception('scrape_segmento error')
    if year_bucket:
        y_min, y_max = year_bucket - 1, year_bucket + 1
        filtered = [
            l for l in result.listings
            if l.year is None or (y_min <= l.year <= y_max)
        ]
        if filtered:
            result.listings = filtered
    return result


def upsert_listings(
    listings: list[ListingScraped],
    marca_obj,
    modelo_obj,
    year_bucket: int | None,
) -> set[tuple[str, str]]:
    """
    Upsert avisos y retorna set de (fuente, external_id) vistos en esta corrida.
    """
    from mecanimovilapp.apps.valoracion_mercado.models import AvisoExternoVehiculo

    seen: set[tuple[str, str]] = set()
    now = timezone.now()
    for item in listings:
        key = (item.fuente, item.external_id)
        seen.add(key)
        defaults = {
            'url': item.url[:512],
            'marca_texto': item.marca_texto,
            'modelo_texto': item.modelo_texto,
            'marca': marca_obj,
            'modelo': modelo_obj,
            'year': item.year or year_bucket,
            'kilometraje': item.kilometraje,
            'precio': item.precio,
            'region': item.region,
            'titulo_raw': item.titulo_raw[:2000],
            'activo': True,
            'fecha_removido': None,
            'fecha_ultima_vista': now,
        }
        obj, created = AvisoExternoVehiculo.objects.update_or_create(
            fuente=item.fuente,
            external_id=item.external_id,
            defaults=defaults,
        )
        if created:
            obj.fecha_primera_vista = now
            obj.save(update_fields=['fecha_primera_vista'])
    return seen


def mark_removed_for_segment(marca_obj, modelo_obj, year_min: int, year_max: int, seen_keys: set) -> int:
    """Marca como inactivos los avisos del segmento no vistos en la corrida."""
    from mecanimovilapp.apps.valoracion_mercado.models import AvisoExternoVehiculo

    qs = AvisoExternoVehiculo.objects.filter(
        marca=marca_obj,
        modelo=modelo_obj,
        activo=True,
        year__gte=year_min,
        year__lte=year_max,
    )
    removed = 0
    now = timezone.now()
    for aviso in qs.only('id', 'fuente', 'external_id'):
        if (aviso.fuente, aviso.external_id) not in seen_keys:
            aviso.activo = False
            aviso.fecha_removido = now
            aviso.save(update_fields=['activo', 'fecha_removido', 'fecha_ultima_vista'])
            removed += 1
    return removed
