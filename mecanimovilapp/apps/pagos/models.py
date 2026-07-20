"""
Modelos para la app de pagos con Mercado Pago Checkout Pro
"""
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from django.utils import timezone
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
import uuid
import logging

logger = logging.getLogger(__name__)


class CuentaMercadoPagoProveedor(models.Model):
    """
    Modelo para almacenar las credenciales de Mercado Pago de cada proveedor.
    Permite que cada proveedor (Taller o MecanicoDomicilio) reciba pagos directos.
    """
    ESTADO_CHOICES = [
        ('no_configurada', 'Sin configurar'),
        ('pendiente', 'Pendiente de configuración'),
        ('conectada', 'Cuenta conectada'),
        ('desconectada', 'Cuenta desconectada'),
        ('error', 'Error en la conexión'),
        ('suspendida', 'Cuenta suspendida'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Relación con el proveedor (puede ser Taller o MecanicoDomicilio)
    content_type = models.ForeignKey(
        ContentType, 
        on_delete=models.CASCADE,
        help_text='Tipo de proveedor (Taller o MecanicoDomicilio)'
    )
    object_id = models.PositiveIntegerField(
        help_text='ID del proveedor'
    )
    proveedor = GenericForeignKey('content_type', 'object_id')
    
    # Usuario propietario (para facilitar consultas)
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cuenta_mercadopago',
        help_text='Usuario propietario de la cuenta'
    )
    
    # Estado de la cuenta
    estado = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default='no_configurada',
        help_text='Estado de la cuenta de Mercado Pago'
    )
    
    # Credenciales obtenidas vía OAuth
    access_token = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text='Access token de Mercado Pago (obtenido vía OAuth)'
    )
    refresh_token = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text='Refresh token para renovar el access token'
    )
    public_key = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text='Public key de Mercado Pago'
    )
    
    # Información de la cuenta de Mercado Pago
    user_id_mp = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text='ID del usuario en Mercado Pago'
    )
    email_mp = models.EmailField(
        blank=True,
        null=True,
        help_text='Email asociado a la cuenta de Mercado Pago'
    )
    nombre_cuenta = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text='Nombre del titular de la cuenta de Mercado Pago'
    )
    
    # Fechas de expiración del token
    token_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Fecha de expiración del access token'
    )
    
    # OAuth state para validar el callback
    oauth_state = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text='State token para validar callback OAuth'
    )
    
    # PKCE code_verifier para OAuth seguro
    code_verifier = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        help_text='Code verifier para PKCE OAuth flow'
    )
    
    # Timestamps
    fecha_conexion = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Fecha cuando se conectó la cuenta'
    )
    fecha_desconexion = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Fecha cuando se desconectó la cuenta'
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    # Mensaje de estado (para mostrar al usuario)
    mensaje_estado = models.TextField(
        blank=True,
        null=True,
        help_text='Mensaje descriptivo del estado actual'
    )
    
    class Meta:
        verbose_name = 'Cuenta Mercado Pago Proveedor'
        verbose_name_plural = 'Cuentas Mercado Pago Proveedores'
        unique_together = ['content_type', 'object_id']
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['estado']),
            models.Index(fields=['usuario']),
            models.Index(fields=['user_id_mp']),
        ]
    
    def __str__(self):
        proveedor_str = self.nombre_cuenta or self.email_mp or str(self.object_id)
        return f"Cuenta MP - {proveedor_str} ({self.get_estado_display()})"
    
    @property
    def esta_conectada(self):
        """Verifica si la cuenta está conectada y activa"""
        return self.estado == 'conectada' and self.access_token is not None
    
    @property
    def puede_recibir_pagos(self):
        """Verifica si la cuenta puede recibir pagos"""
        return self.esta_conectada and not self.token_expirado
    
    @property
    def token_expirado(self):
        """Verifica si el token ha expirado"""
        if not self.token_expires_at:
            return False
        return timezone.now() > self.token_expires_at
    
    def conectar(self, access_token, refresh_token=None, user_id_mp=None, 
                 email_mp=None, nombre_cuenta=None, public_key=None, expires_in=None):
        """
        Conecta la cuenta con las credenciales de Mercado Pago.
        """
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.user_id_mp = user_id_mp
        self.email_mp = email_mp
        self.nombre_cuenta = nombre_cuenta
        self.public_key = public_key
        self.estado = 'conectada'
        self.fecha_conexion = timezone.now()
        self.fecha_desconexion = None
        self.mensaje_estado = 'Tu cuenta de Mercado Pago está conectada y lista para recibir pagos.'
        self.oauth_state = None  # Limpiar el state después de conectar
        self.code_verifier = None  # Limpiar el code_verifier después de conectar
        
        if expires_in:
            self.token_expires_at = timezone.now() + timezone.timedelta(seconds=expires_in)
        
        self.save()
        logger.info(f"Cuenta de Mercado Pago conectada para usuario {self.usuario.id}")
    
    def desconectar(self):
        """
        Desconecta la cuenta de Mercado Pago.
        """
        # Limpiar credenciales por seguridad
        self.access_token = None
        self.refresh_token = None
        self.public_key = None
        self.token_expires_at = None
        # Limpiar también oauth_state y code_verifier para permitir reconexión limpia
        self.oauth_state = None
        self.code_verifier = None
        self.estado = 'desconectada'
        self.fecha_desconexion = timezone.now()
        self.mensaje_estado = 'Tu cuenta de Mercado Pago ha sido desconectada. Conéctala nuevamente para recibir pagos.'
        self.save()
        logger.info(f"Cuenta de Mercado Pago desconectada para usuario {self.usuario.id} (tokens y OAuth state limpiados)")
    
    def marcar_error(self, mensaje):
        """
        Marca la cuenta con error.
        """
        self.estado = 'error'
        self.mensaje_estado = mensaje
        self.save()
        logger.error(f"Error en cuenta de Mercado Pago para usuario {self.usuario.id}: {mensaje}")
    
    def get_mensaje_estado_default(self):
        """
        Obtiene un mensaje de estado por defecto según el estado actual.
        """
        mensajes = {
            'no_configurada': 'No tienes una cuenta de Mercado Pago configurada. Conecta tu cuenta para recibir pagos directos de los clientes.',
            'pendiente': 'La configuración de tu cuenta de Mercado Pago está en proceso. Por favor completa la autorización.',
            'conectada': 'Tu cuenta de Mercado Pago está conectada y lista para recibir pagos.',
            'desconectada': 'Tu cuenta de Mercado Pago ha sido desconectada. Conéctala nuevamente para recibir pagos.',
            'error': 'Hubo un problema con tu cuenta de Mercado Pago. Por favor intenta reconectarla.',
            'suspendida': 'Tu cuenta de Mercado Pago ha sido suspendida. Contacta a soporte para más información.',
        }
        return mensajes.get(self.estado, 'Estado desconocido')
    
    def save(self, *args, **kwargs):
        # Si no hay mensaje de estado, establecer uno por defecto
        if not self.mensaje_estado:
            self.mensaje_estado = self.get_mensaje_estado_default()
        super().save(*args, **kwargs)


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
    
    # Relación con el carrito (opcional, para flujo tradicional)
    carrito = models.ForeignKey(
        'ordenes.CarritoAgendamiento',
        on_delete=models.CASCADE,
        related_name='preferencias_pago',
        verbose_name='Carrito',
        null=True,
        blank=True
    )
    
    # Relación con solicitud de servicio (opcional, para ofertas secundarias y solicitudes públicas)
    solicitud_servicio = models.ForeignKey(
        'ordenes.SolicitudServicio',
        on_delete=models.CASCADE,
        related_name='preferencias_pago',
        verbose_name='Solicitud de Servicio',
        null=True,
        blank=True
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
            models.Index(fields=['solicitud_servicio']),
        ]
    
    def __str__(self):
        origen = f"Carrito {self.carrito.id}" if self.carrito else (f"Solicitud {self.solicitud_servicio.id}" if self.solicitud_servicio else "Sin origen")
        return f"Preferencia {self.preference_id_mp} - ${self.total_amount} ({origen})"


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
    
    # Relación con el carrito (opcional, para pagos de ofertas no hay carrito)
    carrito = models.ForeignKey(
        'ordenes.CarritoAgendamiento',
        on_delete=models.CASCADE,
        related_name='pagos',
        verbose_name='Carrito',
        null=True,
        blank=True
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


class LiquidacionProveedor(models.Model):
    """
    Registro de liquidación al proveedor tras cobro al cliente vía Checkout Pro.
    """

    ESTADO_CHOICES = [
        ('pendiente', 'Pendiente de liquidación'),
        ('procesada', 'Procesada'),
        ('pagada', 'Pagada al proveedor'),
        ('cancelada', 'Cancelada'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='liquidaciones_proveedor',
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    proveedor = GenericForeignKey('content_type', 'object_id')

    pago = models.ForeignKey(
        'pagos.Pago',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='liquidaciones',
    )
    oferta_id = models.UUIDField(null=True, blank=True, db_index=True)
    orden_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)

    monto_cobrado_cliente = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    comision_plataforma = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    monto_neto_proveedor = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    moneda = models.CharField(max_length=3, default='CLP')

    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='pendiente', db_index=True)
    referencia_transferencia = models.CharField(max_length=255, blank=True, default='')
    fecha_liquidacion = models.DateTimeField(null=True, blank=True)
    notas = models.TextField(blank=True, default='')

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('liquidación proveedor')
        verbose_name_plural = _('liquidaciones proveedor')
        ordering = ['-creado_en']
        indexes = [
            models.Index(
                fields=['usuario', 'estado'],
                name='pagos_liq_usr_estado_idx',
            ),
            models.Index(
                fields=['estado', '-creado_en'],
                name='pagos_liq_est_creado_idx',
            ),
        ]

    def __str__(self):
        return f'Liquidación {self.id} — {self.estado} — ${self.monto_neto_proveedor}'