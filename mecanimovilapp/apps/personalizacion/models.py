from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from datetime import timedelta
from mecanimovilapp.apps.usuarios.models import Cliente
from mecanimovilapp.apps.vehiculos.models import Vehiculo
from mecanimovilapp.apps.servicios.models import Servicio, OfertaServicio


def get_default_expiration_date():
    """Función para obtener fecha de expiración por defecto (30 días)"""
    return timezone.now() + timedelta(days=30)


class VehiculoActivo(models.Model):
    """
    Modelo para gestionar el vehículo activo seleccionado por el cliente
    """
    cliente = models.OneToOneField(
        Cliente,
        on_delete=models.CASCADE,
        related_name='vehiculo_activo',
        verbose_name=_('cliente')
    )
    vehiculo = models.ForeignKey(
        Vehiculo,
        on_delete=models.CASCADE,
        related_name='activo_para_clientes',
        verbose_name=_('vehículo activo')
    )
    fecha_seleccion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('vehículo activo')
        verbose_name_plural = _('vehículos activos')
    
    def __str__(self):
        return f"{self.cliente} - {self.vehiculo}"
    
    def clean(self):
        """Validar que el vehículo pertenezca al cliente"""
        from django.core.exceptions import ValidationError
        if self.vehiculo.cliente != self.cliente:
            raise ValidationError('El vehículo debe pertenecer al cliente')


class PerfilVehiculo(models.Model):
    """
    Modelo para almacenar el perfil analítico de cada vehículo
    Usado para recomendaciones basadas en ML
    """
    vehiculo = models.OneToOneField(
        Vehiculo,
        on_delete=models.CASCADE,
        related_name='perfil_analitico'
    )
    
    # Métricas de uso
    servicios_realizados = models.PositiveIntegerField(default=0)
    gasto_promedio_mensual = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0
    )
    frecuencia_mantenimiento = models.PositiveIntegerField(
        default=0,
        help_text=_('Días promedio entre servicios')
    )
    
    # Categorías de servicios más utilizadas (JSON)
    categorias_frecuentes = models.JSONField(
        default=dict,
        help_text=_('Categorías de servicios más utilizadas con frecuencias')
    )
    
    # Proveedores preferidos
    talleres_frecuentes = models.JSONField(
        default=list,
        help_text=_('IDs de talleres más utilizados')
    )
    mecanicos_frecuentes = models.JSONField(
        default=list,
        help_text=_('IDs de mecánicos más utilizados')
    )
    
    # Métricas de mantenimiento predictivo
    km_ultimo_servicio = models.PositiveIntegerField(default=0)
    dias_ultimo_servicio = models.PositiveIntegerField(default=0)
    score_mantenimiento_urgente = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text=_('Score de urgencia de mantenimiento (0-1)')
    )
    
    # Timestamps
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    fecha_calculo = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = _('perfil de vehículo')
        verbose_name_plural = _('perfiles de vehículos')
    
    def __str__(self):
        return f"Perfil - {self.vehiculo}"


class RecomendacionPersonalizada(models.Model):
    """
    Modelo para almacenar recomendaciones generadas por ML
    """
    TIPO_RECOMENDACION_CHOICES = [
        ('mantenimiento', 'Mantenimiento Sugerido'),
        ('proveedor', 'Proveedor Recomendado'),
        ('servicio_popular', 'Servicio Popular'),
    ]
    
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        related_name='recomendaciones'
    )
    vehiculo = models.ForeignKey(
        Vehiculo,
        on_delete=models.CASCADE,
        related_name='recomendaciones'
    )
    tipo = models.CharField(
        max_length=20,
        choices=TIPO_RECOMENDACION_CHOICES
    )
    
    # Contenido de la recomendación
    servicio = models.ForeignKey(
        Servicio,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    oferta_servicio = models.ForeignKey(
        OfertaServicio,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    
    # Métricas de la recomendación
    score_relevancia = models.FloatField(
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text=_('Score de relevancia de la recomendación (0-1)')
    )
    razon_recomendacion = models.TextField(
        help_text=_('Explicación de por qué se recomienda')
    )
    
    # Control de vigencia
    fecha_generacion = models.DateTimeField(auto_now_add=True)
    fecha_expiracion = models.DateTimeField(default=get_default_expiration_date)
    activa = models.BooleanField(default=True)
    
    # Métricas de interacción
    veces_mostrada = models.PositiveIntegerField(default=0)
    veces_clickeada = models.PositiveIntegerField(default=0)
    convertida = models.BooleanField(default=False)
    
    class Meta:
        verbose_name = _('recomendación personalizada')
        verbose_name_plural = _('recomendaciones personalizadas')
        ordering = ['-score_relevancia', '-fecha_generacion']
    
    def __str__(self):
        return f"{self.get_tipo_display()} - {self.cliente} - {self.vehiculo}"
    
    @property
    def ctr(self):
        """Click Through Rate"""
        if self.veces_mostrada == 0:
            return 0
        return self.veces_clickeada / self.veces_mostrada


class ConfiguracionPersonalizacion(models.Model):
    """
    Modelo para configuraciones globales del sistema de personalización
    """
    clave = models.CharField(max_length=100, unique=True)
    valor = models.TextField()
    descripcion = models.TextField(blank=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('configuración de personalización')
        verbose_name_plural = _('configuraciones de personalización')
    
    def __str__(self):
        return f"{self.clave}: {self.valor[:50]}" 