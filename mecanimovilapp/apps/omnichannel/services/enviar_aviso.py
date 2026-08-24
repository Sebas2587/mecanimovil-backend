"""Aviso Utility de WhatsApp cuando la ventana de 24 h está cerrada."""
from __future__ import annotations

from datetime import date

from django.utils import timezone

from mecanimovilapp.apps.chat.models import Message
from mecanimovilapp.apps.omnichannel.services.outbound_guard import (
    CHANNEL_DISCONNECTED_MESSAGE,
    customer_care_window_open,
    connection_activa,
    plantillas_whatsapp_habilitadas,
)
from mecanimovilapp.apps.omnichannel.services.whatsapp_templates import (
    KIND_AVISO,
    KIND_CITA,
    payload_aviso,
    payload_cita,
    template_nombre,
)


class AvisoNoDisponibleError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


def _taller_nombre(conversation) -> str:
    contact = getattr(conversation, 'external_contact', None)
    connection = contact.connection if contact else None
    usuario = getattr(connection, 'usuario', None)
    taller = getattr(usuario, 'taller', None)
    if taller is not None and (taller.nombre or '').strip():
        return taller.nombre.strip()
    return 'Tu taller'


def _formatear_slot_cita(cita) -> str:
    if getattr(cita, 'horario_por_confirmar', False):
        return 'horario por confirmar'
    fecha = cita.fecha_servicio.strftime('%d/%m/%Y') if cita.fecha_servicio else ''
    hora = cita.hora_servicio.strftime('%H:%M') if cita.hora_servicio else ''
    if fecha and hora:
        return f'{fecha} a las {hora}'
    return fecha or 'horario por confirmar'


def resolver_cita_para_aviso(conversation):
    from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal

    qs = CitaAgendaPersonal.objects.filter(
        conversation_origen=conversation,
        estado='activa',
    )
    por_confirmar = qs.filter(horario_por_confirmar=True).order_by('-fecha_creacion').first()
    if por_confirmar:
        return por_confirmar
    return (
        qs.filter(horario_por_confirmar=False, fecha_servicio__gte=date.today())
        .order_by('fecha_servicio', 'hora_servicio')
        .first()
    )


def _teaser(kind: str, taller: str, slot: str) -> str:
    if kind == KIND_CITA:
        return f'{taller} te recuerda tu visita: {slot}. Responde este mensaje para continuar.'
    return f'{taller} te dejó un aviso. Responde este mensaje para continuar.'


def enviar_aviso_conversacion(*, conversation, user) -> Message:
    if not plantillas_whatsapp_habilitadas():
        raise AvisoNoDisponibleError(
            'plantillas_deshabilitadas',
            'Por ahora no enviamos avisos por WhatsApp. '
            'Cotiza y comparte el link por el canal que prefieras.',
        )
    if conversation.source_channel == 'APP':
        raise AvisoNoDisponibleError(
            'ventana_abierta',
            'En la app puedes escribir en el chat.',
        )
    if customer_care_window_open(conversation):
        raise AvisoNoDisponibleError(
            'ventana_abierta',
            'La ventana de 24 h está abierta. Escribe en el chat.',
        )
    if conversation.source_channel != 'WHATSAPP':
        raise AvisoNoDisponibleError(
            'canal_sin_plantilla',
            'Instagram y Messenger no permiten avisos fuera de las 24 h. '
            'Espera a que el cliente escriba o comparte el link de la cotización.',
            http_status=403,
        )
    if connection_activa(conversation) is None:
        raise AvisoNoDisponibleError(
            'channel_disconnected',
            CHANNEL_DISCONNECTED_MESSAGE,
            http_status=403,
        )

    cita = resolver_cita_para_aviso(conversation)
    taller = _taller_nombre(conversation)
    if cita is not None and template_nombre(KIND_CITA):
        kind = KIND_CITA
        slot = _formatear_slot_cita(cita)
        tpl = payload_cita(taller=taller, slot=slot)
        teaser = _teaser(kind, taller, slot)
    else:
        kind = KIND_AVISO
        tpl = payload_aviso(taller=taller)
        teaser = _teaser(kind, taller, '')
    if not tpl.get('name'):
        raise AvisoNoDisponibleError(
            'plantilla_no_configurada',
            'Falta una plantilla Utility de WhatsApp (aviso o cita) en Meta. '
            'Mientras tanto espera a que el cliente escriba o comparte un link.',
        )

    message = Message.objects.create(
        conversation=conversation,
        sender=user,
        content=teaser,
        direction='outbound',
        channel_metadata={
            'whatsapp_template': True,
            'template_kind': kind,
            'template_name': tpl['name'],
            'template_language': tpl['language'],
            'template_components': tpl['components'],
        },
    )
    conversation.updated_at = timezone.now()
    conversation.save(update_fields=['updated_at'])

    from mecanimovilapp.apps.omnichannel.services.broadcast import (
        broadcast_to_participants,
        build_chat_payload,
    )
    from mecanimovilapp.apps.omnichannel.tasks import send_meta_message
    from mecanimovilapp.apps.omnichannel.utils import channel_to_api_slug

    sender_name = (
        f'{user.first_name or ""} {user.last_name or ""}'.strip()
        or getattr(user, 'username', '')
        or 'Taller'
    )
    payload = build_chat_payload(
        conversation=conversation,
        message=message,
        channel_slug=channel_to_api_slug(conversation.source_channel),
        es_proveedor=True,
        sender_name=sender_name,
        external_contact=getattr(conversation, 'external_contact', None),
    )
    broadcast_to_participants(conversation, payload)
    send_meta_message.delay(message.id)
    return message
