from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator
from mecanimovilapp.apps.usuarios.models import Cliente, MecanicoDomicilio, Taller, Usuario, DireccionUsuario
from mecanimovilapp.apps.servicios.models import Servicio, OfertaServicio
from mecanimovilapp.apps.vehiculos.models import Vehiculo
from django.utils import timezone
from decimal import Decimal
from django.contrib.gis.db import models as gis_models
from datetime import timedelta, datetime, time
import logging
import uuid

logger = logging.getLogger(__name__)


class SolicitudServicio(models.Model):
    """
    Modelo para gestionar las solicitudes de servicio
    """
    ESTADO_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('pago_validado', 'Pago Validado'),
        ('confirmado', 'Confirmado'),
        ('pendiente_aceptacion_proveedor', 'Pendiente de Aceptación del Proveedor'),
        ('aceptada_por_proveedor', 'Aceptada por Proveedor'),
        ('rechazada_por_proveedor', 'Rechazada por Proveedor'),
        ('checklist_en_progreso', 'Checklist en Progreso'),
        ('checklist_completado', 'Checklist Completado'),
        ('en_proceso', 'En Proceso'),
        ('pendiente_firma_cliente', 'Pendiente de Firma del Cliente'),
        ('completado', 'Completado'),
        ('cancelado', 'Cancelado'),
        ('solicitud_cancelacion', 'Solicitud de Cancelación'),
        ('pendiente_devolucion', 'Pendiente de Devolución'),
        ('devuelto', 'Devuelto'),
    ]
    
    TIPO_SERVICIO_CHOICES = [
        ('taller', 'Taller'),
        ('domicilio', 'Domicilio'),
    ]
    
    METODO_PAGO_CHOICES = [
        ('efectivo', 'Efectivo'),
        ('debito', 'Débito'),
        ('credito', 'Crédito'),
        ('transferencia', 'Transferencia'),
        ('mercadopago', 'Mercado Pago'),
    ]
    
    # Información básica de la solicitud
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        related_name='solicitudes'
    )
    vehiculo = models.ForeignKey(
        Vehiculo,
        on_delete=models.SET_NULL,  # Changed from CASCADE to SET_NULL - preserves service history
        related_name='solicitudes',
        null=True,
        blank=True
    )
    fecha_hora_solicitud = models.DateTimeField(auto_now_add=True)
    ubicacion_servicio = models.CharField(max_length=255, null=True, blank=True)
    
    # Información del servicio
    tipo_servicio = models.CharField(max_length=20, choices=TIPO_SERVICIO_CHOICES)
    taller = models.ForeignKey(
        Taller,
        on_delete=models.CASCADE,
        related_name='solicitudes',
        null=True,
        blank=True
    )
    mecanico = models.ForeignKey(
        MecanicoDomicilio,
        on_delete=models.CASCADE,
        related_name='solicitudes',
        null=True,
        blank=True
    )
    fecha_servicio = models.DateField()
    hora_servicio = models.TimeField()
    
    # Información de pago y estado
    metodo_pago = models.CharField(max_length=20, choices=METODO_PAGO_CHOICES)
    total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    estado = models.CharField(max_length=40, choices=ESTADO_CHOICES, default='pendiente')
    
    # Campos adicionales para gestión de pagos
    comprobante_pago = models.ImageField(
        upload_to='comprobantes/',
        null=True,
        blank=True,
        help_text=_('Comprobante de pago subido por el cliente')
    )
    comprobante_validado = models.BooleanField(
        default=False,
        help_text=_('Indica si el comprobante de pago ha sido validado por un administrador')
    )
    fecha_validacion = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Fecha cuando se validó el comprobante de pago')
    )
    notas_cliente = models.TextField(
        null=True,
        blank=True,
        help_text=_('Notas adicionales del cliente sobre la solicitud')
    )
    notas_admin = models.TextField(
        null=True,
        blank=True,
        help_text=_('Notas internas del administrador')
    )
    
    # Campos para proceso de cancelación y devolución
    motivo_cancelacion = models.TextField(
        null=True,
        blank=True,
        help_text=_('Motivo de la cancelación proporcionado por el cliente')
    )
    fecha_cancelacion = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Fecha cuando se procesó la cancelación')
    )
    fecha_devolucion = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Fecha cuando se procesó la devolución')
    )
    devolucion_procesada = models.BooleanField(
        default=False,
        help_text=_('Indica si la devolución ha sido procesada')
    )
    requiere_devolucion = models.BooleanField(
        default=False,
        help_text=_('Indica si la solicitud requiere devolución')
    )
    
    # Campos para gestión de proveedores
    fecha_respuesta_proveedor = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Fecha cuando el proveedor respondió a la solicitud')
    )
    motivo_rechazo = models.TextField(
        null=True,
        blank=True,
        help_text=_('Motivo del rechazo por parte del proveedor')
    )
    notas_proveedor = models.TextField(
        null=True,
        blank=True,
        help_text=_('Notas adicionales del proveedor sobre la orden')
    )
    
    # Relación con oferta de proveedor (para solicitudes públicas)
    oferta_proveedor = models.ForeignKey(
        'OfertaProveedor',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='solicitudes_servicio',
        help_text='Oferta de proveedor que originó esta solicitud',
        verbose_name='Oferta Proveedor'
    )
    # Trazabilidad marketplace: oferta de compra que origina inspección pre-compra
    oferta_marketplace = models.ForeignKey(
        'vehiculos.OfertaVehiculo',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='solicitudes_inspeccion',
        help_text='Oferta de compra marketplace que originó esta inspección pre-compra',
        verbose_name='Oferta Marketplace',
    )
    
    class Meta:
        verbose_name = _('solicitud de servicio')
        verbose_name_plural = _('solicitudes de servicio')
    
    def __str__(self):
        return f"Solicitud #{self.id} - {self.cliente.nombre} - {self.estado}"
    
    def puede_cancelar_directamente(self):
        """
        Determina si la solicitud puede cancelarse directamente sin proceso especial
        """
        return (
            self.estado in ['pendiente'] and 
            not self.comprobante_validado
        )
    
    def requiere_proceso_cancelacion(self):
        """
        Determina si la cancelación requiere un proceso especial (con devolución)
        """
        return (
            self.estado in ['pendiente', 'pago_validado', 'confirmado'] and 
            self.comprobante_validado and
            self.metodo_pago == 'transferencia'
        )
    
    def puede_solicitar_cancelacion(self):
        """
        Determina si el cliente puede solicitar cancelación
        """
        return self.estado in ['pendiente', 'pago_validado', 'confirmado']
    
    def requiere_checklist(self):
        """
        Determina si esta orden requiere checklist de pre-servicio
        """
        # El checklist es obligatorio cuando el proveedor acepta la orden
        return self.estado in [
            'aceptada_por_proveedor', 
            'checklist_en_progreso', 
            'checklist_completado',
            'en_proceso', 
            'completado'
        ]
    
    def puede_iniciar_checklist(self):
        """
        Determina si se puede iniciar el checklist para esta orden
        """
        return self.estado == 'aceptada_por_proveedor'
    
    def puede_continuar_checklist(self):
        """
        Determina si se puede continuar con un checklist en progreso
        """
        return self.estado == 'checklist_en_progreso'
    
    def puede_pasar_a_en_proceso(self):
        """
        Determina si la orden puede pasar al estado 'en_proceso'
        """
        # Solo puede pasar a 'en_proceso' si el checklist está completado
        return (
            self.estado == 'checklist_completado' and 
            hasattr(self, 'checklist_instance') and
            self.checklist_instance.estado == 'COMPLETADO'
        )
    
    def puede_finalizar(self):
        """
        Determina si la orden puede ser finalizada
        """
        # Solo se puede finalizar si está en proceso y tiene checklist completado
        return (
            self.estado == 'en_proceso' and
            hasattr(self, 'checklist_instance') and
            self.checklist_instance.estado == 'COMPLETADO'
        )


