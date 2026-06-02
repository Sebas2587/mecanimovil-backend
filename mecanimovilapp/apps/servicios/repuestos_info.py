"""
Utilidad compartida para serializar repuestos desde JSON repuestos_seleccionados.
"""
from __future__ import annotations

from typing import Any

from mecanimovilapp.apps.servicios.models import Repuesto
from mecanimovilapp.storage.utils import get_image_url


def build_repuestos_info(
    repuestos_seleccionados: list | None,
    *,
    request=None,
) -> list[dict[str, Any]]:
    """Lista de repuestos con nombre, cantidad y precio para API cliente."""
    if not repuestos_seleccionados or not isinstance(repuestos_seleccionados, list):
        return []

    repuestos_info: list[dict[str, Any]] = []
    for repuesto_data in repuestos_seleccionados:
        if not isinstance(repuesto_data, dict):
            continue
        repuesto_id = repuesto_data.get('id')
        cantidad = repuesto_data.get('cantidad', repuesto_data.get('cantidad_estimada', 1))
        precio_personalizado = repuesto_data.get('precio')
        if not repuesto_id:
            continue
        try:
            repuesto = Repuesto.objects.get(id=repuesto_id)
        except Repuesto.DoesNotExist:
            continue
        repuesto_info: dict[str, Any] = {
            'id': repuesto.id,
            'nombre': repuesto.nombre,
            'descripcion': repuesto.descripcion or '',
            'marca': repuesto.marca or '',
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
        repuestos_info.append(repuesto_info)
    return repuestos_info
