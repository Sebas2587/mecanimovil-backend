from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from mecanimovilapp.apps.vehiculos.models import Vehiculo
from mecanimovilapp.apps.checklists.models import ChecklistInstance
from mecanimovilapp.apps.servicios.models import Servicio
import math

# ==========================================
# CATÁLOGO MAESTRO DE COMPONENTES
# ==========================================

class ComponenteSalud(models.Model):
    """
    Catálogo maestro de componentes de salud (ej: Aceite, Bujías, Frenos).
    """
    nombre = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, help_text="Identificador para iconos y frontend (ej: oil, brakes)")
    descripcion = models.TextField(blank=True, null=True)
    es_critico = models.BooleanField(default=False, help_text="Si falla, ¿es crítico para el funcionamiento?")
    
    # Visualización
    icono = models.CharField(max_length=50, default='construct-outline')
    orden_visualizacion = models.PositiveIntegerField(default=0)
    
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    # Servicios que el usuario puede agendar cuando este componente requiere atención
    # (ej. componente "Bujías" → servicio "Cambio de bujías"). Configurable en Admin.
    servicios_asociados = models.ManyToManyField(
        Servicio,
        blank=True,
        related_name='componentes_salud',
        help_text='Servicios sugeridos al tocar este componente en salud del vehículo (modal en app).',
    )

    class Meta:
        verbose_name = 'Componente de Salud (Maestro)'
        verbose_name_plural = 'Componentes de Salud (Maestro)'
        ordering = ['orden_visualizacion', 'nombre']

    def __str__(self):
        return self.nombre


# ==========================================
# REGLAS DE MANTENIMIENTO (CASCADA)
# ==========================================

class ReglaMantenimientoGenerica(models.Model):
    """
    Nivel 2 (Fallback): Reglas genéricas por Tipo de Motor.
    Se aplican si no existe una regla específica para la marca/modelo.
    """
    TIPO_MOTOR_CHOICES = [
        ('GASOLINA', 'Gasolina'),
        ('DIESEL', 'Diésel'),
        ('ELECTRICO', 'Eléctrico'),
        ('HIBRIDO', 'Híbrido'),
    ]

    componente = models.ForeignKey(ComponenteSalud, on_delete=models.CASCADE, related_name='reglas_genericas')
    tipo_motor = models.CharField(max_length=20, choices=TIPO_MOTOR_CHOICES)
    
    vida_util_km = models.PositiveIntegerField(help_text="Vida útil estimada en Kilómetros (ETA)")
    beta = models.FloatField(default=2.0, help_text="Factor de forma Weibull (2.0 = desgaste lineal/normal)")
    # Intervalo por tiempo (ej. aceite cada 6 meses aunque no se alcance el km). Si se define, la salud
    # usa el mínimo entre desgaste por km y por tiempo desde fecha_ultimo_servicio.
    intervalo_meses = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Meses recomendados entre servicios (ej. 6). Opcional; si null, solo aplica eje km.",
    )

    # Factores adicionales opcionales
    meses_critico = models.PositiveIntegerField(null=True, blank=True, help_text="Límite en meses (opcional)")

    class Meta:
        verbose_name = 'Regla Mantenimiento Genérica'
        verbose_name_plural = 'Reglas Mantenimiento Genéricas'
        unique_together = ['componente', 'tipo_motor']

    def __str__(self):
        return f"{self.componente.nombre} - {self.tipo_motor} ({self.vida_util_km}km)"


