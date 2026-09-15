"""Avisa al cliente cuando el taller confirma día y hora de la visita."""
from __future__ import annotations

import logging

from django.utils import timezone

from mecanimovilapp.apps.chat.models import Message

logger = logging.getLogger(__name__)

_DIAS_ES = (
    'lunes',
    'martes',
    'miércoles',
    'jueves',
    'viernes',
    'sábado',
    'domingo',
)


def formatear_slot_cita_cliente(cita) -> str:
    fecha = getattr(cita, 'fecha_servicio', None)
    hora = getattr(cita, 'hora_servicio', None)
    hora_txt = hora.strftime('%H:%M') if hora else ''
    if not fecha:
        return hora_txt or 'horario por confirmar'
    dia = _DIAS_ES[fecha.weekday()]
    fecha_txt = f'{dia} {fecha.day}/{fecha.month:02d}'
    if hora_txt:
        return f'{fecha_txt} a las {hora_txt}'
    return fecha_txt


def texto_cita_agendada_cliente(cita) -> str:
    det = getattr(cita, 'detalle', None)
    servicio = (getattr(det, 'servicio_nombre', None) or '').strip() or 'tu servicio'
    taller = ''
    if getattr(cita, 'taller', None) is not None:
        taller = (cita.taller.nombre or '').strip()
    slot = formatear_slot_cita_cliente(cita)
    texto = f'¡Listo! Quedó agendado {servicio} para el {slot}.'
    if taller:
        texto += f' Te esperamos en {taller}.'
    else:
        texto += ' Te esperamos.'
    return texto


def resolver_conversation_cita(cita):
    conv = getattr(cita, 'conversation_origen', None)
    if conv is not None:
        return conv
    cot = getattr(cita, 'cotizacion_canal_origen', None)
    if cot is not None:
        return getattr(cot, 'conversation', None)
    return None


def _taller_nombre_conversacion(conversation, cita) -> str:
    if getattr(cita, 'taller', None) is not None and (cita.taller.nombre or '').strip():
        return cita.taller.nombre.strip()
    contact = getattr(conversation, 'external_contact', None)
    connection = contact.connection if contact else None
    usuario = getattr(connection, 'usuario', None)
    taller = getattr(usuario, 'taller', None)
    if taller is not None and (taller.nombre or '').strip():
        return taller.nombre.strip()
    return 'Tu taller'


def _sender_name(user) -> str:
    if user is None:
        return 'Taller'
    return (
        f'{getattr(user, "first_name", "") or ""} {getattr(user, "last_name", "") or ""}'.strip()
        or getattr(user, 'username', '')
        or 'Taller'
    )


def _push_app_participantes(conversation, *, user, texto: str, cita) -> None:
    from mecanimovilapp.apps.omnichannel.services.broadcast import send_chat_push
    from mecanimovilapp.apps.usuarios.models import Notificacion

    skip_id = getattr(user, 'id', None)
    for participant in conversation.participants.all():
        if skip_id and participant.id == skip_id:
            continue
        data = {
            'type': 'cita_agendada',
            'cita_id': cita.id,
            'conversation_id': conversation.id,
        }
        Notificacion.crear_unica(
            participant,
            tipo='order_update',
            titulo='Visita agendada',
            mensaje=texto[:200],
            data=data,
            ventana_horas=6,
            dedup_key={'type': 'cita_agendada', 'cita_id': cita.id},
        )
        try:
            send_chat_push(
                participant.id,
                channel_code=conversation.source_channel,
                sender_name=_sender_name(user),
                preview=texto[:140],
                conversation_id=str(conversation.id),
            )
        except Exception:
            logger.warning('No se pudo encolar push chat cita agendada user=%s', participant.id)


