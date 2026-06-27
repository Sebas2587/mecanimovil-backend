import json
import logging

from celery import shared_task

from mecanimovilapp.apps.chat.models import Conversation, Message
from mecanimovilapp.apps.omnichannel.services import MetaGraphClient, OmnichannelService
from mecanimovilapp.apps.omnichannel.utils import channel_to_api_slug

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
    text = message.content or ''
    external_id = contact.external_id
    resp = None

    try:
        if connection.channel == 'WHATSAPP' and connection.phone_number_id:
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

        if resp is not None and resp.status_code >= 400:
            logger.error('Meta send failed: %s', resp.text)
            Message.objects.filter(pk=message_id).update(
                channel_metadata={'send_error': resp.text[:500]},
            )
            return {'error': resp.text}

        ext_id = None
        if resp is not None:
            try:
                ext_id = resp.json().get('messages', [{}])[0].get('id') or resp.json().get('message_id')
            except Exception:
                ext_id = None
        if ext_id:
            Message.objects.filter(pk=message_id).update(external_message_id=ext_id)

        return {'ok': True, 'channel': channel_to_api_slug(connection.channel)}
    except Exception as exc:
        logger.exception('send_meta_message error: %s', exc)
        raise
