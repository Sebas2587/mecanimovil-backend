from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.gis.db import models as gis_models
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.core.validators import FileExtensionValidator, MinValueValidator, MaxValueValidator
from django.contrib.gis.geos import Point
from django.conf import settings
from datetime import time, datetime, timedelta
from django.utils import timezone
import uuid
from django.db.models import Avg, Count
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
import logging

logger = logging.getLogger(__name__)


class Usuario(AbstractUser):
    """
    Modelo personalizado para el usuario que extiende el modelo AbstractUser de Django
    """
    es_mecanico = models.BooleanField(default=False)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    direccion = models.CharField(max_length=255, blank=True, null=True)
    foto_perfil = models.ImageField(upload_to='perfiles/', blank=True, null=True)
    password_reset_token = models.CharField(max_length=100, blank=True, null=True, unique=True)
    password_reset_token_expires = models.DateTimeField(blank=True, null=True)
    # NUEVO: Token para notificaciones push de Expo
    expo_push_token = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    
    class Meta:
        verbose_name = _('usuario')
        verbose_name_plural = _('usuarios')
    
    def __str__(self):
        return self.username


class DireccionUsuario(models.Model):
    """
    Modelo para las direcciones de los usuarios
    """
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='direcciones')
    direccion = models.CharField(max_length=255)
    etiqueta = models.CharField(max_length=50, default='Casa')
    detalles = models.CharField(max_length=255, blank=True, null=True)
    es_principal = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    ubicacion = gis_models.PointField(geography=True, blank=True, null=True)
    
    class Meta:
        verbose_name = _('dirección de usuario')
        verbose_name_plural = _('direcciones de usuario')
        ordering = ['-es_principal', '-fecha_actualizacion']
    
    def __str__(self):
        return f"{self.etiqueta} - {self.direccion}"
    
    def save(self, *args, **kwargs):
        # Si la dirección es marcada como principal, actualizar otras direcciones del usuario
        if self.es_principal:
            # Obtener todas las direcciones del usuario que están marcadas como principales
            direcciones_principales = DireccionUsuario.objects.filter(
                usuario=self.usuario,
                es_principal=True
            ).exclude(pk=self.pk if self.pk else None)
            
            # Marcar todas las direcciones principales como no principales
            for direccion in direcciones_principales:
                direccion.es_principal = False
                direccion.save(update_fields=['es_principal'])
        
        super().save(*args, **kwargs)


class Cliente(models.Model):
    """
    Modelo para los clientes que extiende del modelo Usuario
    """
    usuario = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='cliente')
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    email = models.EmailField(max_length=255, unique=True)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    fecha_registro = models.DateField(auto_now_add=True)
    direccion = models.CharField(max_length=255, blank=True, null=True)
    ubicacion = gis_models.PointField(geography=True, blank=True, null=True)
    
    class Meta:
        verbose_name = _('cliente')
        verbose_name_plural = _('clientes')
    
    def __str__(self):
        return f"{self.nombre} {self.apellido}"
    
    def save(self, *args, **kwargs):
        if not self.nombre and self.usuario:
            self.nombre = self.usuario.first_name
        if not self.apellido and self.usuario:
            self.apellido = self.usuario.last_name
        if not self.email and self.usuario:
            self.email = self.usuario.email
        if not self.telefono and self.usuario:
            self.telefono = self.usuario.telefono
        super().save(*args, **kwargs)


class ProveedorServicio(models.Model):
    """
    Modelo abstracto para representar proveedores de servicios 
    (talleres y mecánicos) con atributos comunes
    """
    ESTADO_VERIFICACION_CHOICES = [
        ('pendiente', 'Pendiente de revisión'),
        ('en_revision', 'En revisión'),
        ('aprobado', 'Aprobado'),
        ('rechazado', 'Rechazado'),
    ]
    
    nombre = models.CharField(max_length=255)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    ubicacion = gis_models.PointField(geography=True, null=True)  # Temporalmente nullable para migración
    foto_perfil = models.ImageField(upload_to='proveedores/', blank=True, null=True)
    calificacion_promedio = models.FloatField(default=0.0)
    numero_de_calificaciones = models.IntegerField(default=0)
    activo = models.BooleanField(default=True)
    
    # Campos para verificación y onboarding
    estado_verificacion = models.CharField(
        max_length=20, 
        choices=ESTADO_VERIFICACION_CHOICES, 
        default='pendiente',
        help_text='Estado de verificación del proveedor'
    )
    verificado = models.BooleanField(
        default=False,
        help_text='Indica si el proveedor ha sido verificado y puede aparecer en la app de clientes'
    )
    onboarding_completado = models.BooleanField(
        default=False,
        help_text='Indica si el proveedor completó el proceso de onboarding'
    )
    onboarding_iniciado = models.BooleanField(
        default=False,
        help_text='Indica si el proveedor inició el proceso de onboarding'
    )
    fecha_verificacion = models.DateTimeField(
        null=True, 
        blank=True,
        help_text='Fecha cuando fue verificado el proveedor'
    )
    verificado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(class)s_verificados',
        help_text='Usuario administrador que verificó el proveedor'
    )
    
    # Campos adicionales del onboarding
    descripcion = models.TextField(blank=True, null=True, help_text='Descripción del proveedor')
    rut = models.CharField(max_length=50, blank=True, null=True, help_text='RUT/CUIT/ID Fiscal')
    dni = models.CharField(max_length=50, blank=True, null=True, help_text='DNI/RUT Personal')
    experiencia_anos = models.PositiveIntegerField(null=True, blank=True, help_text='Años de experiencia')
    
    # Campos para timestamping
    fecha_registro = models.DateTimeField(auto_now_add=True)
    ultima_actualizacion = models.DateTimeField(auto_now=True)
    
    # Campo para estado de conexión del proveedor
    ultima_conexion = models.DateTimeField(
        null=True, 
        blank=True,
        help_text='Última vez que el proveedor estuvo conectado en la app'
    )
    esta_conectado = models.BooleanField(
        default=False,
        help_text='Indica si el proveedor está actualmente conectado en la app'
    )

    class Meta:
        abstract = True
        
    def __str__(self):
        return self.nombre
    
    def aprobar_verificacion(self, usuario_verificador=None):
        """Método para aprobar la verificación del proveedor"""
        self.estado_verificacion = 'aprobado'
        self.verificado = True
        self.fecha_verificacion = timezone.now()
        self.verificado_por = usuario_verificador
        self.save(update_fields=['estado_verificacion', 'verificado', 'fecha_verificacion', 'verificado_por'])
    
    def rechazar_verificacion(self, usuario_verificador=None):
        """Método para rechazar la verificación del proveedor"""
        self.estado_verificacion = 'rechazado'
        self.verificado = False
        self.verificado_por = usuario_verificador
        self.save(update_fields=['estado_verificacion', 'verificado', 'verificado_por'])
    
    def marcar_en_revision(self, usuario_verificador=None):
        """Método para marcar como en revisión"""
        self.estado_verificacion = 'en_revision'
        self.verificado_por = usuario_verificador
        self.save(update_fields=['estado_verificacion', 'verificado_por'])


