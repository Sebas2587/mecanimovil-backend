from rest_framework import serializers
from django.utils import timezone
from .models import (
    Usuario, Cliente, Taller, MecanicoDomicilio, ZonaCobertura, 
    Resena, DireccionUsuario, HorarioProveedor, DocumentoOnboarding,
    ConfiguracionSemanalProveedor, MechanicServiceArea, ChileanCommune,
    ConnectionStatus, ProviderProfile, Review, TallerDireccion, Notificacion
)
from mecanimovilapp.apps.servicios.models import CategoriaServicio
from django.contrib.gis.geos import Point
import logging
from django.db.models import Avg, Count

# Helper para URLs de archivos en cPanel
from mecanimovilapp.storage.utils import get_image_url


# Configurar logger
logger = logging.getLogger(__name__)


def _proveedor_suscripcion_mensual_activa(usuario):
    """
    True si el usuario proveedor tiene SuscripcionProveedor en estado 'activa'.
    Excluye 'pausada': no se muestran insignias KPI a clientes sin cobro mensual vigente.
    """
    if usuario is None:
        return False
    sus = getattr(usuario, 'suscripcion_proveedor', None)
    return sus is not None and getattr(sus, 'estado', None) == 'activa'


def aggregate_public_provider_rating(provider_type, provider_id):
    """
    Misma fuente que `ReviewViewSet.list` (`/usuarios/providers/<id>/reviews/`):
    promedio de `Review.rating` para ese proveedor.
    Retorna (promedio redondeado a 1 decimal o None, cantidad de reseñas).
    """
    stats = Review.objects.filter(provider_type=provider_type, provider_id=provider_id).aggregate(
        avg_rating=Avg('rating'),
        total_reviews=Count('id'),
    )
    total = stats['total_reviews'] or 0
    if not total:
        return None, 0
    avg = float(stats['avg_rating'] or 0.0)
    return round(avg, 1), int(total)


def _cached_public_review_stats(serializer, provider_type, obj):
    """Una agregación por proveedor por serialización (rating_average + rating_reviews_count)."""
    cache = serializer.context.setdefault('_public_review_stats_by_provider', {})
    key = (provider_type, obj.pk)
    if key not in cache:
        cache[key] = aggregate_public_provider_rating(provider_type, obj.id)
    return cache[key]


class TallerDireccionSerializer(serializers.ModelSerializer):
    """
    Serializer para el modelo TallerDireccion
    """
    direccion_completa = serializers.ReadOnlyField()
    
    class Meta:
        model = TallerDireccion
        fields = [
            'id', 'calle', 'numero', 'comuna', 'ciudad', 'region', 
            'codigo_postal', 'detalles_adicionales', 'direccion_completa',
            'fecha_creacion', 'fecha_actualizacion'
        ]
        read_only_fields = ['id', 'fecha_creacion', 'fecha_actualizacion']

# Import lazy para evitar circular imports
def get_marca_vehiculo_queryset():
    """Función lazy para obtener el queryset de MarcaVehiculo"""
    try:
        from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo
        return MarcaVehiculo.objects.all()
    except ImportError:
        # Si hay error de import circular, devolver queryset vacío temporalmente
        from django.db.models import QuerySet
        return QuerySet().none()

class UsuarioSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo Usuario
    """
    password = serializers.CharField(write_only=True, required=True, allow_blank=False, min_length=8)
    is_client = serializers.SerializerMethodField()
    foto_perfil_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Usuario
        fields = ('id', 'username', 'email', 'password', 'first_name', 'last_name', 
                  'es_mecanico', 'telefono', 'direccion', 'foto_perfil', 'foto_perfil_url', 'is_client')
        extra_kwargs = {
            'password': {'write_only': True},
            'username': {'required': True},
            'email': {'required': True}
        }
    
    def get_is_client(self, obj):
        """Determina si el usuario tiene un perfil de cliente"""
        return hasattr(obj, 'cliente')
    
    def get_foto_perfil_url(self, obj):
        """Retorna la URL completa de la foto de perfil usando cPanel si está configurado"""
        request = self.context.get('request')
        return get_image_url(obj.foto_perfil, request)
    
    def validate_password(self, value):
        """Validar que la contraseña tenga al menos 8 caracteres"""
        if not value:
            raise serializers.ValidationError("La contraseña es requerida")
        if len(value) < 8:
            raise serializers.ValidationError("La contraseña debe tener al menos 8 caracteres")
        return value
    
    def create(self, validated_data):
        logger.info(f"Creando usuario con datos: {validated_data}")
        password = validated_data.pop('password', None)
        if not password:
            raise serializers.ValidationError({"password": "La contraseña es requerida"})
        instance = self.Meta.model(**validated_data)
        instance.set_password(password)
        logger.info(f"Contraseña establecida para usuario: {validated_data.get('username', '')}")
        instance.save()
        return instance
    
    def update(self, instance, validated_data):
        logger.info(f"Actualizando usuario: {instance.username}")
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        if password is not None:
            instance.set_password(password)
            logger.info(f"Contraseña actualizada para usuario: {instance.username}")
        
        instance.save()
        return instance


class ClienteSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo Cliente
    """
    usuario = UsuarioSerializer(read_only=True)
    
    class Meta:
        model = Cliente
        fields = ('id', 'usuario', 'nombre', 'apellido', 'email', 'telefono', 
                  'fecha_registro', 'direccion', 'ubicacion')
        read_only_fields = ('fecha_registro',)
    
    def to_representation(self, instance):
        """
        Convierte la ubicación a formato GeoJSON para la respuesta API
        """
        ret = super().to_representation(instance)
        if instance.ubicacion:
            ret['ubicacion'] = {
                'type': 'Point',
                'coordinates': [instance.ubicacion.x, instance.ubicacion.y]
            }
        return ret
    
    def create(self, validated_data):
        usuario_data = validated_data.pop('usuario')
        usuario = Usuario.objects.create(**usuario_data)
        cliente = Cliente.objects.create(usuario=usuario, **validated_data)
        return cliente


class UserProfileSerializer(serializers.ModelSerializer):
    """
    Serializador para visualizar y actualizar la información del perfil de usuario.
    El modelo Usuario hereda de AbstractUser, por lo que first_name, last_name y email
    son campos directos del modelo, no necesitan 'source'.
    """
    # NOTA: first_name, last_name y email son campos directos de AbstractUser/Usuario
    # No usar source='usuario.xxx' porque el modelo ya es Usuario
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(read_only=True)  # Email es solo lectura para seguridad
    foto_perfil = serializers.ImageField(required=False)
    foto_perfil_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Usuario
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 
                  'telefono', 'direccion', 'foto_perfil', 'foto_perfil_url', 'es_mecanico']
        read_only_fields = ['id', 'username', 'email', 'es_mecanico']  # Email no editable
    
    def get_foto_perfil_url(self, obj):
        """Retorna la URL completa de la foto de perfil usando cPanel si está configurado"""
        request = self.context.get('request')
        return get_image_url(obj.foto_perfil, request)
        
    def update(self, instance, validated_data):
        """
        Actualizar perfil de usuario, guardando foto en cPanel si está configurado
        """
        from django.conf import settings
        
        # Extraer foto si existe
        foto_file = validated_data.pop('foto_perfil', None)
        
        # Actualizar campos del modelo Usuario directamente
        if 'first_name' in validated_data:
            instance.first_name = validated_data.get('first_name', instance.first_name)
            
        if 'last_name' in validated_data:
            instance.last_name = validated_data.get('last_name', instance.last_name)
            
        if 'telefono' in validated_data:
            instance.telefono = validated_data.get('telefono', instance.telefono)
        if 'direccion' in validated_data:
            instance.direccion = validated_data.get('direccion', instance.direccion)
        
        # Guardar foto usando el storage configurado (R2, S3, cPanel o local)
        if foto_file:
            from django.core.files.storage import default_storage
            import time
            try:
                filename = f"perfiles/profile_{instance.id}_{int(time.time() * 1000)}.{foto_file.name.split('.')[-1]}"
                saved_name = default_storage.save(filename, foto_file)
                instance.foto_perfil = saved_name
                logger.info(f"✅ Foto de perfil guardada en storage: {saved_name}")
            except Exception as e:
                logger.error(f"❌ Error guardando foto de perfil en storage: {e}")
                instance.foto_perfil = foto_file
            
        instance.save()
        return instance


