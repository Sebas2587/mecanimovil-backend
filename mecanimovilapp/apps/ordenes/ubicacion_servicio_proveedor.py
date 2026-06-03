"""
Ubicación del servicio según modalidad: taller (dirección del local) vs mecánico a domicilio.
"""
from __future__ import annotations

from typing import Any

from django.contrib.gis.geos import Point


def texto_direccion_taller(taller) -> str | None:
    if not taller:
        return None
    try:
        direccion = getattr(taller, 'direccion_fisica', None)
        if direccion:
            completa = (getattr(direccion, 'direccion_completa', None) or '').strip()
            if completa:
                return completa
            partes = [
                getattr(direccion, 'calle', None),
                getattr(direccion, 'numero', None),
                getattr(direccion, 'comuna', None),
                getattr(direccion, 'ciudad', None),
            ]
            texto = ', '.join(p for p in partes if p)
            if texto.strip():
                return texto.strip()
    except Exception:
        pass
    return None


def punto_ubicacion_taller(taller) -> Point | None:
    if not taller:
        return None
    ubic = getattr(taller, 'ubicacion', None)
    if ubic is None:
        return None
    try:
        return Point(float(ubic.x), float(ubic.y), srid=4326)
    except (TypeError, ValueError):
        return None


def modalidad_servicio_dict(tipo_proveedor: str | None) -> dict[str, Any] | None:
    if tipo_proveedor == 'taller':
        return {
            'tipo': 'taller',
            'label': 'En taller',
            'a_domicilio': False,
        }
    if tipo_proveedor == 'mecanico':
        return {
            'tipo': 'mecanico',
            'label': 'A domicilio',
            'a_domicilio': True,
        }
    return None


def direccion_servicio_texto_para_solicitud(
    *,
    direccion_guardada: str,
    tipo_proveedor: str | None,
    taller=None,
) -> str:
    """Texto a mostrar en detalle/listado; prioriza dirección del taller si aplica."""
    if tipo_proveedor == 'taller' and taller:
        texto_taller = texto_direccion_taller(taller)
        if texto_taller:
            return texto_taller
    return (direccion_guardada or '').strip() or 'Ubicación no especificada'
