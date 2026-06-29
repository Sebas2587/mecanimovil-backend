"""Descarga de media Meta → R2 y helpers de tipo MIME."""
import logging
import mimetypes
import os
import re
from typing import Any

import requests
from django.core.files.base import ContentFile
from django.utils import timezone

from mecanimovilapp.apps.omnichannel.services.meta_graph import MetaGraphClient

logger = logging.getLogger(__name__)

MAX_MEDIA_BYTES = 20 * 1024 * 1024

MEDIA_LABELS = {
    'image': 'Imagen',
    'video': 'Video',
    'audio': 'Audio',
    'document': 'Documento',
    'file': 'Archivo',
    'sticker': 'Sticker',
}

_EXT_BY_KIND = {
    'image': '.jpg',
    'video': '.mp4',
    'audio': '.m4a',
    'document': '.bin',
}


def media_label(kind: str | None) -> str:
    return MEDIA_LABELS.get(kind or '', 'Adjunto')


def infer_media_kind(mime_type: str | None, filename: str | None = None) -> str:
    mime = (mime_type or '').lower()
    name = (filename or '').lower()
    if mime.startswith('image/') or re.search(r'\.(jpe?g|png|gif|webp|heic)$', name):
        return 'image'
    if mime.startswith('video/') or re.search(r'\.(mp4|mov|webm|3gp)$', name):
        return 'video'
    if mime.startswith('audio/') or re.search(r'\.(mp3|m4a|ogg|wav|aac)$', name):
        return 'audio'
    return 'document'


def _safe_filename(kind: str, mime_type: str | None, hint: str | None = None) -> str:
    if hint and '.' in hint:
        base = re.sub(r'[^\w.\-]', '_', os.path.basename(hint))
        if base:
            return base
    ext = mimetypes.guess_extension(mime_type or '') or _EXT_BY_KIND.get(kind, '.bin')
    stamp = timezone.now().strftime('%Y%m%d%H%M%S')
    return f'omnichannel_{kind}_{stamp}{ext}'


def _read_limited_response(resp: requests.Response, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f'Media exceeds limit ({max_bytes} bytes)')
        chunks.append(chunk)
    return b''.join(chunks)


def download_bytes(url: str, token: str | None = None, max_bytes: int = MAX_MEDIA_BYTES) -> bytes:
    download_url = url
    if token and 'access_token=' not in url:
        sep = '&' if '?' in url else '?'
        download_url = f'{url}{sep}access_token={token}'
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    resp = requests.get(download_url, headers=headers, stream=True, timeout=90)
    if resp.status_code >= 400:
        raise RuntimeError(f'Media download failed: {resp.status_code} {resp.text[:200]}')
    return _read_limited_response(resp, max_bytes)


def fetch_whatsapp_media_bytes(media_id: str, token: str) -> tuple[bytes, str, str]:
    client = MetaGraphClient(token)
    meta_resp = requests.get(
        client._url(media_id),
        params={'access_token': token},
        timeout=30,
    )
    if meta_resp.status_code >= 400:
        raise RuntimeError(f'WhatsApp media meta failed: {meta_resp.text[:200]}')
    meta = meta_resp.json()
    media_url = meta.get('url')
    if not media_url:
        raise RuntimeError('WhatsApp media meta missing url')
    mime_type = meta.get('mime_type') or ''
    content = download_bytes(media_url, token=token)
    kind = infer_media_kind(mime_type)
    filename = _safe_filename(kind, mime_type)
    return content, filename, kind


def fetch_url_media_bytes(
    url: str,
    token: str | None,
    kind_hint: str | None = None,
) -> tuple[bytes, str, str]:
    content = download_bytes(url, token=token)
    kind = kind_hint or 'document'
    mime_type = mimetypes.guess_type(url)[0]
    kind = infer_media_kind(mime_type, url) if mime_type else kind
    filename = _safe_filename(kind, mime_type, hint=url)
    return content, filename, kind


def save_message_attachment(message, content: bytes, filename: str) -> None:
    message.attachment.save(filename, ContentFile(content), save=True)


def parse_whatsapp_media(msg: dict[str, Any]) -> dict[str, Any] | None:
    msg_type = msg.get('type') or ''
    if msg_type in ('text', 'button', 'interactive', 'reaction', 'unknown'):
        return None
    body = msg.get(msg_type) if isinstance(msg.get(msg_type), dict) else {}
    if not body:
        return None
    media_id = body.get('id')
    if not media_id:
        return None
    return {
        'kind': msg_type,
        'media_id': media_id,
        'mime_type': body.get('mime_type'),
        'caption': body.get('caption') or '',
    }


def parse_messenger_attachments(msg: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for att in msg.get('attachments') or []:
        if not isinstance(att, dict):
            continue
        payload = att.get('payload') or {}
        url = payload.get('url')
        if not url:
            continue
        items.append({
            'kind': att.get('type') or 'file',
            'url': url,
        })
    return items
