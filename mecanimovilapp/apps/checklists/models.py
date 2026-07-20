from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.gis.db import models as gis_models
from django.contrib.auth import get_user_model
from mecanimovilapp.apps.servicios.models import Servicio

User = get_user_model()


class ChecklistItemCatalog(models.Model):
    """
    Catálogo de items reutilizables para checklists
    Este es el núcleo del sistema: permite crear elementos que se pueden usar en cualquier template
    """
    
    TIPO_PREGUNTA_CHOICES = [
        # Tipos básicos
        ('TEXT', 'Texto libre'),
        ('NUMBER', 'Número'),
        ('BOOLEAN', 'Sí/No (Booleano)'),
        ('SELECT', 'Selección única'),
        ('MULTISELECT', 'Selección múltiple'),
        ('PHOTO', 'Fotografía'),
        ('SIGNATURE', 'Firma digital'),
        ('LOCATION', 'Ubicación GPS'),
        ('DATETIME', 'Fecha y hora'),
        ('RATING', 'Calificación (1-5 estrellas)'),
        
        # Tipos específicos automotrices
        ('KILOMETER_INPUT', 'Entrada de kilometraje'),
        ('FUEL_GAUGE', 'Medidor de combustible'),
        ('FLUID_LEVEL', 'Nivel de fluidos'),
        ('COMPONENT_HEALTH', 'Vida útil de componente (slider 0–100%)'),
        
        # Tipos de inventario e inspección
        ('INVENTORY_CHECKLIST', 'Lista de inventario'),
        ('SERVICE_SELECTION', 'Selección de servicios'),
        ('VEHICLE_CONDITION', 'Estado del vehículo'),
        
        # Tipos de inspección específica
        ('VEHICLE_DIAGRAM', 'Diagrama de vehículo'),
        ('DAMAGE_REPORT', 'Reporte de daños'),
        ('EXTERIOR_INSPECTION', 'Inspección exterior'),
        ('INTERIOR_INSPECTION', 'Inspección interior'),
        ('ENGINE_INSPECTION', 'Inspección del motor'),
        
        # Tipos de verificación de sistemas
        ('ELECTRICAL_CHECK', 'Verificación eléctrica'),
        ('BRAKE_CHECK', 'Verificación de frenos'),
        ('SUSPENSION_CHECK', 'Verificación de suspensión'),
        ('TIRE_CONDITION', 'Estado de neumáticos'),
        
        # Tipos de finalización
        ('FINAL_NOTES', 'Notas finales'),
        ('CLIENT_CONFIRMATION', 'Confirmación del cliente'),
        ('WORK_SUMMARY', 'Resumen del trabajo'),
    ]
    
    CATEGORIA_CHOICES = [
        # Categorías principales
        ('INFORMACION_GENERAL', 'Información General'),
        ('DATOS_VEHICULO', 'Datos del Vehículo'),
        
        # Inventario y verificación inicial
        ('INVENTARIO_VEHICULO', 'Inventario del Vehículo'),
        ('ACCESORIOS_HERRAMIENTAS', 'Accesorios y Herramientas'),
        ('DOCUMENTOS_VEHICULO', 'Documentos del Vehículo'),
        
        # Inspección externa
        ('CARROCERIA_EXTERIOR', 'Carrocería Exterior'),
        ('CRISTALES_ESPEJOS', 'Cristales y Espejos'),
        ('LUCES_SENALIZACION', 'Luces y Señalización'),
        ('NEUMATICOS_LLANTAS', 'Neumáticos y Llantas'),
        
        # Inspección interna
        ('INTERIOR_CABINA', 'Interior de Cabina'),
        ('TABLERO_CONTROLES', 'Tablero y Controles'),
        ('ASIENTOS_TAPICERIA', 'Asientos y Tapicería'),
        
        # Sistemas mecánicos
        ('MOTOR_COMPARTIMIENTO', 'Motor y Compartimiento'),
        ('FLUIDOS_NIVELES', 'Fluidos y Niveles'),
        ('SISTEMA_ELECTRICO', 'Sistema Eléctrico'),
        ('SISTEMA_FRENOS', 'Sistema de Frenos'),
        ('SUSPENSION_DIRECCION', 'Suspensión y Dirección'),
        ('TRANSMISION_EMBRAGUE', 'Transmisión y Embrague'),
        
        # Servicios y trabajos
        ('TIPO_TRABAJO', 'Tipo de Trabajo Realizado'),
        ('SERVICIOS_APLICADOS', 'Servicios Aplicados'),
        ('REPUESTOS_UTILIZADOS', 'Repuestos Utilizados'),
        
        # Finalización
        ('OBSERVACIONES_TECNICO', 'Observaciones del Técnico'),
        ('RECOMENDACIONES', 'Recomendaciones'),
        ('FOTOS_FINALES', 'Fotos Finales'),
        ('FIRMAS_CONFORMIDAD', 'Firmas de Conformidad'),
    ]
    
    # Información básica del item
    nombre = models.CharField(
        max_length=255,
        help_text=_('Nombre identificativo del item')
    )
    categoria = models.CharField(
        max_length=50,
        choices=CATEGORIA_CHOICES,
        help_text=_('Categoría a la que pertenece este item')
    )
    tipo_pregunta = models.CharField(
        max_length=30,
        choices=TIPO_PREGUNTA_CHOICES,
        help_text=_('Tipo de pregunta/input para este item')
    )
    pregunta_texto = models.TextField(
        help_text=_('Texto de la pregunta que se mostrará al usuario')
    )
    descripcion_ayuda = models.TextField(
        blank=True,
        null=True,
        help_text=_('Descripción adicional o ayuda para el usuario')
    )
    placeholder = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text=_('Texto de ejemplo que se muestra en el campo')
    )
    
    # Configuración de validación
    es_obligatorio_por_defecto = models.BooleanField(
        default=True,
        help_text=_('Si este item debe ser obligatorio por defecto')
    )
    opciones_seleccion = models.JSONField(
        null=True,
        blank=True,
        help_text=_('Lista de opciones para SELECT y MULTISELECT (formato JSON)')
    )
    valor_minimo = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_('Valor mínimo para tipos numéricos')
    )
    valor_maximo = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_('Valor máximo para tipos numéricos')
    )
    
    # Configuración de fotos
    min_fotos = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=_('Número mínimo de fotos requeridas (para tipo PHOTO)')
    )
    max_fotos = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=_('Número máximo de fotos permitidas (para tipo PHOTO)')
    )
    
    # Metadatos
    activo = models.BooleanField(
        default=True,
        help_text=_('Si este item está disponible para usar en templates')
    )
    uso_frecuente = models.BooleanField(
        default=False,
        help_text=_('Marcar si es un item de uso frecuente para facilitar la selección')
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('Item del Catálogo')
        verbose_name_plural = _('Items del Catálogo')
        ordering = ['categoria', 'nombre']
        indexes = [
            models.Index(fields=['categoria', 'tipo_pregunta']),
            models.Index(fields=['uso_frecuente', 'activo']),
        ]
    
    def __str__(self):
        return f"[{self.get_tipo_pregunta_display()}] {self.nombre} ({self.get_categoria_display()})"


class ChecklistTemplate(models.Model):
    """
    Template de checklist asociado a servicios específicos
    """

    TIPO_INTENCION_CHOICES = [
        ('REPARACION', 'Reparación / reemplazo de componentes'),
        ('INSPECCION', 'Inspección / diagnóstico'),
        ('PRECOMPRA', 'Inspección pre-compra (no afecta salud)'),
        ('MIXTO', 'Mixto (definido a nivel de ítem)'),
    ]

    nombre = models.CharField(
        max_length=255,
        help_text=_('Nombre descriptivo del template (ej. "Checklist Cambio de Aceite")')
    )
    descripcion = models.TextField(
        blank=True,
        null=True,
        help_text=_('Descripción detallada del checklist')
    )
    servicio = models.ForeignKey(
        Servicio,
        on_delete=models.CASCADE,
        related_name='checklist_templates',
        help_text=_('Servicio al que aplica este checklist')
    )
    tipo_intencion_default = models.CharField(
        max_length=20,
        choices=TIPO_INTENCION_CHOICES,
        default='MIXTO',
        help_text=_(
            'Intención por defecto del checklist sobre la salud del vehículo. '
            'Cada ítem puede sobrescribirla con su propio tipo_actualizacion.'
        ),
    )
    activo = models.BooleanField(
        default=True,
        help_text=_('Indica si este template está disponible para uso')
    )
    generado_por_ia = models.BooleanField(
        default=False,
        help_text=_('True si el template fue generado automáticamente por IA'),
    )
    revisado_en = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Fecha en que un administrador revisó/validó el template generado por IA'),
    )
    version = models.CharField(
        max_length=10,
        default='1.0',
        help_text=_('Versión del template para control de cambios')
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('Template de Checklist')
        verbose_name_plural = _('Templates de Checklist')
        unique_together = ('servicio', 'version')
        ordering = ['servicio__nombre', '-version']
    
    def __str__(self):
        return f"{self.nombre} v{self.version} - {self.servicio.nombre}"


class ChecklistItemTemplate(models.Model):
    """
    Item específico dentro de un template, basado en items del catálogo
    """

    TIPO_ACTUALIZACION_CHOICES = [
        ('REEMPLAZA', 'Reemplaza el componente (resetea salud a 100%)'),
        ('INSPECCIONA', 'Inspecciona y declara estado actual del componente'),
        ('INFORMATIVO', 'No afecta métricas de salud'),
    ]

    checklist_template = models.ForeignKey(
        ChecklistTemplate,
        on_delete=models.CASCADE,
        related_name='items'
    )
    
    # Referencia al item del catálogo
    catalog_item = models.ForeignKey(
        ChecklistItemCatalog,
        on_delete=models.CASCADE,
        related_name='template_usages',
        help_text=_('Item del catálogo en el que se basa este item del template')
    )
    
    # Configuración específica del template
    orden_visual = models.PositiveIntegerField(
        help_text=_('Orden de aparición en el checklist (1, 2, 3...)')
    )
    
    # Sobrescribir configuraciones del catálogo si es necesario
    es_obligatorio = models.BooleanField(
        null=True,
        blank=True,
        help_text=_('Sobrescribe la configuración del catálogo. Deja vacío para usar valor por defecto.')
    )
    descripcion_ayuda_custom = models.TextField(
        blank=True,
        null=True,
        help_text=_('Descripción personalizada que sobrescribe la del catálogo')
    )
    placeholder_custom = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text=_('Placeholder personalizado que sobrescribe el del catálogo')
    )

    # Semántica de salud: cómo afecta la respuesta a este ítem la salud del vehículo
    tipo_actualizacion = models.CharField(
        max_length=20,
        choices=TIPO_ACTUALIZACION_CHOICES,
        null=True,
        blank=True,
        help_text=_(
            'Si null, hereda de checklist_template.tipo_intencion_default. '
            'REEMPLAZA: setea salud=100. INSPECCIONA: usa el valor declarado. '
            'INFORMATIVO: no toca métricas.'
        ),
    )
    componente_salud_asociado = models.ForeignKey(
        'vehiculos.ComponenteSalud',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='checklist_item_templates',
        help_text=_(
            'Componente cuya salud se actualiza con la respuesta a este ítem. '
            'Sustituye al antiguo mapeo_componentes por substring.'
        ),
    )
    
    class Meta:
        verbose_name = _('Item de Template de Checklist')
        verbose_name_plural = _('Items de Template de Checklist')
        unique_together = ('checklist_template', 'orden_visual')
        ordering = ['checklist_template', 'orden_visual']
    
    def __str__(self):
        if self.catalog_item:
            return f"{self.checklist_template.nombre} - {self.orden_visual}: {self.catalog_item.nombre}"
        else:
            return f"{self.checklist_template.nombre} - {self.orden_visual}: [Sin item del catálogo]"
    
    # Propiedades que delegan al item del catálogo
    @property
    def categoria(self):
        return self.catalog_item.categoria if self.catalog_item else None
    
    @property
    def tipo_pregunta(self):
        return self.catalog_item.tipo_pregunta if self.catalog_item else None
    
    @property
    def pregunta_texto(self):
        return self.catalog_item.pregunta_texto if self.catalog_item else "Pregunta no disponible"
    
    @property
    def descripcion_ayuda(self):
        if self.descripcion_ayuda_custom:
            return self.descripcion_ayuda_custom
        return self.catalog_item.descripcion_ayuda if self.catalog_item else None
    
    @property
    def placeholder(self):
        if self.placeholder_custom:
            return self.placeholder_custom
        return self.catalog_item.placeholder if self.catalog_item else None
    
    @property
    def es_obligatorio_efectivo(self):
        if self.es_obligatorio is not None:
            return self.es_obligatorio
        return self.catalog_item.es_obligatorio_por_defecto if self.catalog_item else False
    
    @property
    def opciones_seleccion(self):
        return self.catalog_item.opciones_seleccion if self.catalog_item else None
    
    @property
    def valor_minimo(self):
        return self.catalog_item.valor_minimo if self.catalog_item else None
    
    @property
    def valor_maximo(self):
        return self.catalog_item.valor_maximo if self.catalog_item else None
    
    @property
    def min_fotos(self):
        return self.catalog_item.min_fotos if self.catalog_item else None
    
    @property
    def max_fotos(self):
        return self.catalog_item.max_fotos if self.catalog_item else None

    @property
    def tipo_actualizacion_efectivo(self):
        """
        Resuelve el tipo de actualización aplicado a la salud del vehículo.

        Si el ítem define `tipo_actualizacion`, gana. En caso contrario hereda
        del template:
            REPARACION  → REEMPLAZA
            INSPECCION  → INSPECCIONA
            PRECOMPRA   → INFORMATIVO (la certificación se hace fuera de salud)
            MIXTO       → INFORMATIVO (no se asume nada por defecto)
        """
        if self.tipo_actualizacion:
            return self.tipo_actualizacion
        intencion = getattr(self.checklist_template, 'tipo_intencion_default', 'MIXTO')
        return {
            'REPARACION': 'REEMPLAZA',
            'INSPECCION': 'INSPECCIONA',
            'PRECOMPRA': 'INFORMATIVO',
            'MIXTO': 'INFORMATIVO',
        }.get(intencion, 'INFORMATIVO')