class HorarioProveedorSerializer(serializers.ModelSerializer):
    """
    Serializer para el modelo HorarioProveedor
    """
    dia_nombre = serializers.CharField(source='get_dia_semana_display', read_only=True)
    proveedor_nombre = serializers.CharField(source='proveedor.nombre', read_only=True)
    tipo_proveedor = serializers.CharField(read_only=True)
    
    class Meta:
        model = HorarioProveedor
        fields = [
            'id', 'dia_semana', 'dia_nombre', 'activo', 
            'hora_inicio', 'hora_fin', 'duracion_slot', 'tiempo_descanso',
            'proveedor_nombre', 'tipo_proveedor'
        ]
    
    def validate(self, data):
        """Validaciones personalizadas"""
        if data.get('activo', True):
            hora_inicio = data.get('hora_inicio')
            hora_fin = data.get('hora_fin')
            
            if hora_inicio and hora_fin and hora_inicio >= hora_fin:
                raise serializers.ValidationError(
                    "La hora de inicio debe ser menor que la hora de fin"
                )
        
        return data


class ConfigurarSemanaCompletaSerializer(serializers.Serializer):
    """
    Serializer para configurar todos los horarios de la semana en una sola solicitud
    """
    DIAS_SEMANA_CHOICES = [
        (0, 'Lunes'),
        (1, 'Martes'),
        (2, 'Miércoles'),
        (3, 'Jueves'),
        (4, 'Viernes'),
        (5, 'Sábado'),
        (6, 'Domingo'),
    ]
    
    # Configuración global para todos los días
    hora_inicio_global = serializers.TimeField(
        default='08:00',
        help_text='Hora de inicio aplicable a todos los días habilitados'
    )
    hora_fin_global = serializers.TimeField(
        default='18:00',
        help_text='Hora de fin aplicable a todos los días habilitados'
    )
    duracion_slot_global = serializers.IntegerField(
        default=60,
        min_value=15,
        max_value=480,
        help_text='Duración en minutos de cada slot (aplicable a todos los días)'
    )
    tiempo_descanso_global = serializers.IntegerField(
        default=0,
        min_value=0,
        max_value=120,
        help_text='Tiempo de descanso en minutos entre slots (aplicable a todos los días)'
    )
    
    # Días habilitados (configuración simple)
    dias_habilitados = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6),
        default=[0, 1, 2, 3, 4],  # Lunes a Viernes por defecto
        help_text='Lista de días habilitados: 0=Lunes, 1=Martes, ..., 6=Domingo'
    )
    
    # Configuración avanzada por día (opcional)
    configuracion_por_dia = serializers.DictField(
        child=serializers.DictField(),
        required=False,
        help_text='Configuración específica por día. Formato: {dia: {hora_inicio, hora_fin, duracion_slot, tiempo_descanso}}'
    )
    
    # Opción para eliminar configuración existente
    eliminar_existente = serializers.BooleanField(
        default=True,
        help_text='Si eliminar horarios existentes antes de crear los nuevos'
    )
    
    def validate_configuracion_por_dia(self, value):
        """Validar configuración específica por día"""
        if not value:
            return value
        
        for dia, config in value.items():
            try:
                dia_num = int(dia)
                if dia_num < 0 or dia_num > 6:
                    raise serializers.ValidationError(f"Día {dia} inválido. Debe estar entre 0-6")
            except ValueError:
                raise serializers.ValidationError(f"Día {dia} debe ser un número")
            
            # Validar campos de configuración
            required_fields = ['hora_inicio', 'hora_fin']
            for field in required_fields:
                if field not in config:
                    raise serializers.ValidationError(f"Campo {field} requerido para el día {dia}")
            
            # Validar formato de horas
            try:
                from datetime import datetime
                hora_inicio = datetime.strptime(config['hora_inicio'], '%H:%M').time()
                hora_fin = datetime.strptime(config['hora_fin'], '%H:%M').time()
                
                if hora_inicio >= hora_fin:
                    raise serializers.ValidationError(f"Hora de inicio debe ser menor que hora de fin para el día {dia}")
            except ValueError:
                raise serializers.ValidationError(f"Formato de hora inválido para el día {dia}. Use HH:MM")
        
        return value
    
    def validate(self, data):
        """Validaciones globales"""
        # Validar horarios globales
        if data['hora_inicio_global'] >= data['hora_fin_global']:
            raise serializers.ValidationError(
                "La hora de inicio global debe ser menor que la hora de fin global"
            )
        
        # Validar días habilitados únicos
        dias_habilitados = data['dias_habilitados']
        if len(dias_habilitados) != len(set(dias_habilitados)):
            raise serializers.ValidationError("Los días habilitados no pueden repetirse")
        
        return data


class ConfigurarHorarioRapidoSerializer(serializers.Serializer):
    """
    Serializer para configuración rápida con presets
    """
    PRESETS_CHOICES = [
        ('taller_estandar', 'Taller Estándar (L-S 8:00-18:00, slots 60min)'),
        ('taller_extendido', 'Taller Extendido (L-S 7:00-20:00, slots 60min)'),
        ('mecanico_estandar', 'Mecánico Estándar (L-V 8:00-18:00, slots 120min)'),
        ('mecanico_24h', 'Mecánico 24H (L-D 0:00-23:59, slots 180min)'),
        ('personalizado', 'Personalizado'),
    ]
    
    preset = serializers.ChoiceField(
        choices=PRESETS_CHOICES,
        default='taller_estandar',
        help_text='Preset de configuración predefinida'
    )
    
    # Campos para preset personalizado
    dias_habilitados = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6),
        required=False,
        help_text='Solo para preset personalizado'
    )
    hora_inicio = serializers.TimeField(required=False)
    hora_fin = serializers.TimeField(required=False)
    duracion_slot = serializers.IntegerField(min_value=15, max_value=480, required=False)
    tiempo_descanso = serializers.IntegerField(min_value=0, max_value=120, required=False)
    
    def validate(self, data):
        """Validaciones"""
        if data['preset'] == 'personalizado':
            required_fields = ['dias_habilitados', 'hora_inicio', 'hora_fin', 'duracion_slot']
            for field in required_fields:
                if field not in data or data[field] is None:
                    raise serializers.ValidationError(f"Campo {field} requerido para preset personalizado")
            
            if data['hora_inicio'] >= data['hora_fin']:
                raise serializers.ValidationError("Hora de inicio debe ser menor que hora de fin")
        
        return data
    
    def get_configuracion(self):
        """Retorna la configuración basada en el preset seleccionado"""
        preset = self.validated_data['preset']
        
        presets = {
            'taller_estandar': {
                'dias_habilitados': [0, 1, 2, 3, 4, 5],  # L-S
                'hora_inicio': '08:00',
                'hora_fin': '18:00',
                'duracion_slot': 60,
                'tiempo_descanso': 0
            },
            'taller_extendido': {
                'dias_habilitados': [0, 1, 2, 3, 4, 5],  # L-S
                'hora_inicio': '07:00',
                'hora_fin': '20:00',
                'duracion_slot': 60,
                'tiempo_descanso': 15
            },
            'mecanico_estandar': {
                'dias_habilitados': [0, 1, 2, 3, 4],  # L-V
                'hora_inicio': '08:00',
                'hora_fin': '18:00',
                'duracion_slot': 120,
                'tiempo_descanso': 30
            },
            'mecanico_24h': {
                'dias_habilitados': [0, 1, 2, 3, 4, 5, 6],  # L-D
                'hora_inicio': '00:00',
                'hora_fin': '23:59',
                'duracion_slot': 180,
                'tiempo_descanso': 60
            }
        }
        
        if preset == 'personalizado':
            return {
                'dias_habilitados': self.validated_data['dias_habilitados'],
                'hora_inicio': self.validated_data['hora_inicio'].strftime('%H:%M'),
                'hora_fin': self.validated_data['hora_fin'].strftime('%H:%M'),
                'duracion_slot': self.validated_data['duracion_slot'],
                'tiempo_descanso': self.validated_data.get('tiempo_descanso', 0)
            }
        
        return presets[preset]


