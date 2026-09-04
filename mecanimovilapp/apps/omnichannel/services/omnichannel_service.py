"""Lógica de negocio omnicanal."""
import logging
from typing import Any

from django.db import transaction
from django.db.models import Q

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

# IDs fijos del botón "Probar" en Meta Developer → Webhooks → Instagram.
_META_IG_TEST_ENTRY_ID = '0'
_META_IG_TEST_RECIPIENT_ID = '23245'
_META_IG_TEST_SENDER_ID = '12334'


def normalize_meta_id(value: Any) -> str:
    if value is None:
        return ''
    return str(value).strip()


def is_meta_instagram_test_webhook(
    entry_id: Any,
    recipient_id: Any,
    sender_id: Any = None,
) -> bool:
    """Payload de prueba del panel Meta (no coincide con cuentas reales conectadas)."""
    entry = normalize_meta_id(entry_id)
    recipient = normalize_meta_id(recipient_id)
    sender = normalize_meta_id(sender_id)
    if entry == _META_IG_TEST_ENTRY_ID and recipient == _META_IG_TEST_RECIPIENT_ID:
        return True
    if sender == _META_IG_TEST_SENDER_ID and recipient == _META_IG_TEST_RECIPIENT_ID:
        return True
    return False


def instagram_webhook_account_id(entry_id: Any, recipient_id: Any) -> str:
    """ID de cuenta profesional para resolver la conexión (entry o recipient)."""
    entry = normalize_meta_id(entry_id)
    recipient = normalize_meta_id(recipient_id)
    if entry and entry != _META_IG_TEST_ENTRY_ID:
        return entry
    return recipient


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
        account_id = normalize_meta_id(page_id)
        if not account_id:
            return None
        base = ProviderChannelConnection.objects.filter(
            channel=channel,
            status='conectada',
            enabled=True,
        ).select_related('usuario')
        if channel == 'INSTAGRAM':
            # Webhook entry.id puede ser instagram_account_id o, en algunos casos, page_id.
            return base.filter(
                Q(instagram_account_id=account_id) | Q(page_id=account_id),
            ).first()
        return base.filter(page_id=account_id).first()

    @staticmethod
    def _is_placeholder_display_name(name: str, external_id: str) -> bool:
        """True si el nombre es vacío, igual al PSID/external_id, o solo dígitos largos."""
        trimmed = (name or '').strip()
        if not trimmed:
            return True
        ext = (external_id or '').strip()
        if ext and trimmed == ext:
            return True
        compact = trimmed.replace(' ', '')
        if len(compact) >= 8 and compact.isdigit():
            return True
        return False

    @classmethod
    def get_or_create_external_contact(
        cls,
        connection: ProviderChannelConnection,
        external_id: str,
        *,
        display_name: str = '',
        phone: str | None = None,
    ) -> ExternalContact:
        # Evita persistir PSID como "nombre" en Messenger/IG.
        safe_name = '' if cls._is_placeholder_display_name(display_name, external_id) else display_name.strip()
        contact, created = ExternalContact.objects.get_or_create(
            connection=connection,
            external_id=external_id,
            defaults={
                'channel': connection.channel,
                'display_name': safe_name,
                'phone': phone,
            },
        )
        if not created and safe_name and contact.display_name != safe_name:
            # No pisar un nombre humano previo con placeholder.
            if not cls._is_placeholder_display_name(safe_name, external_id):
                contact.display_name = safe_name
                contact.save(update_fields=['display_name', 'updated_at'])
        return contact

    @classmethod
    def maybe_enrich_messenger_contact_profile(
        cls,
        connection: ProviderChannelConnection,
        contact: ExternalContact,
    ) -> ExternalContact:
        """Completa display_name vía Graph si el contacto solo tiene PSID."""
        if connection.channel not in ('MESSENGER', 'INSTAGRAM'):
            return contact
        if not cls._is_placeholder_display_name(contact.display_name or '', contact.external_id):
            return contact
        token = (connection.access_token or '').strip()
        if not token:
            return contact
        try:
            from mecanimovilapp.apps.omnichannel.services.meta_graph import MetaGraphClient

            profile = MetaGraphClient().fetch_messenger_user_profile(contact.external_id, token)
        except Exception:
            logger.exception(
                'Error enriqueciendo perfil Meta contact=%s channel=%s',
                contact.id,
                connection.channel,
            )
            return contact
        if not profile or not profile.get('name'):
            return contact
        update_fields = ['display_name', 'updated_at']
        contact.display_name = profile['name']
        pic = profile.get('profile_pic')
        if pic and not contact.profile_picture_url:
            contact.profile_picture_url = pic
            update_fields.append('profile_picture_url')
        contact.save(update_fields=update_fields)
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
        contact = cls.maybe_enrich_messenger_contact_profile(connection, contact)
        conversation = cls.get_or_create_conversation(connection, contact)

        if not external_message_id:
            ts = (metadata or {}).get('timestamp') or ''
            external_message_id = f'{connection.channel.lower()}-{external_id}-{ts}'
        elif Message.objects.filter(external_message_id=external_message_id).exists():
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
            # Primero baja el adjunto; el agente se encola al terminar (evita
            # responder "Audio"/"Imagen" sin haber analizado el archivo).
            from mecanimovilapp.apps.omnichannel.tasks import fetch_inbound_meta_media
            fetch_inbound_meta_media.delay(message.id)
        else:
            from mecanimovilapp.apps.agente_ia.hooks import encolar_agente_para_mensaje
            encolar_agente_para_mensaje(message)

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
                    elif msg.get('type') == 'interactive':
                        interactive = msg.get('interactive') or {}
                        btn = interactive.get('button_reply') or interactive.get('list_reply') or {}
                        text = btn.get('title') or text
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
                        'interactive': msg.get('interactive') if msg.get('type') == 'interactive' else None,
                        'message_type': msg.get('type'),
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
        recipient = item.get('recipient', {})
        return {
            'kind': channel.lower(),
            'page_id': page_id,
            'recipient_id': recipient.get('id'),
            'external_id': sender.get('id'),
            'external_message_id': msg.get('mid'),
            'text': text,
            # Messenger/IG no envían nombre en el webhook; se enriquece vía Graph.
            'display_name': '',
            'media': media,
            'timestamp': item.get('timestamp'),
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
                if not event.get('text') and not event.get('media') and not event.get('interactive'):
                    continue
                msg = cls.ingest_inbound_message(
                    conn,
                    external_id=event['external_id'],
                    text=event.get('text') or media_label((event.get('media') or {}).get('kind')),
                    external_message_id=event['external_message_id'],
                    display_name=event.get('display_name', ''),
                    phone=event.get('external_id'),
                    metadata={**event, 'media': event.get('media')},
                )
                if msg and event.get('interactive'):
                    btn = (event.get('interactive') or {}).get('button_reply') or {}
                    button_id = btn.get('id')
                    if button_id:
                        if str(button_id).startswith('calidad_'):
                            from mecanimovilapp.apps.agente_ia.models import (
                                AgenteConversacionSesion,
                            )
                            from mecanimovilapp.apps.agente_ia.services.pregunta_calidad import (
                                parsear_respuesta_calidad,
                            )

                            calidad = parsear_respuesta_calidad(button_id)
                            if calidad:
                                ses = AgenteConversacionSesion.objects.filter(
                                    conversation=msg.conversation,
                                ).first()
                                if ses is not None:
                                    datos = dict(ses.datos_capturados or {})
                                    datos['calidad_preferida'] = calidad
                                    ses.datos_capturados = datos
                                    ses.save(update_fields=['datos_capturados', 'actualizado_en'])
                        else:
                            from mecanimovilapp.apps.ordenes.services.cotizacion_canal import (
                                procesar_respuesta_interactive_cotizacion,
                            )
                            procesar_respuesta_interactive_cotizacion(
                                button_id=button_id,
                                conversation=msg.conversation,
                            )
                processed += 1
        elif body.get('object') == 'page':
            events = cls.parse_messenger_payload(body, 'MESSENGER')
            logger.info('Parsed %s Page messaging events', len(events))
            for event in events:
                ig_lookup = instagram_webhook_account_id(
                    event.get('page_id'),
                    event.get('recipient_id'),
                )
                ig_conn = cls.resolve_connection_for_page(ig_lookup, 'INSTAGRAM')
                if not ig_conn and event.get('recipient_id'):
                    ig_conn = cls.resolve_connection_for_page(event['recipient_id'], 'INSTAGRAM')
                if ig_conn:
                    conn = ig_conn
                    channel_label = 'INSTAGRAM (via page webhook)'
                else:
                    conn = cls.resolve_connection_for_page(event['page_id'], 'MESSENGER')
                    channel_label = 'MESSENGER'
                if not conn:
                    logger.warning(
                        'No PAGE webhook connection for page_id=%s recipient_id=%s',
                        event.get('page_id'),
                        event.get('recipient_id'),
                    )
                    continue
                if not event.get('text') and not event.get('media'):
                    continue
                logger.info(
                    'Ingesting Page webhook event as %s page_id=%s recipient_id=%s',
                    channel_label,
                    event.get('page_id'),
                    event.get('recipient_id'),
                )
                cls.ingest_inbound_message(
                    conn,
                    external_id=event['external_id'],
                    text=event.get('text') or media_label((event.get('media') or {}).get('kind')),
                    external_message_id=event['external_message_id'],
                    display_name=event.get('display_name', ''),
                    metadata={**event, 'media': event.get('media'), 'via_page_webhook': True},
                )
                processed += 1
        elif body.get('object') == 'instagram':
            events = cls.parse_messenger_payload(body, 'INSTAGRAM')
            logger.info('Parsed %s Instagram events', len(events))
            for event in events:
                if is_meta_instagram_test_webhook(
                    event.get('page_id'),
                    event.get('recipient_id'),
                    event.get('external_id'),
                ):
                    logger.info(
                        'Meta Instagram webhook de prueba del panel (entry=0, recipient=23245). '
                        'Ignorado: envía un DM real a la cuenta Instagram conectada en la app.'
                    )
                    continue

                lookup_id = instagram_webhook_account_id(
                    event.get('page_id'),
                    event.get('recipient_id'),
                )
                conn = cls.resolve_connection_for_page(lookup_id, 'INSTAGRAM')
                if not conn and event.get('recipient_id'):
                    conn = cls.resolve_connection_for_page(event['recipient_id'], 'INSTAGRAM')
                if not conn and event.get('page_id'):
                    conn = cls.resolve_connection_for_page(event['page_id'], 'INSTAGRAM')
                if not conn:
                    active = ProviderChannelConnection.objects.filter(
                        channel='INSTAGRAM',
                        status='conectada',
                        enabled=True,
                    ).values_list('instagram_account_id', 'page_id', 'display_identifier')
                    logger.warning(
                        'No INSTAGRAM connection for entry_id=%s recipient_id=%s sender_id=%s '
                        '(lookup=%s). Conexiones activas: %s',
                        event.get('page_id'),
                        event.get('recipient_id'),
                        event.get('external_id'),
                        lookup_id,
                        list(active),
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
