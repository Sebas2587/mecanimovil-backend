from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from mecanimovilapp.apps.vehiculos.models import Vehiculo
from mecanimovilapp.apps.checklists.models import ChecklistInstance
from mecanimovilapp.apps.servicios.models import Servicio
import math


class ComponenteSaludConfig(models.Model):
    """
    Configuración parametrizable de componentes desde el admin
    Permite configurar cómo se degrada cada componente según kilometraje y tiempo
    """
    TIPO_MEDICION_CHOICES = [
        ('KILOMETRAJE', 'Por Kilometraje'),
        ('TIEMPO', 'Por Tiempo (meses)'),
        ('MIXTO', 'Kilometraje y Tiempo'),
    ]
    
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True, null=True)
    tipo_medicion = models.CharField(
        max_length=20, 
        choices=TIPO_MEDICION_CHOICES, 
        default='KILOMETRAJE'
    )
    
    # Parámetros de Weibull para cálculo de degradación
    beta = models.FloatField(
        default=2.0,
        validators=[MinValueValidator(0.1)],
        help_text='Factor de forma (1.0-4.0). Mayor = degradación más abrupta'
    )
    eta = models.FloatField(
        default=20000,
        validators=[MinValueValidator(100)],
        help_text='Parámetro de escala (vida característica en km o meses)'
    )
    
    # Umbrales de servicio
    km_critico = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text='Kilometraje crítico para reemplazo'
    )
    meses_critico = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text='Meses críticos para reemplazo'
    )
    
    # Factores de ajuste
    factor_edad_vehiculo = models.FloatField(
        default=0.05,
        help_text='Degradación adicional por año del vehículo (0.05 = 5%/año)'
    )
    factor_uso_intensivo = models.FloatField(
        default=1.2,
        help_text='Multiplicador para uso intensivo'
    )
    
    # Relación con servicios
    servicio_asociado = models.ForeignKey(
        Servicio,
        on_delete=models.SET_NULL,
        null=True, 
        blank=True,
        related_name='componentes_salud'
    )
    
    activo = models.BooleanField(default=True)
    orden_visualizacion = models.PositiveIntegerField(default=0)
    icono = models.CharField(max_length=50, default='construct-outline')
    
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Componente de Salud'
        verbose_name_plural = 'Componentes de Salud'
        ordering = ['orden_visualizacion', 'nombre']
    
    def __str__(self):
        return self.nombre


class EstadoSaludVehiculo(models.Model):
    """
    Estado de salud general del vehículo (snapshot)
    Se actualiza cuando se calcula la salud del vehículo
    """
    vehiculo = models.ForeignKey(
        Vehiculo, 
        on_delete=models.CASCADE, 
        related_name='estados_salud'
    )
    
    # Métricas generales
    salud_general_porcentaje = models.FloatField(
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text='Promedio ponderado de salud de todos los componentes'
    )
    
    kilometraje_snapshot = models.PositiveIntegerField()
    fecha_calculo = models.DateTimeField(auto_now_add=True)
    
    # Contadores de componentes por nivel
    total_componentes_evaluados = models.PositiveIntegerField(default=0)
    componentes_optimos = models.PositiveIntegerField(default=0)
    componentes_atencion = models.PositiveIntegerField(default=0)
    componentes_urgentes = models.PositiveIntegerField(default=0)
    componentes_criticos = models.PositiveIntegerField(default=0)
    
    # Recomendaciones
    tiene_alertas_activas = models.BooleanField(default=False)
    costo_estimado_mantenimiento = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        default=0,
        help_text='Suma de servicios recomendados'
    )
    
    class Meta:
        verbose_name = 'Estado de Salud de Vehículo'
        verbose_name_plural = 'Estados de Salud de Vehículos'
        ordering = ['-fecha_calculo']
        indexes = [
            models.Index(fields=['vehiculo', '-fecha_calculo']),
            models.Index(fields=['tiene_alertas_activas', '-fecha_calculo']),
        ]
    
    def __str__(self):
        return f"{self.vehiculo} - {self.salud_general_porcentaje}% ({self.fecha_calculo.strftime('%Y-%m-%d')})"