class PanelServiciosSerializerMixin:
    """Ofertas resumidas para cards del home (`include_panel_servicios` en query)."""

    def get_panel_servicios(self, obj):
        if not self.context.get('include_panel_servicios'):
            return []
        cached = getattr(obj, '_panel_servicios_cache', None)
        return cached if cached is not None else []


class TallerSerializer(PanelServiciosSerializerMixin, serializers.ModelSerializer):
    """
    Serializador para el modelo Taller
    """
    usuario = UsuarioSerializer(read_only=True)
    especialidades = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=CategoriaServicio.objects.all(),
        required=False
    )
    especialidades_nombres = serializers.SerializerMethodField()
    marcas_atendidas = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=get_marca_vehiculo_queryset(),
        required=False
    )
    marcas_atendidas_nombres = serializers.SerializerMethodField()
    estado_verificacion_display = serializers.SerializerMethodField()
    distance = serializers.SerializerMethodField()  # NUEVO: Campo para distancia
    servicios_completados = serializers.SerializerMethodField()  # NUEVO: Número de servicios completados
    comunas_atendidas = serializers.SerializerMethodField()  # NUEVO: Comunas de servicio del taller
    
    # NUEVO: Campos de conexión desde ConnectionStatus
    esta_conectado = serializers.SerializerMethodField()
    ultima_conexion = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    total_resenas = serializers.SerializerMethodField()
    
    # NUEVO: Campos para coordenadas (no se guardan en el modelo, solo para entrada)
    latitud = serializers.FloatField(write_only=True, required=False)
    longitud = serializers.FloatField(write_only=True, required=False)
    
    # NUEVO: Campo para dirección física del taller
    direccion_fisica = TallerDireccionSerializer(read_only=True)
    
    # NUEVO: URL de foto de perfil compatible con cPanel
    foto_perfil_url = serializers.SerializerMethodField()

    # Verificado para clientes: estado aprobado + documentos obligatorios validados en BD
    verificado = serializers.SerializerMethodField()
    kpi_badge = serializers.SerializerMethodField()
    panel_servicios = serializers.SerializerMethodField()
    # Misma media que `/usuarios/providers/<id>/reviews/` (modelo Review), no solo Resena en BD
    rating_average = serializers.SerializerMethodField()
    rating_reviews_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Taller
        fields = ('id', 'usuario', 'nombre', 'telefono', 'ubicacion',
                  'rut', 'capacidad_diaria', 'horario_atencion',
                  'especialidades', 'especialidades_nombres',
                  'marcas_atendidas', 'marcas_atendidas_nombres',
                  'descripcion', 'calificacion_promedio', 'rating_average', 'rating_reviews_count', 'numero_de_calificaciones', 'activo',
                  'foto_perfil', 'foto_perfil_url',  # NUEVO: foto de perfil
                  'estado_verificacion', 'estado_verificacion_display', 
                  'verificado', 'kpi_badge', 'onboarding_completado', 'onboarding_iniciado', 'fecha_verificacion',
                  'fecha_registro', 'ultima_actualizacion', 'distance',
                  'ultima_conexion', 'esta_conectado', 'status', 'total_resenas',
                  'servicios_completados', 'comunas_atendidas', 'experiencia_anos',
                  'latitud', 'longitud', 'direccion_fisica', 'panel_servicios')
        read_only_fields = ('fecha_registro', 'ultima_actualizacion', 'fecha_verificacion', 
                            'verificado', 'estado_verificacion', 'onboarding_completado', 'onboarding_iniciado',
                            'distance')
        extra_kwargs = {
            # Evita que ModelSerializer serialice el PointField antes de nuestro GeoJSON:
            # geometrías corruptas o errores GEOS rompían toda la respuesta (500 HTML).
            'ubicacion': {'required': False, 'write_only': True}
        }
    
    def get_foto_perfil_url(self, obj):
        """Retorna la URL completa de la foto de perfil usando cPanel si está configurado"""
        request = self.context.get('request')
        return get_image_url(obj.foto_perfil, request)

    def get_verificado(self, obj):
        from mecanimovilapp.apps.usuarios.verification_utils import proveedor_visible_como_verificado

        return proveedor_visible_como_verificado(obj)

    def get_kpi_badge(self, obj):
        """
        Etiqueta KPI visible a usuarios solo con suscripción mensual activa.
        Se computa en `retrieve` y en `cerca` (contexto include_kpi_badge).
        """
        include = bool(self.context.get('include_kpi_badge'))
        if not include:
            return None
        if not _proveedor_suscripcion_mensual_activa(obj.usuario):
            return None
        try:
            from mecanimovilapp.apps.usuarios.kpi_badge_utils import compute_kpi_badge_for_proveedor

            return compute_kpi_badge_for_proveedor(proveedor_usuario=obj.usuario, window_days=30)
        except Exception:
            return None

    def get_rating_average(self, obj):
        avg, _cnt = _cached_public_review_stats(self, 'taller', obj)
        return avg

    def get_rating_reviews_count(self, obj):
        _avg, cnt = _cached_public_review_stats(self, 'taller', obj)
        return cnt
    
    def get_especialidades_nombres(self, obj):
        """Devuelve los nombres de las especialidades"""
        return [esp.nombre for esp in obj.especialidades.all()]
    
    def get_marcas_atendidas_nombres(self, obj):
        """Devuelve los nombres de las marcas atendidas"""
        return [marca.nombre for marca in obj.marcas_atendidas.all()]
    
    def get_estado_verificacion_display(self, obj):
        """Devuelve el display name del estado de verificación"""
        return obj.get_estado_verificacion_display()
    
    def get_distance(self, obj):
        """
        Devuelve la distancia calculada por PostGIS si está disponible
        La distancia viene en metros, se convierte a kilómetros
        """
        if hasattr(obj, 'distance') and obj.distance is not None:
            # ✅ CORREGIDO: Manejar diferentes tipos de distancia
            try:
                if hasattr(obj.distance, 'km'):
                    # Si es un objeto Distance de Django con .km
                    return round(obj.distance.km, 2)
                elif hasattr(obj.distance, 'm'):
                    # Si es un objeto Distance de Django con .m
                    return round(obj.distance.m / 1000, 2)
                elif isinstance(obj.distance, (int, float)):
                    # Si es un número directo (ya en km)
                    return round(float(obj.distance), 2)
                else:
                    # Si es otro tipo, intentar convertir
                    return round(float(obj.distance) / 1000, 2)
            except (ValueError, TypeError, AttributeError) as e:
                print(f"⚠️ Error procesando distancia en serializer: {e}, distancia: {obj.distance}")
                return None
        return None
    
    def get_esta_conectado(self, obj):
        """
        Obtiene el estado de conexión desde ConnectionStatus.
        Sin registro de conexión: se asume disponible (no forzar “no disponible” en clientes).
        """
        try:
            if hasattr(obj, 'connection_status'):
                return obj.connection_status.esta_conectado
            
            from .models import ConnectionStatus
            conn_status = ConnectionStatus.objects.filter(taller=obj).first()
            if conn_status:
                return conn_status.esta_conectado
            return True
        except Exception:
            return True
    
    def get_ultima_conexion(self, obj):
        """
        Obtiene la última conexión desde ConnectionStatus
        """
        try:
            if hasattr(obj, 'connection_status'):
                return obj.connection_status.ultima_conexion

            from .models import ConnectionStatus
            conn_status = ConnectionStatus.objects.filter(taller=obj).first()
            if conn_status:
                return conn_status.ultima_conexion
            return None
        except Exception:
            return None

    def get_status(self, obj):
        """
        Obtiene el estado actual desde ConnectionStatus
        """
        try:
            if hasattr(obj, 'connection_status'):
                return obj.connection_status.status

            from .models import ConnectionStatus
            conn_status = ConnectionStatus.objects.filter(taller=obj).first()
            if conn_status:
                return conn_status.status
            return 'offline'
        except Exception:
            return 'offline'
    
    def get_total_resenas(self, obj):
        """
        Devuelve el total de reseñas como alias de numero_de_calificaciones
        """
        return obj.numero_de_calificaciones
    
    def get_servicios_completados(self, obj):
        """Retorna el número de servicios completados por el taller"""
        if hasattr(obj, 'servicios_completados_count'):
            return obj.servicios_completados_count
            
        try:
            from mecanimovilapp.apps.ordenes.models import SolicitudServicio
            return SolicitudServicio.objects.filter(
                taller=obj,
                estado='completado'
            ).count()
        except Exception:
            return 0
    
    def get_comunas_atendidas(self, obj):
        """Retorna las comunas atendidas del taller (desde direccion_fisica)"""
        try:
            if hasattr(obj, 'direccion_fisica') and obj.direccion_fisica:
                comuna = obj.direccion_fisica.comuna
                if comuna:
                    return [comuna]
            return []
        except Exception:
            return []
    
    def to_representation(self, instance):
        """
        Convierte la ubicación a formato GeoJSON para la respuesta API
        """
        ret = super().to_representation(instance)
        try:
            if instance.ubicacion:
                ret['ubicacion'] = {
                    'type': 'Point',
                    'coordinates': [instance.ubicacion.x, instance.ubicacion.y]
                }
            else:
                ret['ubicacion'] = None
        except Exception:
            ret['ubicacion'] = None
        return ret
    
    def update(self, instance, validated_data):
        """
        Actualiza la instancia del taller, manejando coordenadas especiales
        """
        # ✅ EXTRAER COORDENADAS ANTES DE ACTUALIZAR
        latitud = validated_data.pop('latitud', None)
        longitud = validated_data.pop('longitud', None)
        
        # ✅ VERIFICAR SI HUBO CAMBIO DE UBICACIÓN
        ubicacion_anterior = instance.ubicacion
        
        # ✅ ACTUALIZAR UBICACIÓN SI SE PROPORCIONAN COORDENADAS
        if latitud is not None and longitud is not None:
            try:
                from django.contrib.gis.geos import Point
                instance.ubicacion = Point(longitud, latitud, srid=4326)
                print(f"✅ Ubicación actualizada para taller {instance.nombre}: {latitud}, {longitud}")
            except Exception as e:
                print(f"❌ Error actualizando ubicación: {e}")
        
        # ✅ ACTUALIZAR OTROS CAMPOS
        instance_actualizada = super().update(instance, validated_data)
        
        # ✅ NOTIFICAR A CLIENTES SOBRE CAMBIO DE UBICACIÓN
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            import json
            
            # Verificar si hubo cambio de ubicación
            if ubicacion_anterior != instance.ubicacion:
                
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    "clientes",
                    {
                        'type': 'provider_location_update',
                        'proveedor_id': instance.id,
                        'tipo_proveedor': 'taller',
                        'nombre_proveedor': instance.nombre,
                        'nueva_ubicacion': {
                            'lat': instance.ubicacion.y if instance.ubicacion else None,
                            'lng': instance.ubicacion.x if instance.ubicacion else None
                        } if instance.ubicacion else None,
                        'timestamp': timezone.now().isoformat()
                    }
                )
                print(f"📢 Notificación enviada: Taller {instance.nombre} cambió de ubicación")
        except Exception as e:
            print(f"⚠️ No se pudo enviar notificación de cambio de ubicación: {e}")
        
        return instance_actualizada


