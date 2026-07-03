"""Broadcast WS + push para mensajes omnicanal y chat."""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)

CHANNEL_LABELS = {
    'WHATSAPP': 'WhatsApp',
    'MESSENGER': 'Messenger',
    'INSTAGRAM': 'Instagram',
    'APP': 'App',
}


def build_chat_payload(
    *,
    conversation,
    message,
    channel_slug: str,
    es_proveedor: bool,
    sender_name: str,
    oferta_id=None,
    solicitud_id=None,
    external_contact=None,
    attachment_url=None,
):
    ext = external_contact
    return {
        'type': 'nuevo_mensaje_chat',
        'conversation_id': str(conversation.id),
        'id': str(message.id),
        'mensaje_id': str(message.id),
        'message': message.content or '',
        'mensaje': message.content or '',
        'content': message.content or '',
        'oferta_id': str(oferta_id) if oferta_id else None,
        'solicitud_id': str(solicitud_id) if solicitud_id else None,
        'enviado_por': sender_name,
        'sender_name': sender_name,
        'es_proveedor': es_proveedor,
        'sender_id': message.sender_id,
        'timestamp': message.timestamp.isoformat(),
        'archivo_adjunto': attachment_url,
        'attachment': attachment_url,
        'channel': channel_slug,
        'external_contact_name': ext.display_name if ext else None,
        'external_contact_phone': ext.phone if ext else None,
        'channel_metadata': message.channel_metadata or {},
    }


def broadcast_to_participants(conversation, payload, skip_user_id=None):
    channel_layer = get_channel_layer()
    if not channel_layer:
        return
    for participant in conversation.participants.all():
        if skip_user_id and participant.id == skip_user_id:
            continue
        async_to_sync(channel_layer.group_send)(f'cliente_{participant.id}', payload)
        async_to_sync(channel_layer.group_send)(f'proveedor_{participant.id}', payload)
    async_to_sync(channel_layer.group_send)(
        f'chat_{conversation.id}',
        {**payload, 'type': 'chat_message'},
    )


def send_chat_push(
    recipient_user_id: int,
    *,
    channel_code: str,
    sender_name: str,
    preview: str,
    conversation_id: str,
    oferta_id: str = '',
    solicitud_id: str = '',
):
    from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification

    label = CHANNEL_LABELS.get(channel_code, channel_code)
    title = f'{label} · {sender_name}' if channel_code != 'APP' else f'💬 {sender_name}'
    send_expo_push_notification.delay(
        recipient_user_id,
        title,
        preview[:140] or 'Nuevo mensaje',
        {
            'type': 'chat_message',
            'channel': channel_code.lower() if channel_code else 'app',
            'conversation_id': conversation_id,
            'oferta_id': oferta_id or '',
            'solicitud_id': solicitud_id or '',
        },
    )
