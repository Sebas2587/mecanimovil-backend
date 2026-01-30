from django.db import models
from django.utils.translation import gettext_lazy as _
from mecanimovilapp.apps.usuarios.models import Cliente
from mecanimovilapp.apps.chat.models import Conversation


class MarcaVehiculo(models.Model):
    """
    Modelo para las marcas de vehículos
    """
    nombre = models.CharField(max_length=50, unique=True)
    logo = models.ImageField(upload_to='marcas/', blank=True, null=True, help_text="Logo de la marca")
    
    class Meta:
        verbose_name = _('marca de vehículo')
        verbose_name_plural = _('marcas de vehículos')
        ordering = ['nombre']
    
    def __str__(self):
        return self.nombre


# Mantenemos Marca para compatibilidad con código existente
class Marca(MarcaVehiculo):
    class Meta:
        proxy = True
        verbose_name = _('marca')
        verbose_name_plural = _('marcas')


class Modelo(models.Model):
    """
    Modelo para los modelos de vehículos asociados a una marca
    """
    nombre = models.CharField(max_length=100)
    marca = models.ForeignKey(
        MarcaVehiculo, 
        on_delete=models.CASCADE, 
        related_name='modelos'
    )
    
    class Meta:
        verbose_name = _('modelo')
        verbose_name_plural = _('modelos')
        ordering = ['nombre']
        unique_together = ['nombre', 'marca']
    
    def __str__(self):
        return f"{self.marca} - {self.nombre}"


class Vehiculo(models.Model):
    """
    Modelo para los vehículos de los clientes
    """
    TIPO_MOTOR_CHOICES = [
        ('Gasolina', 'Gasolina'),
        ('GASOLINA', 'GASOLINA'),
        ('BENCINA', 'BENCINA'),
        ('Diésel', 'Diésel'),
        ('DIESEL', 'DIESEL'),
        ('Electric', 'Electric'),
    ]
    
    marca = models.ForeignKey(
        MarcaVehiculo, 
        on_delete=models.PROTECT, 
        related_name='vehiculos'
    )
    modelo = models.ForeignKey(
        Modelo, 
        on_delete=models.PROTECT, 
        related_name='vehiculos'
    )
    cilindraje = models.CharField(max_length=50, blank=True, null=True)
    tipo_motor = models.CharField(
        max_length=20, 
        choices=TIPO_MOTOR_CHOICES, 
        default='Gasolina'
    )
    year = models.IntegerField(verbose_name=_('año'), default=2024)
    color = models.CharField(max_length=30, blank=True, null=True, verbose_name=_('color'))
    transmision = models.CharField(max_length=20, blank=True, null=True, verbose_name=_('transmisión'))
    
    # Nuevos campos detallados
    vin = models.CharField(max_length=30, blank=True, null=True, verbose_name=_('VIN'))
    numero_motor = models.CharField(max_length=30, blank=True, null=True, verbose_name=_('número de motor'))
    version = models.CharField(max_length=100, blank=True, null=True, verbose_name=_('versión'))
    puertas = models.IntegerField(null=True, blank=True, verbose_name=_('puertas'))
    mes_revision_tecnica = models.CharField(max_length=20, blank=True, null=True, verbose_name=_('mes revisión técnica'))

    patente = models.CharField(max_length=20, unique=True)
    kilometraje = models.PositiveIntegerField(default=0)
    kilometraje_api = models.IntegerField(null=True, blank=True, help_text="Kilometraje obtenido de API externa")
    foto = models.ImageField(
        upload_to='',  # Guardar directamente en la raíz del storage (mecanimovil-app-media/)
        blank=True, 
        null=True
    )
    cliente = models.ForeignKey(
        Cliente, 
        on_delete=models.CASCADE, 
        related_name='vehiculos'
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True, null=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True, null=True)
    
    # Campos de Tasación y Valoración (GetAPI)
    tasacion_fiscal = models.IntegerField(default=0, help_text="Tasación fiscal del SII")
    permiso_circulacion = models.IntegerField(default=0, help_text="Valor permiso circulación")
    year_tasacion_fiscal = models.IntegerField(null=True, blank=True)
    
    precio_mercado_min = models.IntegerField(default=0, help_text="Precio mercado mínimo (GetAPI)")
    precio_mercado_max = models.IntegerField(default=0, help_text="Precio mercado máximo (GetAPI)")
    precio_mercado_promedio = models.IntegerField(default=0, help_text="Precio referencia usado")
    
    precio_retoma = models.IntegerField(default=0, help_text="Precio sugerido de retoma")
    fecha_ultima_tasacion = models.DateTimeField(null=True, blank=True)
    
    precio_sugerido_final = models.IntegerField(default=0, help_text="Precio calculado por nuestro algoritmo")
    
    # Campos de Marketplace
    is_published = models.BooleanField(default=False, verbose_name=_('publicado'))
    precio_venta = models.IntegerField(null=True, blank=True, verbose_name=_('precio de venta'))
    views_count = models.PositiveIntegerField(default=0, verbose_name=_('vistas'))
    favorites_count = models.PositiveIntegerField(default=0, verbose_name=_('favoritos'))
    leads_count = models.PositiveIntegerField(default=0, verbose_name=_('interesados'))
    
    class Meta:
        verbose_name = _('vehículo')
        verbose_name_plural = _('vehículos')
        ordering = ['-fecha_actualizacion']
    
    def __str__(self):
        return f"{self.marca} {self.modelo} ({self.patente})"
    
    @property
    def marca_nombre(self):
        return self.marca.nombre
    
    @property
    def modelo_nombre(self):
        return self.modelo.nombre

class OfertaVehiculo(models.Model):
    """
    Ofertas de compra para vehículos en el Marketplace
    """
    ESTADO_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('aceptada', 'Aceptada'),
        ('rechazada', 'Rechazada'),
        ('contraoferta', 'Contraoferta'),
        ('cancelada', 'Cancelada'),
        ('completada', 'Completada'),
    ]

    vehiculo = models.ForeignKey(
        Vehiculo, 
        on_delete=models.CASCADE, 
        related_name='ofertas_recibidas'
    )
    comprador = models.ForeignKey(
        'usuarios.Usuario', 
        on_delete=models.CASCADE, 
        related_name='ofertas_compras_vehiculos'
    )
    monto = models.IntegerField(help_text="Monto ofrecido")
    mensaje = models.TextField(blank=True, null=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='pendiente')
    # Relación con la conversación de chat (se crea al aceptar)
    conversacion = models.OneToOneField(
        Conversation, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='oferta_vehiculo'
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('oferta de vehículo')
        verbose_name_plural = _('ofertas de vehículos')
        ordering = ['-fecha_creacion']

    def __str__(self):
        return f"Oferta {self.id} - {self.vehiculo} - {self.monto}"