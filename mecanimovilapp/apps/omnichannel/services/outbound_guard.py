"""Validaciones antes de enviar mensajes salientes por Meta."""
from datetime import timedelta

from django.utils import timezone

WHATSAPP_REPLY_WINDOW = timedelta(hours=24)

WHATSAPP_WINDOW_MESSAGE = (
    'Pasaron más de 24 horas desde el último mensaje del cliente. '
    'Solo podrás responder cuando el cliente escriba de nuevo.'
)

WHATSAPP_NO_INBOUND_MESSAGE = (
    'El cliente aún no ha escrito. Solo podrás responder cuando te contacte por WhatsApp.'
)

CHANNEL_DISCONNECTED_MESSAGE = (
    'Este canal está desconectado. Conéctalo de nuevo en Configuración de canales '
    'para enviar mensajes.'
)


class OutboundBlockedError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def validate_omnichannel_outbound(conversation) -> None:
    """Lanza OutboundBlockedError si no se puede enviar por Meta."""
    if conversation.source_channel == 'APP':
        return

    contact = conversation.external_contact
    connection = contact.connection if contact else None

    if not connection or not connection.is_active:
        raise OutboundBlockedError('channel_disconnected', CHANNEL_DISCONNECTED_MESSAGE)

    if conversation.source_channel != 'WHATSAPP':
        return

    last_inbound = (
        conversation.messages.filter(direction='inbound')
        .order_by('-timestamp')
        .values_list('timestamp', flat=True)
        .first()
    )
    if not last_inbound:
        raise OutboundBlockedError('whatsapp_window_closed', WHATSAPP_NO_INBOUND_MESSAGE)
    if timezone.now() - last_inbound > WHATSAPP_REPLY_WINDOW:
        raise OutboundBlockedError('whatsapp_window_closed', WHATSAPP_WINDOW_MESSAGE)
