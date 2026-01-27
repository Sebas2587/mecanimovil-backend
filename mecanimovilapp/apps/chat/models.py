from django.db import models
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

class Conversation(models.Model):
    TYPE_CHOICES = (
        ('SERVICE', 'Servicio'), # Reparaciones activas
        ('MARKETPLACE', 'Negocio'), # Compra/Venta
    )

    participants = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='conversations')
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='SERVICE')
    
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
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_messages')
    content = models.TextField(blank=True, null=True) # Content can be empty if there is an attachment
    attachment = models.FileField(upload_to='chat_attachments/%Y/%m/', blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"Message {self.id} from {self.sender} in {self.conversation}"