class LineaServicio(models.Model):
    """
    Modelo para representar cada línea de servicio en una solicitud
    """
    solicitud = models.ForeignKey(
        SolicitudServicio,
        on_delete=models.CASCADE,
        related_name='lineas'
    )
    oferta_servicio = models.ForeignKey(
        OfertaServicio,
        on_delete=models.CASCADE,
        related_name='lineas_servicio',
        null=True,
        blank=True
    )
    con_repuestos = models.BooleanField(default=False)
    cantidad = models.PositiveIntegerField(default=1)
    precio_unitario = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    descuento_porcentaje = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    precio_final = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    
    class Meta:
        verbose_name = _('línea de servicio')
        verbose_name_plural = _('líneas de servicio')
    
    def __str__(self):
        return f"{self.solicitud.id} - {self.oferta_servicio.servicio.nombre if self.oferta_servicio else 'Sin servicio'}"
    
    def save(self, *args, **kwargs):
        """Calcula automáticamente el precio final al guardar"""
        precio_base = self.precio_unitario * Decimal(self.cantidad)
        descuento = precio_base * (self.descuento_porcentaje / Decimal('100'))
        self.precio_final = precio_base - descuento
        super().save(*args, **kwargs)


class ConfiguracionPrecio(models.Model):
    """
    Modelo para configurar IVA y tarifa de servicio
    """
    iva_porcentaje = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=19.0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text=_('Porcentaje de IVA a aplicar')
    )
    tarifa_servicio_porcentaje = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=3.0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text=_('Porcentaje de tarifa de servicio a aplicar')
    )
    activo = models.BooleanField(
        default=True,
        help_text=_('Indica si esta configuración está activa')
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = _('configuración de precio')
        verbose_name_plural = _('configuraciones de precio')
        ordering = ['-fecha_creacion']
    
    def __str__(self):
        return f"IVA: {self.iva_porcentaje}% - Tarifa: {self.tarifa_servicio_porcentaje}%"
    
    def save(self, *args, **kwargs):
        """Si se marca como activo, desactivar las demás configuraciones"""
        if self.activo:
            ConfiguracionPrecio.objects.filter(activo=True).update(activo=False)
        super().save(*args, **kwargs)


class CarritoAgendamiento(models.Model):
    """
    Modelo para el carrito de agendamiento - agrupa servicios por vehículo antes de confirmar
    """
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        related_name='carritos'
    )
    vehiculo = models.ForeignKey(
        Vehiculo,
        on_delete=models.CASCADE,
        related_name='carritos'
    )
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    # Campos para la programación del servicio (opcional, para carritos simples)
    fecha_programada = models.DateField(null=True, blank=True)
    hora_programada = models.TimeField(null=True, blank=True)
    
    # Campo para notas adicionales
    notas = models.TextField(
        null=True,
        blank=True,
        help_text=_('Notas adicionales sobre el carrito')
    )
    # Inspección pre-compra: oferta marketplace que habilita vehículo ajeno
    oferta_marketplace = models.ForeignKey(
        'vehiculos.OfertaVehiculo',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='carritos_inspeccion',
        help_text=_('Oferta de compra marketplace (inspección pre-compra)'),
    )
    
    class Meta:
        verbose_name = _('carrito de agendamiento')
        verbose_name_plural = _('carritos de agendamiento')
        # CORREGIDO: Usar índices únicos parciales en lugar de unique_together
        # La restricción única se maneja a nivel de base de datos con un índice parcial
        # que solo aplica a carritos activos (activo=true)
        # Esto permite múltiples carritos inactivos pero solo uno activo por cliente
        indexes = [
            # Índice para mejorar consultas por cliente y estado
            models.Index(fields=['cliente', 'activo'], name='carrito_cliente_activo_idx'),
            # Índice para consultas por vehículo
            models.Index(fields=['vehiculo', 'activo'], name='carrito_vehiculo_activo_idx'),
        ]
        # NOTA: La restricción única parcial se crea en la migración 0021
        # CREATE UNIQUE INDEX ordenes_carritoagendamiento_cliente_activo_unique_partial
        # ON ordenes_carritoagendamiento (cliente_id) WHERE activo = true;
    
    def __str__(self):
        vehiculo_info = f"{self.vehiculo.marca} {self.vehiculo.modelo}" if self.vehiculo else "Sin vehículo"
        return f"Carrito {self.id} - {self.cliente.nombre} - {vehiculo_info}"
    
    @property
    def total(self):
        """Calcula el total del carrito"""
        return sum(item.precio_estimado for item in self.items.all())
    
    @property
    def cantidad_items(self):
        """Retorna la cantidad total de items en el carrito"""
        return sum(item.cantidad for item in self.items.all())
    
    def puede_confirmar(self):
        """Verifica si el carrito puede ser confirmado"""
        return (
            self.activo and 
            self.items.exists() and
            all(item.fecha_servicio and item.hora_servicio for item in self.items.all())
        )


class ItemCarritoAgendamiento(models.Model):
    """
    Modelo para los items individuales del carrito de agendamiento
    """
    carrito = models.ForeignKey(
        CarritoAgendamiento,
        on_delete=models.CASCADE,
        related_name='items'
    )
    oferta_servicio = models.ForeignKey(
        OfertaServicio,
        on_delete=models.CASCADE,
        related_name='items_carrito'
    )
    con_repuestos = models.BooleanField(default=True)
    cantidad = models.PositiveIntegerField(default=1)
    fecha_agregado = models.DateTimeField(auto_now_add=True)
    
    # NUEVOS CAMPOS: Cada servicio tiene su propia fecha y hora
    fecha_servicio = models.DateField(null=True, blank=True)
    hora_servicio = models.TimeField(null=True, blank=True)
    
    # NUEVOS CAMPOS: Información de repuestos
    configuracion_repuestos = models.JSONField(
        null=True, 
        blank=True,
        help_text=_('Configuración JSON de repuestos seleccionados')
    )
    notas_repuestos = models.TextField(
        null=True,
        blank=True,
        help_text=_('Notas adicionales sobre los repuestos')
    )
    
    class Meta:
        verbose_name = _('item de carrito de agendamiento')
        verbose_name_plural = _('items de carrito de agendamiento')
        # Un servicio solo puede estar una vez en el carrito
        unique_together = ('carrito', 'oferta_servicio')
    
    def __str__(self):
        fecha_hora = ""
        if self.fecha_servicio and self.hora_servicio:
            fecha_hora = f" - {self.fecha_servicio} {self.hora_servicio}"
        return f"{self.carrito.id} - {self.oferta_servicio.servicio.nombre}{fecha_hora}"
    
    @property
    def precio_estimado(self):
        """Calcula el precio estimado del item"""
        if self.con_repuestos:
            precio_unitario = self.oferta_servicio.precio_con_repuestos
        else:
            precio_unitario = self.oferta_servicio.precio_sin_repuestos
        return precio_unitario * Decimal(self.cantidad)


