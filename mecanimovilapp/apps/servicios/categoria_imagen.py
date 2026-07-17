"""
Normaliza iconos de categoría para el home (Airbnb Explore):
PNG transparente, sin padding vacío, lienzo cuadrado.
"""
from __future__ import annotations

from io import BytesIO

from PIL import Image

# Tamaño de salida: suficiente para @2x/@3x del slot 56px.
OUTPUT_SIDE = 256
# Aire alrededor del glifo (Explore: no edge-to-edge absoluto).
INSET_RATIO = 0.08


def normalize_categoria_icon(file_obj) -> BytesIO:
    """
    Recorta transparencia, centra en cuadrado con inset y redimensiona.
    Devuelve un buffer PNG listo para FileResponse.
    """
    img = Image.open(file_obj).convert('RGBA')
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