class Taller(ProveedorServicio):
    """
    Modelo para los talleres mecánicos
    """
    usuario = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='taller', null=True, blank=True)
    rut = models.CharField(max_length=20, blank=True, null=True, help_text=_('RUT del taller'))
    capacidad_diaria = models.IntegerField(default=10, help_text=_('Capacidad de servicios por día'))
    horario_atencion = models.CharField(max_length=100, blank=True, null=True)
    
    # Nuevas relaciones para onboarding (usando string reference)
    especialidades = models.ManyToManyField(
        'servicios.CategoriaServicio',
        related_name='talleres',
        blank=True,
        help_text=_('Especialidades del taller')
    )
    marcas_atendidas = models.ManyToManyField(
        'vehiculos.MarcaVehiculo',
        related_name='talleres',
        blank=True,
        help_text=_('Marcas de vehículos que atiende el taller')
    )
    
    class Meta:
        verbose_name = _('taller')
        verbose_name_plural = _('talleres')

    def save(self, *args, **kwargs):
        # Si existe un usuario asociado y no se ha establecido nombre o teléfono,
        # obtenerlos del usuario
        if self.usuario:
            if not self.nombre:
                self.nombre = f"{self.usuario.first_name} {self.usuario.last_name}".strip()
            if not self.telefono:
                self.telefono = self.usuario.telefono
        
        super().save(*args, **kwargs)


class MecanicoDomicilio(ProveedorServicio):
    """
    Modelo para los mecánicos a domicilio
    """
    usuario = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='mecanico_domicilio', null=True, blank=True)
    disponible = models.BooleanField(default=True)
    especialidades = models.ManyToManyField(
        'servicios.CategoriaServicio',
        related_name='mecanicos_domicilio',
        blank=True
    )
    # Nueva relación para marcas atendidas (usando string reference)
    marcas_atendidas = models.ManyToManyField(
        'vehiculos.MarcaVehiculo',
        related_name='mecanicos_domicilio',
        blank=True,
        help_text=_('Marcas de vehículos que atiende el mecánico')
    )
    disponibilidad = models.TextField(blank=True, null=True)
    radio_cobertura = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=10.0,
        help_text=_('Radio de cobertura en kilómetros')
    )
    
    class Meta:
        verbose_name = _('mecánico a domicilio')
        verbose_name_plural = _('mecánicos a domicilio')

    def save(self, *args, **kwargs):
        # Si existe un usuario asociado y no se ha establecido nombre o teléfono,
        # obtenerlos del usuario
        if self.usuario:
            if not self.nombre:
                self.nombre = f"{self.usuario.first_name} {self.usuario.last_name}".strip()
            if not self.telefono:
                self.telefono = self.usuario.telefono
            
            # Marcar el usuario como mecánico
            if not self.usuario.es_mecanico:
                self.usuario.es_mecanico = True
                self.usuario.save(update_fields=['es_mecanico'])
        
        super().save(*args, **kwargs)


class ZonaCobertura(models.Model):
    """
    Modelo para las zonas de cobertura de los mecánicos a domicilio
    """
    mecanico = models.ForeignKey(MecanicoDomicilio, on_delete=models.CASCADE, related_name='zonas_cobertura')
    poligono_cobertura = gis_models.PolygonField(geography=True)
    
    class Meta:
        verbose_name = _('zona de cobertura')
        verbose_name_plural = _('zonas de cobertura')
    
    def __str__(self):
        return f"Zona de cobertura para {self.mecanico.nombre}"


# Validador personalizado para commune_names (DEBE IR ANTES del modelo)
def validate_commune_names(value):
    """Valida que commune_names sea una lista válida de comunas"""
    if not isinstance(value, list):
        raise ValidationError('Las comunas deben ser una lista.')
    
    if len(value) == 0:
        raise ValidationError('Debe seleccionar al menos una comuna.')
    
    if len(value) > 50:  # Límite razonable
        raise ValidationError('No puede seleccionar más de 50 comunas.')
    
    for commune in value:
        if not isinstance(commune, str):
            raise ValidationError('Cada comuna debe ser una cadena de texto.')
        
        if len(commune.strip()) < 2:
            raise ValidationError('Los nombres de comunas deben tener al menos 2 caracteres.')
        
        if len(commune.strip()) > 100:
            raise ValidationError('Los nombres de comunas no pueden exceder 100 caracteres.')


# NUEVO: Modelo para Zonas de Servicio por Comunas
class MechanicServiceArea(models.Model):
    """
    Modelo para gestionar las zonas de servicio de mecánicos a domicilio
    basadas en selección de comunas/distritos
    """
    AREA_TYPE_CHOICES = [
        ('COMMUNE', 'Comuna/Distrito'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mechanic = models.ForeignKey(
        MecanicoDomicilio, 
        on_delete=models.CASCADE, 
        related_name='service_areas',
        verbose_name='Mecánico'
    )
    area_type = models.CharField(
        max_length=20, 
        choices=AREA_TYPE_CHOICES, 
        default='COMMUNE',
        verbose_name='Tipo de Zona'
    )
    name = models.CharField(
        max_length=100, 
        null=True, 
        blank=True,
        verbose_name='Nombre de la Zona',
        help_text='Nombre descriptivo opcional (ej: "Mi Zona Central")'
    )
    commune_names = models.JSONField(
        verbose_name='Nombres de Comunas',
        help_text='Lista de nombres de comunas donde presta servicios',
        validators=[validate_commune_names]
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='Zona Activa',
        help_text='Determina si esta zona está activa para recibir órdenes'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Zona de Servicio'
        verbose_name_plural = 'Zonas de Servicio'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['mechanic', 'is_active']),
            models.Index(fields=['area_type', 'is_active']),
        ]
    
    def __str__(self):
        name_part = f" - {self.name}" if self.name else ""
        communes_part = ", ".join(self.commune_names[:3])
        if len(self.commune_names) > 3:
            communes_part += f" (+{len(self.commune_names)-3} más)"
        return f"{self.mechanic.nombre}{name_part} ({communes_part})"
    
    def get_commune_count(self):
        """Retorna el número de comunas en esta zona"""
        return len(self.commune_names) if self.commune_names else 0
    
    def covers_commune(self, commune_name):
        """Verifica si esta zona cubre una comuna específica"""
        if not self.is_active or not self.commune_names:
            return False
        # Búsqueda case-insensitive para mayor flexibilidad
        commune_name_clean = commune_name.strip().lower()
        return any(
            commune.strip().lower() == commune_name_clean 
            for commune in self.commune_names
        )


# NUEVO: Modelo maestro de Comunas de Chile
class ChileanCommune(models.Model):
    """
    Modelo maestro con todas las comunas de Chile
    """
    code = models.CharField(
        max_length=10, 
        unique=True,
        verbose_name='Código Comuna',
        help_text='Código oficial de la comuna'
    )
    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name='Nombre Comuna'
    )
    region_code = models.CharField(
        max_length=10,
        verbose_name='Código Región'
    )
    region_name = models.CharField(
        max_length=100,
        verbose_name='Nombre Región'
    )
    province_name = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name='Nombre Provincia'
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='Comuna Activa',
        help_text='Determina si la comuna está disponible para selección'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Comuna Chilena'
        verbose_name_plural = 'Comunas Chilenas'
        ordering = ['region_code', 'name']
        indexes = [
            models.Index(fields=['is_active', 'name']),
            models.Index(fields=['region_code', 'name']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.region_name})"


