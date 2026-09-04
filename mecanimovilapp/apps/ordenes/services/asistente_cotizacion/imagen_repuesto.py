"""Hidrata imagen de ficha de producto vía OpenGraph y la re-hospeda en R2."""
from __future__ import annotations

import hashlib
import logging
from io import BytesIO
from typing import Any

import requests
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from mecanimovilapp.apps.chat.link_preview import (
    TIMEOUT,
    USER_AGENT,
    fetch_link_preview,
    validate_preview_url,
)

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 1_500_000
MIN_LADO_PX = 200
MAX_ASPECT = 2.4  # descarta banners anchos
ESTADO_PENDIENTE = 'pendiente'
ESTADO_OK = 'ok'
ESTADO_SIN = 'sin_imagen'
ESTADO_ERROR = 'error'


def _sha1(url: str) -> str:
    return hashlib.sha1((url or '').encode('utf-8')).hexdigest()


def _descargar_imagen(image_url: str) -> bytes | None:
    safe = validate_preview_url(image_url)
    if not safe:
        return None
    try:
        resp = requests.get(
            safe,
            timeout=TIMEOUT,
            stream=True,
            headers={'User-Agent': USER_AGENT, 'Accept': 'image/*,*/*;q=0.8'},
        )
    except requests.RequestException:
        return None
    ctype = (resp.headers.get('Content-Type') or '').lower()
    if resp.status_code >= 400 or not ctype.startswith('image/'):
        resp.close()
        return None
    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_content(8192):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_IMAGE_BYTES:
            resp.close()
            return None
        chunks.append(chunk)
    resp.close()
    return b''.join(chunks) or None


def _dimensiones_ok(data: bytes) -> bool:
    try:
        from PIL import Image
    except Exception:
        return True
    try:
        img = Image.open(BytesIO(data))
        w, h = img.size
    except Exception:
        return False
    if w < MIN_LADO_PX or h < MIN_LADO_PX:
        return False
    ratio = max(w, h) / max(1, min(w, h))
    return ratio <= MAX_ASPECT


def resolver_imagen_opcion(url: str) -> str | None:
    """Devuelve URL propia en R2 o None. Idempotente por hash de la URL origen."""
    safe_page = validate_preview_url(url)
    if not safe_page:
        return None
    try:
        preview = fetch_link_preview(safe_page)
    except ValueError:
        return None
    except Exception:
        logger.info('imagen_repuesto[og] preview failed url=%s', safe_page[:80])
        return None
    image = str((preview or {}).get('image') or '').strip()
    if not image:
        return None
    if not validate_preview_url(image):
        return None
    key = f'repuestos/og/{_sha1(image)}.jpg'
    if default_storage.exists(key):
        try:
            return default_storage.url(key)
        except Exception:
            return key
    data = _descargar_imagen(image)
    if not data or not _dimensiones_ok(data):
        return None
    try:
        saved = default_storage.save(key, ContentFile(data))
        return default_storage.url(saved)
    except Exception:
        logger.info('imagen_repuesto[og] upload failed key=%s', key)
        return None


def hidratar_precio_web(row) -> str:
    """Actualiza imagen_url / imagen_estado de un PrecioRepuestoWeb. Devuelve estado."""
    estado = str(getattr(row, 'imagen_estado', '') or ESTADO_PENDIENTE)
    if estado in (ESTADO_OK, ESTADO_SIN, ESTADO_ERROR) and (row.imagen_url or estado != ESTADO_PENDIENTE):
        if estado == ESTADO_OK and row.imagen_url:
            return ESTADO_OK
        if estado in (ESTADO_SIN, ESTADO_ERROR):
            return estado
    url = str(getattr(row, 'url', '') or '')
    if not url:
        row.imagen_estado = ESTADO_SIN
        row.save(update_fields=['imagen_estado'])
        return ESTADO_SIN
    try:
        propia = resolver_imagen_opcion(url)
    except Exception:
        row.imagen_estado = ESTADO_ERROR
        row.save(update_fields=['imagen_estado'])
        return ESTADO_ERROR
    if propia:
        row.imagen_url = propia[:500]
        row.imagen_estado = ESTADO_OK
        row.save(update_fields=['imagen_url', 'imagen_estado'])
        return ESTADO_OK
    row.imagen_estado = ESTADO_SIN
    row.save(update_fields=['imagen_estado'])
    return ESTADO_SIN


def hidratar_opciones_en_memoria(opciones: list[dict[str, Any]], *, max_n: int = 9) -> int:
    """Rellena imagen_url in-place. Best-effort."""
    n = 0
    for op in opciones[:max_n]:
        if not isinstance(op, dict):
            continue
        if op.get('imagen_url'):
            continue
        url = str(op.get('url') or '')
        if not url:
            continue
        propia = resolver_imagen_opcion(url)
        if propia:
            op['imagen_url'] = propia
            n += 1
    return n