class MecanicoDomicilioSerializer(PanelServiciosSerializerMixin, serializers.ModelSerializer):
    """
    Serializador para el modelo MecanicoDomicilio
    """
    usuario = UsuarioSerializer(read_only=True)
    especialidades = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=CategoriaServicio.objects.all(),
        required=False
    )
    especialidades_nombres = serializers.SerializerMethodField()
    marcas_atendidas = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=get_marca_vehiculo_queryset(),
        required=False
    )
    marcas_atendidas_nombres = serializers.SerializerMethodField()
    estado_verificacion_display = serializers.SerializerMethodField()
    distance = serializers.SerializerMethodField()  # NUEVO: Campo para distancia calculada por PostGIS
    zonas_servicio = serializers.SerializerMethodField()  # NUEVO: Información de zonas de servicio
    servicios_completados = serializers.SerializerMethodField()  # NUEVO: Número de servicios completados
    
    # NUEVO: Campos de conexión desde ConnectionStatus
    esta_conectado = serializers.SerializerMethodField()
    ultima_conexion = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    total_resenas = serializers.SerializerMethodField()
    
    # NUEVO: Campos para coordenadas (no se guardan en el modelo, solo para entrada)
    latitud = serializers.FloatField(write_only=True, required=False)
    longitud = serializers.FloatField(write_only=True, required=False)
    
    # NUEVO: Campo para dirección legible basada en zonas de servicio
    direccion = serializers.SerializerMethodField()
    
    # NUEVO: URL de foto de perfil compatible con cPanel
    foto_perfil_url = serializers.SerializerMethodField()

    verificado = serializers.SerializerMethodField()
    kpi_badge = serializers.SerializerMethodField()
    panel_servicios = serializers.SerializerMethodField()
    rating_average = serializers.SerializerMethodField()
    rating_reviews_count = serializers.SerializerMethodField()
    
    class Meta:
        model = MecanicoDomicilio
        fields = ('id', 'usuario', 'nombre', 'telefono', 'ubicacion', 'disponible', 
                  'especialidades', 'especialidades_nombres', 
                  'marcas_atendidas', 'marcas_atendidas_nombres',
                  'disponibilidad', 'foto_perfil', 'foto_perfil_url', 'distance',
                  'radio_cobertura', 'calificacion_promedio', 'rating_average', 'rating_reviews_count', 'numero_de_calificaciones', 'activo',
                  'descripcion', 'dni', 'experiencia_anos',
                  'estado_verificacion', 'estado_verificacion_display', 
                  'verificado', 'kpi_badge', 'onboarding_completado', 'onboarding_iniciado', 'fecha_verificacion',
                  'fecha_registro', 'ultima_actualizacion', 'zonas_servicio',
                  'ultima_conexion', 'esta_conectado', 'status', 'total_resenas',
                  'servicios_completados',
                  'latitud', 'longitud', 'direccion', 'panel_servicios')
        read_only_fields = ('fecha_registro', 'ultima_actualizacion', 'fecha_verificacion', 
                            'verificado', 'estado_verificacion', 'onboarding_completado', 'onboarding_iniciado')
        extra_kwargs = {
            'ubicacion': {'required': False, 'write_only': True}
        }
    
    def get_foto_perfil_url(self, obj):
        """Retorna la URL completa de la foto de perfil usando cPanel si está configurado"""
        request = self.context.get('request')
        return get_image_url(obj.foto_perfil, request)

    def get_verificado(self, obj):
        from mecanimovilapp.apps.usuarios.verification_utils import proveedor_visible_como_verificado

        return proveedor_visible_como_verificado(obj)

    def get_kpi_badge(self, obj):
        """Ver `TallerSerializer.get_kpi_badge`."""
        include = bool(self.context.get('include_kpi_badge'))
        if not include:
            return None
        if not _proveedor_suscripcion_mensual_activa(obj.usuario):
            return None
        try:
            from mecanimovilapp.apps.usuarios.kpi_badge_utils import compute_kpi_badge_for_proveedor

            return compute_kpi_badge_for_proveedor(proveedor_usuario=obj.usuario, window_days=30)
        except Exception:
            return None

    def get_rating_average(self, obj):
        avg, _cnt = _cached_public_review_stats(self, 'mecanico', obj)
        return avg

    def get_rating_reviews_count(self, obj):
        _avg, cnt = _cached_public_review_stats(self, 'mecanico', obj)
        return cnt
    
    def get_especialidades_nombres(self, obj):
        """Devuelve los nombres de las especialidades"""
        return [esp.nombre for esp in obj.especialidades.all()]
    
    def get_marcas_atendidas_nombres(self, obj):
        """Devuelve los nombres de las marcas atendidas"""
        return [marca.nombre for marca in obj.marcas_atendidas.all()]
    
    def get_estado_verificacion_display(self, obj):
        """Devuelve el display name del estado de verificación"""
        return obj.get_estado_verificacion_display()
    
    def get_distance(self, obj):
        """
        Devuelve la distancia calculada por PostGIS en kilómetros
        """
        if hasattr(obj, 'distance') and obj.distance is not None:
            # ✅ CORREGIDO: Manejar diferentes tipos de distancia
            try:
                if hasattr(obj.distance, 'km'):
                    # Si es un objeto Distance de Django con .km
                    return round(obj.distance.km, 2)
                elif hasattr(obj.distance, 'm'):
                    # Si es un objeto Distance de Django con .m
                    return round(obj.distance.m / 1000, 2)
                elif isinstance(obj.distance, (int, float)):
                    # Si es un número directo (ya en km)
                    return round(float(obj.distance), 2)
                else:
                    # Si es otro tipo, intentar convertir
                    return round(float(obj.distance) / 1000, 2)
            except (ValueError, TypeError, AttributeError) as e:
                print(f"⚠️ Error procesando distancia en serializer de mecánico: {e}, distancia: {obj.distance}")
                return None
        return None
    
    def get_zonas_servicio(self, obj):
        """
        Devuelve información sobre las zonas de servicio del mecánico
        """
        try:
            # **OPTIMIZACIÓN**: Usar prefetch si está disponible
            if hasattr(obj, '_prefetched_objects_cache') and 'service_areas' in obj._prefetched_objects_cache:
                zonas = [z for z in obj.service_areas.all() if z.is_active]
            else:
                zonas = MechanicServiceArea.objects.filter(
                    mechanic=obj,
                    is_active=True
                )
            
            zonas_info = []
            for zona in zonas:
                zonas_info.append({
                    'id': zona.id,
                    'nombre': zona.name,
                    'comunas': zona.commune_names,
                    'total_comunas': len(zona.commune_names) if zona.commune_names else 0,
                    'activa': zona.is_active
                })
            
            return zonas_info
        except Exception as e:
            print(f"Error obteniendo zonas de servicio: {e}")
            return []
    
    def get_esta_conectado(self, obj):
        """
        Obtiene el estado de conexión desde ConnectionStatus.
        Sin registro de conexión: se asume disponible (no forzar “no disponible” en clientes).
        """
        try:
            # **OPTIMIZACIÓN**: Intentar usar relación inversa pre-cargada
            # Validar si connection_status está en la caché de prefetch o si ya fue cargado por select_related
            # Nota: para OneToOne invertido, si usamos select_related('connection_status') desde Mecanico,
            # el atributo connection_status debería estar disponible directamente.
            
            # Si se usó select_related (en MecanicoDomicilio -> ConnectionStatus)
            if hasattr(obj, 'connection_status'):
                return obj.connection_status.esta_conectado
                
            # Si se usó prefetch_related, Django lo cachea en _prefetched_objects_cache
            # pero para relaciones inversa 1-1 es más complejo.
            # Sin embargo, proveedores_filtrados usa prefetch_related('connection_status').
            # En ese caso, Django asigna el objeto a la instancia si coincide.
            
            return True
        except Exception as e:
            # print(f"Error obteniendo estado de conexión: {e}")
            return True
    
    def get_ultima_conexion(self, obj):
        """
        Obtiene la última conexión desde ConnectionStatus
        """
        try:
            # **OPTIMIZACIÓN**: Intentar usar relación inversa pre-cargada
            if hasattr(obj, 'connection_status'):
                return obj.connection_status.ultima_conexion
                
            return None
        except Exception as e:
            # print(f"Error obteniendo última conexión: {e}")
            return None

    def get_status(self, obj):
        """
        Obtiene el estado actual desde ConnectionStatus
        """
        try:
            # **OPTIMIZACIÓN**: Intentar usar relación inversa pre-cargada
            if hasattr(obj, 'connection_status'):
                return obj.connection_status.status
                
            return 'offline'
        except Exception as e:
            # print(f"Error obteniendo estado actual: {e}")
            return 'offline'
    
    def get_total_resenas(self, obj):
        """
        Devuelve el total de reseñas como alias de numero_de_calificaciones
        """
        return obj.numero_de_calificaciones
    
    def get_servicios_completados(self, obj):
        """Retorna el número de servicios completados por el mecánico"""
        if hasattr(obj, 'servicios_completados_count'):
            return obj.servicios_completados_count
            
        try:
            from mecanimovilapp.apps.ordenes.models import SolicitudServicio
            return SolicitudServicio.objects.filter(
                mecanico=obj,
                estado='completado'
            ).count()
        except Exception:
            return 0
    
    def get_direccion(self, obj):
        """
        Genera una dirección legible basada en las zonas de servicio del mecánico
        En lugar de mostrar coordenadas, muestra las comunas donde presta servicios
        """
        try:
            # Obtener las zonas de servicio activas
            # OPTIMIZACIÓN: Usar prefetch si está disponible
            if hasattr(obj, '_prefetched_objects_cache') and 'service_areas' in obj._prefetched_objects_cache:
                zonas = [z for z in obj.service_areas.all() if z.is_active]
            else:
                zonas = list(MechanicServiceArea.objects.filter(
                    mechanic=obj,
                    is_active=True
                ))
            
            if zonas:
                # Obtener todas las comunas de todas las zonas
                todas_comunas = []
                for zona in zonas:
                    if zona.commune_names:
                        todas_comunas.extend(zona.commune_names)
                
                # Eliminar duplicados y limitar
                comunas_unicas = list(set(todas_comunas))
                
                if len(comunas_unicas) == 1:
                    return f"Servicio en {comunas_unicas[0]}"
                elif len(comunas_unicas) <= 3:
                    return f"Servicio en {', '.join(comunas_unicas)}"
                else:
                    # Mostrar las primeras 3 y agregar "y X más"
                    primeras_tres = comunas_unicas[:3]
                    restantes = len(comunas_unicas) - 3
                    return f"Servicio en {', '.join(primeras_tres)} y {restantes} más"
            
            # Fallback: si no hay zonas configuradas
            return "Servicio a domicilio"
            
        except Exception as e:
            print(f"Error generando dirección para mecánico {obj.id}: {e}")
            return "Servicio a domicilio"
    
    def to_representation(self, instance):
        """
        Convierte la ubicación a formato GeoJSON para la respuesta API
        """
        ret = super().to_representation(instance)
        try:
            if instance.ubicacion:
                ret['ubicacion'] = {
                    'type': 'Point',
                    'coordinates': [instance.ubicacion.x, instance.ubicacion.y]
                }
            else:
                ret['ubicacion'] = None
        except Exception:
            ret['ubicacion'] = None
        return ret
    
    def create(self, validated_data):
        from django.contrib.gis.geos import Point
        
        # Extraer usuario si se proporciona en la solicitud
        usuario_id = self.context['request'].data.get('usuario_id') if 'request' in self.context else None
        usuario = None
        
        if usuario_id:
            try:
                from django.contrib.auth import get_user_model
                Usuario = get_user_model()
                usuario = Usuario.objects.get(id=usuario_id)
            except Usuario.DoesNotExist:
                raise serializers.ValidationError("Usuario no encontrado")
        
        # Si no se proporciona ubicación, crear una ubicación por defecto
        if 'ubicacion' not in validated_data:
            # Coordenadas por defecto para Santiago, Chile (-33.4489, -70.6693)
            validated_data['ubicacion'] = Point(-70.6693, -33.4489)
        
        # Extraer especialidades y marcas si se proporcionan
        especialidades = validated_data.pop('especialidades', [])
        marcas_atendidas = validated_data.pop('marcas_atendidas', [])
        
        # Crear mecánico a domicilio
        mecanico = MecanicoDomicilio.objects.create(usuario=usuario, **validated_data)
        
        # Asignar especialidades y marcas
        for especialidad in especialidades:
            mecanico.especialidades.add(especialidad)
        
        for marca in marcas_atendidas:
            mecanico.marcas_atendidas.add(marca)
        
        return mecanico
    
    def update(self, instance, validated_data):
        """
        Actualiza la instancia del mecánico, manejando coordenadas especiales
        """
        # ✅ EXTRAER COORDENADAS ANTES DE ACTUALIZAR
        latitud = validated_data.pop('latitud', None)
        longitud = validated_data.pop('longitud', None)
        
        # ✅ VERIFICAR SI HUBO CAMBIO DE UBICACIÓN
        ubicacion_anterior = instance.ubicacion
        
        # ✅ ACTUALIZAR UBICACIÓN SI SE PROPORCIONAN COORDENADAS
        if latitud is not None and longitud is not None:
            try:
                from django.contrib.gis.geos import Point
                instance.ubicacion = Point(longitud, latitud, srid=4326)
                print(f"✅ Ubicación actualizada para mecánico {instance.nombre}: {latitud}, {longitud}")
            except Exception as e:
                print(f"❌ Error actualizando ubicación: {e}")
        
        # ✅ ACTUALIZAR OTROS CAMPOS
        instance_actualizada = super().update(instance, validated_data)
        
        # ✅ NOTIFICAR A CLIENTES SOBRE CAMBIO DE UBICACIÓN
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            import json
            
            # Verificar si hubo cambio de ubicación
            if ubicacion_anterior != instance.ubicacion:
                
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    "clientes",
                    {
                        'type': 'provider_location_update',
                        'proveedor_id': instance.id,
                        'tipo_proveedor': 'mecanico',
                        'nombre_proveedor': instance.nombre,
                        'nueva_ubicacion': {
                            'lat': instance.ubicacion.y if instance.ubicacion else None,
                            'lng': instance.ubicacion.x if instance.ubicacion else None
                        } if instance.ubicacion else None,
                        'timestamp': timezone.now().isoformat()
                    }
                )
                print(f"📢 Notificación enviada: Mecánico {instance.nombre} cambió de ubicación")
        except Exception as e:
            print(f"⚠️ No se pudo enviar notificación de cambio de ubicación: {e}")
        
        return instance_actualizada


class ZonaCoberturaSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo ZonaCobertura
    """
    class Meta:
        model = ZonaCobertura
        fields = ('id', 'mecanico', 'poligono_cobertura')
    
    def to_representation(self, instance):
        """
        Convierte el polígono a formato GeoJSON para la respuesta API
        """
        ret = super().to_representation(instance)
        if instance.poligono_cobertura:
            coords = []
            for point in instance.poligono_cobertura[0]:
                coords.append([point[0], point[1]])
            
            ret['poligono_cobertura'] = {
                'type': 'Polygon',
                'coordinates': [coords]
            }
        return ret


        return data

    def get_service_context(self, obj):
        """Retorna información contextual del servicio realizado"""
        if obj.solicitud:
            return {
                'service_name': obj.solicitud.servicio.nombre if hasattr(obj.solicitud, 'servicio') and obj.solicitud.servicio else 'Servicio General',
                'vehicle_model': f"{obj.solicitud.vehiculo.marca.nombre} {obj.solicitud.vehiculo.modelo.nombre}" if obj.solicitud.vehiculo else 'Vehículo no especificado',
                'date': obj.solicitud.fecha_servicio
            }
        return None

    def get_photos(self, obj):
        """Retorna lista de URLs de fotos adjuntas"""
        request = self.context.get('request')
        photos = []
        for foto_obj in obj.fotos.all():
            if foto_obj.foto:
                photos.append(get_image_url(foto_obj.foto, request))
        return photos


class ResenaSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo Resena
    """
    cliente_nombre = serializers.SerializerMethodField()
    cliente_avatar = serializers.SerializerMethodField()
    service_context = serializers.SerializerMethodField()
    photos = serializers.SerializerMethodField()
    
    class Meta:
        model = Resena
        fields = ('id', 'cliente', 'cliente_nombre', 'cliente_avatar', 'comentario', 'calificacion', 
                  'fecha_hora_resena', 'taller', 'mecanico', 'solicitud',
                  # Aspectos estructurados (KPIs)
                  'puntualidad', 'recepcion_a_tiempo', 'limpieza_auto', 'zona_limpia',
                  'claridad_explicacion', 'informacion_relevante', 'trato', 'entrego_repuestos',
                  'service_context', 'photos')
        read_only_fields = ('fecha_hora_resena',)
    
    def get_cliente_nombre(self, obj):
        # Intentar obtener nombre completo, o usar username si no hay nombre
        full_name = f"{obj.cliente.nombre} {obj.cliente.apellido}".strip()
        return full_name if full_name else obj.cliente.usuario.username
        
    def get_cliente_avatar(self, obj):
        request = self.context.get('request')
        if obj.cliente.usuario.foto_perfil:
             return get_image_url(obj.cliente.usuario.foto_perfil, request)
        return None
    
    def get_service_context(self, obj):
        """Retorna información contextual del servicio realizado"""
        if obj.solicitud:
            # Intentar obtener el nombre del servicio desde diferentes fuentes posibles en SolicitudServicio
            service_name = 'Servicio realizado'
            
            # Si SolicitudServicio tiene relación directa con Servicio (oferta->servicio)
            # Nota: SolicitudServicio no tiene campo 'servicio' directo en el modelo mostrado anteriormente, 
            # pero asumiremos que podemos inferirlo o que el modelo lo tiene. 
            # Si no, usamos un genérico.
            
            # Verificamos si podemos obtener el vehículo
            vehicle_info = 'Vehículo'
            if obj.solicitud.vehiculo:
                 vehicle_info = f"{obj.solicitud.vehiculo.marca.nombre} {obj.solicitud.vehiculo.modelo.nombre}"
            
            return {
                'service_name': service_name, 
                'vehicle_model': vehicle_info,
                'date': obj.solicitud.fecha_servicio
            }
        return None

    def get_photos(self, obj):
        """Retorna lista de URLs de fotos adjuntas"""
        request = self.context.get('request')
        photos = []
        if hasattr(obj, 'fotos'):
            for foto_obj in obj.fotos.all():
                if foto_obj.foto:
                    photos.append(get_image_url(foto_obj.foto, request))
        return photos
        
    def validate(self, data):
        """
        Validar que se proporcione al menos un taller o mecánico, pero no ambos
        """
        taller = data.get('taller')
        mecanico = data.get('mecanico')
        
        if not taller and not mecanico:
            raise serializers.ValidationError(
                "Debe proporcionar un taller o un mecánico para la reseña."
            )
        
        if taller and mecanico:
            raise serializers.ValidationError(
                "No puede proporcionar tanto un taller como un mecánico para la misma reseña."
            )
        
        return data 


class DireccionUsuarioSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo DireccionUsuario
    """
    usuario_username = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = DireccionUsuario
        fields = ('id', 'usuario', 'usuario_username', 'direccion', 'etiqueta', 'detalles', 
                  'es_principal', 'fecha_creacion', 'fecha_actualizacion', 'ubicacion')
        read_only_fields = ('fecha_creacion', 'fecha_actualizacion')
        extra_kwargs = {
            'usuario': {'required': False}  # El usuario no es requerido en el input
        }
    
    def get_usuario_username(self, obj):
        """
        Obtener el nombre de usuario
        """
        return obj.usuario.username if obj.usuario else None
    
    def to_representation(self, instance):
        """
        Convierte la ubicación a formato GeoJSON para la respuesta API
        """
        ret = super().to_representation(instance)
        if instance.ubicacion:
            ret['ubicacion'] = {
                'type': 'Point',
                'coordinates': [instance.ubicacion.x, instance.ubicacion.y]
            }
        return ret
    
    def create(self, validated_data):
        # Verificar si hay coordenadas en los datos
        latitude = self.context['request'].data.get('latitude')
        longitude = self.context['request'].data.get('longitude')
        
        if latitude and longitude:
            # Crear punto con las coordenadas proporcionadas
            validated_data['ubicacion'] = Point(float(longitude), float(latitude))
        
        # Si no se proporciona usuario, usar el de la solicitud
        if 'usuario' not in validated_data and 'request' in self.context:
            validated_data['usuario'] = self.context['request'].user
        
        # Crear la dirección
        direccion = DireccionUsuario.objects.create(**validated_data)
        return direccion
    
    def update(self, instance, validated_data):
        # Verificar si hay coordenadas en los datos
        latitude = self.context['request'].data.get('latitude')
        longitude = self.context['request'].data.get('longitude')
        
        if latitude and longitude:
            # Actualizar punto con las coordenadas proporcionadas
            instance.ubicacion = Point(float(longitude), float(latitude))
        
        # Actualizar otros campos
        instance.direccion = validated_data.get('direccion', instance.direccion)
        instance.etiqueta = validated_data.get('etiqueta', instance.etiqueta)
        instance.detalles = validated_data.get('detalles', instance.detalles)
        instance.es_principal = validated_data.get('es_principal', instance.es_principal)
        
        instance.save()
        return instance 


class DocumentoOnboardingSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo DocumentoOnboarding
    """
    proveedor_nombre = serializers.SerializerMethodField()
    tipo_documento_display = serializers.SerializerMethodField()
    archivo_url = serializers.SerializerMethodField()
    
    class Meta:
        model = DocumentoOnboarding
        fields = ('id', 'taller', 'mecanico', 'tipo_documento', 'tipo_documento_display', 
                  'archivo', 'archivo_url', 'nombre_original', 'fecha_subida', 
                  'verificado', 'comentarios_verificacion', 'proveedor_nombre')
        read_only_fields = ('fecha_subida',)
    
    def get_proveedor_nombre(self, obj):
        """Devuelve el nombre del proveedor (taller o mecánico)"""
        if obj.taller:
            return f"Taller: {obj.taller.nombre}"
        elif obj.mecanico:
            return f"Mecánico: {obj.mecanico.nombre}"
        return "No especificado"
    
    def get_tipo_documento_display(self, obj):
        """Devuelve el display name del tipo de documento"""
        return obj.get_tipo_documento_display()
    
    def get_archivo_url(self, obj):
        """Devuelve la URL completa del archivo usando cPanel si está configurado"""
        request = self.context.get('request')
        return get_image_url(obj.archivo, request)
    
    def validate(self, data):
        """Validar que se especifique un taller o mecánico, pero no ambos"""
        taller = data.get('taller')
        mecanico = data.get('mecanico')
        
        if not taller and not mecanico:
            raise serializers.ValidationError("Debe especificar un taller o mecánico.")
        
        if taller and mecanico:
            raise serializers.ValidationError("No puede especificar tanto taller como mecánico.")
        
        return data 