class ComponenteSaludVehiculo(models.Model):
    """
    Estado de salud de un componente específico del vehículo
    Se calcula usando el algoritmo de Weibull modificado
    """
    NIVEL_ALERTA_CHOICES = [
        ('OPTIMO', 'Óptimo'),
        ('ATENCION', 'Atención'),
        ('URGENTE', 'Urgente'),
        ('CRITICO', 'Crítico'),
    ]
    
    vehiculo = models.ForeignKey(
        Vehiculo, 
        on_delete=models.CASCADE, 
        related_name='componentes_salud'
    )
    componente_config = models.ForeignKey(
        ComponenteSaludConfig, 
        on_delete=models.CASCADE
    )
    
    # Estado actual
    salud_porcentaje = models.FloatField(
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    nivel_alerta = models.CharField(
        max_length=20, 
        choices=NIVEL_ALERTA_CHOICES
    )
    
    # Referencias de servicio
    km_ultimo_servicio = models.PositiveIntegerField(default=0)
    fecha_ultimo_servicio = models.DateTimeField(null=True, blank=True)
    checklist_ultimo_servicio = models.ForeignKey(
        ChecklistInstance,
        on_delete=models.SET_NULL,
        null=True, 
        blank=True,
        related_name='componentes_actualizados'
    )
    
    # Predicciones
    km_estimados_restantes = models.PositiveIntegerField(default=0)
    dias_estimados_restantes = models.PositiveIntegerField(default=0)
    fecha_estimada_servicio = models.DateField(null=True, blank=True)
    
    # Alertas
    requiere_servicio_inmediato = models.BooleanField(default=False)
    mensaje_alerta = models.TextField(blank=True)
    
    # Metadatos
    ultima_actualizacion = models.DateTimeField(auto_now=True)
    actualizado_automaticamente = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = 'Componente de Salud de Vehículo'
        verbose_name_plural = 'Componentes de Salud de Vehículos'
        unique_together = ('vehiculo', 'componente_config')
        ordering = ['componente_config__orden_visualizacion']
        indexes = [
            models.Index(fields=['vehiculo', 'nivel_alerta']),
            models.Index(fields=['requiere_servicio_inmediato', '-salud_porcentaje']),
        ]
    
    def __str__(self):
        return f"{self.vehiculo} - {self.componente_config.nombre}: {self.salud_porcentaje}%"
    
    def calcular_salud(self):
        """
        Calcular salud usando el algoritmo de Weibull modificado
        Actualiza los campos del componente con el cálculo
        """
        config = self.componente_config
        vehiculo = self.vehiculo
        
        # Calcular edad del vehículo
        edad_vehiculo = timezone.now().year - vehiculo.year
        
        # Kilometraje actual y desde último servicio
        km_actual = vehiculo.kilometraje
        km_desde_servicio = km_actual - self.km_ultimo_servicio
        
        # Factor de edad (vehículos viejos degradan más rápido)
        factor_edad = 1 + (edad_vehiculo * config.factor_edad_vehiculo)
        
        # Calcular degradación según tipo de medición
        if config.tipo_medicion == 'TIEMPO' and self.fecha_ultimo_servicio:
            # Degradación basada en tiempo (meses)
            meses_desde_servicio = (timezone.now() - self.fecha_ultimo_servicio).days / 30.0
            degradacion_base = 1 - math.exp(-((meses_desde_servicio / config.eta) ** config.beta))
        elif config.tipo_medicion == 'MIXTO' and self.fecha_ultimo_servicio:
            # Degradación mixta: promedio de km y tiempo
            meses_desde_servicio = (timezone.now() - self.fecha_ultimo_servicio).days / 30.0
            degradacion_km = 1 - math.exp(-((km_desde_servicio / config.eta) ** config.beta))
            degradacion_tiempo = 1 - math.exp(-((meses_desde_servicio / config.eta) ** config.beta))
            degradacion_base = (degradacion_km + degradacion_tiempo) / 2.0
        else:
            # Degradación basada en kilometraje (default)
            degradacion_base = 1 - math.exp(-((km_desde_servicio / config.eta) ** config.beta))
        
        # Ajustar por factor de edad
        degradacion_ajustada = min(degradacion_base * factor_edad, 1.0)
        
        # Convertir a porcentaje de salud (100% = nuevo, 0% = crítico)
        salud_porcentaje = (1 - degradacion_ajustada) * 100
        
        # Determinar nivel de alerta
        if salud_porcentaje >= 70:
            nivel_alerta = 'OPTIMO'
        elif salud_porcentaje >= 40:
            nivel_alerta = 'ATENCION'
        elif salud_porcentaje >= 20:
            nivel_alerta = 'URGENTE'
        else:
            nivel_alerta = 'CRITICO'
        
        # Calcular km restantes hasta próximo servicio
        km_critico = config.km_critico or 0
        km_restantes = max(0, km_critico - km_desde_servicio)
        
        # Estimar días restantes (asumiendo 50km/día promedio)
        dias_estimados = int(km_restantes / 50) if km_restantes > 0 else 0
        
        # Actualizar campos
        self.salud_porcentaje = round(salud_porcentaje, 1)
        self.nivel_alerta = nivel_alerta
        self.km_estimados_restantes = km_restantes
        self.dias_estimados_restantes = dias_estimados
        self.requiere_servicio_inmediato = salud_porcentaje < 30
        
        # Generar mensaje de alerta si es necesario
        if self.requiere_servicio_inmediato:
            self.mensaje_alerta = f"⚠️ {config.nombre} requiere atención urgente. Salud: {self.salud_porcentaje}%"
        else:
            self.mensaje_alerta = ''
        
        # Guardar cambios
        self.save()
        
        return {
            'salud_porcentaje': self.salud_porcentaje,
            'nivel_alerta': self.nivel_alerta,
            'km_restantes': km_restantes,
            'dias_estimados': dias_estimados,
        }


class AlertaMantenimiento(models.Model):
    """
    Alertas de mantenimiento generadas automáticamente
    Se crean cuando un componente requiere atención
    """
    TIPO_ALERTA_CHOICES = [
        ('MANTENCION_PREVENTIVA', 'Mantención Preventiva'),
        ('COMPONENTE_CRITICO', 'Componente Crítico'),
        ('MANTENCION_POR_KM', 'Mantención por Kilometraje'),
        ('MANTENCION_POR_TIEMPO', 'Mantención por Tiempo'),
    ]
    
    vehiculo = models.ForeignKey(
        Vehiculo, 
        on_delete=models.CASCADE, 
        related_name='alertas_mantenimiento'
    )
    componente_salud = models.ForeignKey(
        ComponenteSaludVehiculo,
        on_delete=models.CASCADE,
        null=True, 
        blank=True,
        related_name='alertas'
    )
    
    tipo_alerta = models.CharField(max_length=30, choices=TIPO_ALERTA_CHOICES)
    titulo = models.CharField(max_length=200)
    descripcion = models.TextField()
    prioridad = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        default=3,
        help_text='1=Baja, 5=Crítica'
    )
    
    # Servicios recomendados
    servicios_recomendados = models.ManyToManyField(
        Servicio,
        related_name='alertas_mantenimiento'
    )
    costo_estimado = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0
    )
    
    # Estado
    activa = models.BooleanField(default=True)
    vista_por_usuario = models.BooleanField(default=False)
    fecha_vista = models.DateTimeField(null=True, blank=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_resolucion = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = 'Alerta de Mantenimiento'
        verbose_name_plural = 'Alertas de Mantenimiento'
        ordering = ['-prioridad', '-fecha_creacion']
    
    def __str__(self):
        return f"{self.vehiculo} - {self.titulo}"

