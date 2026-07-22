"""Notificaciones del agente IA al taller."""
from __future__ import annotations

import logging

from mecanimovilapp.apps.ordenes.models import CotizacionCanal

logger = logging.getLogger(__name__)


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
