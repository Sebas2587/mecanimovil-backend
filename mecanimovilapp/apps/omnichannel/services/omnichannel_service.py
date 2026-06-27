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
            preview=text,
            conversation_id=str(conversation.id),
        )
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
                    if msg.get('type') == 'text':
                        text = msg.get('text', {}).get('body', '')
                    elif msg.get('type') == 'button':
                        text = msg.get('button', {}).get('text', '')
                    events.append({
                        'kind': 'whatsapp',
                        'phone_number_id': phone_number_id,
                        'external_id': msg.get('from'),
                        'external_message_id': msg.get('id'),
                        'text': text,
                        'display_name': value.get('contacts', [{}])[0].get('profile', {}).get('name', ''),
                    })
        return events

    @staticmethod
    def parse_messenger_payload(body: dict, channel: str) -> list[dict[str, Any]]:
        events = []
        for entry in body.get('entry', []):
            page_id = entry.get('id')
            for messaging in entry.get('messaging', []):
                msg = messaging.get('message') or {}
                if not msg or messaging.get('message', {}).get('is_echo'):
                    continue
                text = msg.get('text', '')
                sender = messaging.get('sender', {})
                events.append({
                    'kind': channel.lower(),
                    'page_id': page_id,
                    'external_id': sender.get('id'),
                    'external_message_id': msg.get('mid'),
                    'text': text,
                    'display_name': sender.get('id', ''),
                })
        return events

    @classmethod
    def process_webhook_body(cls, body: dict) -> int:
        processed = 0
        if body.get('object') == 'whatsapp_business_account':
            for event in cls.parse_whatsapp_payload(body):
                conn = cls.resolve_connection_for_whatsapp(event['phone_number_id'])
                if not conn or not event.get('text'):
                    continue
                cls.ingest_inbound_message(
                    conn,
                    external_id=event['external_id'],
                    text=event['text'],
                    external_message_id=event['external_message_id'],
                    display_name=event.get('display_name', ''),
                    phone=event.get('external_id'),
                    metadata=event,
                )
                processed += 1
        elif body.get('object') == 'page':
            for event in cls.parse_messenger_payload(body, 'MESSENGER'):
                conn = cls.resolve_connection_for_page(event['page_id'], 'MESSENGER')
                if not conn or not event.get('text'):
                    continue
                cls.ingest_inbound_message(
                    conn,
                    external_id=event['external_id'],
                    text=event['text'],
                    external_message_id=event['external_message_id'],
                    display_name=event.get('display_name', ''),
                    metadata=event,
                )
                processed += 1
        elif body.get('object') == 'instagram':
            for event in cls.parse_messenger_payload(body, 'INSTAGRAM'):
                conn = cls.resolve_connection_for_page(event['page_id'], 'INSTAGRAM')
                if not conn or not event.get('text'):
                    continue
                cls.ingest_inbound_message(
                    conn,
                    external_id=event['external_id'],
                    text=event['text'],
                    external_message_id=event['external_message_id'],
                    display_name=event.get('display_name', ''),
                    metadata=event,
                )
                processed += 1
        return processed
