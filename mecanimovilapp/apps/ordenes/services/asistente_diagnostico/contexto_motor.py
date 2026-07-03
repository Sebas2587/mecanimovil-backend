"""Resolución de tipo de motor para el asistente de diagnóstico IA."""
from __future__ import annotations

import re
from typing import Any

from mecanimovilapp.apps.vehiculos.catalogo_resolver import normalizar_tipo_motor_vehiculo

MOTOR_LABELS = {
    'GASOLINA': 'Bencinero (gasolina)',
    'DIESEL': 'Diésel',
    'ELECTRICO': 'Eléctrico',
    'HIBRIDO': 'Híbrido',
}

MOTOR_REGLAS_PROMPT = {
    'GASOLINA': (
        'Motor a bencina/gasolina: bujías, bobina, inyectores gasolina, filtro de aire. '
        'NO glow plugs, NO bomba inyectora diésel, NO prechamber.'
    ),
    'DIESEL': (
        'Motor diésel: bujías de incandescencia/glow plugs, bomba inyectora, filtros diésel, turbo. '
        'NO bujías de encendido convencionales de gasolina.'
    ),
    'ELECTRICO': (
        'Vehículo 100% eléctrico: batería de alto voltaje, motor de tracción, refrigeración de batería. '
        'NO bujías, NO aceite de motor ICE, NO filtros de combustible.'
    ),
    'HIBRIDO': (
        'Híbrido: distingue componentes del motor de combustión y del tren eléctrico. '
        'Incluye precauciones de aislamiento HV cuando aplique.'
    ),
}

_MOTOR_TEXTO_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r'\b(?:di[eé]sel|petr[oó]leo|petrolero)\b', re.I), 'DIESEL'),
    (re.compile(r'\b(?:bencin[a-o]|gasolin[a-o]|bencinero)\b', re.I), 'GASOLINA'),
    (re.compile(r'\b(?:el[eé]ctric[oa-o]s?|bev|100\s*%\s*el[eé]ctric)\b', re.I), 'ELECTRICO'),
    (re.compile(r'\b(?:h[ií]brid[oa-o]s?|hybrid|phev|hev)\b', re.I), 'HIBRIDO'),
]


def parse_tipo_motor_si_presente(valor: str | None) -> str | None:
    if not valor or not str(valor).strip():
        return None
    return normalizar_tipo_motor_vehiculo(valor)


def inferir_tipo_motor_desde_texto(texto: str | None) -> str | None:
    if not texto or not str(texto).strip():
        return None
    for pattern, codigo in _MOTOR_TEXTO_PATTERNS:
        if pattern.search(str(texto)):
            return codigo
    return None


def motor_desde_oferta(oferta) -> str | None:
    if oferta is None:
        return None
    parsed = parse_tipo_motor_si_presente(getattr(oferta, 'tipo_motor', None))
    if parsed:
        return parsed
    servicio = getattr(oferta, 'servicio', None)
    if servicio is not None:
        tipos = getattr(servicio, 'tipos_motor_compatibles', None) or []
        if len(tipos) == 1:
            return parse_tipo_motor_si_presente(tipos[0])
        nombre = getattr(servicio, 'nombre', '') or ''
        inferred = inferir_tipo_motor_desde_texto(nombre)
        if inferred:
            return inferred
    return None


def resolver_motor_vehiculo(*, vehiculo=None, patente: str = '') -> str | None:
    if vehiculo is not None:
        parsed = parse_tipo_motor_si_presente(getattr(vehiculo, 'tipo_motor', None))
        if parsed:
            return parsed

    patente_norm = (patente or '').strip().upper()
    if not patente_norm:
        return None

    from mecanimovilapp.apps.vehiculos.models import Vehiculo

    registro = Vehiculo.objects.filter(patente=patente_norm).only('tipo_motor').first()
    if registro is not None:
        parsed = parse_tipo_motor_si_presente(registro.tipo_motor)
        if parsed:
            return parsed

    from mecanimovilapp.apps.vehiculos.getapi_client import fetch_plate_basic_info

    info = fetch_plate_basic_info(patente_norm)
    return parse_tipo_motor_si_presente(info.get('tipo_motor'))


def consolidar_contexto_motor(
    *,
    motor_vehiculo: str | None,
    motor_servicio: str | None,
) -> dict[str, Any]:
    """
    Define el motor efectivo para la guía IA.
    Prioridad: vehículo (patente/registro) > servicio/oferta.
    """
    conflicto = bool(
        motor_vehiculo and motor_servicio and motor_vehiculo != motor_servicio
    )
    efectivo = motor_vehiculo or motor_servicio

    if efectivo:
        label = MOTOR_LABELS.get(efectivo, efectivo)
        reglas = MOTOR_REGLAS_PROMPT.get(efectivo, '')
    else:
        label = 'No especificado'
        reglas = (
            'Si no hay tipo de motor confirmado, no mezcles procedimientos diésel y bencina. '
            'Indica en advertencias que se debe verificar el combustible antes de intervenir.'
        )

    servicio_label = MOTOR_LABELS.get(motor_servicio, motor_servicio or 'No especificado')
    vehiculo_label = MOTOR_LABELS.get(motor_vehiculo, motor_vehiculo or 'No especificado')

    return {
        'tipo_motor_vehiculo': motor_vehiculo or '',
        'tipo_motor_servicio': motor_servicio or '',
        'tipo_motor_efectivo': efectivo or '',
        'tipo_motor_efectivo_label': label,
        'tipo_motor_vehiculo_label': vehiculo_label,
        'tipo_motor_servicio_label': servicio_label,
        'tipo_motor_conflicto': conflicto,
        'tipo_motor_reglas': reglas,
    }
