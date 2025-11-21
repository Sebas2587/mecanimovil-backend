"""
Modelos para la app de pagos con Mercado Pago Checkout Pro
"""
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from django.utils import timezone
import uuid
import logging

logger = logging.getLogger(__name__)


class PreferenciaPago(models.Model):
    """
    Modelo para almacenar preferencias de pago creadas con Mercado Pago Checkout Pro
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Usuario que creó la preferencia
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='preferencias_pago',
        verbose_name='Usuario'
    )
    
    # ID de la preferencia en Mercado Pago
    preference_id_mp = models.CharField(
        max_length=255,
        unique=True,
        help_text='ID de la preferencia en Mercado Pago'
    )
    
    # Relación con el carrito
    carrito = models.ForeignKey(
        'ordenes.CarritoAgendamiento',
        on_delete=models.CASCADE,
        related_name='preferencias_pago',
        verbose_name='Carrito'
    )
    
    # Información de la preferencia
    init_point = models.URLField(
        help_text='URL de inicio de Checkout Pro'
    )
    sandbox_init_point = models.URLField(
        null=True,
        blank=True,
        help_text='URL de inicio en modo sandbox'
    )
    
    # Monto total
    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text='Monto total de la preferencia'
    )
    currency_id = models.CharField(
        max_length=3,
        default='CLP',
        help_text='Moneda (CLP, USD, etc.)'
    )
    
    # Estado
    procesada = models.BooleanField(
        default=False,
        help_text='Indica si la preferencia ya fue procesada (pago completado)'
    )
    
    # Timestamps
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('preferencia de pago')
        verbose_name_plural = _('preferencias de pago')
        ordering = ['-fecha_creacion']
        indexes = [
            models.Index(fields=['usuario', 'procesada']),
            models.Index(fields=['preference_id_mp']),
            models.Index(fields=['carrito']),
        ]
    
    def __str__(self):
        return f"Preferencia {self.preference_id_mp} - ${self.total_amount}"


class Pago(models.Model):
    """
    Modelo para almacenar pagos procesados con Mercado Pago Checkout Pro
    """
    ESTADO_CHOICES = [
        ('pending', 'Pendiente'),
        ('approved', 'Aprobado'),
        ('authorized', 'Autorizado'),
        ('in_process', 'En Proceso'),
        ('in_mediation', 'En Mediación'),
        ('rejected', 'Rechazado'),
        ('cancelled', 'Cancelado'),
        ('refunded', 'Reembolsado'),
        ('charged_back', 'Contracargo'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # ID del pago en Mercado Pago
    payment_id_mp = models.BigIntegerField(
        unique=True,
        null=True,
        blank=True,
        help_text='ID del pago en Mercado Pago'
    )
    
    # Usuario que realizó el pago
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='pagos',
        verbose_name='Usuario'
    )
    
    # Relación con la preferencia
    preferencia = models.ForeignKey(
        PreferenciaPago,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pagos',
        help_text='Preferencia de pago relacionada'
    )
    
    # Relación con el carrito
    carrito = models.ForeignKey(
        'ordenes.CarritoAgendamiento',
        on_delete=models.CASCADE,
        related_name='pagos',
        verbose_name='Carrito'
    )
    
    # Información del pago
    transaction_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text='Monto de la transacción'
    )
    currency_id = models.CharField(
        max_length=3,
        default='CLP',
        help_text='Código de moneda (CLP, USD, etc.)'
    )
    description = models.TextField(
        help_text='Descripción del pago'
    )
    
    # Estado del pago
    status = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default='pending',
        help_text='Estado del pago'
    )
    status_detail = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text='Detalle del estado del pago'
    )
    
    # Método de pago
    payment_method_id = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text='ID del método de pago usado'
    )
    payment_type_id = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text='Tipo de pago (credit_card, debit_card, etc.)'
    )
    
    # Información del pagador
    payer_email = models.EmailField(
        help_text='Email del pagador'
    )
    payer_first_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text='Nombre del pagador'
    )
    payer_last_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text='Apellido del pagador'
    )
    payer_identification_type = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        help_text='Tipo de identificación del pagador'
    )
    payer_identification_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text='Número de identificación del pagador'
    )
    
    # Referencia externa (ID del carrito)
    external_reference = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text='Referencia externa (ID de carrito)'
    )
    
    # Metadata adicional (JSON)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text='Metadata adicional del pago'
    )
    
    # URLs de retorno
    receipt_url = models.URLField(
        null=True,
        blank=True,
        help_text='URL del comprobante de pago'
    )
    
    # Información adicional de Mercado Pago
    date_created_mp = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Fecha de creación en Mercado Pago'
    )
    date_approved_mp = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Fecha de aprobación en Mercado Pago'
    )
    date_last_updated_mp = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Fecha de última actualización en Mercado Pago'
    )
    
    # Timestamps locales
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('pago')
        verbose_name_plural = _('pagos')
        ordering = ['-fecha_creacion']
        indexes = [
            models.Index(fields=['usuario', 'status']),
            models.Index(fields=['payment_id_mp']),
            models.Index(fields=['external_reference']),
            models.Index(fields=['status', 'fecha_creacion']),
            models.Index(fields=['carrito']),
        ]
    
    def __str__(self):
        return f"Pago {self.payment_id_mp or self.id} - {self.status} - ${self.transaction_amount}"
    
    @property
    def esta_aprobado(self):
        """Verifica si el pago está aprobado"""
        return self.status == 'approved'
    
    @property
    def esta_pendiente(self):
        """Verifica si el pago está pendiente"""
        return self.status == 'pending'
    
    @property
    def fue_rechazado(self):
        """Verifica si el pago fue rechazado"""
        return self.status == 'rejected'


class WebhookNotificacion(models.Model):
    """
    Modelo para almacenar notificaciones webhook de Mercado Pago
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Información del webhook
    payment_id_mp = models.BigIntegerField(
        null=True,
        blank=True,
        help_text='ID del pago en Mercado Pago relacionado con la notificación'
    )
    notification_type = models.CharField(
        max_length=50,
        help_text='Tipo de notificación (payment, etc.)'
    )
    
    # Datos del webhook (JSON)
    data = models.JSONField(
        default=dict,
        help_text='Datos completos de la notificación webhook'
    )
    
    # Estado de procesamiento
    procesado = models.BooleanField(
        default=False,
        help_text='Indica si la notificación ya fue procesada'
    )
    fecha_procesamiento = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Fecha cuando se procesó la notificación'
    )
    
    # Mensaje de error (si hubo alguno)
    error_procesamiento = models.TextField(
        null=True,
        blank=True,
        help_text='Mensaje de error si hubo problemas procesando la notificación'
    )
    
    # Timestamps
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = _('notificación webhook')
        verbose_name_plural = _('notificaciones webhook')
        ordering = ['-fecha_creacion']
        indexes = [
            models.Index(fields=['payment_id_mp']),
            models.Index(fields=['procesado', 'fecha_creacion']),
        ]
    
    def __str__(self):
        return f"Webhook {self.notification_type} - Payment {self.payment_id_mp or 'N/A'}"