class ReglaMantenimientoEspecifica(models.Model):
    """
    Nivel 1 (Prioridad Alta): Reglas específicas por Marca y Modelo.
    Sobrescriben a las reglas genéricas.
    """
    componente = models.ForeignKey(ComponenteSalud, on_delete=models.CASCADE, related_name='reglas_especificas')
    marca = models.CharField(max_length=100, help_text="Debe coincidir EXACTAMENTE con vehiculo.marca")
    modelo = models.CharField(max_length=100, help_text="Debe coincidir EXACTAMENTE con vehiculo.modelo")
    
    vida_util_km = models.PositiveIntegerField(help_text="Vida útil específica en Kilómetros")
    beta = models.FloatField(default=2.0, help_text="Factor de forma Weibull")
    intervalo_meses = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Meses entre servicios para este modelo; si null, hereda solo eje km o usar regla genérica.",
    )

    class Meta:
        verbose_name = 'Regla Mantenimiento Específica'
        verbose_name_plural = 'Reglas Mantenimiento Específicas'
        unique_together = ['marca', 'modelo', 'componente']

    def __str__(self):
        return f"{self.componente.nombre} - {self.marca} {self.modelo} ({self.vida_util_km}km)"


# ==========================================
# ESTADO DEL VEHÍCULO (PERSISTENCIA)
# ==========================================

class EstadoSaludVehiculo(models.Model):
    """
    Snapshot del estado de salud general del vehículo.
    """
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.CASCADE, related_name='estados_salud')
    salud_general_porcentaje = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(100)])
    kilometraje_snapshot = models.PositiveIntegerField()
    fecha_calculo = models.DateTimeField(auto_now_add=True)
    # Se actualiza en cada recálculo (HealthEngine) para saber si cache/lectura está obsoleto
    ultima_actualizacion = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Última vez que HealthEngine actualizó este snapshot'
    )

    # Stats
    total_componentes_evaluados = models.PositiveIntegerField(default=0)
    componentes_optimos = models.PositiveIntegerField(default=0)
    componentes_atencion = models.PositiveIntegerField(default=0)
    componentes_urgentes = models.PositiveIntegerField(default=0)
    componentes_criticos = models.PositiveIntegerField(default=0)
    
    tiene_alertas_activas = models.BooleanField(default=False)
    costo_estimado_mantenimiento = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Tracking de push: último % global con el que se emitió salud_actualizada/alerta_global.
    ultimo_pct_global_notificado = models.FloatField(
        null=True, blank=True,
        help_text='Último salud_general_porcentaje notificado. '
                  'Evita pushes repetitivas cuando el % no cambia.',
    )

    class Meta:
        verbose_name = 'Estado de Salud de Vehículo'
        verbose_name_plural = 'Estados de Salud de Vehículos'
        ordering = ['-fecha_calculo']
        constraints = [
            models.UniqueConstraint(fields=['vehiculo'], name='unique_estado_salud_per_vehiculo'),
        ]


