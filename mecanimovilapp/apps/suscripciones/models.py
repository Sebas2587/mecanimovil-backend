"""
Modelos para el sistema Pay-per-Win con créditos y Suscripciones Mensuales.
"""
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import Q
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# MODELOS DEL SISTEMA PAY-PER-WIN CON CRÉDITOS
# ============================================================================

class CreditoProveedor(models.Model):
    """
    Saldo de créditos de un proveedor.
    Relación uno-a-uno con Usuario (proveedor).
    """
    proveedor = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='credito_proveedor',
        verbose_name='Proveedor',
        help_text='Usuario proveedor (taller o mecánico)'
    )
    saldo_creditos = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name='Saldo de Créditos',
        help_text='Cantidad de créditos disponibles'
    )
    fecha_ultima_compra = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de Última Compra',
        help_text='Fecha de la última compra de créditos'
    )
    fecha_ultimo_consumo = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de Último Consumo',
        help_text='Fecha del último consumo de créditos'
    )
    creditos_expirados = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name='Créditos Expirados',
        help_text='Cantidad de créditos que han expirado (para tracking)'
    )
    
    # Campos de timestamp
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('Crédito de Proveedor')
        verbose_name_plural = _('Créditos de Proveedores')
        ordering = ['-fecha_actualizacion']
        indexes = [
            models.Index(fields=['proveedor']),
            models.Index(fields=['saldo_creditos']),
        ]
    
    def __str__(self):
        return f"{self.proveedor.username} - {self.saldo_creditos} créditos"
    
    def clean(self):
        """Validaciones del modelo"""
        if self.saldo_creditos < 0:
            raise ValidationError({
                'saldo_creditos': 'El saldo de créditos no puede ser negativo'
            })
    
    def save(self, *args, **kwargs):
        """Sobrescribir save para ejecutar validaciones"""
        self.full_clean()
        super().save(*args, **kwargs)


class PaqueteCreditos(models.Model):
    """
    Paquetes de créditos disponibles para compra.
    """
    nombre = models.CharField(
        max_length=100,
        verbose_name='Nombre',
        help_text='Nombre del paquete (ej: "Paquete Básico", "Paquete Premium")'
    )
    cantidad_creditos = models.IntegerField(
        validators=[MinValueValidator(1)],
        verbose_name='Cantidad de Créditos',
        help_text='Número de créditos incluidos en el paquete'
    )
    precio = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name='Precio',
        help_text='Precio del paquete en CLP'
    )
    bonificacion_creditos = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name='Bonificación de Créditos',
        help_text='Créditos extra que se otorgan como bonificación'
    )
    activo = models.BooleanField(
        default=True,
        verbose_name='Activo',
        help_text='Indica si el paquete está disponible para compra'
    )
    orden = models.IntegerField(
        default=0,
        verbose_name='Orden',
        help_text='Orden de visualización en la UI (menor = primero)'
    )
    destacado = models.BooleanField(
        default=False,
        verbose_name='Destacado',
        help_text='Indica si el paquete debe destacarse en la UI'
    )
    
    # Campos de timestamp
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('Paquete de Créditos')
        verbose_name_plural = _('Paquetes de Créditos')
        ordering = ['orden', 'precio']
        indexes = [
            models.Index(fields=['activo', 'orden']),
        ]
    
    def __str__(self):
        return f"{self.nombre} - {self.cantidad_creditos} créditos - ${self.precio:,.0f}"
    
    @property
    def precio_por_credito(self):
        """Calcula el precio por crédito"""
        total_creditos = self.cantidad_creditos + self.bonificacion_creditos
        if total_creditos > 0:
            return self.precio / total_creditos
        return self.precio
    
    @property
    def total_creditos(self):
        """Retorna el total de créditos (incluyendo bonificación)"""
        return self.cantidad_creditos + self.bonificacion_creditos
    
    def clean(self):
        """Validaciones del modelo"""
        if self.precio < 0:
            raise ValidationError({
                'precio': 'El precio no puede ser negativo'
            })
        if self.cantidad_creditos <= 0:
            raise ValidationError({
                'cantidad_creditos': 'La cantidad de créditos debe ser mayor a 0'
            })
    
    def save(self, *args, **kwargs):
        """Sobrescribir save para ejecutar validaciones"""
        self.full_clean()
        super().save(*args, **kwargs)


