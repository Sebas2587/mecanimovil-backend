from django.db import models
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

class Conversation(models.Model):
    TYPE_CHOICES = (
        ('SERVICE', 'Servicio'), # Reparaciones activas
        ('MARKETPLACE', 'Negocio'), # Compra/Venta
        ('OMNICHANNEL', 'Omnicanal'), # Inbox externo (WhatsApp, etc.)
    )

    SOURCE_CHANNEL_CHOICES = (
        ('APP', 'App'),
        ('WHATSAPP', 'WhatsApp'),
        ('MESSENGER', 'Messenger'),
        ('INSTAGRAM', 'Instagram'),
    )

    participants = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='conversations')
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='SERVICE')
    source_channel = models.CharField(
        max_length=20,
        choices=SOURCE_CHANNEL_CHOICES,
        default='APP',
        db_index=True,
    )
    external_contact = models.ForeignKey(
        'omnichannel.ExternalContact',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='conversations',
    )
    external_thread_id = models.CharField(max_length=255, null=True, blank=True)
    
    # Generic relation to context (SolicitudServicio or Vehiculo)
    # Using CharField to support both integer and UUID primary keys
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    object_id = models.CharField(max_length=255, null=True, blank=True)
    context_object = GenericForeignKey('content_type', 'object_id')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True) # Useful for sorting by recent activity

    def __str__(self):
        return f"Chat {self.id} - {self.type}"

class Message(models.Model):
    DIRECTION_CHOICES = (
        ('inbound', 'Entrante'),
        ('outbound', 'Saliente'),
    )

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_messages',
        null=True,
        blank=True,
    )
    content = models.TextField(blank=True, null=True) # Content can be empty if there is an attachment
    attachment = models.FileField(upload_to='chat_attachments/%Y/%m/', blank=True, null=True)
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES, default='outbound')
    external_message_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    channel_metadata = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"Message {self.id} from {self.sender} in {self.conversation}"
