"""Notificaciones del agente IA al taller."""
from __future__ import annotations

import logging

from mecanimovilapp.apps.ordenes.models import CotizacionCanal

logger = logging.getLogger(__name__)


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

    titulo = 'Cotización enviada por Agente IA'
    mensaje = (
        f'Se envió al cliente la cotización de "{cotizacion.servicio_nombre or "servicio"}" '
        f'por {int(cotizacion.total_clp or 0):,} CLP. Esperando aceptación.'.replace(',', '.')
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


def notificar_cotizacion_borrador_agente(
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

    titulo = 'Cotización IA lista para revisar'
    mensaje = (
        f'El agente generó un borrador para "{cotizacion.servicio_nombre or "servicio"}". '
        f'Revisa y ajusta los precios antes de enviar al cliente.'
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


def notificar_escalamiento_humano(
    *,
    proveedor_user_id: int,
    conversation_id: int,
    preview: str = '',
) -> None:
    from mecanimovilapp.apps.usuarios.models import Notificacion
    from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification
    from django.contrib.auth import get_user_model

    User = get_user_model()
    usuario = User.objects.filter(pk=proveedor_user_id).first()
    if not usuario:
        return

    titulo = 'Cliente necesita atención'
    mensaje = preview[:140] or 'Un cliente requiere que respondas personalmente en el chat.'
    data = {
        'type': 'agente_ia_escalamiento',
        'conversation_id': conversation_id,
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