def _entregar_mensaje_conversacion(*, conversation, message, cita, use_template: bool) -> None:
    from mecanimovilapp.apps.omnichannel.services.broadcast import (
        broadcast_to_participants,
        build_chat_payload,
    )
    from mecanimovilapp.apps.omnichannel.utils import channel_to_api_slug

    if use_template:
        from mecanimovilapp.apps.omnichannel.services.whatsapp_templates import (
            KIND_CITA,
            payload_cita,
        )

        slot = formatear_slot_cita_cliente(cita)
        tpl = payload_cita(taller=_taller_nombre_conversacion(conversation, cita), slot=slot)
        meta = dict(message.channel_metadata or {})
        meta['whatsapp_template'] = True
        meta['template_kind'] = KIND_CITA
        meta['template_name'] = tpl.get('name') or ''
        meta['template_language'] = tpl.get('language') or 'es'
        meta['template_components'] = tpl.get('components') or []
        message.channel_metadata = meta
        message.save(update_fields=['channel_metadata'])

    channel_slug = channel_to_api_slug(conversation.source_channel)
    payload = build_chat_payload(
        conversation=conversation,
        message=message,
        channel_slug=channel_slug,
        es_proveedor=True,
        sender_name=_sender_name(message.sender),
        external_contact=getattr(conversation, 'external_contact', None),
    )
    broadcast_to_participants(conversation, payload)
    if conversation.source_channel != 'APP':
        from mecanimovilapp.apps.omnichannel.tasks import send_meta_message

        send_meta_message.delay(message.id)
    else:
        _push_app_participantes(
            conversation,
            user=message.sender,
            texto=message.content or '',
            cita=cita,
        )


def avisar_cliente_cita_agendada(cita, *, user) -> dict:
    """Envía al cliente el día y la hora que el taller acaba de confirmar.

    - App / ventana Meta abierta: mensaje libre en el chat.
    - WhatsApp fuera de 24 h: plantilla Utility de cita, si está habilitada.
    No debe usarse desde el agente IA (ese flujo ya escribe en el hilo).
    """
    from mecanimovilapp.apps.omnichannel.services.outbound_guard import (
        connection_activa,
        customer_care_window_open,
        plantillas_whatsapp_habilitadas,
    )
    from mecanimovilapp.apps.omnichannel.services.whatsapp_templates import (
        KIND_CITA,
        template_nombre,
    )
    from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal

    cita = (
        CitaAgendaPersonal.objects.select_related(
            'detalle',
            'taller',
            'conversation_origen',
            'cotizacion_canal_origen__conversation',
        )
        .filter(pk=cita.pk)
        .first()
        or cita
    )

    conversation = resolver_conversation_cita(cita)
    texto = texto_cita_agendada_cliente(cita)
    if conversation is None:
        logger.info('Cita %s confirmada sin conversación; no hay canal para avisar al cliente', cita.id)
        return {'enviado': False, 'via': 'sin_canal'}

    use_template = False
    enviar_meta = conversation.source_channel == 'APP'
    if conversation.source_channel != 'APP':
        ventana_abierta = customer_care_window_open(conversation)
        conexion_ok = connection_activa(conversation) is not None
        if ventana_abierta and conexion_ok:
            enviar_meta = True
        elif (
            conversation.source_channel == 'WHATSAPP'
            and conexion_ok
            and plantillas_whatsapp_habilitadas()
            and template_nombre(KIND_CITA)
        ):
            use_template = True
            enviar_meta = True

    message = Message.objects.create(
        conversation=conversation,
        sender=user,
        content=texto,
        direction='outbound',
        channel_metadata={'cita_agendada': True, 'cita_id': cita.id},
    )
    conversation.updated_at = timezone.now()
    conversation.save(update_fields=['updated_at'])

    if enviar_meta or conversation.source_channel == 'APP':
        try:
            _entregar_mensaje_conversacion(
                conversation=conversation,
                message=message,
                cita=cita,
                use_template=use_template,
            )
        except Exception:
            logger.exception('No se pudo entregar aviso de cita %s al cliente', cita.id)
            return {'enviado': False, 'via': 'error'}
        via = 'whatsapp_template' if use_template else (
            'app' if conversation.source_channel == 'APP' else 'sesion_meta'
        )
        return {'enviado': True, 'via': via}

    logger.info(
        'Cita %s confirmada; ventana Meta cerrada y sin plantilla. Aviso quedó en el chat interno.',
        cita.id,
    )
    return {'enviado': False, 'via': 'ventana_cerrada'}
