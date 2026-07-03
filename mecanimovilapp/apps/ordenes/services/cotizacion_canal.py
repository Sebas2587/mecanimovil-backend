"""Envío y respuesta de cotizaciones canal."""
from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from mecanimovilapp.apps.chat.models import Conversation, Message
from mecanimovilapp.apps.ordenes.models import CotizacionCanal
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import recalcular_totales

logger = logging.getLogger(__name__)


def formatear_moneda_clp(valor: int | Decimal) -> str:
    n = int(valor or 0)
    return f'${n:,}'.replace(',', '.')


def _linea_vehiculo_cotizacion(cotizacion: CotizacionCanal) -> list[str]:
    lineas = ['*Vehículo:*']
    if cotizacion.vehiculo_marca:
        lineas.append(f'Marca: {cotizacion.vehiculo_marca}')
    if cotizacion.vehiculo_modelo:
        lineas.append(f'Modelo: {cotizacion.vehiculo_modelo}')
    if cotizacion.vehiculo_anio:
        lineas.append(f'Año: {cotizacion.vehiculo_anio}')
    if cotizacion.vehiculo_cilindraje:
        lineas.append(f'Cilindraje: {cotizacion.vehiculo_cilindraje}')
    if cotizacion.vehiculo_patente:
        lineas.append(f'Patente: {cotizacion.vehiculo_patente}')
    if cotizacion.tipo_motor_label:
        lineas.append(f'Motor: {cotizacion.tipo_motor_label}')
    return lineas


def metadata_cotizacion_mensaje(cotizacion: CotizacionCanal, *, estado: str = 'enviada') -> dict:
    repuestos_meta: list[dict] = []
    for rep in cotizacion.repuestos or []:
        cant = int(rep.get('cantidad') or 1)
        precio = int(rep.get('precio_unitario_clp') or 0)
        repuestos_meta.append({
            'nombre': str(rep.get('nombre') or 'Repuesto')[:200],
            'cantidad': max(1, cant),
            'precio_unitario_clp': max(0, precio),
        })
    advertencias = [str(a).strip() for a in (cotizacion.advertencias or []) if str(a).strip()]
    return {
        'tipo': 'cotizacion_canal',
        'cotizacion_id': cotizacion.id,
        'estado': estado,
        'servicio_nombre': cotizacion.servicio_nombre or '',
        'descripcion_problema': cotizacion.descripcion_problema or '',
        'modalidad': cotizacion.modalidad or 'taller',
        'vehiculo_marca': cotizacion.vehiculo_marca or '',
        'vehiculo_modelo': cotizacion.vehiculo_modelo or '',
        'vehiculo_anio': cotizacion.vehiculo_anio,
        'vehiculo_cilindraje': cotizacion.vehiculo_cilindraje or '',
        'vehiculo_patente': cotizacion.vehiculo_patente or '',
        'tipo_motor_label': cotizacion.tipo_motor_label or '',
        'mano_obra_clp': int(cotizacion.mano_obra_clp or 0),
        'costo_repuestos_clp': int(cotizacion.costo_repuestos_clp or 0),
        'total_clp': int(cotizacion.total_clp or 0),
        'duracion_minutos_estimada': cotizacion.duracion_minutos_estimada,
        'repuestos': repuestos_meta,
        'advertencias': advertencias,
        'interactive': True,
    }


