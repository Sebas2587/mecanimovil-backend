"""Validaciones antes de enviar mensajes salientes por Meta.

Política de ventana de atención (customer care):
- WhatsApp, Messenger e Instagram: 24 h desde el último mensaje inbound del cliente.
- Dentro de la ventana: texto libre / interactivos.
- Fuera de la ventana:
  - Chat libre: bloqueado (política de Meta).
  - Cotización WhatsApp: plantilla UTILITY aprobada, si está configurada.
  - Si no hay plantilla (o el canal es IG/Messenger): link público de la cotización.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

WHATSAPP_REPLY_WINDOW = timedelta(hours=24)
META_SESSION_CHANNELS = frozenset({'WHATSAPP', 'MESSENGER', 'INSTAGRAM'})

WHATSAPP_WINDOW_MESSAGE = (
    'Pasaron más de 24 horas desde el último mensaje del cliente. '
    'WhatsApp no permite mensajes libres fuera de esa ventana. '
    'Puedes enviar la cotización: el cliente la abre con un link.'
)

WHATSAPP_NO_INBOUND_MESSAGE = (
    'El cliente aún no ha escrito por WhatsApp. '
    'No se pueden enviar mensajes libres hasta que te contacte. '
    'Sí puedes compartir el link de la cotización.'
)

MESSENGER_WINDOW_MESSAGE = (
    'Pasaron más de 24 horas desde el último mensaje del cliente. '
    'Messenger no permite mensajes libres fuera de esa ventana. '
    'Comparte el link de la cotización.'
)

MESSENGER_NO_INBOUND_MESSAGE = (
    'El cliente aún no ha escrito por Messenger. '
    'Comparte el link de la cotización.'
)

INSTAGRAM_WINDOW_MESSAGE = (
    'Pasaron más de 24 horas desde el último mensaje del cliente. '
    'Instagram no permite mensajes libres fuera de esa ventana. '
    'Comparte el link de la cotización.'
)

INSTAGRAM_NO_INBOUND_MESSAGE = (
    'El cliente aún no ha escrito por Instagram. '
    'Comparte el link de la cotización.'
)

CHANNEL_DISCONNECTED_MESSAGE = (
    'Este canal está desconectado. Conéctalo de nuevo en Configuración de canales '
    'para enviar mensajes. Mientras tanto puedes compartir el link de la cotización.'
)

ENTREGA_APP = 'app'
ENTREGA_SESION_META = 'sesion_meta'
ENTREGA_WHATSAPP_TEMPLATE = 'whatsapp_template'
ENTREGA_LINK_PUBLICO = 'link_publico'


class OutboundBlockedError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class EntregaPlan:
    """Cómo entregar una cotización según el canal y la ventana de 24 h."""

    via: str
    should_send_meta: bool
    use_template: bool
    code: str | None = None
    message: str | None = None


def last_inbound_at(conversation):
    return (
        conversation.messages.filter(direction='inbound')
        .order_by('-timestamp')
        .values_list('timestamp', flat=True)
        .first()
    )


def customer_care_window_open(conversation) -> bool:
    last = last_inbound_at(conversation)
    if not last:
        return False
    return timezone.now() - last <= WHATSAPP_REPLY_WINDOW


def _window_copy(channel: str, has_inbound: bool) -> tuple[str, str]:
    if channel == 'MESSENGER':
        msg = MESSENGER_WINDOW_MESSAGE if has_inbound else MESSENGER_NO_INBOUND_MESSAGE
        return 'messenger_window_closed', msg
    if channel == 'INSTAGRAM':
        msg = INSTAGRAM_WINDOW_MESSAGE if has_inbound else INSTAGRAM_NO_INBOUND_MESSAGE
        return 'instagram_window_closed', msg
    msg = WHATSAPP_WINDOW_MESSAGE if has_inbound else WHATSAPP_NO_INBOUND_MESSAGE
    return 'whatsapp_window_closed', msg


def connection_activa(conversation):
    contact = getattr(conversation, 'external_contact', None)
    connection = contact.connection if contact else None
    if not connection or not connection.is_active:
        return None
    return connection


def whatsapp_template_cotizacion_nombre() -> str:
    return (getattr(settings, 'WHATSAPP_TEMPLATE_COTIZACION', '') or '').strip()


def validate_omnichannel_outbound(conversation) -> None:
    """Lanza OutboundBlockedError si no se puede enviar texto libre por Meta."""
    if conversation.source_channel == 'APP':
        return

    if connection_activa(conversation) is None:
        raise OutboundBlockedError('channel_disconnected', CHANNEL_DISCONNECTED_MESSAGE)

    if conversation.source_channel not in META_SESSION_CHANNELS:
        return

    last_inbound = last_inbound_at(conversation)
    if last_inbound and timezone.now() - last_inbound <= WHATSAPP_REPLY_WINDOW:
        return
    code, message = _window_copy(conversation.source_channel, bool(last_inbound))
    raise OutboundBlockedError(code, message)


def plan_entrega_cotizacion(conversation) -> EntregaPlan:
    """Decide si la cotización viaja por sesión Meta, plantilla WhatsApp o link público."""
    channel = conversation.source_channel
    if channel == 'APP':
        return EntregaPlan(via=ENTREGA_APP, should_send_meta=False, use_template=False)

    if connection_activa(conversation) is None:
        return EntregaPlan(
            via=ENTREGA_LINK_PUBLICO,
            should_send_meta=False,
            use_template=False,
            code='channel_disconnected',
            message=CHANNEL_DISCONNECTED_MESSAGE,
        )

    if customer_care_window_open(conversation):
        return EntregaPlan(via=ENTREGA_SESION_META, should_send_meta=True, use_template=False)

    code, message = _window_copy(channel, bool(last_inbound_at(conversation)))
    if channel == 'WHATSAPP' and whatsapp_template_cotizacion_nombre():
        return EntregaPlan(
            via=ENTREGA_WHATSAPP_TEMPLATE,
            should_send_meta=True,
            use_template=True,
            code=code,
            message=(
                'La ventana de 24 h está cerrada. Se envía una plantilla de WhatsApp '
                'aprobada y también el link público por si el cliente no la recibe.'
            ),
        )
    return EntregaPlan(
        via=ENTREGA_LINK_PUBLICO,
        should_send_meta=False,
        use_template=False,
        code=code,
        message=message,
    )