class ComponenteSaludVehiculo(models.Model):
    """
    Estado persistente de un componente en un vehículo.
    Se actualiza mediante el Health Engine.
    """
    NIVEL_ALERTA_CHOICES = [
        ('OPTIMO', 'Óptimo'),
        ('ATENCION', 'Atención'),
        ('URGENTE', 'Urgente'),
        ('CRITICO', 'Crítico'),
    ]
    
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.CASCADE, related_name='componentes_salud')
    # Refactor: FK a ComponenteSalud (Maestro) en lugar de Config
    componente = models.ForeignKey(ComponenteSalud, on_delete=models.CASCADE, null=True)
    
    salud_porcentaje = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(100)])
    nivel_alerta = models.CharField(max_length=20, choices=NIVEL_ALERTA_CHOICES)
    
    # Datos de cálculo (Snapshot de la regla aplicada)
    vida_util_proyectada = models.PositiveIntegerField(default=0, help_text="Vida util (eta) usada para el cálculo")
    es_regla_especifica = models.BooleanField(default=False, help_text="¿Se usó una regla específica?")

    # Historial Servicios
    km_ultimo_servicio = models.PositiveIntegerField(default=0)
    fecha_ultimo_servicio = models.DateTimeField(null=True, blank=True)

    # True cuando el dato de km_ultimo_servicio proviene de una fuente real confirmada
    # (registro de vehículo con historial, checklist completado, viaje GPS registrado).
    # False cuando fue auto-creado por el Engine sin historial → se usa estimación conservadora.
    historial_conocido = models.BooleanField(
        default=False,
        help_text='Indica si km_ultimo_servicio proviene de datos reales (checklist/registro). '
                  'Si False, el Engine usa estimación conservadora de ~1 ciclo de mantenimiento.',
    )

    # Fuente del último dato de historial.
    # Permite al frontend mostrar distintos niveles de confianza y al
    # engine saber si puede confiar plenamente en el dato.
    FUENTE_CHOICES = [
        ('ENGINE',           'Estimado automáticamente'),
        ('CHECKLIST',        'Confirmado por checklist de taller'),
        ('USUARIO_DECLARADO','Declarado por el usuario (retroactivo)'),
        ('REGISTRO_INICIAL', 'Informado al registrar el vehículo'),
    ]
    historial_fuente = models.CharField(
        max_length=20,
        choices=FUENTE_CHOICES,
        default='ENGINE',
        help_text='Origen del último dato de km/fecha de servicio.',
    )

    # Ancla de la curva Weibull cuando un técnico declara un porcentaje de
    # vida útil restante durante una INSPECCIÓN. Persistir el valor permite
    # al HealthEngine recalcular en cada nuevo km usando este punto como
    # origen de la curva (en lugar de km_ultimo_servicio).
    salud_anclada_pct = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text=(
            'Porcentaje de vida útil declarado en la última inspección de checklist. '
            'Si no es null, el HealthEngine ancla la curva Weibull en este punto. '
            'Se limpia (None) cuando el componente se reemplaza.'
        ),
    )
    
    # Predicciones
    km_estimados_restantes = models.PositiveIntegerField(default=0)
    requiere_servicio_inmediato = models.BooleanField(default=False)
    mensaje_alerta = models.TextField(blank=True)

    # Tracking de notificaciones — se actualiza cada vez que se envía una push
    # para este componente. Permite detectar cambios reales entre recálculos.
    ultimo_pct_notificado = models.FloatField(
        null=True, blank=True,
        help_text='Último salud_porcentaje con el que se emitió push. '
                  'Null = nunca notificado.',
    )
    ultimo_nivel_notificado = models.CharField(
        max_length=20, null=True, blank=True,
        help_text='Último nivel_alerta (OPTIMO/ATENCION/URGENTE/CRITICO) notificado.',
    )

    ultima_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Componente de Salud de Vehículo'
        verbose_name_plural = 'Componentes de Salud de Vehículos'
        unique_together = ('vehiculo', 'componente')
        ordering = ['componente__orden_visualizacion']

    def __str__(self):
        return f"{self.vehiculo} - {self.componente.nombre}: {self.salud_porcentaje}%"


class AlertaMantenimiento(models.Model):
    """
    Alertas generadas (Legacy/Compatibilidad).
    """
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.CASCADE, related_name='alertas_mantenimiento')
    componente_salud = models.ForeignKey(ComponenteSaludVehiculo, on_delete=models.CASCADE, null=True, blank=True, related_name='alertas')
    tipo_alerta = models.CharField(max_length=50) # Simplificado
    titulo = models.CharField(max_length=200)
    descripcion = models.TextField()
    prioridad = models.PositiveIntegerField(default=3)
    servicios_recomendados = models.ManyToManyField(Servicio, related_name='alertas_mantenimiento')
    costo_estimado = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    activa = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Alerta de Mantenimiento'
        verbose_name_plural = 'Alertas de Mantenimiento'


# ==========================================
# DATASET DE EVENTOS (PARA APRENDIZAJE ML)
# ==========================================