def formatear_resumen_cotizacion(cotizacion: CotizacionCanal) -> str:
    modalidad_label = 'Servicio a domicilio' if cotizacion.modalidad == 'domicilio' else 'Servicio en taller'
    lineas = [
        f'*Cotización — {cotizacion.servicio_nombre}*',
        modalidad_label,
        '',
    ]
    lineas.extend(_linea_vehiculo_cotizacion(cotizacion))
    if cotizacion.descripcion_problema:
        lineas.extend(['', f'*Detalle del servicio:*', cotizacion.descripcion_problema[:400]])

    repuestos = cotizacion.repuestos or []
    if repuestos:
        lineas.extend(['', '*Repuestos estimados:*'])
        for rep in repuestos:
            nombre = rep.get('nombre', 'Repuesto')
            cant = int(rep.get('cantidad') or 1)
            precio = int(rep.get('precio_unitario_clp') or 0)
            sub = cant * precio
            lineas.append(
                f'• {nombre} x{cant} ({formatear_moneda_clp(precio)} c/u): {formatear_moneda_clp(sub)}',
            )
        lineas.append(f'Subtotal repuestos: {formatear_moneda_clp(cotizacion.costo_repuestos_clp)}')

    lineas.extend([
        '',
        f'Mano de obra: {formatear_moneda_clp(cotizacion.mano_obra_clp)}',
        f'*Total estimado: {formatear_moneda_clp(cotizacion.total_clp)}*',
    ])
    if cotizacion.duracion_minutos_estimada:
        lineas.append(f'Duración estimada: {cotizacion.duracion_minutos_estimada} min')

    advertencias = [str(a).strip() for a in (cotizacion.advertencias or []) if str(a).strip()]
    if advertencias:
        lineas.extend(['', '*Condiciones:*'])
        lineas.extend(f'• {adv}' for adv in advertencias)
    else:
        lineas.extend(['', '*Condiciones:*', '• Precios referenciales. Confirme con el taller antes de agendar.'])

    return '\n'.join(lineas)


def snapshot_desde_cotizacion(cotizacion: CotizacionCanal) -> dict:
    return {
        'servicio_nombre': cotizacion.servicio_nombre,
        'descripcion_problema': cotizacion.descripcion_problema,
        'modalidad': cotizacion.modalidad,
        'vehiculo_marca': cotizacion.vehiculo_marca,
        'vehiculo_modelo': cotizacion.vehiculo_modelo,
        'vehiculo_anio': cotizacion.vehiculo_anio,
        'vehiculo_patente': cotizacion.vehiculo_patente,
        'vehiculo_cilindraje': cotizacion.vehiculo_cilindraje,
        'tipo_motor': cotizacion.tipo_motor,
        'tipo_motor_label': cotizacion.tipo_motor_label,
        'repuestos': cotizacion.repuestos,
        'mano_obra_clp': int(cotizacion.mano_obra_clp or 0),
        'costo_repuestos_clp': int(cotizacion.costo_repuestos_clp or 0),
        'total_clp': int(cotizacion.total_clp or 0),
        'duracion_minutos_estimada': cotizacion.duracion_minutos_estimada,
        'advertencias': cotizacion.advertencias,
    }


def aplicar_edicion_cotizacion(cotizacion: CotizacionCanal, data: dict) -> CotizacionCanal:
    if 'servicio_nombre' in data:
        cotizacion.servicio_nombre = str(data['servicio_nombre'] or '')[:255]
    if 'descripcion_problema' in data:
        cotizacion.descripcion_problema = str(data['descripcion_problema'] or '')
    if 'modalidad' in data and data['modalidad'] in ('taller', 'domicilio'):
        cotizacion.modalidad = data['modalidad']
    if 'repuestos' in data and isinstance(data['repuestos'], list):
        cotizacion.repuestos = data['repuestos']
    if 'mano_obra_clp' in data:
        cotizacion.mano_obra_clp = int(data['mano_obra_clp'] or 0)
    if 'duracion_minutos_estimada' in data:
        val = data['duracion_minutos_estimada']
        cotizacion.duracion_minutos_estimada = int(val) if val else None
    costo_rep, mo, total = recalcular_totales(
        cotizacion.repuestos or [],
        int(cotizacion.mano_obra_clp or 0),
    )
    cotizacion.costo_repuestos_clp = costo_rep
    cotizacion.mano_obra_clp = mo
    cotizacion.total_clp = total
    return cotizacion


