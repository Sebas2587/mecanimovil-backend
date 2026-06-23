"""
Utilidad compartida para serializar repuestos desde JSON repuestos_seleccionados.
"""
from __future__ import annotations

from typing import Any

from mecanimovilapp.apps.servicios.models import Repuesto
from mecanimovilapp.apps.servicios.repuesto_oferta import enriquecer_repuesto_oferta


def build_repuestos_info(
    repuestos_seleccionados: list | None,
    *,
    request=None,
) -> list[dict[str, Any]]:
    """Lista de repuestos con nombre, cantidad, precio, marca y calidad para API cliente."""
    if not repuestos_seleccionados or not isinstance(repuestos_seleccionados, list):
        return []

    repuestos_info: list[dict[str, Any]] = []
    for repuesto_data in repuestos_seleccionados:
        if not isinstance(repuesto_data, dict):
            continue
        repuesto_id = repuesto_data.get('id')
        if not repuesto_id:
            continue
        try:
            repuesto = Repuesto.objects.get(id=repuesto_id)
        except Repuesto.DoesNotExist:
            continue
        repuestos_info.append(enriquecer_repuesto_oferta(repuesto_data, repuesto, request=request))
    return repuestos_info