def validar_archivo_documento(archivo):
    """Validar que el archivo sea una imagen válida (JPG, PNG) o PDF"""
    import os
    from django.core.exceptions import ValidationError
    
    # Obtener extensión del archivo
    extension = os.path.splitext(archivo.name)[1].lower()
    
    # Tipos de archivo permitidos
    tipos_permitidos = ['.jpg', '.jpeg', '.png', '.pdf']
    
    if extension not in tipos_permitidos:
        raise ValidationError(
            f'Tipo de archivo no permitido: {extension}. '
            f'Tipos permitidos: {", ".join(tipos_permitidos)}'
        )
    
    # Verificar tamaño del archivo (máximo 10MB)
    if archivo.size > 10 * 1024 * 1024:  # 10MB en bytes
        raise ValidationError('El archivo no puede ser mayor a 10MB')
    
    # Verificar que el archivo no esté vacío
    if archivo.size == 0:
        raise ValidationError('El archivo no puede estar vacío')


class DocumentoOnboarding(models.Model):
    """
    Modelo para almacenar los documentos subidos durante el onboarding
    """
    TIPO_DOCUMENTO_CHOICES = [
        ('dni_frontal', 'DNI/ID Personal (Frontal)'),
        ('dni_trasero', 'DNI/ID Personal (Trasero)'),
        ('rut_fiscal', 'RUT/CUIT/ID Fiscal del Negocio'),
        ('licencia_conducir', 'Licencia de Conducir'),
        ('curriculum', 'Curriculum Vitae'),
        ('certificado_antecedentes', 'Certificado de Antecedentes'),
        ('foto_fachada', 'Foto de la Fachada del Taller'),
        ('foto_interior', 'Foto del Interior del Taller'),
        ('foto_equipos', 'Foto de Equipos/Herramientas'),
        ('foto_herramientas', 'Foto de Herramientas Portátiles'),
        ('foto_vehiculo', 'Foto de Vehículo de Trabajo'),
    ]
    
    # Relaciones genéricas para talleres y mecánicos
    taller = models.ForeignKey(
        Taller, 
        on_delete=models.CASCADE, 
        related_name='documentos_onboarding',
        null=True, 
        blank=True
    )
    mecanico = models.ForeignKey(
        MecanicoDomicilio, 
        on_delete=models.CASCADE, 
        related_name='documentos_onboarding',
        null=True, 
        blank=True
    )
    
    tipo_documento = models.CharField(max_length=50, choices=TIPO_DOCUMENTO_CHOICES)
    # CAMBIADO: De ImageField a FileField para soportar múltiples tipos
    archivo = models.FileField(
        upload_to='documentos_onboarding/',
        validators=[validar_archivo_documento],
        help_text='Archivos permitidos: JPG, PNG, PDF (máximo 10MB)'
    )
    nombre_original = models.CharField(max_length=255, help_text='Nombre original del archivo')
    fecha_subida = models.DateTimeField(auto_now_add=True)
    verificado = models.BooleanField(default=False)
    comentarios_verificacion = models.TextField(blank=True, null=True)
    
    class Meta:
        verbose_name = _('documento de onboarding')
        verbose_name_plural = _('documentos de onboarding')
        constraints = [
            models.CheckConstraint(
                check=models.Q(taller__isnull=False) | models.Q(mecanico__isnull=False),
                name='documento_debe_tener_taller_o_mecanico'
            )
        ]
    
    def __str__(self):
        proveedor = self.taller or self.mecanico
        return f"{self.get_tipo_documento_display()} - {proveedor.nombre if proveedor else 'Sin proveedor'}"
    
    def get_tipo_archivo(self):
        """Obtener el tipo de archivo basado en la extensión"""
        import os
        extension = os.path.splitext(self.archivo.name)[1].lower()
        if extension in ['.jpg', '.jpeg']:
            return 'imagen/jpeg'
        elif extension == '.png':
            return 'imagen/png'
        elif extension == '.pdf':
            return 'documento/pdf'
        else:
            return 'desconocido'
    
    def es_imagen(self):
        """Verificar si el archivo es una imagen"""
        return self.get_tipo_archivo().startswith('imagen/')
    
    def es_pdf(self):
        """Verificar si el archivo es un PDF"""
        return self.get_tipo_archivo() == 'documento/pdf'


