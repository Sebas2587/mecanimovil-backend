"""Coexistencia: el taller sigue usando la app WhatsApp Business del teléfono.

Meta avisa por webhook de tres cosas que el chat debe reflejar:
- ``smb_message_echoes``: lo que el taller escribe desde el teléfono. Se guarda
  como mensaje saliente manual, se muestra en el chat y pausa al agente IA.
- ``history``: hasta 6 meses de chats que el taller aceptó compartir al vincular.
- ``smb_app_state_sync``: nombres de la agenda del teléfono.
"""
from __future__ import annotations

import logging
from typing import Any

from django.db import transaction

from mecanimovilapp.apps.chat.models import Message
from mecanimovilapp.apps.omnichannel.models import ExternalContact, ProviderChannelConnection
from mecanimovilapp.apps.omnichannel.services.broadcast import (
    broadcast_to_participants,
    build_chat_payload,
)
from mecanimovilapp.apps.omnichannel.services.meta_media import media_label, parse_whatsapp_media
from mecanimovilapp.apps.omnichannel.utils import channel_to_api_slug

logger = logging.getLogger(__name__)

ORIGEN_APP_TELEFONO = 'app_whatsapp'
ORIGEN_HISTORIAL = 'historial_whatsapp'


def texto_de_mensaje_meta(msg: dict[str, Any]) -> tuple[str, dict | None]:
    """Texto visible y adjunto (si lo hay) de un mensaje tal como lo manda Meta."""
    tipo = msg.get('type') or ''
    if tipo == 'text':
        return (msg.get('text') or {}).get('body', ''), None
    if tipo == 'button':
        return (msg.get('button') or {}).get('text', ''), None
    if tipo == 'interactive':
        interactive = msg.get('interactive') or {}
        btn = interactive.get('button_reply') or interactive.get('list_reply') or {}
        return btn.get('title') or '', None
    if tipo == 'media_placeholder':
        return 'Adjunto del historial (no disponible)', None
    if tipo == 'reaction':
        return (msg.get('reaction') or {}).get('emoji', ''), None
    media = parse_whatsapp_media(msg)
    if media:
        return media.get('caption') or media_label(media.get('kind')), media
    return '', None


def _conversacion_para(connection: ProviderChannelConnection, wa_id: str, nombre: str = ''):
    from mecanimovilapp.apps.omnichannel.services.omnichannel_service import OmnichannelService

    contact = OmnichannelService.get_or_create_external_contact(
        connection, wa_id, display_name=nombre, phone=wa_id,
    )
    conversation, _ = OmnichannelService.get_or_create_conversation(connection, contact)
    return contact, conversation


@transaction.atomic
def registrar_eco_telefono(connection: ProviderChannelConnection, echo: dict[str, Any]) -> Message | None:
    """Mensaje que el taller mandó desde la app del teléfono."""
    wa_id = str(echo.get('to') or '').strip()
    wamid = echo.get('id')
    if not wa_id or not wamid:
        return None
    if Message.objects.filter(external_message_id=wamid).exists():
        return None
    texto, media = texto_de_mensaje_meta(echo)
    if not texto and not media:
        return None

    contact, conversation = _conversacion_para(connection, wa_id)
    message = Message.objects.create(
        conversation=conversation,
        sender=connection.usuario,
        content=texto,
        direction='outbound',
        external_message_id=wamid,
        channel_metadata={
            'origen': ORIGEN_APP_TELEFONO,
            'message_type': echo.get('type'),
            'provider_timestamp': echo.get('timestamp'),
            'media': media,
        },
    )
    conversation.save()

    payload = build_chat_payload(
        conversation=conversation,
        message=message,
        channel_slug=channel_to_api_slug(connection.channel),
        es_proveedor=True,
        sender_name=connection.display_name or 'Taller',
        external_contact=contact,
    )
    broadcast_to_participants(conversation, payload)

    if media:
        from mecanimovilapp.apps.omnichannel.tasks import fetch_inbound_meta_media

        transaction.on_commit(lambda: fetch_inbound_meta_media.delay(message.id))
    else:
        from mecanimovilapp.apps.agente_ia.hooks import encolar_agente_para_mensaje

        # Saliente manual: pausa al agente en este chat para que no pise al taller.
        encolar_agente_para_mensaje(message)
    return message


