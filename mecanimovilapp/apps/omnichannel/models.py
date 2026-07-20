"""
Modelos para integración Meta (WhatsApp, Messenger, Instagram).
"""
import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class ProviderChannelConnection(models.Model):
    CHANNEL_CHOICES = [
        ('WHATSAPP', 'WhatsApp'),
        ('MESSENGER', 'Messenger'),
        ('INSTAGRAM', 'Instagram'),
    ]
    STATUS_CHOICES = [
        ('no_configurada', 'Sin configurar'),
        ('pendiente', 'Pendiente'),
        ('conectada', 'Conectada'),
        ('desconectada', 'Desconectada'),
        ('error', 'Error'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    proveedor = GenericForeignKey('content_type', 'object_id')
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='channel_connections',
    )
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    enabled = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='no_configurada')
    access_token = models.CharField(max_length=500, blank=True, null=True)
    phone_number_id = models.CharField(max_length=100, blank=True, null=True)
    waba_id = models.CharField(max_length=100, blank=True, null=True)
    page_id = models.CharField(max_length=100, blank=True, null=True)
    instagram_account_id = models.CharField(max_length=100, blank=True, null=True)
    meta_business_id = models.CharField(max_length=100, blank=True, null=True)
    display_name = models.CharField(max_length=255, blank=True, null=True)
    display_identifier = models.CharField(max_length=255, blank=True, null=True)
    oauth_state = models.CharField(max_length=128, blank=True, null=True)
    mensaje_estado = models.TextField(blank=True, null=True)
    connected_at = models.DateTimeField(null=True, blank=True)
    disconnected_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Conexión de canal proveedor'
        verbose_name_plural = 'Conexiones de canal proveedor'
        constraints = [
            models.UniqueConstraint(
                fields=['content_type', 'object_id', 'channel'],
                name='unique_provider_channel',
            ),
        ]
        indexes = [
            models.Index(fields=['phone_number_id'], name='omnichannel_phone_n_163449_idx'),
            models.Index(fields=['page_id'], name='omnichannel_page_id_6be930_idx'),
            models.Index(fields=['instagram_account_id'], name='omnichannel_instagr_be243e_idx'),
        ]

    def __str__(self):
        return f'{self.channel} — {self.usuario_id} ({self.status})'

    @property
    def is_active(self):
        return self.status == 'conectada' and self.enabled

    def mark_connected(self, **fields):
        from django.utils import timezone
        for key, value in fields.items():
            setattr(self, key, value)
        self.status = 'conectada'
        self.connected_at = timezone.now()
        self.disconnected_at = None
        self.oauth_state = None
        self.mensaje_estado = 'Canal conectado y listo para recibir mensajes.'
        self.save()

    def disconnect(self):
        from django.utils import timezone
        self.access_token = None
        self.phone_number_id = None
        self.waba_id = None
        self.page_id = None
        self.instagram_account_id = None
        self.meta_business_id = None
        self.display_name = None
        self.display_identifier = None
        self.oauth_state = None
        self.enabled = False
        self.status = 'desconectada'
        self.disconnected_at = timezone.now()
        self.mensaje_estado = 'Canal desconectado. Conéctalo de nuevo para recibir mensajes.'
        self.save()


class ExternalContact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(
        ProviderChannelConnection,
        on_delete=models.CASCADE,
        related_name='contacts',
    )
    channel = models.CharField(max_length=20, choices=ProviderChannelConnection.CHANNEL_CHOICES)
    external_id = models.CharField(max_length=255, db_index=True)
    display_name = models.CharField(max_length=255, blank=True, default='')
    phone = models.CharField(max_length=30, blank=True, null=True)
    profile_picture_url = models.URLField(blank=True, null=True)
    cliente = models.ForeignKey(
        'usuarios.Cliente',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='external_contacts',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Contacto externo'
        verbose_name_plural = 'Contactos externos'
        constraints = [
            models.UniqueConstraint(
                fields=['connection', 'external_id'],
                name='unique_external_contact_per_connection',
            ),
        ]

    def __str__(self):
        return self.display_name or self.external_id
