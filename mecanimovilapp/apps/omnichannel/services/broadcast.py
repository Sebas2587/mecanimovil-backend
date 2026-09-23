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


def _attachment_meta_from_message(message, attachment_url=None):
    """mime/nombre para que el cliente detecte imagen/audio sin adivinar por extensión."""
    meta = message.channel_metadata or {}
    media = meta.get('media') if isinstance(meta.get('media'), dict) else {}
    mime = (media.get('mime_type') or media.get('mime') or '').strip() or None
    name = (media.get('filename') or media.get('name') or '').strip() or None
    if not name and attachment_url:
        path = str(attachment_url).split('?', 1)[0]
        name = path.rsplit('/', 1)[-1] or None
    if not name and getattr(message, 'attachment', None):
        try:
            name = (message.attachment.name or '').rsplit('/', 1)[-1] or None
        except Exception:
            name = None
    return mime, name


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
    mime, name = _attachment_meta_from_message(message, attachment_url)
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
        'attachment_mime': mime,
        'attachment_name': name,
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
    sender_id: str = '',
    is_new_contact: bool = False,
    message_id: str = '',
):
    from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification

    raw = channel_code or 'APP'
    channel_code = str(raw).upper()
    label = CHANNEL_LABELS.get(channel_code, channel_code)
    channel_slug = channel_code.lower() if channel_code else 'app'
    if is_new_contact:
        title = f'Nuevo contacto · {label}'
        body = f'{sender_name}: {preview[:120]}' if preview else f'{sender_name} escribió por {label}.'
        notif_type = 'nuevo_contacto_canal'
    else:
        title = f'{label} · {sender_name}' if channel_code != 'APP' else f'💬 {sender_name}'
        body = preview[:140] or 'Nuevo mensaje'
        notif_type = 'chat_message'

    send_expo_push_notification.delay(
        recipient_user_id,
        title,
        body,
        {
            'type': notif_type,
            'channel': channel_slug,
            'conversation_id': conversation_id,
            'oferta_id': oferta_id or '',
            'solicitud_id': solicitud_id or '',
            'sender_id': str(sender_id or ''),
            'message_id': str(message_id or ''),
            'preview': (preview or '')[:140],
            'nuevo_contacto': 'true' if is_new_contact else 'false',
        },
    )
