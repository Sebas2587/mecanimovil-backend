"""Notificaciones del agente IA al taller."""
from __future__ import annotations

import logging

from mecanimovilapp.apps.ordenes.models import CotizacionCanal

logger = logging.getLogger(__name__)


def _emitir_ws_agente(proveedor_user_id: int, event_type: str, **payload) -> None:
    from mecanimovilapp.apps.agente_ia.services.ws_broadcast import emitir_evento_ws_agente_ia

    emitir_evento_ws_agente_ia(
        proveedor_user_id=proveedor_user_id,
        event_type=event_type,
        **payload,
    )


def notificar_cotizacion_enviada_agente(
    *,
    proveedor_user_id: int,
    cotizacion: CotizacionCanal,
    conversation_id: int,
) -> None:
    from mecanimovilapp.apps.usuarios.models import Notificacion
    from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification
    from django.contrib.auth import get_user_model

    User = get_user_model()
    usuario = User.objects.filter(pk=proveedor_user_id).first()
    if not usuario:
        return

    titulo = 'Cotización enviada al cliente'
    mensaje = (
        f'Se envió la cotización de "{cotizacion.servicio_nombre or "servicio"}" '
        f'(${int(cotizacion.total_clp or 0):,} CLP). El cliente puede aceptar o rechazar '
        f'en el enlace de la cotización.'.replace(',', '.')
    )
    data = {
        'type': 'agente_ia_cotizacion_enviada',
        'cotizacion_id': cotizacion.id,
        'conversation_id': conversation_id,
    }
    Notificacion.crear_unica(
        usuario,
        tipo='system',
        titulo=titulo,
        mensaje=mensaje,
        data=data,
        ventana_horas=2,
        dedup_key={'type': 'agente_ia_cotizacion_enviada', 'cotizacion_id': cotizacion.id},
    )
    try:
        send_expo_push_notification.delay(proveedor_user_id, titulo, mensaje, data)
    except Exception as exc:
        logger.warning('No se pudo encolar push cotización enviada: %s', exc)
    _emitir_ws_agente(proveedor_user_id, 'agente_ia_cotizacion_enviada', **data)


def notificar_cotizacion_aceptada_agente(
    *,
    proveedor_user_id: int,
    cotizacion: CotizacionCanal,
    conversation_id: int,
    cita_id: int | None = None,
) -> None:
    from mecanimovilapp.apps.usuarios.models import Notificacion
    from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification
    from django.contrib.auth import get_user_model

    User = get_user_model()
    usuario = User.objects.filter(pk=proveedor_user_id).first()
    if not usuario:
        return

    titulo = 'Cliente aceptó cotización'
    mensaje = (
        f'{cotizacion.cliente_nombre or "Un cliente"} aceptó '
        f'"{cotizacion.servicio_nombre or "servicio"}". Está en tu bandeja para agendar.'
    )
    data = {
        'type': 'agente_ia_cotizacion_aceptada',
        'cotizacion_id': cotizacion.id,
        'conversation_id': conversation_id,
        'cita_id': cita_id,
    }
    Notificacion.crear_unica(
        usuario,
        tipo='system',
        titulo=titulo,
        mensaje=mensaje,
        data=data,
        ventana_horas=6,
        dedup_key={'type': 'agente_ia_cotizacion_aceptada', 'cotizacion_id': cotizacion.id},
    )
    try:
        send_expo_push_notification.delay(proveedor_user_id, titulo, mensaje, data)
    except Exception as exc:
        logger.warning('No se pudo encolar push cotización aceptada: %s', exc)
    _emitir_ws_agente(proveedor_user_id, 'agente_ia_cotizacion_aceptada', **data)


def notificar_cotizacion_borrador_agente(
    *,
    proveedor_user_id: int,
    cotizacion: CotizacionCanal,
    conversation_id: int,
    precio_desde_catalogo: bool = False,
    listo_para_enviar: bool = False,
    pendientes_revision: list[str] | None = None,
    reabierta: bool = False,
) -> None:
    from mecanimovilapp.apps.usuarios.models import Notificacion
    from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification
    from django.contrib.auth import get_user_model

    User = get_user_model()
    usuario = User.objects.filter(pk=proveedor_user_id).first()
    if not usuario:
        return

    pendientes = [p for p in (pendientes_revision or []) if p]
    servicio = cotizacion.servicio_nombre or 'servicio'
    total_txt = f'${int(cotizacion.total_clp or 0):,} CLP'.replace(',', '.')

    if reabierta:
        titulo = 'Cotización actualizada por el cliente'
        mensaje = (
            f'El cliente pidió agregar o modificar algo en "{servicio}". '
            f'Revisa la misma cotización en Cotizar con IA y vuelve a enviarla si hace falta.'
        )
    elif listo_para_enviar:
        titulo = 'Cotización lista para enviar'
        mensaje = (
            f'El borrador de "{servicio}" está completo ({total_txt}). '
            f'Revisa en Cotizar con IA y envíala al cliente con un clic.'
        )
    else:
        titulo = 'Cotización con pendientes'
        pendientes_txt = '; '.join(pendientes[:4])
        if precio_desde_catalogo:
            mensaje = (
                f'El agente actualizó el borrador de "{servicio}" ({total_txt}). '
                f'Pendiente: {pendientes_txt}. Revisa en Cotizar con IA antes de enviar.'
            )
        else:
            mensaje = (
                f'El agente actualizó el borrador de "{servicio}". '
                f'Pendiente: {pendientes_txt}. Completa el valor en Cotizar con IA y envíala tú.'
            )
    data = {
        'type': 'agente_ia_cotizacion_borrador',
        'cotizacion_id': cotizacion.id,
        'conversation_id': conversation_id,
    }

    Notificacion.crear_unica(
        usuario,
        tipo='system',
        titulo=titulo,
        mensaje=mensaje,
        data=data,
        ventana_horas=2,
        dedup_key={'type': 'agente_ia_cotizacion_borrador', 'cotizacion_id': cotizacion.id},
    )

    try:
        send_expo_push_notification.delay(
            proveedor_user_id,
            titulo,
            mensaje,
            data,
        )
    except Exception as exc:
        logger.warning('No se pudo encolar push cotización agente: %s', exc)
    _emitir_ws_agente(proveedor_user_id, 'agente_ia_cotizacion_borrador', **data)