class ChecklistInstance(models.Model):
    """
    Instancia de checklist creada para una orden específica
    """
    ESTADO_CHOICES = [
        ('PENDIENTE', 'Pendiente de inicio'),
        ('EN_PROGRESO', 'En progreso'),
        ('PAUSADO', 'Pausado temporalmente'),
        ('PENDIENTE_FIRMA_CLIENTE', 'Pendiente de firma del cliente'),
        ('COMPLETADO', 'Completado'),
        ('CANCELADO', 'Cancelado'),
    ]
    
    # Relación con la orden (marketplace) o cita personal del taller
    orden = models.OneToOneField(
        'ordenes.SolicitudServicio',
        on_delete=models.CASCADE,
        related_name='checklist_instance',
        null=True,
        blank=True,
    )
    cita_personal = models.OneToOneField(
        'ordenes.CitaAgendaPersonal',
        on_delete=models.CASCADE,
        related_name='checklist_instance',
        null=True,
        blank=True,
    )
    
    # Template utilizado
    checklist_template = models.ForeignKey(
        ChecklistTemplate,
        on_delete=models.PROTECT,
        related_name='instancias',
        help_text=_('Template utilizado para crear esta instancia')
    )
    
    # Estado y timestamps
    estado = models.CharField(
        max_length=30,
        choices=ESTADO_CHOICES,
        default='PENDIENTE'
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_inicio = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Momento en que se inició el checklist')
    )
    fecha_finalizacion = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Momento en que se completó el checklist')
    )
    fecha_completado_proveedor = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_(
            'Momento en que el proveedor finaliza su parte (firma del técnico), '
            'antes de esperar la firma del cliente. Usado en KPIs de tiempo real.'
        )
    )
    
    # Información de finalización
    ubicacion_finalizacion = gis_models.PointField(
        geography=True,
        null=True,
        blank=True,
        help_text=_('Ubicación GPS donde se finalizó el checklist')
    )
    
    # Firmas digitales (almacenadas como Base64)
    firma_tecnico = models.TextField(
        null=True,
        blank=True,
        help_text=_('Firma digital del técnico en formato Base64')
    )
    firma_cliente = models.TextField(
        null=True,
        blank=True,
        help_text=_('Firma digital del cliente en formato Base64')
    )
    
    # Metadatos adicionales
    progreso_porcentaje = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text=_('Porcentaje de completado del checklist')
    )
    tiempo_total_minutos = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=_('Tiempo total invertido en completar el checklist (en minutos)')
    )
    
    class Meta:
        verbose_name = _('Instancia de Checklist')
        verbose_name_plural = _('Instancias de Checklist')
        ordering = ['-fecha_creacion']
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(orden__isnull=False, cita_personal__isnull=True)
                    | models.Q(orden__isnull=True, cita_personal__isnull=False)
                ),
                name='checklist_instance_exactly_one_parent',
            ),
        ]

    @property
    def parent_label(self) -> str:
        if self.orden_id:
            return f'Orden {self.orden_id}'
        if self.cita_personal_id:
            return f'Cita {self.cita_personal_id}'
        return 'Sin padre'

    def __str__(self):
        return f"Checklist #{self.id} - {self.parent_label} - {self.estado}"


