"""
Normaliza iconos de categoría para el home (Airbnb Explore):
PNG transparente, sin padding vacío, lienzo cuadrado.
"""
from __future__ import annotations

import hashlib
import logging
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image

logger = logging.getLogger(__name__)

# Tamaño de salida: suficiente para @2x/@3x del slot 56px.
OUTPUT_SIDE = 256
# Aire alrededor del glifo (Explore: no edge-to-edge absoluto).
INSET_RATIO = 0.08


def normalize_categoria_icon(file_obj) -> BytesIO:
    """
    Recorta transparencia, centra en cuadrado con inset y redimensiona.
    Devuelve un buffer PNG listo para HttpResponse / ContentFile.
    """
    img = Image.open(file_obj)
    img.load()
    img = img.convert('RGBA')
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)

    w, h = img.size
    if w <= 0 or h <= 0:
        raise ValueError('Imagen de categoría vacía')

    content_side = max(w, h)
    inset = max(1, int(content_side * INSET_RATIO))
    canvas_side = content_side + inset * 2
    canvas = Image.new('RGBA', (canvas_side, canvas_side), (0, 0, 0, 0))
    canvas.paste(img, ((canvas_side - w) // 2, (canvas_side - h) // 2), img)

    if canvas_side != OUTPUT_SIDE:
        canvas = canvas.resize((OUTPUT_SIDE, OUTPUT_SIDE), Image.Resampling.LANCZOS)

    buf = BytesIO()
    canvas.save(buf, format='PNG', optimize=True)
    buf.seek(0)
    return buf


def categoria_imagen_cache_key(obj) -> str:
    """Token estable por archivo en storage (cambia al re-subir)."""
    name = getattr(getattr(obj, 'imagen', None), 'name', '') or ''
    if not name:
        return 'none'
    return hashlib.md5(name.encode('utf-8')).hexdigest()[:10]


def persist_normalized_categoria_imagen(obj) -> bool:
    """
    Reescribe obj.imagen como PNG normalizado en storage.
    Devuelve True si guardó un archivo nuevo.
    """
    if not getattr(obj, 'imagen', None):
        return False
    try:
        with obj.imagen.open('rb') as src:
            buf = normalize_categoria_icon(src)
    except Exception:
        logger.exception('No se pudo normalizar imagen de categoría id=%s', getattr(obj, 'pk', None))
        return False

    filename = f'categoria-{obj.pk or "new"}-icon.png'
    # Evita re-guardar si ya es el PNG normalizado reciente (mismo tamaño aprox).
    obj.imagen.save(filename, ContentFile(buf.getvalue()), save=False)
    return True