class CompraCreditos(models.Model):
    """
    Registro de compra de créditos por un proveedor.
    """
    ESTADOS = [
        ('pendiente', 'Pendiente'),
        ('completada', 'Completada'),
        ('cancelada', 'Cancelada'),
        ('reembolsada', 'Reembolsada'),
    ]
    
    METODOS_PAGO = [
        ('mercadopago', 'Mercado Pago'),
        ('transferencia', 'Transferencia Bancaria'),
        ('migracion', 'Migración de Suscripción'),
    ]
    
    proveedor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='compras_creditos',
        verbose_name='Proveedor',
        help_text='Usuario proveedor que compra los créditos'
    )
    paquete = models.ForeignKey(
        PaqueteCreditos,
        on_delete=models.SET_NULL,
        related_name='compras',
        verbose_name='Paquete',
        help_text='Paquete de créditos comprado',
        null=True,
        blank=True
    )
    cantidad_creditos = models.IntegerField(
        validators=[MinValueValidator(1)],
        verbose_name='Cantidad de Créditos',
        help_text='Cantidad total de créditos (incluye bonificación)'
    )
    precio_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name='Precio Total',
        help_text='Precio total pagado en CLP'
    )
    metodo_pago = models.CharField(
        max_length=20,
        choices=METODOS_PAGO,
        verbose_name='Método de Pago',
        help_text='Método de pago utilizado'
    )
    estado = models.CharField(
        max_length=20,
        choices=ESTADOS,
        default='pendiente',
        verbose_name='Estado',
        help_text='Estado de la compra'
    )
    payment_id_mp = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name='ID Pago Mercado Pago',
        help_text='ID del pago en Mercado Pago (si aplica)'
    )
    fecha_compra = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de Compra',
        help_text='Fecha cuando se realizó la compra'
    )
    fecha_expiracion_creditos = models.DateTimeField(
        verbose_name='Fecha de Expiración',
        help_text='Fecha cuando expiran estos créditos'
    )
    
    # Campos de timestamp
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('Compra de Créditos')
        verbose_name_plural = _('Compras de Créditos')
        ordering = ['-fecha_compra']
        indexes = [
            models.Index(fields=['proveedor', 'estado']),
            models.Index(fields=['fecha_compra']),
            models.Index(fields=['fecha_expiracion_creditos']),
            models.Index(fields=['estado']),
        ]
    
    def __str__(self):
        return f"{self.proveedor.username} - {self.cantidad_creditos} créditos - {self.get_estado_display()}"
    
    def clean(self):
        """Validaciones del modelo"""
        if self.precio_total < 0:
            raise ValidationError({
                'precio_total': 'El precio total no puede ser negativo'
            })
        if self.cantidad_creditos <= 0:
            raise ValidationError({
                'cantidad_creditos': 'La cantidad de créditos debe ser mayor a 0'
            })
    
    def save(self, *args, **kwargs):
        """Sobrescribir save para ejecutar validaciones"""
        self.full_clean()
        super().save(*args, **kwargs)


class ConsumoCredito(models.Model):
    """
    Registro de consumo de créditos al adjudicar una oferta.
    """
    proveedor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='consumos_creditos',
        verbose_name='Proveedor',
        help_text='Proveedor que consumió los créditos'
    )
    oferta = models.ForeignKey(
        'ordenes.OfertaProveedor',
        on_delete=models.CASCADE,
        related_name='consumos_credito',
        verbose_name='Oferta',
        help_text='Oferta que generó el consumo de créditos'
    )
    servicio = models.ForeignKey(
        'servicios.Servicio',
        on_delete=models.PROTECT,
        related_name='consumos_credito',
        verbose_name='Servicio',
        help_text='Servicio por el cual se consumieron los créditos'
    )
    creditos_consumidos = models.IntegerField(
        validators=[MinValueValidator(1)],
        verbose_name='Créditos Consumidos',
        help_text='Cantidad de créditos consumidos'
    )
    precio_credito = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name='Precio del Crédito',
        help_text='Precio del crédito al momento del consumo'
    )
    fecha_consumo = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de Consumo',
        help_text='Fecha cuando se consumieron los créditos'
    )
    
    # Campos de timestamp
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('Consumo de Crédito')
        verbose_name_plural = _('Consumos de Créditos')
        ordering = ['-fecha_consumo']
        indexes = [
            models.Index(fields=['proveedor', 'fecha_consumo']),
            models.Index(fields=['oferta']),
            models.Index(fields=['servicio']),
            models.Index(fields=['fecha_consumo']),
        ]
    
    def __str__(self):
        return f"{self.proveedor.username} - {self.creditos_consumidos} créditos - {self.servicio.nombre}"
    
    def clean(self):
        """Validaciones del modelo"""
        if self.creditos_consumidos <= 0:
            raise ValidationError({
                'creditos_consumidos': 'Los créditos consumidos deben ser mayor a 0'
            })
        if self.precio_credito < 0:
            raise ValidationError({
                'precio_credito': 'El precio del crédito no puede ser negativo'
            })
    
    def save(self, *args, **kwargs):
        """Sobrescribir save para ejecutar validaciones"""
        self.full_clean()
        super().save(*args, **kwargs)