class AuditAccesoCliente(models.Model):
    """
    Modelo para auditar accesos a información sensible de clientes
    """
    TIPO_ACCESO_CHOICES = [
        ('vista_listado', 'Vista de Listado'),
        ('vista_detalle', 'Vista de Detalle'),
        ('contacto_directo', 'Contacto Directo'),
        ('exportacion', 'Exportación de Datos'),
    ]
    
    NIVEL_INFORMACION_CHOICES = [
        ('parcial', 'Información Parcial'),
        ('completo', 'Información Completa'),
        ('restringido', 'Acceso Restringido'),
    ]
    
    # Información del acceso
    solicitud_servicio = models.ForeignKey(
        SolicitudServicio,
        on_delete=models.CASCADE,
        related_name='auditorias_acceso'
    )
    usuario_proveedor = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.CASCADE,
        related_name='accesos_auditados'
    )
    
    # Detalles del acceso
    fecha_acceso = models.DateTimeField(auto_now_add=True)
    tipo_acceso = models.CharField(max_length=20, choices=TIPO_ACCESO_CHOICES)
    nivel_informacion = models.CharField(max_length=15, choices=NIVEL_INFORMACION_CHOICES)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    
    # Contexto adicional
    estado_orden_acceso = models.CharField(
        max_length=40, 
        help_text="Estado de la orden al momento del acceso"
    )
    datos_accedidos = models.JSONField(
        default=dict,
        help_text="Lista de campos específicos accedidos"
    )
    justificacion = models.CharField(
        max_length=200,
        null=True, 
        blank=True,
        help_text="Justificación automática del acceso"
    )
    
    # Flags de seguridad
    acceso_autorizado = models.BooleanField(
        default=True,
        help_text="Si el acceso estaba autorizado según las reglas de negocio"
    )
    requiere_revision = models.BooleanField(
        default=False,
        help_text="Si este acceso requiere revisión manual"
    )
    
    class Meta:
        verbose_name = 'Auditoría de Acceso a Cliente'
        verbose_name_plural = 'Auditorías de Acceso a Clientes'
        ordering = ['-fecha_acceso']
        indexes = [
            models.Index(fields=['fecha_acceso']),
            models.Index(fields=['usuario_proveedor', 'fecha_acceso']),
            models.Index(fields=['solicitud_servicio', 'fecha_acceso']),
            models.Index(fields=['requiere_revision']),
        ]
    
    def __str__(self):
        return f"Acceso {self.tipo_acceso} - {self.usuario_proveedor.username} - Orden {self.solicitud_servicio.id}"
    
    @classmethod
    def registrar_acceso(cls, solicitud_servicio, usuario_proveedor, tipo_acceso, nivel_informacion, request=None, datos_accedidos=None):
        """
        Método para registrar un acceso de manera conveniente
        """
        ip_address = None
        user_agent = None
        
        if request:
            # Obtener IP real considerando proxies
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip_address = x_forwarded_for.split(',')[0]
            else:
                ip_address = request.META.get('REMOTE_ADDR')
            user_agent = request.META.get('HTTP_USER_AGENT', '')
        
        # Determinar si el acceso requiere revisión
        requiere_revision = cls._determinar_si_requiere_revision(
            solicitud_servicio, nivel_informacion, tipo_acceso
        )
        
        # Generar justificación automática
        justificacion = cls._generar_justificacion(
            solicitud_servicio, nivel_informacion, tipo_acceso
        )
        
        return cls.objects.create(
            solicitud_servicio=solicitud_servicio,
            usuario_proveedor=usuario_proveedor,
            tipo_acceso=tipo_acceso,
            nivel_informacion=nivel_informacion,
            ip_address=ip_address,
            user_agent=user_agent,
            estado_orden_acceso=solicitud_servicio.estado,
            datos_accedidos=datos_accedidos or {},
            justificacion=justificacion,
            acceso_autorizado=nivel_informacion != 'restringido',
            requiere_revision=requiere_revision
        )
    
    @staticmethod
    def _determinar_si_requiere_revision(solicitud_servicio, nivel_informacion, tipo_acceso):
        """
        Determina si un acceso requiere revisión manual
        """
        # Accesos que siempre requieren revisión
        if tipo_acceso == 'contacto_directo':
            return True
        
        # Acceso completo a órdenes cerradas
        if (nivel_informacion == 'completo' and 
            solicitud_servicio.estado in ['completado', 'cancelado']):
            return True
        
        # Acceso restringido (no autorizado)
        if nivel_informacion == 'restringido':
            return True
        
        return False
    
    @staticmethod
    def _generar_justificacion(solicitud_servicio, nivel_informacion, tipo_acceso):
        """
        Genera una justificación automática del acceso
        """
        if nivel_informacion == 'completo':
            return f"Acceso autorizado - Orden en estado {solicitud_servicio.estado}"
        elif nivel_informacion == 'parcial':
            return f"Información limitada - Orden pendiente de aceptación"
        else:
            return f"Acceso restringido - Orden en estado {solicitud_servicio.estado}"


# ============================================================================
# MODELOS DEL SISTEMA DE POSTULACIONES
# ============================================================================

