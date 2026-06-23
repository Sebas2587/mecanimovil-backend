"""
Campos por ítem en repuestos_seleccionados (JSON en OfertaServicio).
"""
from __future__ import annotations

CALIDADES_REPUESTO_VALIDAS = frozenset({'original', 'oem', 'alternativo'})

CALIDAD_REPUESTO_LABELS = {
    'original': 'Original',
    'oem': 'OEM',
    'alternativo': 'Alternativo',
}


def normalizar_calidad_repuesto(raw) -> str:
    if not raw or not isinstance(raw, str):
        return ''
    key = raw.strip().lower()
    return key if key in CALIDADES_REPUESTO_VALIDAS else ''


def enriquecer_repuesto_oferta(
    repuesto_data: dict,
    repuesto,
    *,
    request=None,
) -> dict:
    """Combina catálogo maestro + overrides del proveedor en repuestos_seleccionados."""
    from mecanimovilapp.storage.utils import get_image_url

    cantidad = repuesto_data.get('cantidad', repuesto_data.get('cantidad_estimada', 1))
    precio_personalizado = repuesto_data.get('precio')
    marca_repuesto = (repuesto_data.get('marca_repuesto') or '').strip()
    calidad = normalizar_calidad_repuesto(repuesto_data.get('calidad_repuesto'))
    marca_catalogo = (repuesto.marca or '').strip()
    marca_display = marca_repuesto or marca_catalogo

    return {
        'id': repuesto.id,
        'nombre': repuesto.nombre,
        'descripcion': repuesto.descripcion or '',
        'marca': marca_display,
        'marca_catalogo': marca_catalogo,
        'marca_repuesto': marca_repuesto,
        'calidad_repuesto': calidad,
        'calidad_repuesto_label': CALIDAD_REPUESTO_LABELS.get(calidad, ''),
        'precio_referencia': float(repuesto.precio_referencia)
        if repuesto.precio_referencia
        else 0.0,
        'cantidad': cantidad,
        'cantidad_estimada': cantidad,
        'categoria_repuesto': repuesto.categoria_repuesto or '',
        'codigo_fabricante': repuesto.codigo_fabricante or '',
        'foto': get_image_url(repuesto.foto, request),
        'precio': float(precio_personalizado)
        if precio_personalizado is not None
        else None,
    }
