import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import Conversation, Message
from django.contrib.auth import get_user_model

User = get_user_model()

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
        self.room_group_name = f'chat_{self.conversation_id}'
        self.user = self.scope["user"]

        if self.user.is_anonymous:
            await self.close()
            return

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    # Receive message from WebSocket
    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message_content = text_data_json.get('message')

        if not message_content:
            return

        # Save to DB
        message = await self.save_message(self.conversation_id, message_content, self.user)

        await self.encolar_agente(message.id)

        # Broadcast to all room members via WebSocket
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': message_content,
                'sender_id': self.user.id,
                'sender_name': f"{self.user.first_name} {self.user.last_name}",
                'timestamp': message.timestamp.isoformat(),
                'id': message.id
            }
        )

        # Push notification to participants who are NOT in the WS room
        # (throttle of 90 s handled inside send_expo_push_notification)
        await self.send_push_to_other_participants(
            self.conversation_id,
            self.user,
            message_content,
        )

    # Receive message from room group (HTTP broadcast or receive())
    async def chat_message(self, event):
        text = (
            event.get('message')
            or event.get('mensaje')
            or event.get('content')
            or ''
        )
        msg_id = event.get('id') or event.get('mensaje_id')
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'id': msg_id,
            'mensaje_id': msg_id,
            'message': text,
            'content': text,
            'mensaje': text,
            'sender_id': event.get('sender_id'),
            'sender_name': event.get('sender_name') or event.get('enviado_por'),
            'timestamp': event.get('timestamp'),
            'es_proveedor': event.get('es_proveedor', False),
            'archivo_adjunto': event.get('archivo_adjunto') or event.get('attachment'),
            'attachment': event.get('attachment') or event.get('archivo_adjunto'),
        }))

    @database_sync_to_async
    def save_message(self, conversation_id, content, user):
        import logging as _logging
        _log = _logging.getLogger(__name__)

        conversation = Conversation.objects.get(pk=conversation_id)
        conversation.save()  # Triggers auto_now for updated_at

        # Ensure sender is always a participant (covers provider messages via WS)
        if not conversation.participants.filter(pk=user.pk).exists():
            conversation.participants.add(user)
            _log.info(f"[ChatConsumer] WS sender {user.id} añadido a conversación {conversation_id}")

        return Message.objects.create(
            conversation=conversation,
            sender=user,
            content=content
        )

    @database_sync_to_async
    def encolar_agente(self, message_id: int) -> None:
        from mecanimovilapp.apps.agente_ia.hooks import encolar_agente_para_mensaje
        from mecanimovilapp.apps.chat.models import Message as ChatMessage

        message = ChatMessage.objects.filter(pk=message_id).first()
        if message:
            encolar_agente_para_mensaje(message)

    @database_sync_to_async
    def send_push_to_other_participants(self, conversation_id, sender, message_content):
        """
        Envía push a todos los participantes de la conversación excepto el remitente.
        Las pushes duplicadas dentro de 90 s son descartadas por el throttle
        de send_expo_push_notification.
        """
        try:
            from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification

            conversation = Conversation.objects.prefetch_related('participants').get(
                pk=conversation_id
            )

            sender_name = f"{sender.first_name} {sender.last_name}".strip() or sender.email

            # Acortar el texto para la notificación push
            preview = message_content[:80] + "…" if len(message_content) > 80 else message_content

            for participant in conversation.participants.exclude(pk=sender.pk):
                if not getattr(participant, 'expo_push_token', None):
                    continue

                title = f"💬 Mensaje de {sender_name}"
                body = preview

                send_expo_push_notification.delay(
                    participant.id,
                    title,
                    body,
                    {
                        'type': 'chat_message',
                        'conversation_id': str(conversation_id),
                        'sender_id': str(sender.id),
                    },
                )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(
                f"[ChatConsumer] Error enviando push de chat: {exc}", exc_info=True
            )