# NUEVO: Serializers para Zonas de Servicio
class ChileanCommuneSerializer(serializers.ModelSerializer):
    """Serializer para las comunas chilenas (maestro)"""
    
    class Meta:
        model = ChileanCommune
        fields = [
            'code',
            'name', 
            'region_code',
            'region_name',
            'province_name'
        ]


class MechanicServiceAreaSerializer(serializers.ModelSerializer):
    """Serializer para las zonas de servicio de mecánicos"""
    
    commune_count = serializers.SerializerMethodField()
    
    class Meta:
        model = MechanicServiceArea
        fields = [
            'id',
            'area_type',
            'name',
            'commune_names',
            'commune_count',
            'is_active',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'commune_count']
    
    def get_commune_count(self, obj):
        """Retorna el número de comunas en la zona"""
        return obj.get_commune_count()
    
    def validate_commune_names(self, value):
        """Validación personalizada para commune_names"""
        if not isinstance(value, list):
            raise serializers.ValidationError("Las comunas deben ser una lista.")
        
        if len(value) == 0:
            raise serializers.ValidationError("Debe seleccionar al menos una comuna.")
        
        if len(value) > 50:
            raise serializers.ValidationError("No puede seleccionar más de 50 comunas.")
        
        # Validar que todas las comunas sean strings válidos
        for i, commune in enumerate(value):
            if not isinstance(commune, str):
                raise serializers.ValidationError(f"La comuna en posición {i+1} debe ser texto.")
            
            if len(commune.strip()) < 2:
                raise serializers.ValidationError(f"La comuna '{commune}' es demasiado corta.")
            
            if len(commune.strip()) > 100:
                raise serializers.ValidationError(f"La comuna '{commune}' es demasiado larga.")
        
        # Opcional: Validar que las comunas existan en el maestro
        if hasattr(self, 'context') and self.context.get('validate_communes', True):
            invalid_communes = []
            existing_communes = set(
                ChileanCommune.objects.filter(is_active=True).values_list('name', flat=True)
            )
            
            for commune in value:
                commune_clean = commune.strip()
                # Búsqueda case-insensitive
                if not any(
                    existing.lower() == commune_clean.lower() 
                    for existing in existing_communes
                ):
                    invalid_communes.append(commune_clean)
            
            if invalid_communes:
                raise serializers.ValidationError(
                    f"Las siguientes comunas no son válidas: {', '.join(invalid_communes)}. "
                    "Por favor, seleccione comunas de la lista oficial."
                )
        
        return value
    
    def validate_area_type(self, value):
        """Validar que solo sea tipo COMMUNE"""
        if value != 'COMMUNE':
            raise serializers.ValidationError("Solo se permiten zonas de tipo COMMUNE.")
        return value
    
    def validate_name(self, value):
        """Validar el nombre de la zona (opcional)"""
        if value and len(value.strip()) < 3:
            raise serializers.ValidationError("El nombre debe tener al menos 3 caracteres.")
        return value.strip() if value else value


class MechanicServiceAreaCreateSerializer(MechanicServiceAreaSerializer):
    """Serializer específico para crear zonas de servicio"""
    
    def create(self, validated_data):
        """Crear zona de servicio asociada al mecánico autenticado"""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            raise serializers.ValidationError("Usuario no autenticado.")
        
        try:
            mechanic = MecanicoDomicilio.objects.get(usuario=request.user)
        except MecanicoDomicilio.DoesNotExist:
            raise serializers.ValidationError("Usuario no es un mecánico a domicilio.")
        
        validated_data['mechanic'] = mechanic
        return super().create(validated_data)


class MechanicServiceAreaUpdateSerializer(MechanicServiceAreaSerializer):
    """Serializer específico para actualizar zonas de servicio"""
    
    def update(self, instance, validated_data):
        """Actualizar zona de servicio"""
        # Verificar que el mecánico autenticado sea el propietario
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            try:
                mechanic = MecanicoDomicilio.objects.get(usuario=request.user)
                if instance.mechanic != mechanic:
                    raise serializers.ValidationError("No tiene permisos para modificar esta zona.")
            except MecanicoDomicilio.DoesNotExist:
                raise serializers.ValidationError("Usuario no es un mecánico a domicilio.")
        
        return super().update(instance, validated_data) 


