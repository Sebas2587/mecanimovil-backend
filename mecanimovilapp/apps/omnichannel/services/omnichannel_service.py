"""Lógica de negocio omnicanal."""
import logging
from typing import Any

from django.db import transaction

from mecanimovilapp.apps.chat.models import Conversation, Message
from mecanimovilapp.apps.omnichannel.models import ExternalContact, ProviderChannelConnection
from mecanimovilapp.apps.omnichannel.services.broadcast import (
    broadcast_to_participants,
    build_chat_payload,
    send_chat_push,
)
from mecanimovilapp.apps.omnichannel.services.meta_media import (
    media_label,
    parse_messenger_attachments,
    parse_whatsapp_media,
)
from mecanimovilapp.apps.omnichannel.utils import channel_to_api_slug

logger = logging.getLogger(__name__)


class OmnichannelService:
    @staticmethod
    def resolve_connection_for_whatsapp(phone_number_id: str) -> ProviderChannelConnection | None:
        return ProviderChannelConnection.objects.filter(
            phone_number_id=phone_number_id,
            channel='WHATSAPP',
            status='conectada',
            enabled=True,
        ).select_related('usuario').first()

    @staticmethod
    def resolve_connection_for_page(page_id: str, channel: str) -> ProviderChannelConnection | None:
        if channel == 'INSTAGRAM':
            return ProviderChannelConnection.objects.filter(
                instagram_account_id=page_id,
                channel='INSTAGRAM',
                status='conectada',
                enabled=True,
            ).select_related('usuario').first()
        return ProviderChannelConnection.objects.filter(
            page_id=page_id,
            channel='MESSENGER',
            status='conectada',
            enabled=True,
        ).select_related('usuario').first()

    @staticmethod
    def get_or_create_external_contact(
        connection: ProviderChannelConnection,
        external_id: str,
        *,
        display_name: str = '',
        phone: str | None = None,
    ) -> ExternalContact:
        contact, created = ExternalContact.objects.get_or_create(
            connection=connection,
            external_id=external_id,
            defaults={
                'channel': connection.channel,
                'display_name': display_name or external_id,
                'phone': phone,
            },
        )
        if not created and display_name and contact.display_name != display_name:
            contact.display_name = display_name
            contact.save(update_fields=['display_name', 'updated_at'])
        return contact

    @staticmethod
    def get_or_create_conversation(
        connection: ProviderChannelConnection,
        contact: ExternalContact,
    ) -> Conversation:
        conversation, created = Conversation.objects.get_or_create(
            source_channel=connection.channel,
            external_contact=contact,
            defaults={'type': 'OMNICHANNEL'},
        )
        if created or not conversation.participants.filter(id=connection.usuario_id).exists():
            conversation.participants.add(connection.usuario)
        return conversation

    @classmethod
    @transaction.atomic
    def ingest_inbound_message(
        cls,
        connection: ProviderChannelConnection,
        *,
        external_id: str,
        text: str,
        external_message_id: str,
        display_name: str = '',
        phone: str | None = None,
        metadata: dict | None = None,
    ) -> Message | None:
        if not connection.is_active:
            logger.info('Ignoring inbound: connection %s inactive', connection.id)
            return None

        contact = cls.get_or_create_external_contact(
            connection,
            external_id,
            display_name=display_name,
            phone=phone,
        )
        conversation = cls.get_or_create_conversation(connection, contact)

        if Message.objects.filter(external_message_id=external_message_id).exists():
            return None

        message = Message.objects.create(
            conversation=conversation,
            sender=None,
            content=text,
            direction='inbound',
            external_message_id=external_message_id,
            channel_metadata=metadata or {},
        )
        conversation.save()

        sender_name = contact.display_name or contact.phone or 'Contacto'
        channel_slug = channel_to_api_slug(connection.channel)
        payload = build_chat_payload(
            conversation=conversation,
            message=message,
            channel_slug=channel_slug,
            es_proveedor=False,
            sender_name=sender_name,
            external_contact=contact,
        )
        broadcast_to_participants(conversation, payload)
        send_chat_push(
            connection.usuario_id,
            channel_code=connection.channel,
            sender_name=sender_name,
            preview=text[:140] or 'Nuevo mensaje',
            conversation_id=str(conversation.id),
        )
        media = (metadata or {}).get('media')
        if media:
            from mecanimovilapp.apps.omnichannel.tasks import fetch_inbound_meta_media
            fetch_inbound_meta_media.delay(message.id)
        return message

    @staticmethod
    def parse_whatsapp_payload(body: dict) -> list[dict[str, Any]]:
        events = []
        for entry in body.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})
                metadata = value.get('metadata', {})
                phone_number_id = metadata.get('phone_number_id')
                for msg in value.get('messages', []):
                    text = ''
                    media = None
                    if msg.get('type') == 'text':
                        text = msg.get('text', {}).get('body', '')
                    elif msg.get('type') == 'button':
                        text = msg.get('button', {}).get('text', '')
                    else:
                        media = parse_whatsapp_media(msg)
                        if media:
                            text = media.get('caption') or media_label(media.get('kind'))
                    events.append({
                        'kind': 'whatsapp',
                        'phone_number_id': phone_number_id,
                        'external_id': msg.get('from'),
                        'external_message_id': msg.get('id'),
                        'text': text,
                        'display_name': value.get('contacts', [{}])[0].get('profile', {}).get('name', ''),
                        'media': media,
                    })
        return events

    @staticmethod
    def _messenger_event_from_item(
        page_id: str,
        channel: str,
        item: dict,
    ) -> dict[str, Any] | None:
        msg = item.get('message') or {}
        if not msg or msg.get('is_echo'):
            return None
        text = msg.get('text') or ''
        attachments = parse_messenger_attachments(msg)
        media = attachments[0] if attachments else None
        if not text and media:
            text = media_label(media.get('kind'))
        if not text and not media:
            return None
        sender = item.get('sender', {})
        return {
            'kind': channel.lower(),
            'page_id': page_id,
            'external_id': sender.get('id'),
            'external_message_id': msg.get('mid'),
            'text': text,
            'display_name': sender.get('id', ''),
            'media': media,
        }

    @staticmethod
    def parse_messenger_payload(body: dict, channel: str) -> list[dict[str, Any]]:
        events = []
        for entry in body.get('entry', []):
            page_id = entry.get('id')
            for messaging in entry.get('messaging', []):
                event = OmnichannelService._messenger_event_from_item(page_id, channel, messaging)
                if event:
                    events.append(event)
            for change in entry.get('changes', []):
                if change.get('field') != 'messages':
                    continue
                value = change.get('value') or {}
                if 'messaging' in value:
                    for messaging in value.get('messaging', []):
                        event = OmnichannelService._messenger_event_from_item(page_id, channel, messaging)
                        if event:
                            events.append(event)
                else:
                    event = OmnichannelService._messenger_event_from_item(page_id, channel, value)
                    if event:
                        events.append(event)
        return events

    @classmethod
    def process_webhook_body(cls, body: dict) -> int:
        processed = 0
        obj = body.get('object')
        logger.info('Meta webhook object=%s entries=%s', obj, len(body.get('entry', [])))
        if body.get('object') == 'whatsapp_business_account':
            events = cls.parse_whatsapp_payload(body)
            logger.info('Parsed %s WhatsApp events', len(events))
            for event in events:
                conn = cls.resolve_connection_for_whatsapp(event['phone_number_id'])
                if not conn:
                    logger.warning(
                        'No WHATSAPP connection for phone_number_id=%s',
                        event.get('phone_number_id'),
                    )
                    continue
                if not event.get('text') and not event.get('media'):
                    continue
                cls.ingest_inbound_message(
                    conn,
                    external_id=event['external_id'],
                    text=event.get('text') or media_label((event.get('media') or {}).get('kind')),
                    external_message_id=event['external_message_id'],
                    display_name=event.get('display_name', ''),
                    phone=event.get('external_id'),
                    metadata={**event, 'media': event.get('media')},
                )
                processed += 1
        elif body.get('object') == 'page':
            events = cls.parse_messenger_payload(body, 'MESSENGER')
            logger.info('Parsed %s Messenger events', len(events))
            for event in events:
                conn = cls.resolve_connection_for_page(event['page_id'], 'MESSENGER')
                if not conn:
                    logger.warning(
                        'No MESSENGER connection for page_id=%s (status=conectada, enabled=True)',
                        event['page_id'],
                    )
                    continue
                if not event.get('text') and not event.get('media'):
                    continue
                cls.ingest_inbound_message(
                    conn,
                    external_id=event['external_id'],
                    text=event.get('text') or media_label((event.get('media') or {}).get('kind')),
                    external_message_id=event['external_message_id'],
                    display_name=event.get('display_name', ''),
                    metadata={**event, 'media': event.get('media')},
                )
                processed += 1
        elif body.get('object') == 'instagram':
            events = cls.parse_messenger_payload(body, 'INSTAGRAM')
            logger.info('Parsed %s Instagram events', len(events))
            for event in events:
                conn = cls.resolve_connection_for_page(event['page_id'], 'INSTAGRAM')
                if not conn:
                    logger.warning(
                        'No INSTAGRAM connection for page_id=%s',
                        event['page_id'],
                    )
                    continue
                if not event.get('text') and not event.get('media'):
                    continue
                cls.ingest_inbound_message(
                    conn,
                    external_id=event['external_id'],
                    text=event.get('text') or media_label((event.get('media') or {}).get('kind')),
                    external_message_id=event['external_message_id'],
                    display_name=event.get('display_name', ''),
                    metadata={**event, 'media': event.get('media')},
                )
                processed += 1
        return processed