@transaction.atomic
def enviar_cotizacion_canal(cotizacion: CotizacionCanal, user) -> Message:
    if cotizacion.estado not in ('borrador',):
        raise ValueError('Solo se pueden enviar cotizaciones en borrador.')
    conversation = cotizacion.conversation
    if conversation.type != 'OMNICHANNEL':
        raise ValueError('La cotización debe estar ligada a una conversación omnicanal.')

    costo_rep, mo, total = recalcular_totales(
        cotizacion.repuestos or [],
        int(cotizacion.mano_obra_clp or 0),
    )
    cotizacion.costo_repuestos_clp = costo_rep
    cotizacion.mano_obra_clp = mo
    cotizacion.total_clp = total
    cotizacion.save(
        update_fields=['costo_repuestos_clp', 'mano_obra_clp', 'total_clp', 'actualizado_en'],
    )

    resumen = formatear_resumen_cotizacion(cotizacion)
    meta = metadata_cotizacion_mensaje(cotizacion, estado='enviada')
    message = Message.objects.create(
        conversation=conversation,
        sender=user,
        content=resumen,
        direction='outbound',
        channel_metadata=meta,
    )
    cotizacion.message_envio = message
    cotizacion.estado = 'enviada'
    cotizacion.enviada_en = timezone.now()
    cotizacion.save(
        update_fields=['message_envio', 'estado', 'enviada_en', 'actualizado_en'],
    )

    from mecanimovilapp.apps.omnichannel.services.broadcast import (
        broadcast_to_participants,
        build_chat_payload,
    )
    from mecanimovilapp.apps.omnichannel.utils import channel_to_api_slug

    channel_slug = channel_to_api_slug(conversation.source_channel)
    sender_name = (
        f'{user.first_name or ""} {user.last_name or ""}'.strip()
        or getattr(user, 'username', '')
        or 'Taller'
    )
    payload = build_chat_payload(
        conversation=conversation,
        message=message,
        channel_slug=channel_slug,
        es_proveedor=True,
        sender_name=sender_name,
        external_contact=getattr(conversation, 'external_contact', None),
    )
    broadcast_to_participants(conversation, payload)

    return message


def _parse_button_id(button_id: str) -> tuple[str, int] | None:
    if not button_id:
        return None
    parts = button_id.split('_')
    if len(parts) < 3:
        return None
    accion = parts[1]
    try:
        cot_id = int(parts[2])
    except ValueError:
        return None
    if accion not in ('aceptar', 'rechazar'):
        return None
    return accion, cot_id


@transaction.atomic
def procesar_respuesta_interactive_cotizacion(
    *,
    button_id: str,
    conversation: Conversation,
) -> CotizacionCanal | None:
    parsed = _parse_button_id(button_id)
    if not parsed:
        return None
    accion, cot_id = parsed
    cotizacion = CotizacionCanal.objects.select_for_update().filter(
        pk=cot_id,
        conversation=conversation,
    ).first()
    if cotizacion is None:
        logger.warning('Cotización %s no encontrada para conversación %s', cot_id, conversation.id)
        return None
    if cotizacion.estado != 'enviada':
        return cotizacion

    ahora = timezone.now()
    if accion == 'aceptar':
        cotizacion.estado = 'aceptada'
        cotizacion.aceptada_en = ahora
        cotizacion.save(update_fields=['estado', 'aceptada_en', 'actualizado_en'])
    else:
        cotizacion.estado = 'rechazada'
        cotizacion.rechazada_en = ahora
        cotizacion.save(update_fields=['estado', 'rechazada_en', 'actualizado_en'])

    if cotizacion.message_envio_id:
        meta = dict(cotizacion.message_envio.channel_metadata or {})
        meta['estado'] = cotizacion.estado
        Message.objects.filter(pk=cotizacion.message_envio_id).update(channel_metadata=meta)

    Message.objects.create(
        conversation=conversation,
        sender=None,
        content=(
            '✅ Cotización aceptada. El taller coordinará el agendamiento.'
            if accion == 'aceptar'
            else '❌ Cotización rechazada.'
        ),
        direction='inbound',
        channel_metadata={
            'tipo': 'cotizacion_canal_respuesta',
            'cotizacion_id': cotizacion.id,
            'estado': cotizacion.estado,
        },
    )
    return cotizacion