class Resena(models.Model):
    """
    Modelo para las reseñas de talleres y mecánicos
    """
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='resenas')
    comentario = models.TextField(blank=True, null=True)
    calificacion = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    fecha_hora_resena = models.DateTimeField(auto_now_add=True)
    taller = models.ForeignKey(Taller, on_delete=models.CASCADE, related_name='resenas', null=True, blank=True)
    mecanico = models.ForeignKey(MecanicoDomicilio, on_delete=models.CASCADE, related_name='resenas', null=True, blank=True)
    # New Link to Service Request
    solicitud = models.OneToOneField(
        'ordenes.SolicitudServicio', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='resena',
        help_text='Solicitud de servicio asociada a esta reseña'
    )
    
    class Meta:
        verbose_name = _('reseña')
        verbose_name_plural = _('reseñas')
        constraints = [
            models.CheckConstraint(
                check=models.Q(taller__isnull=False) | models.Q(mecanico__isnull=False),
                name='resena_debe_tener_taller_o_mecanico'
            )
        ]
    
    def __str__(self):
        if self.taller:
            return f"Reseña para {self.taller.nombre} por {self.cliente.nombre}"
        elif self.mecanico:
            return f"Reseña para {self.mecanico.nombre} por {self.cliente.nombre}"
        return f"Reseña por {self.cliente.nombre}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Actualizar promedio de calificaciones para taller o mecánico
        if self.taller:
            taller_resenas = Resena.objects.filter(taller=self.taller)
            total = sum(resena.calificacion for resena in taller_resenas)
            count = taller_resenas.count()
            
            if count > 0:
                self.taller.calificacion_promedio = total / count
                self.taller.numero_de_calificaciones = count
                self.taller.save(update_fields=['calificacion_promedio', 'numero_de_calificaciones'])
                
        elif self.mecanico:
            mecanico_resenas = Resena.objects.filter(mecanico=self.mecanico)
            total = sum(resena.calificacion for resena in mecanico_resenas)
            count = mecanico_resenas.count()
            
            if count > 0:
                self.mecanico.calificacion_promedio = total / count
                self.mecanico.numero_de_calificaciones = count
                self.mecanico.save(update_fields=['calificacion_promedio', 'numero_de_calificaciones'])


class ResenaFoto(models.Model):
    """
    Modelo para almacenar fotos adjuntas a una reseña
    """
    resena = models.ForeignKey(Resena, on_delete=models.CASCADE, related_name='fotos')
    foto = models.ImageField(upload_to='resenas/', help_text="Foto adjunta a la reseña")
    fecha_subida = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = _('foto de reseña')
        verbose_name_plural = _('fotos de reseñas')
        
    def __str__(self):
        return f"Foto para reseña {self.resena.id}"


class HorarioProveedor(models.Model):
    """
    Modelo unificado para gestionar los horarios de atención de talleres y mecánicos por día de la semana
    """
    DIAS_SEMANA = [
        (0, 'Lunes'),
        (1, 'Martes'),
        (2, 'Miércoles'),
        (3, 'Jueves'),
        (4, 'Viernes'),
        (5, 'Sábado'),
        (6, 'Domingo'),
    ]
    
    # Relaciones opcionales para taller o mecánico
    taller = models.ForeignKey(
        'Taller',
        on_delete=models.CASCADE,
        related_name='horarios_configurados',
        null=True,
        blank=True
    )
    mecanico = models.ForeignKey(
        'MecanicoDomicilio',
        on_delete=models.CASCADE,
        related_name='horarios_configurados',
        null=True,
        blank=True
    )
    
    dia_semana = models.IntegerField(
        choices=DIAS_SEMANA,
        help_text=_('Día de la semana (0=Lunes, 6=Domingo)')
    )
    activo = models.BooleanField(
        default=True,
        help_text=_('Si el proveedor atiende este día')
    )
    hora_inicio = models.TimeField(
        help_text=_('Hora de inicio de atención'),
        default='08:00'
    )
    hora_fin = models.TimeField(
        help_text=_('Hora de fin de atención'),
        default='18:00'
    )
    
    # Configuración de slots de tiempo
    duracion_slot = models.PositiveIntegerField(
        default=60,
        help_text=_('Duración de cada slot en minutos')
    )
    tiempo_descanso = models.PositiveIntegerField(
        default=0,
        help_text=_('Tiempo libre entre servicios en minutos')
    )
    
    class Meta:
        verbose_name = _('horario de proveedor')
        verbose_name_plural = _('horarios de proveedores')
        constraints = [
            models.CheckConstraint(
                check=models.Q(taller__isnull=False) | models.Q(mecanico__isnull=False),
                name='horario_debe_tener_taller_o_mecanico'
            ),
            models.UniqueConstraint(
                fields=['taller', 'dia_semana'],
                condition=models.Q(taller__isnull=False),
                name='unique_taller_dia_semana'
            ),
            models.UniqueConstraint(
                fields=['mecanico', 'dia_semana'],
                condition=models.Q(mecanico__isnull=False),
                name='unique_mecanico_dia_semana'
            ),
        ]
        ordering = ['dia_semana']
    
    def __str__(self):
        proveedor = self.taller or self.mecanico
        dia_nombre = dict(self.DIAS_SEMANA)[self.dia_semana]
        if self.activo:
            return f"{proveedor.nombre} - {dia_nombre}: {self.hora_inicio.strftime('%H:%M')} - {self.hora_fin.strftime('%H:%M')}"
        else:
            return f"{proveedor.nombre} - {dia_nombre}: Cerrado"
    
    def clean(self):
        """Validar que la hora de inicio sea menor que la de fin"""
        if self.activo and self.hora_inicio >= self.hora_fin:
            raise ValidationError('La hora de inicio debe ser menor que la hora de fin')
        
        # Validar que tenga taller o mecánico, pero no ambos
        if not self.taller and not self.mecanico:
            raise ValidationError('Debe especificar un taller o un mecánico')
        if self.taller and self.mecanico:
            raise ValidationError('No puede especificar tanto taller como mecánico')
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
    
    def generar_slots_disponibles(self, fecha=None):
        """
        Genera los slots de tiempo disponibles para este día
        """
        if not self.activo:
            return []
        
        slots = []
        hora_actual = datetime.combine(fecha or datetime.today().date(), self.hora_inicio)
        hora_fin = datetime.combine(fecha or datetime.today().date(), self.hora_fin)
        
        while hora_actual + timedelta(minutes=self.duracion_slot) <= hora_fin:
            slot_fin = hora_actual + timedelta(minutes=self.duracion_slot)
            slots.append({
                'hora_inicio': hora_actual.time().strftime('%H:%M'),
                'hora_fin': slot_fin.time().strftime('%H:%M'),
                'hora_inicio_24h': hora_actual.time(),
                'hora_fin_24h': slot_fin.time(),
                'disponible': True  # Se verificará disponibilidad real en el servicio
            })
            hora_actual = slot_fin + timedelta(minutes=self.duracion_slot + self.tiempo_descanso)
        
        return slots
    
    @property
    def proveedor(self):
        """Retorna el proveedor asociado (taller o mecánico)"""
        return self.taller or self.mecanico
    
    @property
    def tipo_proveedor(self):
        """Retorna el tipo de proveedor"""
        return 'taller' if self.taller else 'mecanico'