class ChecklistItemResponse(models.Model):
    """
    Respuesta a un item específico del checklist
    """
    checklist_instance = models.ForeignKey(
        ChecklistInstance,
        on_delete=models.CASCADE,
        related_name='respuestas'
    )
    item_template = models.ForeignKey(
        ChecklistItemTemplate,
        on_delete=models.CASCADE,
        related_name='respuestas'
    )
    
    # Diferentes tipos de respuestas
    respuesta_texto = models.TextField(null=True, blank=True)
    respuesta_numero = models.DecimalField(
        max_digits=15,
        decimal_places=4,
        null=True,
        blank=True
    )
    respuesta_booleana = models.BooleanField(null=True, blank=True)
    respuesta_seleccion = models.JSONField(
        null=True,
        blank=True,
        help_text=_('Respuesta para preguntas de selección (simple o múltiple)')
    )
    respuesta_fecha = models.DateTimeField(null=True, blank=True)
    respuesta_ubicacion = gis_models.PointField(
        geography=True,
        null=True,
        blank=True
    )
    
    # Metadatos de la respuesta
    completado = models.BooleanField(
        default=False,
        help_text=_('Indica si esta respuesta está completa y validada')
    )
    fecha_respuesta = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('Respuesta de Checklist')
        verbose_name_plural = _('Respuestas de Checklist')
        unique_together = ('checklist_instance', 'item_template')
        ordering = ['item_template__orden_visual']
    
    def __str__(self):
        if self.item_template.catalog_item:
            return f"Respuesta #{self.id} - {self.item_template.catalog_item.nombre}"
        else:
            return f"Respuesta #{self.id} - [Item sin catálogo]"


class ChecklistPhoto(models.Model):
    """
    Fotografías asociadas a respuestas del checklist
    """
    response = models.ForeignKey(
        ChecklistItemResponse,
        on_delete=models.CASCADE,
        related_name='fotos'
    )
    
    # Archivo de imagen
    imagen = models.ImageField(
        upload_to='checklist_photos/',
        help_text=_('Archivo de imagen capturado')
    )
    
    # Metadatos de la foto
    descripcion = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text=_('Descripción opcional de la foto')
    )
    orden_en_respuesta = models.PositiveIntegerField(
        default=1,
        help_text=_('Orden de esta foto dentro de la respuesta')
    )
    
    fecha_captura = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = _('Foto de Checklist')
        verbose_name_plural = _('Fotos de Checklist')
        unique_together = ('response', 'orden_en_respuesta')
        ordering = ['response', 'orden_en_respuesta']
    
    def __str__(self):
        if self.response.item_template.catalog_item:
            return f"Foto #{self.id} - {self.response.item_template.catalog_item.nombre}"
        else:
            return f"Foto #{self.id} - [Item sin catálogo]" 