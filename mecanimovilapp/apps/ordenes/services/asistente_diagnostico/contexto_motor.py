"""Resolución de tipo de motor para el asistente de diagnóstico IA."""
from __future__ import annotations

import re
from typing import Any

from mecanimovilapp.apps.vehiculos.catalogo_resolver import normalizar_tipo_motor_vehiculo

MOTOR_LABELS = {
    'GASOLINA': 'Bencinero (gasolina)',
    'DIESEL': 'Diésel (petróleo)',
    'ELECTRICO': 'Eléctrico',
    'HIBRIDO': 'Híbrido',
}

MOTOR_REGLAS_PROMPT = {
    'GASOLINA': (
        'Motor a bencina/gasolina: bujías, bobina, inyectores gasolina, filtro de aire. '
        'NO glow plugs, NO bomba inyectora diésel, NO prechamber.'
    ),
    'DIESEL': (
        'Motor diésel/petróleo: bujías de incandescencia (glow plugs), bomba inyectora, '
        'inyectores diésel, filtros diésel, rail/common rail. '
        'NO bujías de encendido convencionales de gasolina. '
        'El "sistema de encendido" en diésel se refiere a precalentamiento/incandescencia, no a bujías ICE gasolina.'
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
    (re.compile(r'\b(?:di[eé]sel|petr[oó]leo|petroler[oa]s?)\b', re.I), 'DIESEL'),
    (re.compile(r'\b(?:bencin[a-o]|gasolin[a-o]|benciner[oa]s?)\b', re.I), 'GASOLINA'),
    (re.compile(r'\b(?:el[eé]ctric[oa-o]s?|bev|100\s*%\s*el[eé]ctric)\b', re.I), 'ELECTRICO'),
    (re.compile(r'\b(?:h[ií]brid[oa-o]s?|hybrid|phev|hev)\b', re.I), 'HIBRIDO'),
]

# Indicadores habituales en nombre comercial del modelo (Chile/Latam)
_MODELO_DIESEL_MARKERS = (
    'HDI', 'JTD', 'JTDM', 'TDI', 'TDCI', 'CDTI', 'DCI', 'DCi', 'ECOTDI', 'BLUETDI',
    'MULTIJET', 'CRDI', 'D4D', 'TD ', ' TD', ' 2.0D', '1.6D', '2.2D',
)
_MODELO_GASOLINA_MARKERS = (
    'T-JET', 'TJET', 'T JET', 'TSI', 'TFSI', 'GDI', 'MPI', 'SKYACTIV-G', 'FIRE',
    'ECOBOOST', 'VTI', '16V', 'VVT', 'TURBO 1.4', '1.4T',
)


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


def inferir_motor_desde_modelo(
    marca: str = '',
    modelo: str = '',
    version: str = '',
) -> str | None:
    """Inferencia débil por siglas/nomenclatura del modelo (ej. T-Jet → bencina, HDi → diésel)."""
    texto = f'{marca} {modelo} {version}'.upper().replace('-', ' ')
    compacto = re.sub(r'\s+', '', texto)

    for marker in _MODELO_DIESEL_MARKERS:
        mk = marker.upper().replace('-', '').replace(' ', '')
        if mk in compacto or marker.upper() in texto:
            return 'DIESEL'

    for marker in _MODELO_GASOLINA_MARKERS:
        mk = marker.upper().replace('-', '').replace(' ', '')
        if mk in compacto or marker.upper() in texto:
            return 'GASOLINA'

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


def _label(codigo: str | None) -> str:
    if not codigo:
        return 'No especificado'
    return MOTOR_LABELS.get(codigo, codigo)


def _resolver_motor_registro(
    motor_vehiculo: str | None,
    motor_modelo: str | None,
) -> tuple[str | None, bool]:
    """
    Motor según datos del vehículo (API patente + nomenclatura del modelo).
    Retorna (código, es_autoritativo).
    """
    if motor_vehiculo and motor_modelo:
        return motor_vehiculo, True
    if motor_vehiculo:
        return motor_vehiculo, True
    if motor_modelo:
        return motor_modelo, False
    return None, False


def _incoherencias_operativas(
    motor_registro: str,
    *,
    motor_servicio: str | None,
    motor_problema: str | None,
) -> list[str]:
    """Señales de servicio o nota que no cuadran con el vehículo registrado."""
    partes: list[str] = []
    if motor_servicio and motor_servicio != motor_registro:
        partes.append(
            f'el servicio/oferta catalogado es {_label(motor_servicio)} '
            f'(posible error de asignación)'
        )
    if motor_problema and motor_problema != motor_registro:
        partes.append(
            f'la descripción del caso sugiere {_label(motor_problema)} '
            f'(puede no concordar con el vehículo)'
        )
    return partes


def consolidar_contexto_motor(
    *,
    motor_vehiculo: str | None,
    motor_servicio: str | None,
    motor_problema: str | None = None,
    motor_modelo: str | None = None,
) -> dict[str, Any]:
    """
    Define el motor efectivo para la guía IA cruzando todas las fuentes.

    Prioridad (datos del vehículo primero — el servicio puede estar mal asignado):
    1. Patente / API de registro (fuente autoritativa).
    2. Nomenclatura del modelo (T-Jet, HDi, etc.) si no hay patente.
    3. Solo sin datos de vehículo: descripción del problema o servicio.

    Si servicio o nota contradicen patente/modelo, se marca conflicto y la guía
    sigue el motor del vehículo, avisando la posible mala asignación.
    """
    motor_registro, registro_autoritativo = _resolver_motor_registro(
        motor_vehiculo, motor_modelo
    )

    efectivo: str | None = None
    razon_conflicto = ''
    servicio_posible_error = False

    if motor_registro:
        efectivo = motor_registro
        incoherencias = _incoherencias_operativas(
            motor_registro,
            motor_servicio=motor_servicio,
            motor_problema=motor_problema,
        )
        if incoherencias:
            servicio_posible_error = bool(
                motor_servicio and motor_servicio != motor_registro
            )
            autoridad = (
                'patente/registro oficial'
                if registro_autoritativo
                else 'nomenclatura del modelo'
            )
            razon_conflicto = (
                f'Según {autoridad}, el vehículo es {_label(motor_registro)}. '
                f'{"; ".join(incoherencias)}. '
                'Genera la guía para el motor del vehículo, no para el servicio mal asignado.'
            )
        elif (
            motor_vehiculo
            and motor_modelo
            and motor_vehiculo != motor_modelo
        ):
            razon_conflicto = (
                f'Patente indica {_label(motor_vehiculo)} pero el modelo '
                f'sugiere {_label(motor_modelo)}. Se usa el registro de patente.'
            )
    elif motor_problema and motor_servicio:
        if motor_problema == motor_servicio:
            efectivo = motor_problema
        else:
            efectivo = motor_problema
            razon_conflicto = (
                f'La descripción indica {_label(motor_problema)} pero el servicio '
                f'catalogado indica {_label(motor_servicio)}.'
            )
    elif motor_problema:
        efectivo = motor_problema
    elif motor_servicio:
        efectivo = motor_servicio

    fuentes = {
        k: v
        for k, v in {
            'patente_registro': motor_vehiculo,
            'modelo': motor_modelo,
            'servicio': motor_servicio,
            'problema': motor_problema,
        }.items()
        if v
    }
    conflicto = len(set(fuentes.values())) > 1 or bool(razon_conflicto)

    if efectivo:
        reglas = MOTOR_REGLAS_PROMPT.get(efectivo, '')
    else:
        reglas = (
            'No hay tipo de motor confirmado. No mezcles procedimientos diésel y bencina. '
            'Indica en advertencias verificar combustible y tipo de motor antes de intervenir.'
        )

    return {
        'tipo_motor_vehiculo': motor_vehiculo or '',
        'tipo_motor_servicio': motor_servicio or '',
        'tipo_motor_problema': motor_problema or '',
        'tipo_motor_modelo': motor_modelo or '',
        'tipo_motor_registro': motor_registro or '',
        'tipo_motor_registro_label': _label(motor_registro),
        'tipo_motor_efectivo': efectivo or '',
        'tipo_motor_efectivo_label': _label(efectivo),
        'tipo_motor_vehiculo_label': _label(motor_vehiculo),
        'tipo_motor_servicio_label': _label(motor_servicio),
        'tipo_motor_problema_label': _label(motor_problema),
        'tipo_motor_modelo_label': _label(motor_modelo),
        'tipo_motor_conflicto': conflicto,
        'tipo_motor_conflicto_detalle': razon_conflicto,
        'tipo_motor_servicio_posible_error': servicio_posible_error,
        'tipo_motor_registro_autoritativo': registro_autoritativo,
        'tipo_motor_reglas': reglas,
    }