class ConfiguracionSemanalProveedor(models.Model):
    """
    Modelo auxiliar para facilitar la configuración semanal completa desde el admin
    No se almacena en base de datos - solo para formularios
    """
    # Datos del proveedor
    taller = models.ForeignKey(
        'Taller', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        verbose_name="Taller"
    )
    mecanico = models.ForeignKey(
        'MecanicoDomicilio', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        verbose_name="Mecánico"
    )
    
    # Configuración global
    hora_inicio_global = models.TimeField(
        default='08:00',
        verbose_name="Hora de inicio (global)",
        help_text="Hora de inicio que se aplicará a todos los días habilitados"
    )
    hora_fin_global = models.TimeField(
        default='18:00',
        verbose_name="Hora de fin (global)",
        help_text="Hora de fin que se aplicará a todos los días habilitados"
    )
    duracion_slot_global = models.PositiveIntegerField(
        default=60,
        verbose_name="Duración de slot (minutos)",
        help_text="Duración en minutos de cada slot de atención"
    )
    tiempo_descanso_global = models.PositiveIntegerField(
        default=0,
        verbose_name="Tiempo de descanso (minutos)",
        help_text="Tiempo de descanso entre slots"
    )
    
    # Días habilitados
    lunes_activo = models.BooleanField(default=True, verbose_name="Lunes")
    martes_activo = models.BooleanField(default=True, verbose_name="Martes")
    miercoles_activo = models.BooleanField(default=True, verbose_name="Miércoles")
    jueves_activo = models.BooleanField(default=True, verbose_name="Jueves")
    viernes_activo = models.BooleanField(default=True, verbose_name="Viernes")
    sabado_activo = models.BooleanField(default=False, verbose_name="Sábado")
    domingo_activo = models.BooleanField(default=False, verbose_name="Domingo")
    
    # Configuración específica por día (opcional)
    lunes_hora_inicio = models.TimeField(null=True, blank=True, verbose_name="Lunes - Hora inicio")
    lunes_hora_fin = models.TimeField(null=True, blank=True, verbose_name="Lunes - Hora fin")
    martes_hora_inicio = models.TimeField(null=True, blank=True, verbose_name="Martes - Hora inicio")
    martes_hora_fin = models.TimeField(null=True, blank=True, verbose_name="Martes - Hora fin")
    miercoles_hora_inicio = models.TimeField(null=True, blank=True, verbose_name="Miércoles - Hora inicio")
    miercoles_hora_fin = models.TimeField(null=True, blank=True, verbose_name="Miércoles - Hora fin")
    jueves_hora_inicio = models.TimeField(null=True, blank=True, verbose_name="Jueves - Hora inicio")
    jueves_hora_fin = models.TimeField(null=True, blank=True, verbose_name="Jueves - Hora fin")
    viernes_hora_inicio = models.TimeField(null=True, blank=True, verbose_name="Viernes - Hora inicio")
    viernes_hora_fin = models.TimeField(null=True, blank=True, verbose_name="Viernes - Hora fin")
    sabado_hora_inicio = models.TimeField(null=True, blank=True, verbose_name="Sábado - Hora inicio")
    sabado_hora_fin = models.TimeField(null=True, blank=True, verbose_name="Sábado - Hora fin")
    domingo_hora_inicio = models.TimeField(null=True, blank=True, verbose_name="Domingo - Hora inicio")
    domingo_hora_fin = models.TimeField(null=True, blank=True, verbose_name="Domingo - Hora fin")
    
    def aplicar_configuracion(self, eliminar_existente=True):
        """
        Aplica la configuración semanal creando/actualizando registros HorarioProveedor
        """
        if not self.taller and not self.mecanico:
            raise ValueError("Debe especificar un taller o mecánico")
        
        if self.taller and self.mecanico:
            raise ValueError("No puede especificar tanto taller como mecánico")
        
        # Eliminar configuraciones existentes si se solicita
        if eliminar_existente:
            if self.taller:
                HorarioProveedor.objects.filter(taller=self.taller).delete()
            else:
                HorarioProveedor.objects.filter(mecanico=self.mecanico).delete()
        
        # Mapeo de días
        dias_config = {
            0: ('lunes', self.lunes_activo, self.lunes_hora_inicio, self.lunes_hora_fin),
            1: ('martes', self.martes_activo, self.martes_hora_inicio, self.martes_hora_fin),
            2: ('miercoles', self.miercoles_activo, self.miercoles_hora_inicio, self.miercoles_hora_fin),
            3: ('jueves', self.jueves_activo, self.jueves_hora_inicio, self.jueves_hora_fin),
            4: ('viernes', self.viernes_activo, self.viernes_hora_inicio, self.viernes_hora_fin),
            5: ('sabado', self.sabado_activo, self.sabado_hora_inicio, self.sabado_hora_fin),
            6: ('domingo', self.domingo_activo, self.domingo_hora_inicio, self.domingo_hora_fin),
        }
        
        horarios_creados = []
        
        # Crear horarios para cada día
        for dia_num, (dia_nombre, activo, hora_inicio_especifica, hora_fin_especifica) in dias_config.items():
            # Usar horas específicas del día si están definidas, sino usar globales
            hora_inicio = hora_inicio_especifica if hora_inicio_especifica else self.hora_inicio_global
            hora_fin = hora_fin_especifica if hora_fin_especifica else self.hora_fin_global
            
            horario_data = {
                'dia_semana': dia_num,
                'activo': activo,
                'hora_inicio': hora_inicio,
                'hora_fin': hora_fin,
                'duracion_slot': self.duracion_slot_global,
                'tiempo_descanso': self.tiempo_descanso_global
            }
            
            if self.taller:
                horario_data['taller'] = self.taller
                horario_data['mecanico'] = None
            else:
                horario_data['mecanico'] = self.mecanico
                horario_data['taller'] = None
            
            horario = HorarioProveedor.objects.create(**horario_data)
            horarios_creados.append(horario)
        
        return horarios_creados
    
    def clean(self):
        """Validaciones del modelo"""
        if not self.taller and not self.mecanico:
            raise ValidationError("Debe especificar un taller o mecánico")
        
        if self.taller and self.mecanico:
            raise ValidationError("No puede especificar tanto taller como mecánico")
        
        if self.hora_inicio_global >= self.hora_fin_global:
            raise ValidationError("La hora de inicio global debe ser menor que la hora de fin global")
    
    def __str__(self):
        proveedor = self.taller.nombre if self.taller else self.mecanico.nombre
        return f"Configuración semanal - {proveedor}"
    
    class Meta:
        verbose_name = "Configuración Semanal de Horarios"
        verbose_name_plural = "Configuraciones Semanales de Horarios" 