class ConfiguracionCreditos(models.Model):
    """
    Configuración global del sistema de créditos.
    Define parámetros para calcular el precio de los créditos.
    """
    aov_promedio = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=150000,
        validators=[MinValueValidator(0)],
        verbose_name='AOV Promedio',
        help_text='Average Order Value promedio en CLP'
    )
    tasa_comision = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=0.10,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        verbose_name='Tasa de Comisión',
        help_text='Tasa de comisión deseada (ej: 0.10 = 10%)'
    )
    k_promedio = models.IntegerField(
        default=3,
        validators=[MinValueValidator(1)],
        verbose_name='K Promedio',
        help_text='Créditos promedio consumidos por trabajo'
    )
    precio_credito_base = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=5000,
        validators=[MinValueValidator(0)],
        verbose_name='Precio Crédito Base',
        help_text='Precio base del crédito calculado automáticamente'
    )
    creditos_expiracion_meses = models.IntegerField(
        default=12,
        validators=[MinValueValidator(1)],
        verbose_name='Meses de Expiración',
        help_text='Meses hasta que los créditos expiren'
    )
    activo = models.BooleanField(
        default=True,
        verbose_name='Activo',
        help_text='Indica si esta configuración está activa'
    )
    
    # Campos de timestamp
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('Configuración de Créditos')
        verbose_name_plural = _('Configuraciones de Créditos')
        ordering = ['-fecha_creacion']
    
    def __str__(self):
        return f"Configuración - AOV: ${self.aov_promedio:,.0f}, Tasa: {self.tasa_comision*100:.1f}%, K: {self.k_promedio}"
    
    def calcular_precio_credito(self):
        """Calcula el precio del crédito según la fórmula: C = (AOV × Tasa) / K_avg"""
        if self.k_promedio > 0:
            precio = (self.aov_promedio * self.tasa_comision) / self.k_promedio
            return precio
        return self.precio_credito_base
    
    def save(self, *args, **kwargs):
        """Sobrescribir save para calcular precio_credito_base automáticamente"""
        self.precio_credito_base = self.calcular_precio_credito()
        self.full_clean()
        super().save(*args, **kwargs)


class ConfiguracionCreditosServicio(models.Model):
    """
    Configuración de créditos requeridos por servicio.
    Permite definir créditos específicos para cada tipo de servicio.
    """
    servicio = models.OneToOneField(
        'servicios.Servicio',
        on_delete=models.CASCADE,
        related_name='configuracion_creditos',
        verbose_name='Servicio',
        help_text='Servicio al que aplica esta configuración'
    )
    creditos_requeridos = models.IntegerField(
        default=2,
        validators=[MinValueValidator(1)],
        verbose_name='Créditos Requeridos',
        help_text='Cantidad de créditos que se consumen al adjudicar este servicio'
    )
    activo = models.BooleanField(
        default=True,
        verbose_name='Activo',
        help_text='Indica si esta configuración está activa'
    )
    
    # Campos de timestamp
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('Configuración de Créditos por Servicio')
        verbose_name_plural = _('Configuraciones de Créditos por Servicio')
        ordering = ['servicio__nombre']
        indexes = [
            models.Index(fields=['servicio', 'activo']),
        ]
    
    def __str__(self):
        return f"{self.servicio.nombre} - {self.creditos_requeridos} créditos"
    
    def clean(self):
        """Validaciones del modelo"""
        if self.creditos_requeridos <= 0:
            raise ValidationError({
                'creditos_requeridos': 'Los créditos requeridos deben ser mayor a 0'
            })
    
    def save(self, *args, **kwargs):
        """Sobrescribir save para ejecutar validaciones"""
        self.full_clean()
        super().save(*args, **kwargs)