def notificar_cotizacion_rechazada_agente(
    *,
    proveedor_user_id: int,
    cotizacion: CotizacionCanal,
    conversation_id: int,
) -> None:
    from mecanimovilapp.apps.usuarios.models import Notificacion
    from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification
    from django.contrib.auth import get_user_model

    User = get_user_model()
    usuario = User.objects.filter(pk=proveedor_user_id).first()
    if not usuario:
        return

    titulo = 'Cliente rechazó cotización'
    mensaje = (
        f'{cotizacion.cliente_nombre or "Un cliente"} rechazó '
        f'"{cotizacion.servicio_nombre or "servicio"}". '
        'El agente está ofreciendo ajustar si el cliente responde.'
    )
    data = {
        'type': 'agente_ia_cotizacion_rechazada',
        'cotizacion_id': cotizacion.id,
        'conversation_id': conversation_id,
    }
    Notificacion.crear_unica(
        usuario,
        tipo='system',
        titulo=titulo,
        mensaje=mensaje,
        data=data,
        ventana_horas=6,
        dedup_key={'type': 'agente_ia_cotizacion_rechazada', 'cotizacion_id': cotizacion.id},
    )
    try:
        send_expo_push_notification.delay(proveedor_user_id, titulo, mensaje, data)
    except Exception as exc:
        logger.warning('No se pudo encolar push cotización rechazada: %s', exc)
    _emitir_ws_agente(proveedor_user_id, 'agente_ia_cotizacion_rechazada', **data)


def notificar_cita_confirmada_por_agente(
    *,
    proveedor_user_id: int,
    cita,
    conversation_id: int,
) -> None:
    from mecanimovilapp.apps.usuarios.models import Notificacion
    from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification
    from django.contrib.auth import get_user_model

    User = get_user_model()
    usuario = User.objects.filter(pk=proveedor_user_id).first()
    if not usuario:
        return

    det = getattr(cita, 'detalle', None)
    cliente = getattr(det, 'cliente_nombre', None) or 'Cliente'
    servicio = getattr(det, 'servicio_nombre', None) or 'servicio'
    fecha = cita.fecha_servicio.strftime('%d/%m/%Y') if cita.fecha_servicio else ''
    hora = cita.hora_servicio.strftime('%H:%M') if cita.hora_servicio else ''

    titulo = 'Cita agendada por Agente IA'
    mensaje = f'{cliente} confirmó {servicio} para el {fecha} a las {hora}.'
    data = {
        'type': 'agente_ia_cita_confirmada',
        'cita_id': cita.id,
        'conversation_id': conversation_id,
    }
    Notificacion.crear_unica(
        usuario,
        tipo='system',
        titulo=titulo,
        mensaje=mensaje,
        data=data,
        ventana_horas=6,
        dedup_key={'type': 'agente_ia_cita_confirmada', 'cita_id': cita.id},
    )
    try:
        send_expo_push_notification.delay(proveedor_user_id, titulo, mensaje, data)
    except Exception as exc:
        logger.warning('No se pudo encolar push cita confirmada agente: %s', exc)
    _emitir_ws_agente(proveedor_user_id, 'agente_ia_cita_confirmada', **data)


def notificar_escalamiento_humano(
    *,
    proveedor_user_id: int,
    conversation_id: int,
    preview: str = '',
    lead_categoria: str = '',
) -> None:
    from mecanimovilapp.apps.agente_ia.services.reglas_lead import prioridad_escalamiento_por_lead
    from mecanimovilapp.apps.usuarios.models import Notificacion
    from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification
    from django.contrib.auth import get_user_model

    User = get_user_model()
    usuario = User.objects.filter(pk=proveedor_user_id).first()
    if not usuario:
        return

    prioridad = prioridad_escalamiento_por_lead(lead_categoria)
    if prioridad == 'alta':
        titulo = 'Lead calificado — atención urgente'
        mensaje = preview[:140] or 'Un lead listo para cerrar necesita que respondas personalmente.'
    else:
        titulo = 'Cliente necesita atención'
        mensaje = preview[:140] or 'Un cliente requiere que respondas personalmente en el chat.'
    data = {
        'type': 'agente_ia_escalamiento',
        'conversation_id': conversation_id,
        'prioridad': prioridad,
        'lead_categoria': (lead_categoria or '').strip(),
    }

    Notificacion.crear_unica(
        usuario,
        tipo='system',
        titulo=titulo,
        mensaje=mensaje,
        data=data,
        ventana_horas=1,
        dedup_key={'type': 'agente_ia_escalamiento', 'conversation_id': conversation_id},
    )

    try:
        send_expo_push_notification.delay(
            proveedor_user_id,
            titulo,
            mensaje,
            data,
        )
    except Exception as exc:
        logger.warning('No se pudo encolar push escalamiento agente: %s', exc)
    _emitir_ws_agente(proveedor_user_id, 'agente_ia_escalamiento', **data)
