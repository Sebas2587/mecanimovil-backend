import json
import logging

from celery import shared_task

from mecanimovilapp.apps.chat.models import Conversation, Message
from mecanimovilapp.apps.omnichannel.services import MetaGraphClient, OmnichannelService
from mecanimovilapp.apps.omnichannel.services.broadcast import (
    broadcast_to_participants,
    build_chat_payload,
)
from mecanimovilapp.apps.omnichannel.services.meta_media import (
    fetch_url_media_bytes,
    fetch_whatsapp_media_bytes,
    infer_media_kind,
    save_message_attachment,
)
from mecanimovilapp.apps.omnichannel.utils import channel_to_api_slug
from mecanimovilapp.storage.utils import get_cpanel_file_url

logger = logging.getLogger(__name__)


@shared_task(name='omnichannel.process_meta_webhook', queue='default')
def process_meta_webhook(raw_body: str):
    try:
        body = json.loads(raw_body)
        count = OmnichannelService.process_webhook_body(body)
        logger.info('Processed %s omnichannel events', count)
        return count
    except Exception as exc:
        logger.exception('process_meta_webhook failed: %s', exc)
        raise


@shared_task(name='omnichannel.fetch_inbound_meta_media', queue='default')
def fetch_inbound_meta_media(message_id: int):
    message = Message.objects.select_related(
        'conversation',
        'conversation__external_contact',
        'conversation__external_contact__connection',
    ).get(pk=message_id)
    if message.attachment:
        return {'skipped': True}

    meta = message.channel_metadata or {}
    media = meta.get('media')
    if not media:
        return {'skipped': True, 'reason': 'no_media'}

    conversation = message.conversation
    contact = conversation.external_contact
    connection = contact.connection if contact else None
    if not connection or not connection.access_token:
        logger.error('fetch_inbound_meta_media: no connection for message %s', message_id)
        return {'error': 'no_connection'}

    token = connection.access_token
    try:
        if media.get('media_id'):
            content, filename, kind = fetch_whatsapp_media_bytes(media['media_id'], token)
        elif media.get('url'):
            content, filename, kind = fetch_url_media_bytes(
                media['url'],
                token,
                kind_hint=media.get('kind'),
            )
        else:
            return {'error': 'unsupported_media_meta'}

        save_message_attachment(message, content, filename)
        message.refresh_from_db(fields=['attachment'])

        attachment_url = get_cpanel_file_url(message.attachment)
        channel_slug = channel_to_api_slug(connection.channel)
        sender_name = contact.display_name or contact.phone or 'Contacto'
        payload = build_chat_payload(
            conversation=conversation,
            message=message,
            channel_slug=channel_slug,
            es_proveedor=False,
            sender_name=sender_name,
            external_contact=contact,
            attachment_url=attachment_url,
        )
        broadcast_to_participants(conversation, payload)
        return {'ok': True, 'kind': kind}
    except Exception as exc:
        logger.exception('fetch_inbound_meta_media failed for %s: %s', message_id, exc)
        Message.objects.filter(pk=message_id).update(
            channel_metadata={
                **meta,
                'media_error': str(exc)[:500],
            },
        )
        raise


def _meta_attachment_type(kind: str) -> str:
    if kind == 'document':
        return 'file'
    if kind in ('image', 'video', 'audio'):
        return kind
    return 'file'


@shared_task(name='omnichannel.send_meta_message', queue='default')
def send_meta_message(message_id: int):
    message = Message.objects.select_related(
        'conversation',
        'conversation__external_contact',
        'conversation__external_contact__connection',
    ).get(pk=message_id)
    conversation = message.conversation
    if conversation.source_channel == 'APP':
        return {'skipped': True}

    contact = conversation.external_contact
    connection = contact.connection if contact else None
    if not connection or not connection.access_token:
        logger.error('No connection for outbound message %s', message_id)
        return {'error': 'no_connection'}

    client = MetaGraphClient(connection.access_token)
    text = (message.content or '').strip()
    meta = message.channel_metadata or {}
    external_id = contact.external_id
    attachment_url = get_cpanel_file_url(message.attachment) if message.attachment else None
    media_kind = None
    if message.attachment:
        media_kind = infer_media_kind(
            None,
            message.attachment.name,
        )
    resp = None

    try:
        if attachment_url and connection.channel == 'WHATSAPP' and connection.phone_number_id:
            resp = client.send_whatsapp_media(
                connection.phone_number_id,
                external_id,
                media_kind or 'document',
                attachment_url,
                connection.access_token,
                caption=text or None,
            )
        elif attachment_url and connection.channel == 'MESSENGER' and connection.page_id:
            resp = client.send_page_attachment(
                connection.page_id,
                external_id,
                _meta_attachment_type(media_kind or 'file'),
                attachment_url,
                connection.access_token,
                None,
            )
            if resp is not None and resp.status_code < 400 and text:
                resp = client.send_page_message(
                    connection.page_id,
                    external_id,
                    text,
                    connection.access_token,
                )
        elif attachment_url and connection.channel == 'INSTAGRAM' and connection.instagram_account_id:
            resp = client.send_instagram_attachment(
                connection.instagram_account_id,
                external_id,
                _meta_attachment_type(media_kind or 'file'),
                attachment_url,
                connection.access_token,
                None,
            )
            if resp is not None and resp.status_code < 400 and text:
                resp = client.send_instagram_message(
                    connection.instagram_account_id,
                    external_id,
                    text,
                    connection.access_token,
                )
        elif text:
            if (
                meta.get('interactive')
                and meta.get('tipo') == 'cotizacion_canal'
                and connection.channel == 'WHATSAPP'
                and connection.phone_number_id
            ):
                cot_id = meta.get('cotizacion_id')
                resp = client.send_whatsapp_interactive_buttons(
                    connection.phone_number_id,
                    external_id,
                    text,
                    [
                        {
                            'id': f'cotizacion_aceptar_{cot_id}',
                            'title': 'Aceptar',
                        },
                        {
                            'id': f'cotizacion_rechazar_{cot_id}',
                            'title': 'Rechazar',
                        },
                    ],
                    connection.access_token,
                )
            elif connection.channel == 'WHATSAPP' and connection.phone_number_id:
                resp = client.send_whatsapp_text(
                    connection.phone_number_id,
                    external_id,
                    text,
                    connection.access_token,
                )
            elif connection.channel == 'MESSENGER' and connection.page_id:
                resp = client.send_page_message(
                    connection.page_id,
                    external_id,
                    text,
                    connection.access_token,
                )
            elif connection.channel == 'INSTAGRAM' and connection.instagram_account_id:
                resp = client.send_instagram_message(
                    connection.instagram_account_id,
                    external_id,
                    text,
                    connection.access_token,
                )
            else:
                return {'error': 'unsupported_channel'}
        else:
            return {'error': 'empty_message'}

        if resp is not None and resp.status_code >= 400:
            logger.error('Meta send failed: %s', resp.text)
            Message.objects.filter(pk=message_id).update(
                channel_metadata={'send_error': resp.text[:500]},
            )
            return {'error': resp.text}

        ext_id = None
        if resp is not None:
            try:
                body = resp.json()
                ext_id = body.get('messages', [{}])[0].get('id') or body.get('message_id')
            except Exception:
                ext_id = None
        if ext_id:
            Message.objects.filter(pk=message_id).update(external_message_id=ext_id)

        return {'ok': True, 'channel': channel_to_api_slug(connection.channel)}
    except Exception as exc:
        logger.exception('send_meta_message error: %s', exc)
        raise