class ProveedorCancelaciones(models.Model):
    """
    Registro de cancelaciones de proveedores para medidas anti-gaming.
    """
    proveedor = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cancelaciones_proveedor',
        verbose_name='Proveedor',
        help_text='Usuario proveedor'
    )
    cancelaciones_mes_actual = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name='Cancelaciones Mes Actual',
        help_text='Número de cancelaciones en el mes actual'
    )
    fecha_reset_cancelaciones = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha Reset Cancelaciones',
        help_text='Fecha del último reset del contador de cancelaciones'
    )
    suspension_temporal = models.BooleanField(
        default=False,
        verbose_name='Suspensión Temporal',
        help_text='Indica si el proveedor está suspendido temporalmente'
    )
    fecha_suspension = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de Suspensión',
        help_text='Fecha cuando se aplicó la suspensión'
    )
    
    # Campos de timestamp
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('Cancelaciones de Proveedor')
        verbose_name_plural = _('Cancelaciones de Proveedores')
        ordering = ['-fecha_actualizacion']
        indexes = [
            models.Index(fields=['proveedor']),
            models.Index(fields=['suspension_temporal']),
        ]
    
    def __str__(self):
        estado = "Suspendido" if self.suspension_temporal else "Activo"
        return f"{self.proveedor.username} - {self.cancelaciones_mes_actual} cancelaciones - {estado}"
    
    def clean(self):
        """Validaciones del modelo"""
        if self.cancelaciones_mes_actual < 0:
            raise ValidationError({
                'cancelaciones_mes_actual': 'El número de cancelaciones no puede ser negativo'
            })
    
    def save(self, *args, **kwargs):
        """Sobrescribir save para ejecutar validaciones"""
        self.full_clean()
        super().save(*args, **kwargs)


# ============================================================================
# MODELOS DEL SISTEMA DE SUSCRIPCIONES MENSUALES (CAPA SUPERIOR)
# ============================================================================

class PlanSuscripcion(models.Model):
    """
    Planes de suscripción mensual disponibles para los proveedores.
    Cada plan otorga una cantidad fija de créditos al mes.
    El mp_plan_id se crea manualmente en el panel de MP o via API.
    """
    nombre = models.CharField(
        max_length=100,
        verbose_name='Nombre',
        help_text='Nombre del plan (ej: "Plan Básico", "Plan Pro")'
    )
    descripcion = models.TextField(
        blank=True,
        verbose_name='Descripción',
        help_text='Descripción del plan y sus beneficios'
    )
    precio = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name='Precio Mensual (CLP)',
        help_text='Precio mensual del plan en CLP'
    )
    creditos_mensuales = models.IntegerField(
        validators=[MinValueValidator(1)],
        verbose_name='Créditos Mensuales',
        help_text='Cantidad de créditos que se otorgan cada mes al confirmarse el cobro'
    )
    mp_preapproval_plan_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name='ID Plan MercadoPago',
        help_text='ID del plan de Preapproval en MercadoPago (opcional, si se usan Preapproval Plans)'
    )
    activo = models.BooleanField(
        default=True,
        verbose_name='Activo',
        help_text='Plan disponible para nuevas suscripciones'
    )
    destacado = models.BooleanField(
        default=False,
        verbose_name='Destacado',
        help_text='Plan que se destaca visualmente en la UI'
    )
    orden = models.IntegerField(
        default=0,
        verbose_name='Orden',
        help_text='Orden de visualización (menor = primero)'
    )

    # Timestamps
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Plan de Suscripción')
        verbose_name_plural = _('Planes de Suscripción')
        ordering = ['orden', 'precio']
        indexes = [
            models.Index(fields=['activo', 'orden']),
        ]

    def __str__(self):
        return f"{self.nombre} — {self.creditos_mensuales} créditos/mes — ${self.precio:,.0f}/mes"