class ConnectionStatus(models.Model):
    """
    Modelo para manejar estados de conexión en tiempo real
    """
    STATUS_CHOICES = [
        ('online', 'En línea'),
        ('offline', 'Desconectado'),
        ('busy', 'En servicio'),
    ]
    
    proveedor = models.OneToOneField(
        'MecanicoDomicilio',
        on_delete=models.CASCADE,
        related_name='connection_status',
        null=True,
        blank=True
    )
    taller = models.OneToOneField(
        'Taller',
        on_delete=models.CASCADE,
        related_name='connection_status',
        null=True,
        blank=True
    )
    
    # Campos de estado según el prompt
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='offline',
        help_text='Estado actual del proveedor'
    )
    is_online = models.BooleanField(
        default=False,
        help_text='Campo booleano para consultas rápidas'
    )
    last_heartbeat = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Último latido del proveedor'
    )
    last_status_change = models.DateTimeField(
        auto_now=True,
        help_text='Último cambio de estado'
    )
    
    # Campos existentes mantenidos para compatibilidad
    esta_conectado = models.BooleanField(default=False)
    ultima_conexion = models.DateTimeField(auto_now=True)
    ultima_desconexion = models.DateTimeField(null=True, blank=True)
    session_id = models.CharField(max_length=255, null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    
    class Meta:
        verbose_name = 'Estado de Conexión'
        verbose_name_plural = 'Estados de Conexión'
    
    def __str__(self):
        proveedor_nombre = self.proveedor.nombre if self.proveedor else self.taller.nombre if self.taller else 'Desconocido'
        return f"{proveedor_nombre} - {self.get_status_display()}"
    
    @property
    def tipo_proveedor(self):
        if self.proveedor:
            return 'mecanico'
        elif self.taller:
            return 'taller'
        return 'desconocido'
    
    @property
    def nombre_proveedor(self):
        if self.proveedor:
            return self.proveedor.nombre
        elif self.taller:
            return self.taller.nombre
        return 'Desconocido'
    
    def update_status(self, new_status, update_heartbeat=True):
        """
        Actualiza el estado del proveedor y mantiene sincronizados los campos
        """
        from django.utils import timezone
        
        self.status = new_status
        self.is_online = new_status in ['online', 'busy']
        self.esta_conectado = self.is_online
        self.last_status_change = timezone.now()
        
        if update_heartbeat:
            self.last_heartbeat = timezone.now()
        
        if new_status == 'offline':
            self.ultima_desconexion = timezone.now()
        else:
            self.ultima_conexion = timezone.now()
        
        self.save()
    
    def update_heartbeat(self):
        """
        Actualiza solo el heartbeat sin cambiar el estado
        """
        from django.utils import timezone
        self.last_heartbeat = timezone.now()
        self.save(update_fields=['last_heartbeat']) 


class ProviderProfile(models.Model):
    """
    Modelo para almacenar información detallada de un proveedor (taller o mecánico)
    """
    user = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='provider_profile')
    nombre = models.CharField(max_length=255, help_text='Nombre completo del proveedor')
    telefono = models.CharField(max_length=20, blank=True, null=True)
    direccion = models.CharField(max_length=255, blank=True, null=True)
    foto_perfil = models.ImageField(upload_to='proveedores/', blank=True, null=True)
    descripcion = models.TextField(blank=True, null=True, help_text='Descripción detallada del proveedor')
    rut = models.CharField(max_length=50, blank=True, null=True, help_text='RUT/CUIT/ID Fiscal')
    dni = models.CharField(max_length=50, blank=True, null=True, help_text='DNI/RUT Personal')
    experiencia_anos = models.PositiveIntegerField(null=True, blank=True, help_text='Años de experiencia')
    
    # Campos de calificación
    average_rating = models.DecimalField(
        max_digits=3, 
        decimal_places=2, 
        default=0.00,
        help_text="Calificación promedio del proveedor"
    )
    review_count = models.IntegerField(
        default=0,
        help_text="Número total de reseñas"
    )
    
    # Campos para verificación y onboarding
    estado_verificacion = models.CharField(
        max_length=20, 
        choices=ProveedorServicio.ESTADO_VERIFICACION_CHOICES, 
        default='pendiente',
        help_text='Estado de verificación del proveedor'
    )
    verificado = models.BooleanField(
        default=False,
        help_text='Indica si el proveedor ha sido verificado y puede aparecer en la app de clientes'
    )
    onboarding_completado = models.BooleanField(
        default=False,
        help_text='Indica si el proveedor completó el proceso de onboarding'
    )
    onboarding_iniciado = models.BooleanField(
        default=False,
        help_text='Indica si el proveedor inició el proceso de onboarding'
    )
    fecha_verificacion = models.DateTimeField(
        null=True, 
        blank=True,
        help_text='Fecha cuando fue verificado el proveedor'
    )
    verificado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(class)s_verificados',
        help_text='Usuario administrador que verificó el proveedor'
    )
    
    # Campos adicionales del onboarding
    descripcion_onboarding = models.TextField(blank=True, null=True, help_text='Descripción del proveedor')
    rut_onboarding = models.CharField(max_length=50, blank=True, null=True, help_text='RUT/CUIT/ID Fiscal')
    dni_onboarding = models.CharField(max_length=50, blank=True, null=True, help_text='DNI/RUT Personal')
    experiencia_anos_onboarding = models.PositiveIntegerField(null=True, blank=True, help_text='Años de experiencia')
    
    # Campos para timestamping
    fecha_registro = models.DateTimeField(auto_now_add=True)
    ultima_actualizacion = models.DateTimeField(auto_now=True)
    
    # Campo para estado de conexión del proveedor
    ultima_conexion = models.DateTimeField(
        null=True, 
        blank=True,
        help_text='Última vez que el proveedor estuvo conectado en la app'
    )
    esta_conectado = models.BooleanField(
        default=False,
        help_text='Indica si el proveedor está actualmente conectado en la app'
    )

    class Meta:
        verbose_name = _('perfil de proveedor')
        verbose_name_plural = _('perfiles de proveedores')
    
    def __str__(self):
        return f"{self.nombre} ({self.user.username})"
    
    def update_rating_stats(self):
        """Actualiza las estadísticas de calificación basadas en las reseñas"""
        stats = self.reviews.aggregate(
            avg_rating=Avg('rating'),
            total_reviews=Count('id')
        )
        
        self.average_rating = stats['avg_rating'] or 0.00
        self.review_count = stats['total_reviews'] or 0
        self.save(update_fields=['average_rating', 'review_count'])
    
    def save(self, *args, **kwargs):
        # Si el usuario asociado no tiene un perfil, crear uno
        if not self.pk and not hasattr(self.user, 'provider_profile'):
            ProviderProfile.objects.create(user=self.user)
        
        # Si el usuario asociado tiene un perfil, actualizarlo
        if self.pk:
            self.user.first_name = self.nombre.split()[0] if self.nombre else ''
            self.user.last_name = ' '.join(self.nombre.split()[1:]) if len(self.nombre.split()) > 1 else ''
            self.user.telefono = self.telefono
            self.user.direccion = self.direccion
            self.user.save()
        
        super().save(*args, **kwargs)