def importar_historial(connection: ProviderChannelConnection, value: dict[str, Any]) -> int:
    """Chats compartidos al vincular. Sin push, sin agente, sin broadcast por mensaje."""
    numero_taller = str((value.get('metadata') or {}).get('display_phone_number') or '')
    numero_taller = ''.join(ch for ch in numero_taller if ch.isdigit())
    creados = 0
    for bloque in value.get('history') or []:
        for thread in bloque.get('threads') or []:
            wa_id = str(thread.get('id') or '').strip()
            mensajes = thread.get('messages') or []
            if not wa_id or not mensajes:
                continue
            creados += _importar_hilo(connection, wa_id, numero_taller, mensajes)
    if creados:
        logger.info('Historial WhatsApp importado conn=%s mensajes=%s', connection.id, creados)
    return creados


@transaction.atomic
def _importar_hilo(connection, wa_id: str, numero_taller: str, mensajes: list[dict]) -> int:
    from mecanimovilapp.apps.omnichannel.services.omnichannel_service import _epoch_meta

    _, conversation = _conversacion_para(connection, wa_id)
    wamids = [m.get('id') for m in mensajes if m.get('id')]
    existentes = set(
        Message.objects.filter(external_message_id__in=wamids).values_list('external_message_id', flat=True)
    )
    creados = 0
    for msg in mensajes:
        wamid = msg.get('id')
        if not wamid or wamid in existentes:
            continue
        texto, media = texto_de_mensaje_meta(msg)
        if not texto:
            continue
        remitente = ''.join(ch for ch in str(msg.get('from') or '') if ch.isdigit())
        del_taller = bool(numero_taller) and remitente == numero_taller
        message = Message.objects.create(
            conversation=conversation,
            sender=connection.usuario if del_taller else None,
            content=texto,
            direction='outbound' if del_taller else 'inbound',
            external_message_id=wamid,
            is_read=True,
            channel_metadata={
                'origen': ORIGEN_HISTORIAL,
                'message_type': msg.get('type'),
                'provider_timestamp': msg.get('timestamp'),
                'estado_historial': (msg.get('history_context') or {}).get('status'),
                'media': media,
            },
        )
        momento = _epoch_meta(msg.get('timestamp'))
        if momento:
            # timestamp es auto_now_add: se corrige para respetar el orden real del chat.
            Message.objects.filter(pk=message.pk).update(timestamp=momento)
        creados += 1
    if creados:
        conversation.save()
    return creados


def sincronizar_contactos(connection: ProviderChannelConnection, value: dict[str, Any]) -> int:
    """Pone nombre de la agenda del teléfono a los contactos que ya tienen chat."""
    actualizados = 0
    for item in value.get('state_sync') or []:
        if item.get('type') != 'contact':
            continue
        contacto = item.get('contact') or {}
        wa_id = str(contacto.get('phone_number') or '').strip()
        nombre = (contacto.get('full_name') or contacto.get('first_name') or '').strip()
        if not wa_id or not nombre:
            continue
        wa_id = ''.join(ch for ch in wa_id if ch.isdigit())
        actualizados += ExternalContact.objects.filter(
            connection=connection, external_id=wa_id,
        ).exclude(display_name=nombre).update(display_name=nombre)
    return actualizados


def procesar_cambio_coexistencia(field: str, value: dict[str, Any]) -> bool:
    """True si el campo era de coexistencia (ya procesado o descartado)."""
    if field not in ('smb_message_echoes', 'history', 'smb_app_state_sync'):
        return False
    phone_number_id = (value.get('metadata') or {}).get('phone_number_id')
    connection = ProviderChannelConnection.objects.filter(
        phone_number_id=phone_number_id, channel='WHATSAPP',
    ).select_related('usuario').first()
    if not connection:
        logger.warning('Coexistencia %s sin conexión phone_number_id=%s', field, phone_number_id)
        return True
    try:
        if field == 'smb_message_echoes':
            for echo in value.get('message_echoes') or []:
                registrar_eco_telefono(connection, echo)
        elif field == 'history':
            importar_historial(connection, value)
        else:
            sincronizar_contactos(connection, value)
    except Exception:
        logger.exception('Error procesando %s conn=%s', field, connection.id)
    return True