class SolicitudServicioPublica(models.Model):
    """
    Solicitud pública de servicio creada por cliente.
    Los proveedores pueden ofertar en esta solicitud.
    """
    
    # Identificador único
    id = models.UUIDField(
        primary_key=True, 
        default=uuid.uuid4, 
        editable=False
    )
    
    # Relaciones básicas
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        related_name='solicitudes_publicas',
        verbose_name='Cliente'
    )
    
    vehiculo = models.ForeignKey(
        Vehiculo,
        on_delete=models.SET_NULL,  # Changed from CASCADE to SET_NULL - preserves service history
        related_name='solicitudes_publicas',
        verbose_name='Vehículo',
        null=True,  # Added to allow NULL when vehicle is deleted
        blank=True
    )

    # Vehículo del vendedor (marketplace) en inspección pre-compra sin vehículo registrado del comprador
    vehiculo_inspeccion_precompra = models.ForeignKey(
        Vehiculo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='solicitudes_publicas_inspeccion_precompra',
        verbose_name='Vehículo inspección pre-compra (marketplace)',
        help_text='Vehículo ofertado por el vendedor; permite evitar duplicados de pre-compra por comprador.',
    )
    
    # Descripción general (antes de seleccionar servicios)
    descripcion_problema = models.TextField(
        help_text='Descripción libre del problema o necesidad del cliente',
        verbose_name='Descripción del Problema'
    )
    
    urgencia = models.CharField(
        max_length=20,
        choices=[
            ('normal', 'Normal'),
            ('urgente', 'Urgente')
        ],
        default='normal',
        verbose_name='Urgencia'
    )
    
    # Requiere repuestos
    requiere_repuestos = models.BooleanField(
        default=True,
        help_text='Indica si la solicitud requiere repuestos o solo mano de obra',
        verbose_name='Requiere Repuestos'
    )
    
    # Tipo de solicitud (global vs dirigida)
    tipo_solicitud = models.CharField(
        max_length=20,
        choices=[
            ('global', 'Abierta a Todos'),
            ('dirigida', 'Solo Proveedores Específicos')
        ],
        default='global',
        verbose_name='Tipo de Solicitud',
        help_text='Global: broadcast a todos. Dirigida: solo proveedores seleccionados'
    )
    
    # Proveedores específicos (solo si tipo_solicitud = 'dirigida')
    # Nota: La validación de que sean proveedores se hace en el serializer
    proveedores_dirigidos = models.ManyToManyField(
        Usuario,
        blank=True,
        related_name='solicitudes_dirigidas_recibidas',
        help_text='Proveedores específicos para solicitud dirigida (máx 5). Deben tener taller o mecanico_domicilio relacionado.',
        verbose_name='Proveedores Dirigidos'
    )
    
    # Servicios solicitados (después de que el sistema sugiere)
    servicios_solicitados = models.ManyToManyField(
        Servicio,
        related_name='solicitudes_publicas',
        blank=True,
        help_text='Servicios específicos seleccionados por el cliente',
        verbose_name='Servicios Solicitados'
    )
    
    # Ubicación del servicio (usando direcciones registradas del usuario)
    direccion_usuario = models.ForeignKey(
        DireccionUsuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='solicitudes_en_esta_direccion',
        help_text='Dirección registrada del usuario para el servicio',
        verbose_name='Dirección del Usuario'
    )
    
    ubicacion_servicio = gis_models.PointField(
        geography=True,
        help_text='Coordenadas geográficas del servicio',
        verbose_name='Ubicación del Servicio'
    )
    
    direccion_servicio_texto = models.CharField(
        max_length=500,
        help_text='Dirección en formato texto legible',
        verbose_name='Dirección del Servicio'
    )
    
    detalles_ubicacion = models.CharField(
        max_length=255,
        blank=True,
        help_text='Detalles adicionales (ej: Depto 4B, portón verde)',
        verbose_name='Detalles de Ubicación'
    )
    
    # Fecha y hora preferida
    fecha_preferida = models.DateField(
        help_text='Fecha preferida por el cliente',
        verbose_name='Fecha Preferida'
    )
    
    hora_preferida = models.TimeField(
        null=True,
        blank=True,
        help_text='Hora preferida (opcional)',
        verbose_name='Hora Preferida'
    )
    
    # Estados del ciclo de vida
    estado = models.CharField(
        max_length=30,
        choices=[
            ('creada', 'Creada - Pendiente Servicios'),
            ('seleccionando_servicios', 'Seleccionando Servicios'),
            ('publicada', 'Publicada - Esperando Ofertas'),
            ('con_ofertas', 'Con Ofertas Recibidas'),
            ('esperando_creditos_proveedor', 'Esperando confirmación de créditos del proveedor'),
            ('adjudicada', 'Adjudicada a Proveedor'),
            ('pendiente_pago', 'Cliente Procesando Pago'),
            ('pagada', 'Pago Completado - Listo para Iniciar'),
            ('en_ejecucion', 'Servicio en Progreso'),
            ('completada', 'Servicio Finalizado'),
            ('expirada', 'Expirada Sin Ofertas'),
            ('cancelada', 'Cancelada por Cliente'),
        ],
        default='creada',
        verbose_name='Estado',
        db_index=True
    )
    
    # Control de tiempo
    fecha_creacion = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de Creación'
    )
    
    fecha_publicacion = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Momento en que se publicó a proveedores',
        verbose_name='Fecha de Publicación'
    )
    
    fecha_expiracion = models.DateTimeField(
        help_text='Fecha límite para recibir ofertas',
        verbose_name='Fecha de Expiración'
    )
    
    fecha_limite_pago = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Fecha límite para pagar después de adjudicar (fecha del servicio)',
        verbose_name='Fecha Límite de Pago'
    )

    fecha_limite_confirmacion_creditos = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Plazo para que el proveedor elegido acredite créditos y confirme la adjudicación',
        verbose_name='Fecha límite confirmación créditos proveedor'
    )
    
    fecha_actualizacion = models.DateTimeField(
        auto_now=True,
        verbose_name='Última Actualización'
    )
    
    # Oferta seleccionada (si adjudicada)
    oferta_seleccionada = models.ForeignKey(
        'OfertaProveedor',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='solicitud_ganada',
        verbose_name='Oferta Seleccionada'
    )
    
    # Métricas
    total_ofertas = models.IntegerField(
        default=0,
        verbose_name='Total de Ofertas Recibidas'
    )
    
    total_visualizaciones = models.IntegerField(
        default=0,
        help_text='Cuántos proveedores vieron esta solicitud',
        verbose_name='Total de Visualizaciones'
    )
    
    total_rechazos = models.IntegerField(
        default=0,
        help_text='Total de rechazos recibidos de proveedores',
        verbose_name='Total de Rechazos'
    )

    metadata_ia_entrada = models.JSONField(
        null=True,
        blank=True,
        help_text='Entrada del asistente al crear (temperatura, origen texto/salud)',
        verbose_name='Metadata IA entrada',
    )
    
    class Meta:
        verbose_name = 'Solicitud Pública de Servicio'
        verbose_name_plural = 'Solicitudes Públicas de Servicio'
        ordering = ['-fecha_creacion']
        indexes = [
            models.Index(fields=['estado', 'fecha_creacion']),
            models.Index(fields=['cliente', 'estado']),
            models.Index(fields=['fecha_expiracion']),
        ]

    @staticmethod
    def compute_default_fecha_expiracion(*, now, fecha_preferida):
        """
        Calcula la fecha_expiracion por defecto (ventana para recibir ofertas).

        Reglas:
        - Si la solicitud es para mañana (fecha_preferida == hoy+1), expira en 2 horas.
        - En otros casos, expira en 48 horas.
        """
        try:
            today = timezone.localdate()
            manana = today + timedelta(days=1)
            if fecha_preferida == manana:
                return now + timedelta(hours=2)
        except Exception:
            # Fallback seguro: comportamiento histórico
            pass
        return now + timedelta(hours=48)
    
    def __str__(self):
        return f"Solicitud {self.id} - {self.cliente.usuario.get_full_name()} - {self.estado}"
    
    def save(self, *args, **kwargs):
        # Detectar cambio de estado para notificaciones push
        estado_anterior = None
        if self.pk:
            try:
                old_instance = SolicitudServicioPublica.objects.get(pk=self.pk)
                estado_anterior = old_instance.estado
            except SolicitudServicioPublica.DoesNotExist:
                pass
        
        # Establecer fecha de expiración automáticamente.
        # Regla de negocio:
        # - Si el servicio es para "mañana" (fecha_preferida == hoy+1), ventana corta para ofertar: 2 horas.
        # - Caso general: 48 horas.
        if not self.fecha_expiracion:
            self.fecha_expiracion = self.compute_default_fecha_expiracion(
                now=timezone.now(),
                fecha_preferida=self.fecha_preferida,
            )
        
        # Si cambia a estado 'publicada', registrar fecha
        if self.estado == 'publicada' and not self.fecha_publicacion:
            self.fecha_publicacion = timezone.now()
        
        super().save(*args, **kwargs)
        
        # Enviar notificaciones push si cambió el estado
        if estado_anterior and estado_anterior != self.estado:
            # Importar aquí para evitar imports circulares
            try:
                from mecanimovilapp.apps.ordenes.tasks import enviar_notificacion_cambio_estado
                
                if self.cliente and self.cliente.usuario:
                    # Enviar notificación de cambio de estado
                    # Wrapped en try-except para evitar crashes si Redis está saturado
                    try:
                        enviar_notificacion_cambio_estado.delay(
                            str(self.id),
                            self.cliente.usuario.id,
                            estado_anterior,
                            self.estado
                        )
                    except Exception as celery_error:
                        # Log del error pero no interrumpir el flujo
                        logger.error(
                            f"❌ Error enviando notificación via Celery (Redis saturado?): {celery_error}",
                            exc_info=False  # No imprimir stacktrace completo para reducir logs
                        )
                    
                    # Si cambió a 'adjudicada', programar recordatorio de pago
                    if estado_anterior != 'adjudicada' and self.estado == 'adjudicada':
                        from mecanimovilapp.apps.ordenes.tasks import enviar_push_notificacion_pago_pendiente
                        
                        if self.fecha_preferida:
                            # Combinar fecha y hora para crear un datetime consciente de zona horaria
                            request_time = datetime.combine(
                                self.fecha_preferida, 
                                self.hora_preferida or time(9, 0)
                            )
                            if timezone.is_naive(request_time):
                                request_time = timezone.make_aware(request_time)
                            
                            # Programar recordatorio 6 horas antes de la fecha límite
                            hora_recordatorio = request_time - timedelta(hours=6)
                            
                            # Solo programar si la hora del recordatorio aún no pasó
                            if hora_recordatorio > timezone.now():
                                mensaje = (
                                    f"Tu solicitud #{self.id} requiere pago antes de "
                                    f"{self.fecha_preferida.strftime('%d/%m/%Y a las %H:%M')}. "
                                    f"Recibirás un recordatorio 6 horas antes."
                                )
                                
                                try:
                                    enviar_push_notificacion_pago_pendiente.apply_async(
                                        args=[str(self.id), self.cliente.usuario.id, mensaje, '💳 Recordatorio de Pago'],
                                        eta=hora_recordatorio
                                    )
                                    logger.info(f"📅 Recordatorio de pago programado para solicitud {self.id} a las {hora_recordatorio}")
                                except Exception as celery_error:
                                    logger.error(
                                        f"❌ Error programando recordatorio de pago (Redis saturado?): {celery_error}",
                                        exc_info=False
                                    )
            except Exception as e:
                # No fallar el save si hay error en las notificaciones
                logger.error(f"❌ Error en sistema de notificaciones: {e}", exc_info=False)
    
    @property
    def tiempo_restante(self):
        """Retorna el tiempo restante en formato legible"""
        if self.estado in ['adjudicada', 'expirada', 'cancelada']:
            return "Finalizada"
        
        delta = self.fecha_expiracion - timezone.now()
        if delta.total_seconds() < 0:
            return "Expirada"
        
        horas = int(delta.total_seconds() // 3600)
        if horas < 1:
            minutos = int((delta.total_seconds() % 3600) // 60)
            return f"{minutos} minutos"
        elif horas < 24:
            return f"{horas} horas"
        else:
            dias = horas // 24
            return f"{dias} días"
    
    @property
    def puede_recibir_ofertas(self):
        """Indica si la solicitud aún puede recibir ofertas"""
        return (
            self.estado in ['publicada', 'con_ofertas'] and
            timezone.now() < self.fecha_expiracion
        )
    
    def incrementar_visualizaciones(self):
        """Incrementa el contador de visualizaciones"""
        self.total_visualizaciones += 1
        self.save(update_fields=['total_visualizaciones'])
    
    def incrementar_ofertas(self):
        """Incrementa el contador de ofertas y actualiza estado"""
        self.total_ofertas += 1
        if self.estado == 'publicada':
            self.estado = 'con_ofertas'
        self.save(update_fields=['total_ofertas', 'estado'])
    
    def tiene_respuestas(self):
        """Verifica si la solicitud tiene ofertas o rechazos"""
        return self.total_ofertas > 0 or self.total_rechazos > 0
    
    def puede_reenviar(self):
        """
        Verifica si el cliente puede reenviar la solicitud.
        Solo se puede reenviar si:
        - Tiene rechazos pero no ofertas activas
        - Estado es 'publicada' o 'expirada'
        """
        return (
            self.total_rechazos > 0 and 
            self.total_ofertas == 0 and 
            self.estado in ['publicada', 'expirada']
        )
    
    def puede_pagar(self):
        """
        Verifica si el cliente puede pagar la solicitud adjudicada.
        Solo puede pagar si la fecha actual es anterior a fecha_limite_pago.
        """
        if self.estado not in ['adjudicada', 'pendiente_pago']:
            return False
        
        if not self.fecha_limite_pago:
            # Si no hay fecha límite, permitir pago (compatibilidad con datos antiguos)
            return True
        
        return timezone.now() < self.fecha_limite_pago
    
    def tiempo_restante_pago(self):
        """
        Calcula el tiempo restante hasta la fecha límite de pago.
        Retorna None si no hay fecha límite o si ya expiró.
        """
        if not self.fecha_limite_pago:
            return None
        
        delta = self.fecha_limite_pago - timezone.now()
        if delta.total_seconds() < 0:
            return None
        
        return delta
    
    def debe_mostrar_alerta_cliente(self):
        """
        Verifica si se debe mostrar alerta al cliente.
        Se muestra cuando faltan 6 horas o menos para la fecha límite de pago.
        """
        if self.estado not in ['adjudicada', 'pendiente_pago']:
            return False
        
        if not self.fecha_limite_pago:
            return False
        
        tiempo_restante = self.tiempo_restante_pago()
        if not tiempo_restante:
            return False
        
        # 6 horas = 21600 segundos
        return tiempo_restante.total_seconds() <= 21600


class FotoSolicitudPublica(models.Model):
    """
    Fotos adjuntas por el cliente al describir la necesidad (máx. 3 por solicitud).
    Se muestran al cliente en el detalle de la solicitud y al proveedor en el detalle de la oferta.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    solicitud = models.ForeignKey(
        SolicitudServicioPublica,
        on_delete=models.CASCADE,
        related_name='fotos_necesidad',
        verbose_name='Solicitud',
    )
    imagen = models.ImageField(
        upload_to='solicitudes_publicas/fotos_necesidad/',
        verbose_name='Imagen',
    )
    orden = models.PositiveSmallIntegerField(
        default=1,
        help_text='Orden de visualización (1–3)',
        verbose_name='Orden',
    )
    fecha_subida = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de subida')

    class Meta:
        verbose_name = 'Foto de solicitud pública'
        verbose_name_plural = 'Fotos de solicitudes públicas'
        ordering = ['orden', 'fecha_subida']
        indexes = [
            models.Index(fields=['solicitud', 'orden']),
        ]

    def __str__(self):
        return f'Foto {self.orden} — {self.solicitud_id}'


class OfertaProveedor(models.Model):
    """
    Oferta de un proveedor para una solicitud pública.
    Puede incluir múltiples servicios con precios detallados.
    """
    
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    
    # Relaciones
    solicitud = models.ForeignKey(
        SolicitudServicioPublica,
        on_delete=models.CASCADE,
        related_name='ofertas',
        verbose_name='Solicitud'
    )
    
    # Nota: La validación de que sea proveedor se hace en el serializer/viewset
    proveedor = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name='ofertas_enviadas',
        help_text='Usuario proveedor. Debe tener taller o mecanico_domicilio relacionado.',
        verbose_name='Proveedor'
    )
    
    tipo_proveedor = models.CharField(
        max_length=20,
        choices=[
            ('taller', 'Taller'),
            ('mecanico', 'Mecánico a Domicilio')
        ],
        verbose_name='Tipo de Proveedor'
    )
    
    # Detalles de servicios ofertados (relación many-to-many con through)
    servicios_ofertados = models.ManyToManyField(
        Servicio,
        through='DetalleServicioOferta',
        related_name='ofertas_que_incluyen',
        verbose_name='Servicios Ofertados'
    )
    
    # Oferta general
    precio_total_ofrecido = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text='Precio total de la oferta (suma de todos los servicios)',
        verbose_name='Precio Total'
    )
    
    incluye_repuestos = models.BooleanField(
        default=False,
        help_text='Indica si el precio incluye repuestos',
        verbose_name='Incluye Repuestos'
    )
    
    tiempo_estimado_total = models.DurationField(
        help_text='Tiempo total estimado para completar todos los servicios',
        verbose_name='Tiempo Estimado Total'
    )
    
    descripcion_oferta = models.TextField(
        help_text='Descripción detallada de la oferta',
        verbose_name='Descripción'
    )
    
    garantia_ofrecida = models.CharField(
        max_length=200,
        blank=True,
        help_text='Garantía ofrecida (ej: "6 meses o 10,000 km")',
        verbose_name='Garantía'
    )
    
    # Disponibilidad
    fecha_disponible = models.DateField(
        help_text='Fecha en que el proveedor puede realizar el servicio',
        verbose_name='Fecha Disponible'
    )
    
    hora_disponible = models.TimeField(
        help_text='Hora en que el proveedor puede realizar el servicio',
        verbose_name='Hora Disponible'
    )
    
    es_fecha_alternativa = models.BooleanField(
        default=False,
        verbose_name='Es fecha alternativa',
        help_text='True si el proveedor propone una fecha distinta a la solicitada por el cliente.'
    )
    motivo_fecha_alternativa = models.TextField(
        blank=True,
        null=True,
        verbose_name='Motivo fecha alternativa',
        help_text='Razón por la que el proveedor propone otra fecha.'
    )
    
    # Estado de la oferta
    estado = models.CharField(
        max_length=20,
        choices=[
            ('enviada', 'Enviada'),
            ('vista', 'Vista por Cliente'),
            ('en_chat', 'En Conversación'),
            ('pendiente_creditos', 'Pendiente créditos proveedor'),
            ('aceptada', 'Aceptada por Cliente'),
            ('pendiente_pago', 'Cliente Procesando Pago'),
            ('pagada_parcialmente', 'Pagada Parcialmente - Pendiente Saldo'),
            ('pagada', 'Pagada - Listo para Iniciar'),
            ('en_ejecucion', 'En Ejecución - Servicio en Progreso'),
            ('completada', 'Completada - Servicio Finalizado'),
            ('rechazada', 'Rechazada'),
            ('retirada', 'Retirada por Proveedor'),
            ('expirada', 'Expirada'),
        ],
        default='enviada',
        verbose_name='Estado',
        db_index=True
    )
    
    # Timestamps
    fecha_envio = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de Envío'
    )
    
    fecha_visualizacion_cliente = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Momento en que el cliente vio la oferta',
        verbose_name='Fecha de Visualización'
    )
    
    fecha_respuesta_cliente = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Momento en que el cliente respondió (aceptó/rechazó)',
        verbose_name='Fecha de Respuesta'
    )
    
    # Métricas
    tiempo_respuesta_proveedor = models.DurationField(
        null=True,
        blank=True,
        help_text='Tiempo que tardó el proveedor en enviar la oferta desde publicación',
        verbose_name='Tiempo de Respuesta del Proveedor'
    )
    
    # Campos para ofertas secundarias (servicios adicionales)
    oferta_original = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='ofertas_secundarias',
        help_text='Oferta original a la que está asociada esta oferta secundaria',
        verbose_name='Oferta Original'
    )
    
    es_oferta_secundaria = models.BooleanField(
        default=False,
        help_text='Indica si esta es una oferta secundaria (servicio adicional)',
        verbose_name='Es Oferta Secundaria'
    )

    ORIGEN_OFERTA_CHOICES = [
        ('manual', 'Creada manualmente por proveedor'),
        ('catalogo', 'Generada desde catálogo OfertaServicio'),
        ('secundaria', 'Oferta secundaria en ejecución'),
    ]
    origen = models.CharField(
        max_length=20,
        choices=ORIGEN_OFERTA_CHOICES,
        default='manual',
        db_index=True,
        verbose_name='Origen de la oferta',
    )
    oferta_servicio = models.ForeignKey(
        'servicios.OfertaServicio',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ofertas_proveedor_generadas',
        verbose_name='Oferta de catálogo origen',
    )
    metadata_ia = models.JSONField(
        null=True,
        blank=True,
        help_text='Resumen IA, temperatura, ids sugeridos (sin texto crudo de consultas efímeras)',
        verbose_name='Metadata IA',
    )
    
    motivo_servicio_adicional = models.TextField(
        blank=True,
        help_text='Explicación del proveedor sobre por qué se requiere este servicio adicional',
        verbose_name='Motivo del Servicio Adicional'
    )
    
    # =========================================================================
    # CAMPOS PARA DESGLOSE DE COSTOS (Repuestos + Mano de Obra)
    # =========================================================================
    
    costo_repuestos = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text='Costo total de los repuestos cotizados (sin IVA)',
        verbose_name='Costo Repuestos'
    )
    
    costo_mano_obra = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text='Costo de mano de obra del servicio (sin IVA)',
        verbose_name='Costo Mano de Obra'
    )
    
    costo_gestion_compra = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text='Costo de gestión y traslado para compra de repuestos (sin IVA). Aplica solo cuando incluye_repuestos=True',
        verbose_name='Costo Gestión de Compra'
    )
    
    foto_cotizacion_repuestos = models.URLField(
        max_length=500,
        null=True,
        blank=True,
        help_text='URL de la foto de la cotización de repuestos de la casa de repuestos',
        verbose_name='Foto Cotización Repuestos'
    )
    
    # Método de pago elegido por el cliente
    METODO_PAGO_CLIENTE_CHOICES = [
        ('repuestos_adelantado', 'Repuestos Adelantado + Servicio al Final'),
        ('todo_adelantado', 'Todo Adelantado'),
        ('pendiente', 'Pendiente de Selección'),
    ]
    metodo_pago_cliente = models.CharField(
        max_length=25,
        choices=METODO_PAGO_CLIENTE_CHOICES,
        default='pendiente',
        help_text='Método de pago elegido por el cliente para esta oferta',
        verbose_name='Método de Pago Cliente'
    )
    
    # Estado del pago de repuestos (cuando el cliente elige pagar repuestos adelantado)
    ESTADO_PAGO_REPUESTOS_CHOICES = [
        ('no_aplica', 'No Aplica (Sin Repuestos o Todo Adelantado)'),
        ('pendiente', 'Pendiente de Pago'),
        ('pagado', 'Repuestos Pagados'),
    ]
    estado_pago_repuestos = models.CharField(
        max_length=20,
        choices=ESTADO_PAGO_REPUESTOS_CHOICES,
        default='no_aplica',
        help_text='Estado del pago de repuestos',
        verbose_name='Estado Pago Repuestos'
    )
    
    # Estado del pago de mano de obra
    ESTADO_PAGO_SERVICIO_CHOICES = [
        ('pendiente', 'Pendiente de Pago'),
        ('pagado', 'Servicio Pagado'),
    ]
    estado_pago_servicio = models.CharField(
        max_length=20,
        choices=ESTADO_PAGO_SERVICIO_CHOICES,
        default='pendiente',
        help_text='Estado del pago del servicio/mano de obra',
        verbose_name='Estado Pago Servicio'
    )
    
    class Meta:
        verbose_name = 'Oferta de Proveedor'
        verbose_name_plural = 'Ofertas de Proveedores'
        ordering = ['precio_total_ofrecido', '-fecha_envio']
        # Removemos unique_together para permitir ofertas secundarias del mismo proveedor
        # La validación se hará en el ViewSet
        indexes = [
            models.Index(fields=['solicitud', 'estado']),
            models.Index(fields=['proveedor', 'estado']),
            models.Index(fields=['precio_total_ofrecido']),
            models.Index(fields=['oferta_original', 'es_oferta_secundaria']),
        ]
    
    def __str__(self):
        return f"Oferta de {self.proveedor.get_full_name()} - ${self.precio_total_ofrecido}"
    
    def clean(self):
        """Validación personalizada para ofertas secundarias"""
        from django.core.exceptions import ValidationError
        
        # Si es oferta secundaria, validar que tenga oferta_original
        if self.es_oferta_secundaria and not self.oferta_original:
            raise ValidationError({
                'oferta_original': 'Las ofertas secundarias deben tener una oferta original asociada'
            })
        
        # Si tiene oferta_original, debe ser secundaria
        if self.oferta_original and not self.es_oferta_secundaria:
            self.es_oferta_secundaria = True
        
        # Validar que no sea una oferta original que se referencia a sí misma
        if self.oferta_original and self.oferta_original.id == self.id:
            raise ValidationError({
                'oferta_original': 'Una oferta no puede ser su propia oferta original'
            })
    
    def save(self, *args, **kwargs):
        # Ejecutar validación clean antes de guardar
        self.clean()
        
        # Establecer tipo de proveedor automáticamente
        if not self.tipo_proveedor:
            if hasattr(self.proveedor, 'taller') and self.proveedor.taller:
                self.tipo_proveedor = 'taller'
            elif hasattr(self.proveedor, 'mecanico_domicilio') and self.proveedor.mecanico_domicilio:
                self.tipo_proveedor = 'mecanico'
        
        # Si tiene oferta_original, establecer es_oferta_secundaria automáticamente
        if self.oferta_original and not self.es_oferta_secundaria:
            self.es_oferta_secundaria = True
        
        # Calcular tiempo de respuesta del proveedor
        if not self.tiempo_respuesta_proveedor and self.solicitud.fecha_publicacion:
            self.tiempo_respuesta_proveedor = timezone.now() - self.solicitud.fecha_publicacion
        
        # Determinar si es una nueva oferta (antes de guardar)
        es_nueva = not self.pk
        
        super().save(*args, **kwargs)
        
        # Actualizar contador en la solicitud solo si es nueva oferta y no es secundaria
        # Las ofertas secundarias no incrementan el contador de ofertas de la solicitud
        if es_nueva and self.estado == 'enviada' and not self.es_oferta_secundaria:
            # Actualizar directamente sin llamar al método que hace save
            self.solicitud.total_ofertas += 1
            if self.solicitud.estado == 'publicada':
                self.solicitud.estado = 'con_ofertas'
            self.solicitud.save(update_fields=['total_ofertas', 'estado'])
    
    def marcar_como_vista(self):
        """Marca la oferta como vista por el cliente"""
        if self.estado == 'enviada':
            self.estado = 'vista'
            self.fecha_visualizacion_cliente = timezone.now()
            self.save(update_fields=['estado', 'fecha_visualizacion_cliente'])
    
    @property
    def nombre_proveedor(self):
        """Retorna el nombre del proveedor"""
        if self.tipo_proveedor == 'taller' and hasattr(self.proveedor, 'taller'):
            return self.proveedor.taller.nombre
        elif self.tipo_proveedor == 'mecanico' and hasattr(self.proveedor, 'mecanico_domicilio'):
            return f"{self.proveedor.first_name} {self.proveedor.last_name}"
        return self.proveedor.get_full_name()
    
    @property
    def rating_proveedor(self):
        """Retorna el rating del proveedor"""
        if self.tipo_proveedor == 'taller' and hasattr(self.proveedor, 'taller'):
            return self.proveedor.taller.calificacion_promedio or 0.0
        elif self.tipo_proveedor == 'mecanico' and hasattr(self.proveedor, 'mecanico_domicilio'):
            return self.proveedor.mecanico_domicilio.calificacion_promedio or 0.0
        return 0.0


class DetalleServicioOferta(models.Model):
    """
    Tabla intermedia para detallar precio y tiempo de cada servicio en una oferta.
    Permite que una oferta incluya múltiples servicios con precios individuales.
    """
    
    oferta = models.ForeignKey(
        OfertaProveedor,
        on_delete=models.CASCADE,
        related_name='detalles_servicios',
        verbose_name='Oferta'
    )
    
    servicio = models.ForeignKey(
        Servicio,
        on_delete=models.CASCADE,
        related_name='detalles_en_ofertas',
        verbose_name='Servicio'
    )
    
    precio_servicio = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text='Precio específico de este servicio en la oferta',
        verbose_name='Precio'
    )
    
    tiempo_estimado = models.DurationField(
        help_text='Tiempo estimado para este servicio específico',
        verbose_name='Tiempo Estimado'
    )
    
    notas = models.TextField(
        blank=True,
        help_text='Notas adicionales sobre este servicio',
        verbose_name='Notas'
    )
    
    # Repuestos seleccionados para este servicio en la oferta
    repuestos_seleccionados = models.JSONField(
        default=list,
        blank=True,
        help_text='Lista de repuestos seleccionados para este servicio en formato JSON',
        verbose_name='Repuestos Seleccionados'
    )
    
    class Meta:
        verbose_name = 'Detalle de Servicio en Oferta'
        verbose_name_plural = 'Detalles de Servicios en Ofertas'
        unique_together = [['oferta', 'servicio']]
    
    def __str__(self):
        return f"{self.servicio.nombre} - ${self.precio_servicio}"


class ChatSolicitud(models.Model):
    """
    Mensajes de chat entre cliente y proveedor sobre una oferta específica.
    """
    
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    
    oferta = models.ForeignKey(
        OfertaProveedor,
        on_delete=models.CASCADE,
        related_name='mensajes_chat',
        verbose_name='Oferta'
    )
    
    mensaje = models.TextField(
        verbose_name='Mensaje'
    )
    
    enviado_por = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name='mensajes_enviados_solicitudes',
        verbose_name='Enviado Por'
    )
    
    es_proveedor = models.BooleanField(
        default=False,
        help_text='True si el mensaje es del proveedor, False si es del cliente',
        verbose_name='Es del Proveedor'
    )
    
    fecha_envio = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de Envío',
        db_index=True
    )
    
    leido = models.BooleanField(
        default=False,
        verbose_name='Leído'
    )
    
    fecha_lectura = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de Lectura'
    )
    
    # Opcional: adjuntos (fotos, etc.)
    archivo_adjunto = models.FileField(
        upload_to='chat_solicitudes/%Y/%m/',
        null=True,
        blank=True,
        verbose_name='Archivo Adjunto'
    )
    
    class Meta:
        verbose_name = 'Mensaje de Chat de Solicitud'
        verbose_name_plural = 'Mensajes de Chat de Solicitudes'
        ordering = ['fecha_envio']
        indexes = [
            models.Index(fields=['oferta', 'fecha_envio']),
            models.Index(fields=['enviado_por', '-fecha_envio']),
        ]
    
    def __str__(self):
        tipo = "Proveedor" if self.es_proveedor else "Cliente"
        return f"{tipo}: {self.mensaje[:50]}"
    
    def marcar_como_leido(self):
        """Marca el mensaje como leído"""
        if not self.leido:
            self.leido = True
            self.fecha_lectura = timezone.now()
            self.save(update_fields=['leido', 'fecha_lectura'])
    
    def save(self, *args, **kwargs):
        # Determinar automáticamente si es proveedor
        if not self.pk:  # Solo en creación
            self.es_proveedor = (self.enviado_por == self.oferta.proveedor)
        
        super().save(*args, **kwargs)
        
        # Actualizar estado de la oferta a 'en_chat' si está en 'vista'
        if self.oferta.estado == 'vista':
            self.oferta.estado = 'en_chat'
            self.oferta.save(update_fields=['estado'])


class RechazoSolicitud(models.Model):
    """
    Registra cuando un proveedor rechaza una solicitud pública.
    Permite rastrear motivos de rechazo para mejorar el matching.
    """
    
    MOTIVOS_RECHAZO = [
        ('ocupado', 'No tengo disponibilidad en esas fechas'),
        ('lejos', 'La ubicación está muy lejos de mi área'),
        ('no_servicio', 'No realizo ese tipo de servicio'),
        ('no_marca', 'No trabajo con esa marca de vehículo'),
        ('precio', 'El precio esperado no es viable'),
        ('complejidad', 'El trabajo es muy complejo para mi taller'),
        ('recursos', 'No cuento con las herramientas/repuestos necesarios'),
        ('politica', 'No cumplo con políticas del cliente'),
        ('otro', 'Otro motivo'),
    ]
    
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    
    solicitud = models.ForeignKey(
        SolicitudServicioPublica,
        on_delete=models.CASCADE,
        related_name='rechazos',
        verbose_name='Solicitud'
    )
    
    proveedor = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name='rechazos_realizados',
        verbose_name='Proveedor'
    )
    
    tipo_proveedor = models.CharField(
        max_length=20,
        choices=[
            ('taller', 'Taller'),
            ('mecanico', 'Mecánico a Domicilio')
        ],
        verbose_name='Tipo de Proveedor'
    )
    
    motivo = models.CharField(
        max_length=20,
        choices=MOTIVOS_RECHAZO,
        verbose_name='Motivo del Rechazo'
    )
    
    detalle_motivo = models.TextField(
        blank=True,
        max_length=500,
        help_text='Explicación adicional del proveedor',
        verbose_name='Detalle'
    )
    
    fecha_rechazo = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de Rechazo'
    )
    
    tiempo_respuesta = models.DurationField(
        null=True,
        blank=True,
        help_text='Tiempo entre publicación y rechazo',
        verbose_name='Tiempo de Respuesta'
    )
    
    class Meta:
        verbose_name = 'Rechazo de Solicitud'
        verbose_name_plural = 'Rechazos de Solicitudes'
        unique_together = [['solicitud', 'proveedor']]
        ordering = ['-fecha_rechazo']
        indexes = [
            models.Index(fields=['solicitud', 'proveedor']),
            models.Index(fields=['motivo']),
            models.Index(fields=['fecha_rechazo']),
        ]
    
    def __str__(self):
        return f"Rechazo de {self.proveedor.get_full_name()} - {self.get_motivo_display()}"
    
    def save(self, *args, **kwargs):
        # Calcular tiempo de respuesta
        if self.solicitud.fecha_publicacion and not self.tiempo_respuesta:
            self.tiempo_respuesta = timezone.now() - self.solicitud.fecha_publicacion
        
        # Establecer tipo de proveedor automáticamente si no está definido
        if not self.tipo_proveedor:
            if hasattr(self.proveedor, 'taller') and self.proveedor.taller:
                self.tipo_proveedor = 'taller'
            elif hasattr(self.proveedor, 'mecanico_domicilio') and self.proveedor.mecanico_domicilio:
                self.tipo_proveedor = 'mecanico'
        
        super().save(*args, **kwargs)


class AlertaDescartada(models.Model):
    """
    Modelo para almacenar alertas descartadas por usuarios.
    Permite que las alertas no vuelvan a aparecer después de ser descartadas.
    """
    TIPO_ALERTA_CHOICES = [
        ('pago_proximo', 'Pago Próximo'),
        ('pago_expirado', 'Pago Expirado'),
    ]
    
    # Usuario que descartó la alerta
    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name='alertas_descartadas',
        verbose_name='Usuario'
    )
    
    # Solicitud relacionada con la alerta
    solicitud = models.ForeignKey(
        SolicitudServicioPublica,
        on_delete=models.CASCADE,
        related_name='alertas_descartadas',
        verbose_name='Solicitud'
    )
    
    # Tipo de alerta descartada
    tipo_alerta = models.CharField(
        max_length=20,
        choices=TIPO_ALERTA_CHOICES,
        verbose_name='Tipo de Alerta'
    )
    
    # Fecha cuando se descartó
    fecha_descarte = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de Descarte'
    )
    
    class Meta:
        verbose_name = 'Alerta Descartada'
        verbose_name_plural = 'Alertas Descartadas'
        unique_together = [['usuario', 'solicitud', 'tipo_alerta']]
        ordering = ['-fecha_descarte']
        indexes = [
            models.Index(fields=['usuario', 'solicitud', 'tipo_alerta']),
            models.Index(fields=['fecha_descarte']),
        ]
    
    def __str__(self):
        return f"Alerta {self.get_tipo_alerta_display()} descartada por {self.usuario.get_full_name()} - Solicitud {self.solicitud.id}"