class ReviewSerializer(serializers.ModelSerializer):
    """Serializer para las reseñas de clientes a proveedores"""
    client_info = serializers.SerializerMethodField()
    car_info = serializers.SerializerMethodField()
    service_info = serializers.SerializerMethodField()
    created_at_formatted = serializers.SerializerMethodField()
    provider_name = serializers.SerializerMethodField()
    
    # Alias para compatibilidad con el frontend
    cliente_nombre = serializers.SerializerMethodField()
    cliente_avatar = serializers.SerializerMethodField()
    calificacion = serializers.ReadOnlyField(source='rating')
    comentario = serializers.ReadOnlyField(source='comment')
    fecha_hora_resena = serializers.SerializerMethodField()
    service_context = serializers.SerializerMethodField()
    
    class Meta:
        model = Review
        fields = [
            'id', 'client', 'provider_type', 'provider_id', 'service_order',
            'rating', 'comment', 'created_at', 'updated_at',
            'client_info', 'car_info', 'service_info', 'created_at_formatted', 'provider_name',
            'cliente_nombre', 'cliente_avatar', 'calificacion', 'comentario', 'fecha_hora_resena', 'service_context'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_cliente_nombre(self, obj):
        """Nombre completo del cliente para el frontend"""
        return f"{obj.client.first_name} {obj.client.last_name}".strip() or obj.client.username

    def get_cliente_avatar(self, obj):
        """URL de la foto de perfil del cliente"""
        info = self.get_client_info(obj)
        return info.get('profile_photo')

    def get_fecha_hora_resena(self, obj):
        """Alias para created_at_formatted"""
        return self.get_created_at_formatted(obj)

    def get_service_context(self, obj):
        """Contexto del servicio para el frontend (nombre de servicio y modelo de auto)"""
        car = self.get_car_info(obj)
        service = self.get_service_info(obj)
        return {
            'service_name': service.get('name', 'Servicio'),
            'vehicle_model': car.get('full_name', 'N/A')
        }
    
    def get_client_info(self, obj):
        """Información del cliente que hizo la reseña"""
        try:
            # Obtener la URL completa de la foto de perfil usando el helper centralizado
            profile_photo_url = get_image_url(obj.client.foto_perfil) if obj.client.foto_perfil else None
            
            return {
                'username': obj.client.username,
                'first_name': obj.client.first_name,
                'last_name': obj.client.last_name,
                'full_name': f"{obj.client.first_name} {obj.client.last_name}".strip() or obj.client.username,
                'profile_photo': profile_photo_url
            }
        except Exception as e:
            logger.error(f"Error obteniendo información del cliente: {e}")
            return {
                'username': obj.client.username if obj.client else 'N/A',
                'first_name': obj.client.first_name if obj.client else '',
                'last_name': obj.client.last_name if obj.client else '',
                'full_name': obj.client.username if obj.client else 'N/A',
                'profile_photo': None
            }
    
    def get_car_info(self, obj):
        """Información del auto del cliente - SOLO MARCA Y MODELO, SIN PATENTE"""
        try:
            # Acceder a través de la relación service_order -> vehiculo
            if hasattr(obj.service_order, 'vehiculo') and obj.service_order.vehiculo:
                vehiculo = obj.service_order.vehiculo
                return {
                    'brand': vehiculo.marca.nombre if vehiculo.marca else 'N/A',
                    'model': vehiculo.modelo.nombre if vehiculo.modelo else 'N/A',
                    'full_name': f"{vehiculo.marca.nombre} {vehiculo.modelo.nombre}" if vehiculo.marca and vehiculo.modelo else 'N/A',
                    'year': vehiculo.ano if hasattr(vehiculo, 'ano') else 'N/A'
                    # ELIMINADO: 'plate' - no mostrar patente
                }
        except Exception as e:
            logger.error(f"Error obteniendo información del vehículo: {e}")
        return {
            'brand': 'N/A',
            'model': 'N/A',
            'full_name': 'N/A',
            'year': 'N/A'
            # ELIMINADO: 'plate'
        }
    
    def get_service_info(self, obj):
        """Información del servicio realizado"""
        try:
            # Intentar obtener el servicio desde las líneas de la orden
            if hasattr(obj.service_order, 'lineas') and obj.service_order.lineas.exists():
                # Obtener el primer servicio de las líneas
                linea = obj.service_order.lineas.first()
                if linea and linea.oferta_servicio and linea.oferta_servicio.servicio:
                    servicio = linea.oferta_servicio.servicio
                    # Obtener la primera categoría (si existe)
                    categoria_nombre = 'N/A'
                    if hasattr(servicio, 'categorias') and servicio.categorias.exists():
                        primera_categoria = servicio.categorias.first()
                        categoria_nombre = primera_categoria.nombre if primera_categoria else 'N/A'
                    
                    return {
                        'name': servicio.nombre if hasattr(servicio, 'nombre') else 'N/A',
                        'description': servicio.descripcion if hasattr(servicio, 'descripcion') else 'N/A',
                        'category': categoria_nombre
                    }
            
            # Fallback: intentar obtener desde service_order.servicio
            if hasattr(obj.service_order, 'servicio') and obj.service_order.servicio:
                servicio = obj.service_order.servicio
                # Obtener la primera categoría (si existe)
                categoria_nombre = 'N/A'
                if hasattr(servicio, 'categorias') and servicio.categorias.exists():
                    primera_categoria = servicio.categorias.first()
                    categoria_nombre = primera_categoria.nombre if primera_categoria else 'N/A'
                
                return {
                    'name': servicio.nombre if hasattr(servicio, 'nombre') else 'N/A',
                    'description': servicio.descripcion if hasattr(servicio, 'descripcion') else 'N/A',
                    'category': categoria_nombre
                }
        except Exception as e:
            logger.error(f"Error obteniendo información del servicio: {e}")
        return {
            'name': 'N/A',
            'description': 'N/A',
            'category': 'N/A'
        }
    
    def get_created_at_formatted(self, obj):
        """Fecha formateada para mostrar"""
        from django.utils import timezone
        from datetime import datetime
        
        if obj.created_at:
            # Formato: "15 de enero, 2024"
            return obj.created_at.strftime("%d de %B, %Y")
        return ""
    
    def get_provider_name(self, obj):
        """Nombre del proveedor"""
        return obj.get_provider_name()


class ProviderProfileSerializer(serializers.ModelSerializer):
    """Serializer para perfiles de proveedores con estadísticas de reseñas"""
    average_rating = serializers.DecimalField(max_digits=3, decimal_places=2, read_only=True)
    review_count = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = ProviderProfile
        fields = [
            'id', 'nombre', 'telefono', 'direccion', 'foto_perfil', 'descripcion',
            'average_rating', 'review_count'
        ]
    
    def to_representation(self, instance):
        """Personalizar la representación para incluir estadísticas actualizadas"""
        data = super().to_representation(instance)
        
        # Asegurar que las estadísticas estén actualizadas
        stats = instance.reviews.aggregate(
            avg_rating=Avg('rating'),
            total_reviews=Count('id')
        )
        
        data['average_rating'] = float(stats['avg_rating'] or 0.00)
        data['review_count'] = stats['total_reviews'] or 0
        
        return data


class ConnectionStatusSerializer(serializers.ModelSerializer):
    """Serializer para el estado de conexión de proveedores"""
    
    class Meta:
        model = ConnectionStatus
        fields = [
            'id', 'proveedor', 'taller', 'status', 'is_online', 
            'last_heartbeat', 'last_status_change', 'esta_conectado',
            'ultima_conexion', 'ultima_desconexion', 'session_id',
            'ip_address', 'user_agent'
        ]
        read_only_fields = ['id', 'last_status_change']
    
    def to_representation(self, instance):
        """Personalizar la representación para incluir información del proveedor"""
        data = super().to_representation(instance)
        
        # Agregar información del proveedor
        if instance.proveedor:
            data['proveedor_info'] = {
                'id': instance.proveedor.id,
                'nombre': instance.proveedor.nombre,
                'tipo': 'mecanico'
            }
        elif instance.taller:
            data['proveedor_info'] = {
                'id': instance.taller.id,
                'nombre': instance.taller.nombre,
                'tipo': 'taller'
            }
        
        return data 

class NotificacionSerializer(serializers.ModelSerializer):
    """
    Serializer para el modelo Notificacion
    """
    class Meta:
        model = Notificacion
        fields = [
            'id', 'tipo', 'titulo', 'mensaje',
            'leida', 'fecha_leida', 'data', 'fecha_creacion'
        ]
        read_only_fields = ['id', 'fecha_creacion', 'fecha_leida']


class ProviderReviewsSummarySerializer(serializers.Serializer):
    """
    Serializer para el resumen de reseñas de un proveedor
    """
    rating_average = serializers.FloatField()
    total_reviews = serializers.IntegerField()
    rating_breakdown = serializers.DictField()
    reviews = ResenaSerializer(many=True)
