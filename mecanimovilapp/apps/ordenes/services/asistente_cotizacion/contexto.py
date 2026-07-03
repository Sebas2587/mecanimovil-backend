"""Contexto para cotización IA desde chat omnicanal."""
from __future__ import annotations

from typing import Any

from mecanimovilapp.apps.ordenes.services.asistente_diagnostico.contexto_motor import (
    consolidar_contexto_motor,
    inferir_motor_desde_modelo,
    inferir_tipo_motor_desde_texto,
    parse_tipo_motor_si_presente,
    resolver_motor_vehiculo,
)


def _mensajes_recientes(conversation, limite: int = 8) -> str:
    if conversation is None:
        return ''
    lineas: list[str] = []
    qs = conversation.messages.order_by('-timestamp')[:limite]
    for msg in reversed(list(qs)):
        quien = 'Cliente' if msg.direction == 'inbound' else 'Taller'
        texto = (msg.content or '').strip()
        if texto:
            lineas.append(f'{quien}: {texto[:400]}')
    return '\n'.join(lineas)


def armar_contexto_cotizacion(
    *,
    conversation=None,
    servicio_nombre: str = '',
    descripcion_problema: str = '',
    modalidad: str = 'taller',
    vehiculo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    v = vehiculo or {}
    marca = str(v.get('marca') or '').strip()
    modelo = str(v.get('modelo') or '').strip()
    anio = v.get('anio') or v.get('year') or ''
    patente = str(v.get('patente') or '').strip().upper()
    cilindraje = str(v.get('cilindraje') or '').strip()
    vin = str(v.get('vin') or '').strip()

    motor_vehiculo = resolver_motor_vehiculo(patente=patente)
    if not cilindraje and patente:
        from mecanimovilapp.apps.vehiculos.getapi_client import fetch_plate_basic_info

        info = fetch_plate_basic_info(patente)
        if not motor_vehiculo:
            motor_vehiculo = parse_tipo_motor_si_presente(info.get('tipo_motor'))
        if not cilindraje and info.get('cilindraje'):
            cilindraje = str(info['cilindraje'])
        if not marca and info.get('marca'):
            marca = str(info['marca'])
        if not modelo and info.get('modelo'):
            modelo = str(info['modelo'])

    motor_servicio = inferir_tipo_motor_desde_texto(servicio_nombre)
    motor_problema = inferir_tipo_motor_desde_texto(descripcion_problema)
    motor_modelo = inferir_motor_desde_modelo(marca, modelo, '')

    motor_ctx = consolidar_contexto_motor(
        motor_vehiculo=motor_vehiculo,
        motor_servicio=motor_servicio,
        motor_problema=motor_problema,
        motor_modelo=motor_modelo,
    )

    chat_ctx = _mensajes_recientes(conversation)

    return {
        'marca': marca,
        'modelo': modelo,
        'anio': str(anio or ''),
        'patente': patente,
        'cilindraje': cilindraje,
        'vin': vin,
        'modalidad': modalidad,
        'servicio_nombre': servicio_nombre,
        'descripcion_problema': descripcion_problema,
        'chat_reciente': chat_ctx,
        **motor_ctx,
    }
