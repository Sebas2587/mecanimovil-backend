"""
Resolución de OfertaServicio por marca del vehículo.

Regla: oferta con marca explícita > oferta genérica (marca null) > sin oferta.
Aplica a multimarca y especialistas por igual.
"""
from __future__ import annotations

from typing import Any, Iterable


def _marca_id(marca: Any) -> int | None:
    if marca is None:
        return None
    mid = getattr(marca, 'id', marca)
    try:
        return int(mid)
    except (TypeError, ValueError):
        return None


def _proveedor_key(oferta: Any) -> tuple[str, int] | None:
    if getattr(oferta, 'taller_id', None):
        return ('taller', int(oferta.taller_id))
    if getattr(oferta, 'mecanico_id', None):
        return ('mecanico', int(oferta.mecanico_id))
    return None


def prioridad_oferta_para_marca(oferta: Any, marca_id: int | None) -> int:
    """
    Mayor valor = más preferida para la marca del vehículo.
    -2: otra marca (no aplica)
    -1: sin marca en contexto
     0: genérica cuando se pide marca concreta (fallback)
     1: genérica sin contexto de marca
     2: marca exacta
    """
    oid = getattr(oferta, 'marca_vehiculo_seleccionada_id', None)
    if oid is None and hasattr(oferta, 'marca_vehiculo_seleccionada'):
        m = getattr(oferta, 'marca_vehiculo_seleccionada', None)
        oid = getattr(m, 'id', None) if m is not None else None

    if marca_id is None:
        return 1 if oid is None else 0

    if oid == marca_id:
        return 2
    if oid is None:
        return 0
    return -2


def resolver_ofertas_preferidas_por_marca(
    ofertas: Iterable[Any],
    marca: Any,
    *,
    servicio_id_attr: str = 'servicio_id',
) -> list[Any]:
    """
    Por (proveedor, servicio_id) conserva la oferta más específica para la marca.
    """
    marca_id = _marca_id(marca)
    mejores: dict[tuple[tuple[str, int], int], Any] = {}
    prioridades: dict[tuple[tuple[str, int], int], int] = {}

    for oferta in ofertas:
        pk = _proveedor_key(oferta)
        sid = getattr(oferta, servicio_id_attr, None)
        if pk is None or sid is None:
            continue
        key = (pk, int(sid))
        prio = prioridad_oferta_para_marca(oferta, marca_id)
        if prio < 0:
            continue
        prev_prio = prioridades.get(key)
        if prev_prio is None or prio > prev_prio:
            mejores[key] = oferta
            prioridades[key] = prio

    return list(mejores.values())


def elegir_mejor_oferta_entre(candidatas: Iterable[Any], marca: Any) -> Any | None:
    """Elige una oferta entre candidatas del mismo proveedor/servicio."""
    marca_id = _marca_id(marca)
    mejor = None
    mejor_prio = -3
    for oferta in candidatas:
        prio = prioridad_oferta_para_marca(oferta, marca_id)
        if prio > mejor_prio:
            mejor = oferta
            mejor_prio = prio
    return mejor