class EventoSaludVehiculo(models.Model):
    """
    Registro inmutable de eventos relevantes para entrenar modelos predictivos.

    Cada fila es un punto de datos para scikit-learn:
      - Cuando se completa un checklist real → se registra el km y meses transcurridos
        desde el último servicio registrado para ese componente. Esto entrena al
        modelo con la pregunta: "¿cuántos km/meses sobrevivió este componente
        antes de necesitar mantenimiento?"
      - Cuando un vehículo registra un viaje → se acumulan km en el odómetro.
      - Cuando un componente cae a salud crítica → se registra el evento de "near-fail".

    El management command `entrenar_modelos_salud` consume esta tabla para
    entrenar Random Forest / Linear Regression por tipo de componente.

    Diseño:
      - Inmutable (auditoría / dataset histórico).
      - Indexado por (componente, marca, modelo) para queries de entrenamiento.
      - Captura snapshot de variables al momento del evento (evita drift de marca/modelo).
    """
    TIPO_EVENTO_CHOICES = [
        ('SERVICIO_REALIZADO',   'Servicio realizado (checklist completado)'),
        ('INSPECCION_DECLARADA', 'Inspección con porcentaje declarado por técnico'),
        ('FALLA_REPORTADA',      'Componente reportó falla / 0 % salud'),
        ('NIVEL_CRITICO',        'Componente alcanzó nivel CRÍTICO'),
        ('VIAJE_KM',             'Acumulación de km por viaje GPS'),
        ('CHECKLIST_KM',         'Lectura de odómetro desde checklist'),
        ('REGISTRO_INICIAL',     'Vehículo registrado con historial inicial'),
    ]

    vehiculo = models.ForeignKey(
        Vehiculo, on_delete=models.CASCADE, related_name='eventos_salud',
    )
    componente = models.ForeignKey(
        ComponenteSalud, on_delete=models.CASCADE, null=True, blank=True,
        related_name='eventos_salud',
        help_text='Componente afectado. Null para eventos globales (viaje, registro).',
    )
    tipo_evento = models.CharField(max_length=30, choices=TIPO_EVENTO_CHOICES)

    # ── Snapshot del vehículo al momento del evento ─────────────────
    marca       = models.CharField(max_length=100, blank=True)
    modelo      = models.CharField(max_length=100, blank=True)
    year        = models.IntegerField(null=True, blank=True)
    tipo_motor  = models.CharField(max_length=20, blank=True)
    transmision = models.CharField(max_length=20, blank=True)
    kilometraje = models.PositiveIntegerField(default=0,
        help_text='Odómetro del vehículo al momento del evento.')

    # ── Métricas relacionadas con el componente / regla ─────────────
    km_desde_ultimo_servicio    = models.IntegerField(null=True, blank=True,
        help_text='Distancia entre el km del evento y el km del último servicio (positivo).')
    meses_desde_ultimo_servicio = models.FloatField(null=True, blank=True)
    vida_util_referencia_km     = models.PositiveIntegerField(null=True, blank=True,
        help_text='eta de la regla aplicada (Weibull) al momento del evento.')
    salud_porcentaje            = models.FloatField(null=True, blank=True,
        help_text='Salud calculada al momento del evento.')

    # ── Variables ambientales y de uso ──────────────────────────────
    clima_condicion   = models.CharField(max_length=20, blank=True,
        help_text='rain | heat | cold | normal (al momento del evento).')
    temperatura_c     = models.FloatField(null=True, blank=True)
    humedad_pct       = models.FloatField(null=True, blank=True)
    promedio_km_dia   = models.FloatField(null=True, blank=True,
        help_text='km/día calculado a partir de viajes recientes (si aplica).')

    # ── Contexto del evento ─────────────────────────────────────────
    checklist_id = models.IntegerField(null=True, blank=True)
    orden_id     = models.IntegerField(null=True, blank=True)
    viaje_id     = models.IntegerField(null=True, blank=True)
    metadata     = models.JSONField(default=dict, blank=True,
        help_text='Datos adicionales del evento (ej. detalles_clima, geolocalización).')

    fecha_evento = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = 'Evento de Salud (ML)'
        verbose_name_plural = 'Eventos de Salud (ML)'
        ordering = ['-fecha_evento']
        indexes = [
            models.Index(fields=['componente', 'tipo_evento']),
            models.Index(fields=['marca', 'modelo']),
            models.Index(fields=['tipo_evento', 'fecha_evento']),
        ]

    def __str__(self):
        comp = self.componente.nombre if self.componente else 'global'
        return f"{self.get_tipo_evento_display()} — {comp} ({self.marca} {self.modelo})"
