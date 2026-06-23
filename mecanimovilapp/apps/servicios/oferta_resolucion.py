"""
Resolución de OfertaServicio por marca, modelo y tipo de motor del vehículo.

Regla marca: oferta con marca explícita > oferta genérica (marca null) > sin oferta.
Regla modelo: oferta con modelo exacto > oferta sin modelo (todos los modelos de la marca).
Regla motor: oferta con motor exacto > oferta universal (tipo_motor '') > motor distinto.
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


def _modelo_id(modelo: Any) -> int | None:
    if modelo is None:
        return None
    mid = getattr(modelo, 'id', modelo)
    try:
        return int(mid)
    except (TypeError, ValueError):
        return None


def prioridad_oferta_para_modelo(oferta: Any, modelo_id: int | None) -> int:
    """
    Mayor valor = más preferida para el modelo del vehículo.
    -2: otro modelo (no aplica)
    -1: sin modelo en contexto
     0: genérica (modelo null) cuando se pide modelo concreto (fallback)
     1: genérica sin contexto de modelo
     2: modelo exacto
    """
    oid = getattr(oferta, 'modelo_vehiculo_seleccionado_id', None)
    if oid is None and hasattr(oferta, 'modelo_vehiculo_seleccionado'):
        m = getattr(oferta, 'modelo_vehiculo_seleccionado', None)
        oid = getattr(m, 'id', None) if m is not None else None

    if modelo_id is None:
        return 1 if oid is None else 0

    if oid == modelo_id:
        return 2
    if oid is None:
        return 0
    return -2


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


def prioridad_oferta_para_motor(oferta: Any, tipo_motor_vehiculo: str | None) -> int:
    """
    Mayor valor = más preferida para el motor del vehículo.
    -2: motor distinto al del vehículo
     0: oferta universal cuando el vehículo tiene motor conocido
     1: sin contexto de motor del vehículo
     2: motor exacto
    """
    from mecanimovilapp.apps.servicios.oferta_compatibilidad import normalizar_tipo_motor_oferta
    from mecanimovilapp.apps.vehiculos.catalogo_resolver import normalizar_tipo_motor_vehiculo

    tipo_oferta = normalizar_tipo_motor_oferta(getattr(oferta, 'tipo_motor', None))
    if not tipo_motor_vehiculo or not str(tipo_motor_vehiculo).strip():
        return 1

    motor_v = normalizar_tipo_motor_vehiculo(tipo_motor_vehiculo)
    if not tipo_oferta:
        return 0
    if tipo_oferta == motor_v:
        return 2
    return -2


def prioridad_oferta_combinada(
    oferta: Any,
    marca_id: int | None,
    tipo_motor_vehiculo: str | None = None,
    modelo_id: int | None = None,
) -> int:
    """Combina prioridad de marca, modelo y motor (marca pesa más)."""
    pm = prioridad_oferta_para_marca(oferta, marca_id)
    if pm < 0:
        return pm
    pmod = prioridad_oferta_para_modelo(oferta, modelo_id)
    if pmod < 0:
        return pmod
    pt = prioridad_oferta_para_motor(oferta, tipo_motor_vehiculo)
    if pt < 0:
        return pt
    return pm * 100 + pmod * 10 + pt


def resolver_ofertas_preferidas_por_marca(
    ofertas: Iterable[Any],
    marca: Any,
    *,
    servicio_id_attr: str = 'servicio_id',
    tipo_motor: str | None = None,
    modelo: Any = None,
) -> list[Any]:
    """
    Por (proveedor, servicio_id) conserva la oferta más específica para marca, modelo y motor.
    """
    marca_id = _marca_id(marca)
    modelo_id = _modelo_id(modelo)
    mejores: dict[tuple[tuple[str, int], int], Any] = {}
    prioridades: dict[tuple[tuple[str, int], int], int] = {}

    for oferta in ofertas:
        pk = _proveedor_key(oferta)
        sid = getattr(oferta, servicio_id_attr, None)
        if pk is None or sid is None:
            continue
        key = (pk, int(sid))
        prio = prioridad_oferta_combinada(oferta, marca_id, tipo_motor, modelo_id)
        if prio < 0:
            continue
        prev_prio = prioridades.get(key)
        if prev_prio is None or prio > prev_prio:
            mejores[key] = oferta
            prioridades[key] = prio

    return list(mejores.values())


def elegir_mejor_oferta_entre(
    candidatas: Iterable[Any],
    marca: Any,
    *,
    tipo_motor: str | None = None,
    modelo: Any = None,
) -> Any | None:
    """Elige una oferta entre candidatas del mismo proveedor/servicio."""
    marca_id = _marca_id(marca)
    modelo_id = _modelo_id(modelo)
    mejor = None
    mejor_prio = -300
    for oferta in candidatas:
        prio = prioridad_oferta_combinada(oferta, marca_id, tipo_motor, modelo_id)
        if prio > mejor_prio:
            mejor = oferta
            mejor_prio = prio
    return mejor