class SuscripcionProveedor(models.Model):
    """
    Registro de suscripción mensual de un proveedor.
    Vincula al proveedor con un PlanSuscripcion y almacena el estado
    de la suscripción en MercadoPago Preapproval.
    """
    ESTADOS = [
        ('pendiente', 'Pendiente'),       # Suscripción creada, aún no autorizada
        ('activa', 'Activa'),             # Cobro periódico activo
        ('pausada', 'Pausada'),           # Pausada temporalmente
        ('cancelada', 'Cancelada'),       # Cancelada por el proveedor o admin
        ('expirada', 'Expirada'),         # Dejó de cobrarse por falta de pago
    ]

    proveedor = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='suscripcion_proveedor',
        verbose_name='Proveedor',
        help_text='Proveedor suscripto'
    )
    plan = models.ForeignKey(
        PlanSuscripcion,
        on_delete=models.PROTECT,
        related_name='suscripciones',
        verbose_name='Plan',
        help_text='Plan de suscripción contratado'
    )
    estado = models.CharField(
        max_length=20,
        choices=ESTADOS,
        default='pendiente',
        verbose_name='Estado',
        help_text='Estado actual de la suscripción'
    )
    mp_preapproval_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        unique=True,
        verbose_name='ID Preapproval MercadoPago',
        help_text='ID de la suscripción (preapproval) en MercadoPago'
    )
    mp_init_point = models.TextField(
        blank=True,
        null=True,
        verbose_name='URL de Pago Inicial',
        help_text='init_point retornado por MercadoPago para que el proveedor autorice'
    )
    ultimo_charge_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name='Último Charge ID',
        help_text='ID del último cobro procesado (legacy, conservado por compatibilidad)'
    )
    processed_charge_ids = models.JSONField(
        default=list,
        blank=True,
        verbose_name='IDs de Cobros Procesados',
        help_text='Lista de todos los charge_ids ya acreditados (idempotencia robusta)'
    )
    fecha_inicio = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de Inicio',
        help_text='Fecha de creación de la suscripción'
    )
    fecha_proximo_cobro = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name='Próximo Cobro',
        help_text='Fecha estimada del próximo cobro automático'
    )
    fecha_cancelacion = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name='Fecha de Cancelación',
        help_text='Fecha en que se canceló la suscripción'
    )

    # Timestamps
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Suscripción de Proveedor')
        verbose_name_plural = _('Suscripciones de Proveedores')
        ordering = ['-fecha_inicio']
        indexes = [
            models.Index(fields=['proveedor', 'estado']),
            models.Index(fields=['mp_preapproval_id']),
            models.Index(fields=['estado']),
        ]

    def __str__(self):
        return f"{self.proveedor.username} — {self.plan.nombre} — {self.get_estado_display()}"

    @property
    def esta_activa(self):
        """Retorna True si la suscripción está activa y otorga créditos."""
        return self.estado == 'activa'


class CobroSuscripcion(models.Model):
    """
    Registro de auditoría para cada cobro recurrente verificado en MercadoPago.
    Se crea SOLO cuando un cobro pasa la verificación de doble nivel:
      1. authorized_payment.status in (approved, processed, authorized)
      2. GET /v1/payments/{id} confirma status=approved, status_detail=accredited,
         collector_id=Mecanimovil
    """
    suscripcion = models.ForeignKey(
        SuscripcionProveedor,
        on_delete=models.CASCADE,
        related_name='cobros',
        verbose_name='Suscripción',
    )
    charge_id = models.CharField(
        max_length=50,
        verbose_name='Authorized Payment ID',
        help_text='ID del authorized_payment en MP',
    )
    payment_id = models.CharField(
        max_length=50,
        verbose_name='Payment ID',
        help_text='ID del payment real en MP (/v1/payments/{id})',
    )
    status = models.CharField(max_length=30, verbose_name='Estado del cobro en MP')
    status_detail = models.CharField(max_length=50, verbose_name='Detalle del estado')
    transaction_amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='Monto cobrado')
    net_received_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name='Monto neto recibido',
    )
    currency_id = models.CharField(max_length=5, default='CLP')
    collector_id = models.BigIntegerField(
        verbose_name='ID de cuenta receptora',
        help_text='Debe coincidir con la cuenta de Mecanimovil',
    )
    payer_email = models.EmailField(blank=True, default='')
    payer_id = models.CharField(max_length=50, blank=True, default='')
    card_last_four = models.CharField(max_length=4, blank=True, default='')
    payment_method = models.CharField(max_length=30, blank=True, default='')
    date_approved = models.DateTimeField(null=True, blank=True, verbose_name='Fecha aprobación MP')
    creditos_otorgados = models.IntegerField(default=0, verbose_name='Créditos otorgados')
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Cobro de Suscripción'
        verbose_name_plural = 'Cobros de Suscripción'
        ordering = ['-date_approved']
        unique_together = [('suscripcion', 'charge_id')]
        indexes = [
            models.Index(fields=['charge_id']),
            models.Index(fields=['payment_id']),
        ]

    def __str__(self):
        return (
            f"Cobro #{self.charge_id} — ${self.transaction_amount} "
            f"({self.status}) → {self.creditos_otorgados} créditos"
        )