class Review(models.Model):
    """Modelo para las reseñas de los clientes a los proveedores"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    client = models.ForeignKey(
        Usuario, 
        on_delete=models.CASCADE,
        related_name='reviews',
        help_text="Cliente que hizo la reseña"
    )
    
    # Campos para identificar el proveedor
    provider_type = models.CharField(
        max_length=20,
        choices=[
            ('taller', 'Taller'),
            ('mecanico', 'Mecánico a Domicilio')
        ],
        help_text="Tipo de proveedor"
    )
    provider_id = models.IntegerField(
        help_text="ID del proveedor (Taller o MecanicoDomicilio)"
    )
    
    service_order = models.OneToOneField(
        'ordenes.SolicitudServicio',
        on_delete=models.CASCADE,
        help_text="Orden de servicio asociada"
    )
    
    rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Calificación de 1 a 5 estrellas"
    )
    
    comment = models.TextField(
        blank=True,
        help_text="Comentario opcional del cliente"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['client', 'provider_type', 'provider_id', 'service_order']
        ordering = ['-created_at']
        verbose_name = "Reseña"
        verbose_name_plural = "Reseñas"
    
    def __str__(self):
        return f"Reseña de {self.client.username} para {self.get_provider_name()}"
    
    def save(self, *args, **kwargs):
        # Validar que el cliente no haya reseñado este servicio antes
        if not self.pk:  # Solo en creación
            existing_review = Review.objects.filter(
                client=self.client,
                provider_type=self.provider_type,
                provider_id=self.provider_id,
                service_order=self.service_order
            ).exists()
            
            if existing_review:
                raise ValidationError("Ya existe una reseña para este servicio")
        
        super().save(*args, **kwargs)
    
    def get_provider_name(self):
        """Obtener el nombre del proveedor"""
        try:
            if self.provider_type == 'taller':
                from .models import Taller
                provider = Taller.objects.get(id=self.provider_id)
                return provider.nombre
            elif self.provider_type == 'mecanico':
                from .models import MecanicoDomicilio
                provider = MecanicoDomicilio.objects.get(id=self.provider_id)
                return provider.nombre
        except:
            return "Proveedor no encontrado"
        return "Proveedor desconocido"
    
    @property
    def client_info(self):
        """Información del cliente que hizo la reseña"""
        return {
            'username': self.client.username,
            'full_name': f"{self.client.first_name} {self.client.last_name}".strip() or self.client.username
        }
    
    @property
    def car_info(self):
        """Información del vehículo del servicio"""
        try:
            service_order = self.service_order
            if hasattr(service_order, 'client_car'):
                car = service_order.client_car
                return {
                    'brand': car.marca.nombre if car.marca else 'N/A',
                    'model': car.modelo.nombre if car.modelo else 'N/A',
                    'full_name': f"{car.marca.nombre} {car.modelo.nombre}" if car.marca and car.modelo else 'N/A'
                }
        except:
            pass
        return {
            'brand': 'N/A',
            'model': 'N/A', 
            'full_name': 'N/A'
        }


# Señales para actualizar estadísticas automáticamente
@receiver(post_save, sender=Review)
def update_provider_rating_on_review_save(sender, instance, created, **kwargs):
    """Actualizar estadísticas de calificación del proveedor cuando se guarda una reseña"""
    if created:
        try:
            if instance.provider_type == 'taller':
                from .models import Taller
                provider = Taller.objects.get(id=instance.provider_id)
                # Actualizar calificación promedio
                reviews = Review.objects.filter(provider_type='taller', provider_id=instance.provider_id)
                avg_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0
                provider.calificacion_promedio = round(avg_rating, 2)
                provider.numero_de_calificaciones = reviews.count()
                provider.save(update_fields=['calificacion_promedio', 'numero_de_calificaciones'])
            elif instance.provider_type == 'mecanico':
                from .models import MecanicoDomicilio
                provider = MecanicoDomicilio.objects.get(id=instance.provider_id)
                # Actualizar calificación promedio
                reviews = Review.objects.filter(provider_type='mecanico', provider_id=instance.provider_id)
                avg_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0
                provider.calificacion_promedio = round(avg_rating, 2)
                provider.numero_de_calificaciones = reviews.count()
                provider.save(update_fields=['calificacion_promedio', 'numero_de_calificaciones'])
        except Exception as e:
            logger.error(f"Error actualizando calificación del proveedor: {e}")

@receiver(post_delete, sender=Review)
def update_provider_rating_on_review_delete(sender, instance, **kwargs):
    """Actualizar estadísticas de calificación del proveedor cuando se elimina una reseña"""
    try:
        if instance.provider_type == 'taller':
            from .models import Taller
            provider = Taller.objects.get(id=instance.provider_id)
            # Actualizar calificación promedio
            reviews = Review.objects.filter(provider_type='taller', provider_id=instance.provider_id)
            avg_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0
            provider.calificacion_promedio = round(avg_rating, 2)
            provider.numero_de_calificaciones = reviews.count()
            provider.save(update_fields=['calificacion_promedio', 'numero_de_calificaciones'])
        elif instance.provider_type == 'mecanico':
            from .models import MecanicoDomicilio
            provider = MecanicoDomicilio.objects.get(id=instance.provider_id)
            # Actualizar calificación promedio
            reviews = Review.objects.filter(provider_type='mecanico', provider_id=instance.provider_id)
            avg_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0
            provider.calificacion_promedio = round(avg_rating, 2)
            provider.numero_de_calificaciones = reviews.count()
            provider.save(update_fields=['calificacion_promedio', 'numero_de_calificaciones'])
    except Exception as e:
        logger.error(f"Error actualizando calificación del proveedor: {e}") 


class TallerDireccion(models.Model):
    """
    Modelo para almacenar la dirección física del taller
    """
    taller = models.OneToOneField(Taller, on_delete=models.CASCADE, related_name='direccion_fisica')
    calle = models.CharField(max_length=255, help_text="Nombre de la calle")
    numero = models.CharField(max_length=20, help_text="Número de la casa/edificio")
    comuna = models.CharField(max_length=100, help_text="Comuna")
    ciudad = models.CharField(max_length=100, help_text="Ciudad")
    region = models.CharField(max_length=100, help_text="Región")
    codigo_postal = models.CharField(max_length=10, blank=True, null=True, help_text="Código postal")
    detalles_adicionales = models.TextField(blank=True, null=True, help_text="Detalles adicionales de ubicación")
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('dirección de taller')
        verbose_name_plural = _('direcciones de talleres')
    
    def __str__(self):
        return f"{self.calle} {self.numero}, {self.comuna}, {self.ciudad}"
    
    @property
    def direccion_completa(self):
        """Retorna la dirección completa formateada"""
        partes = [self.calle, self.numero, self.comuna, self.ciudad, self.region]
        return ", ".join(filter(None, partes))


class PushToken(models.Model):
    """
    Modelo para almacenar push tokens de Expo para notificaciones push
    """
    PLATAFORMA_CHOICES = [
        ('ios', 'iOS'),
        ('android', 'Android'),
        ('unknown', 'Desconocido'),
    ]
    
    usuario = models.ForeignKey(
        Usuario, 
        on_delete=models.CASCADE, 
        related_name='push_tokens',
        help_text='Usuario propietario del token'
    )
    token = models.CharField(
        max_length=255, 
        unique=True,
        help_text='Token de Expo Push Notification'
    )
    dispositivo = models.CharField(
        max_length=100, 
        blank=True, 
        null=True,
        help_text='Nombre o identificador del dispositivo'
    )
    plataforma = models.CharField(
        max_length=20, 
        choices=PLATAFORMA_CHOICES,
        default='unknown',
        help_text='Plataforma del dispositivo'
    )
    activo = models.BooleanField(
        default=True,
        help_text='Indica si el token está activo y debe recibir notificaciones'
    )
    fecha_registro = models.DateTimeField(
        auto_now_add=True,
        help_text='Fecha de registro del token'
    )
    fecha_actualizacion = models.DateTimeField(
        auto_now=True,
        help_text='Fecha de última actualización'
    )
    ultima_notificacion_enviada = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Fecha de la última notificación enviada a este token'
    )

    class Meta:
        db_table = 'usuarios_push_tokens'
        verbose_name = 'Push Token'
        verbose_name_plural = 'Push Tokens'
        indexes = [
            models.Index(fields=['usuario', 'activo']),
            models.Index(fields=['token']),
        ]
        ordering = ['-fecha_registro']
    
    def __str__(self):
        return f"{self.usuario.username} - {self.plataforma} ({'Activo' if self.activo else 'Inactivo'})" 

class Notificacion(models.Model):
    """
    Modelo para notificaciones in-app del usuario
    """
    TIPO_CHOICES = [
        ('health_alert', 'Alerta de Salud'),
        ('salud_actualizada', 'Salud Actualizada'),
        ('viaje_registrado', 'Viaje Registrado'),
        ('payment_reminder', 'Recordatorio de Pago'),
        ('order_update', 'Actualización de Orden'),
        ('nueva_oferta', 'Nueva Oferta'),
        ('solicitud_adjudicada', 'Solicitud Adjudicada'),
        ('system', 'Sistema'),
    ]
    
    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name='notificaciones',
        help_text='Usuario destinatario de la notificación'
    )
    tipo = models.CharField(
        max_length=50,
        choices=TIPO_CHOICES,
        help_text='Tipo de notificación'
    )
    titulo = models.CharField(
        max_length=200,
        help_text='Título de la notificación'
    )
    mensaje = models.TextField(
        help_text='Mensaje de la notificación'
    )
    leida = models.BooleanField(
        default=False,
        help_text='Indica si la notificación ha sido leída'
    )
    fecha_leida = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Fecha en que se marcó como leída'
    )
    eliminada = models.BooleanField(
        default=False,
        help_text='Soft-delete: el usuario la descartó; no se muestra pero evita que Celery la recree'
    )
    fecha_eliminada = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Fecha en que el usuario la eliminó'
    )
    data = models.JSONField(
        default=dict,
        blank=True,
        help_text='Metadatos adicionales en formato JSON'
    )
    fecha_creacion = models.DateTimeField(
        auto_now_add=True,
        help_text='Fecha de creación de la notificación'
    )
    
    class Meta:
        db_table = 'usuarios_notificaciones'
        verbose_name = 'Notificación'
        verbose_name_plural = 'Notificaciones'
        ordering = ['-fecha_creacion']
        indexes = [
            models.Index(fields=['usuario', '-fecha_creacion'], name='usuarios_no_usuario_e45db9_idx'),
            models.Index(fields=['usuario', 'leida'], name='usuarios_no_usuario_b76e82_idx'),
            models.Index(fields=['usuario', 'eliminada'], name='usuarios_no_usr_eliminada_idx'),
        ]
    
    def __str__(self):
        return f"{self.usuario.username} - {self.titulo} ({'Leída' if self.leida else 'No leída'})"

    @classmethod
    def crear_unica(cls, usuario, tipo, titulo, mensaje, data=None, ventana_horas=24, dedup_key=None):
        """
        Crea la notificación solo si no existe otra equivalente en las últimas
        `ventana_horas` (incluye eliminadas via soft-delete, evita que Celery las recree).

        dedup_key (dict, opcional): subset del data a usar para la comparación de
            duplicados (usa data__contains, más permisivo que la igualdad exacta).
            Útil cuando el data puede tener campos que varían entre runs de Celery
            (p.ej. es_critico en health_alert) pero el identificador real es solo
            vehicle_id. Si se omite, se usa igualdad exacta sobre todo el data.

        Retorna (instancia, created).
        """
        from django.utils import timezone
        from datetime import timedelta

        if data is None:
            data = {}

        desde = timezone.now() - timedelta(hours=ventana_horas)

        # Busca tanto activas como eliminadas (soft-delete) para evitar recreación.
        # Si se pasa dedup_key usamos data__contains (subset match) para tolerar
        # campos cambiantes dentro del data (p.ej. es_critico).
        if dedup_key is not None:
            existente = cls.objects.filter(
                usuario=usuario,
                tipo=tipo,
                data__contains=dedup_key,
                fecha_creacion__gte=desde,
            ).first()
        else:
            existente = cls.objects.filter(
                usuario=usuario,
                tipo=tipo,
                data=data,
                fecha_creacion__gte=desde,
            ).first()

        if existente:
            return existente, False

        nueva = cls.objects.create(
            usuario=usuario,
            tipo=tipo,
            titulo=titulo,
            mensaje=mensaje,
            data=data,
        )
        return nueva, True
