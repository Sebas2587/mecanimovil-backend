import base64
from io import BytesIO

from PIL import Image
from django.core.files.base import ContentFile
from rest_framework import serializers
from rest_framework_gis.serializers import GeoFeatureModelSerializer
from .models import (
    SolicitudServicio, LineaServicio, CarritoAgendamiento, ItemCarritoAgendamiento,
    SolicitudServicioPublica, FotoSolicitudPublica, OfertaProveedor, DetalleServicioOferta, ChatSolicitud,
    RechazoSolicitud
)
from .oferta_precio_desglose import desglose_iva_oferta_proveedor
from mecanimovilapp.apps.checklists.firma_utils import firma_a_payload_base64
from mecanimovilapp.apps.usuarios.models import Cliente, Usuario, DireccionUsuario
from mecanimovilapp.apps.vehiculos.models import Vehiculo
from mecanimovilapp.apps.usuarios.serializers import ClienteSerializer, MecanicoDomicilioSerializer, TallerSerializer, UsuarioSerializer
from mecanimovilapp.apps.servicios.serializers import ServicioSerializer, OfertaServicioSerializer, SolicitudRepuestoSerializer
from mecanimovilapp.apps.vehiculos.serializers import VehiculoSerializer
from django.utils import timezone
from datetime import timedelta, datetime, date
from django.contrib.gis.geos import Point
import logging

# Helper para URLs de archivos en cPanel
from mecanimovilapp.storage.utils import get_image_url

logger = logging.getLogger(__name__)

MAX_FOTO_SOLICITUD_BYTES = 5 * 1024 * 1024


def decode_foto_solicitud_base64(raw: str) -> ContentFile:
    """Decodifica data URI o base64 puro y valida que sea imagen (máx. 5 MB)."""
    if not raw or not isinstance(raw, str):
        raise ValueError('Imagen inválida')
    payload = firma_a_payload_base64(raw.strip())
    if not payload:
        raise ValueError('Imagen vacía')
    try:
        binary = base64.b64decode(payload, validate=True)
    except Exception:
        raise ValueError('Formato base64 inválido')
    if len(binary) > MAX_FOTO_SOLICITUD_BYTES:
        raise ValueError('La imagen supera el tamaño máximo permitido (5 MB)')
    try:
        img = Image.open(BytesIO(binary))
        img.load()
        fmt = (img.format or 'JPEG').upper()
    except Exception:
        raise ValueError('El archivo no es una imagen válida')
    ext = 'jpg' if fmt in ('JPEG', 'JPG') else fmt.lower()
    if ext not in ('jpg', 'jpeg', 'png', 'webp'):
        ext = 'jpg'
    return ContentFile(binary, name=f'necesidad.{ext}')


class SolicitudServicioSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo SolicitudServicio
    """
    cliente_detail = ClienteSerializer(source='cliente', read_only=True)
    taller_detail = TallerSerializer(source='taller', read_only=True)
    mecanico_detail = MecanicoDomicilioSerializer(source='mecanico', read_only=True)
    vehiculo_detail = VehiculoSerializer(source='vehiculo', read_only=True)
    lineas_detail = serializers.SerializerMethodField()
    oferta_proveedor_id = serializers.SerializerMethodField()
    taller_id = serializers.SerializerMethodField()
    mecanico_id = serializers.SerializerMethodField()

    def get_taller_id(self, obj):
        return obj.taller_id

    def get_mecanico_id(self, obj):
        return obj.mecanico_id

    class Meta:
        model = SolicitudServicio
        fields = (
            'id', 'cliente', 'cliente_detail', 'vehiculo', 'vehiculo_detail',
            'fecha_hora_solicitud', 'ubicacion_servicio', 'tipo_servicio',
            'taller', 'taller_detail', 'mecanico', 'mecanico_detail',
            'fecha_servicio', 'hora_servicio', 'metodo_pago', 'total', 'estado',
            'comprobante_pago', 'comprobante_validado', 'fecha_validacion',
            'notas_cliente', 'notas_admin', 'motivo_cancelacion', 'fecha_cancelacion',
            'fecha_devolucion', 'fecha_respuesta_proveedor', 'motivo_rechazo',
            'notas_proveedor', 'lineas_detail', 'oferta_proveedor', 'oferta_proveedor_id',
            'taller_id', 'mecanico_id'
        )
        extra_kwargs = {
            'cliente': {'write_only': True},
            'vehiculo': {'write_only': True},
            'taller': {'write_only': True},
            'mecanico': {'write_only': True},
        }
    
    def get_lineas_detail(self, obj):
        """Retorna las l?neas de servicio con detalles"""
        lineas = obj.lineas.all()
        return LineaServicioSerializer(lineas, many=True).data
    
    def get_oferta_proveedor_id(self, obj):
        """Retorna el ID de la oferta de proveedor asociada"""
        if obj.oferta_proveedor:
            return str(obj.oferta_proveedor.id)
        return None

    def validate(self, data):
        # Validar que al menos un taller o mec?nico se especifique
        if not data.get('taller') and not data.get('mecanico'):
            raise serializers.ValidationError("Debe especificar un taller o un mec?nico para el servicio.")
        
        # Validar que no se especifiquen ambos
        if data.get('taller') and data.get('mecanico'):
            raise serializers.ValidationError("No puede especificar tanto taller como mec?nico para el mismo servicio.")
        
        return data

class LineaServicioSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo LineaServicio
    """
    oferta_servicio_detail = OfertaServicioSerializer(source='oferta_servicio', read_only=True)
    servicio_nombre = serializers.SerializerMethodField()

    def get_servicio_nombre(self, obj):
        try:
            if obj.oferta_servicio and obj.oferta_servicio.servicio:
                return obj.oferta_servicio.servicio.nombre
            return "Servicio no disponible"
        except AttributeError:
            return "Servicio no disponible"

    
    class Meta:
        model = LineaServicio
        fields = (
            'id', 'solicitud', 'oferta_servicio', 
            'oferta_servicio_detail', 'servicio_nombre', 'con_repuestos', 
            'cantidad', 'precio_unitario', 'descuento_porcentaje', 'precio_final'
        )
        extra_kwargs = {
            'solicitud': {'write_only': True},
            'oferta_servicio': {'write_only': True},
        }

class CarritoAgendamientoSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo CarritoAgendamiento
    """
    cliente_detail = ClienteSerializer(source='cliente', read_only=True)
    vehiculo_detail = VehiculoSerializer(source='vehiculo', read_only=True)
    items_detail = serializers.SerializerMethodField()
    total = serializers.ReadOnlyField()
    cantidad_items = serializers.ReadOnlyField()
    taller_detail = serializers.SerializerMethodField()
    mecanico_detail = serializers.SerializerMethodField()
    
    class Meta:
        model = CarritoAgendamiento
        fields = (
            'id', 'cliente', 'cliente_detail', 'vehiculo', 'vehiculo_detail',
            'activo', 'fecha_creacion', 'fecha_actualizacion', 'fecha_programada',
            'hora_programada', 'notas', 'items_detail', 'total', 'cantidad_items',
            'taller_detail', 'mecanico_detail'
        )
        extra_kwargs = {
            'cliente': {'write_only': True},
            'vehiculo': {'write_only': True},
        }
    
    def get_items_detail(self, obj):
        """Retorna los items del carrito con detalles"""
        items = obj.items.all()
        return ItemCarritoAgendamientoSerializer(items, many=True).data
    
    def get_taller_detail(self, obj):
        """Obtiene información del taller si hay items que requieren taller"""
        # Buscar el primer item que tenga taller
        for item in obj.items.all():
            if item.oferta_servicio and item.oferta_servicio.taller:
                return TallerSerializer(item.oferta_servicio.taller).data
        return None
    
    def get_mecanico_detail(self, obj):
        """Obtiene información del mecánico si hay items que requieren mecánico"""
        # Buscar el primer item que tenga mecánico
        for item in obj.items.all():
            if item.oferta_servicio and item.oferta_servicio.mecanico:
                return MecanicoDomicilioSerializer(item.oferta_servicio.mecanico).data
        return None

class ItemCarritoAgendamientoSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo ItemCarritoAgendamiento
    """
    oferta_servicio_detail = OfertaServicioSerializer(source='oferta_servicio', read_only=True)
    servicio_nombre = serializers.SerializerMethodField()

    def get_servicio_nombre(self, obj):
        try:
            if obj.oferta_servicio and obj.oferta_servicio.servicio:
                return obj.oferta_servicio.servicio.nombre
            return "Servicio no disponible"
        except AttributeError:
            return "Servicio no disponible"

    precio_estimado = serializers.ReadOnlyField()
    taller_nombre = serializers.SerializerMethodField()
    taller_direccion = serializers.SerializerMethodField()
    mecanico_nombre = serializers.SerializerMethodField()
    tipo_proveedor = serializers.CharField(source='oferta_servicio.tipo_proveedor', read_only=True)
    
    class Meta:
        model = ItemCarritoAgendamiento
        fields = (
            'id', 'carrito', 'oferta_servicio', 
            'oferta_servicio_detail', 'servicio_nombre', 'con_repuestos', 
            'cantidad', 'fecha_agregado', 'fecha_servicio', 'hora_servicio',
            'configuracion_repuestos', 'notas_repuestos', 'precio_estimado',
            'taller_nombre', 'taller_direccion', 'mecanico_nombre', 'tipo_proveedor'
        )
        extra_kwargs = {
            'carrito': {'write_only': True},
            'oferta_servicio': {'write_only': True},
        }
    
    def get_taller_nombre(self, obj):
        """Retorna el nombre del taller si el item es de taller"""
        if obj.oferta_servicio.taller:
            return obj.oferta_servicio.taller.nombre
        return None
    
    def get_taller_direccion(self, obj):
        """Retorna la direcci?n del taller si el item es de taller"""
        if obj.oferta_servicio.taller:
            return "Direcci?n del taller"  # Placeholder ya que el campo direccion fue eliminado
        return None
    
    def get_mecanico_nombre(self, obj):
        """Retorna el nombre del mec?nico si el item es de mec?nico"""
        if obj.oferta_servicio.mecanico:
            return obj.oferta_servicio.mecanico.nombre if hasattr(obj.oferta_servicio.mecanico, 'nombre') else 'Mec?nico a domicilio'
        return None

class AgendamientoDisponibilidadSerializer(serializers.Serializer):
    """
    Serializador para consultar disponibilidad de agendamiento
    NOTA: Este serializer se mantiene para compatibilidad con APIs existentes
    pero internamente usar? HorarioProveedor en lugar de Disponibilidad
    """
    taller_id = serializers.IntegerField()
    fecha_inicio = serializers.DateField()
    fecha_fin = serializers.DateField(required=False)
    duracion_servicio = serializers.IntegerField(default=60, help_text="Duraci?n en minutos")
    
    def validate(self, data):
        if not data.get('fecha_fin'):
            data['fecha_fin'] = data['fecha_inicio']
        
        if data['fecha_fin'] < data['fecha_inicio']:
            raise serializers.ValidationError("La fecha fin no puede ser anterior a la fecha inicio")
        
        return data

class ConfirmarAgendamientoSerializer(serializers.Serializer):
    """
    Serializador para confirmar un agendamiento
    """
    carrito_id = serializers.IntegerField()
    metodo_pago = serializers.ChoiceField(
        choices=SolicitudServicio.METODO_PAGO_CHOICES
    )
    acepta_terminos = serializers.BooleanField(default=True)
    notas_cliente = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True
    )
    
    def validate_carrito_id(self, value):
        """Valida que el carrito existe y est? activo"""
        try:
            carrito = CarritoAgendamiento.objects.get(id=value, activo=True)
            if not carrito.items.exists():
                raise serializers.ValidationError("El carrito est? vac?o.")
        except CarritoAgendamiento.DoesNotExist:
            raise serializers.ValidationError("Carrito no encontrado o no est? activo.")
        return value

class ClienteProtegidoSerializer(serializers.ModelSerializer):
    """
    Serializador de cliente con informaci?n protegida seg?n el contexto
    Incluye la foto del perfil ya que es informaci?n visual b?sica no sensible
    """
    nombre_ofuscado = serializers.SerializerMethodField()
    telefono_ofuscado = serializers.SerializerMethodField()
    foto_perfil = serializers.SerializerMethodField()
    
    class Meta:
        model = Cliente
        fields = ('id', 'nombre_ofuscado', 'telefono_ofuscado', 'foto_perfil')
    
    def get_nombre_ofuscado(self, obj):
        """Retorna nombre ofuscado (solo iniciales)"""
        nombre = obj.nombre or ""
        apellido = obj.apellido or ""
        
        # Si solo hay nombre, mostrar primera letra + '.'
        if nombre and not apellido:
            return f"{nombre[0].upper()}."
        
        # Si hay nombre y apellido, mostrar inicial de cada uno
        if nombre and apellido:
            return f"{nombre[0].upper()}. {apellido[0].upper()}."
        
        return "Cliente"
    
    def get_telefono_ofuscado(self, obj):
        """Retorna tel?fono parcialmente ofuscado"""
        telefono = obj.telefono or ""
        if len(telefono) >= 8:
            # Mostrar solo los ?ltimos 4 d?gitos
            return f"***-***-{telefono[-4:]}"
        return "***-****"
    
    def get_foto_perfil(self, obj):
        """Retorna la URL completa de la foto de perfil del cliente"""
        try:
            logger.info(f"?? get_foto_perfil llamado para cliente {obj.id}")
            
            # Verificar si el cliente tiene usuario asociado
            if not hasattr(obj, 'usuario') or not obj.usuario:
                logger.warning(f"?? Cliente {obj.id} no tiene usuario asociado")
                return None
            
            logger.info(f"? Cliente {obj.id} tiene usuario: {obj.usuario.id}")
            
            # Verificar si el usuario tiene foto_perfil (verificar que existe y no est? vac?o)
            if not hasattr(obj.usuario, 'foto_perfil') or not obj.usuario.foto_perfil:
                logger.warning(f"?? Usuario {obj.usuario.id} no tiene foto_perfil")
                return None
            
            # Verificar que el campo tiene un valor v?lido (no string vac?o)
            foto_perfil_value = obj.usuario.foto_perfil
            if not foto_perfil_value or str(foto_perfil_value).strip() == '':
                logger.warning(f"?? Usuario {obj.usuario.id} tiene foto_perfil vac?o o None")
                return None
            
            logger.info(f"? Usuario {obj.usuario.id} tiene foto_perfil: {foto_perfil_value}")
            
            # Obtener request del contexto
            request = self.context.get('request')
            if request:
                try:
                    # Construir URL absoluta usando el request
                    foto_url = request.build_absolute_uri(foto_perfil_value.url)
                    logger.info(f"? URL construida: {foto_url}")
                    return foto_url
                except (AttributeError, ValueError) as e:
                    logger.error(f"? Error construyendo URL absoluta: {e}")
                    # Fallback: intentar con URL relativa
                    try:
                        return foto_perfil_value.url
                    except (AttributeError, ValueError):
                        logger.error(f"? Error obteniendo URL relativa de foto_perfil")
                        return None
            else:
                # Fallback: construir URL relativa
                logger.warning(f"?? No hay request en contexto, usando URL relativa")
                try:
                    return foto_perfil_value.url
                except (AttributeError, ValueError) as e:
                    logger.error(f"? Error obteniendo URL relativa: {e}")
                    return None
        except Exception as e:
            logger.error(f"? Error obteniendo foto_perfil del cliente {obj.id}: {e}", exc_info=True)
        return None

class ClienteCompletoSerializer(ClienteSerializer):
    """
    Serializador completo del cliente para cuando est? autorizado
    """
    foto_perfil = serializers.SerializerMethodField()
    
    class Meta(ClienteSerializer.Meta):
        fields = ClienteSerializer.Meta.fields + ('foto_perfil',)
    
    def get_foto_perfil(self, obj):
        """Retorna la URL completa de la foto de perfil del cliente"""
        try:
            logger.info(f"?? get_foto_perfil (ClienteCompleto) llamado para cliente {obj.id}")
            
            # Verificar si el cliente tiene usuario asociado
            if not hasattr(obj, 'usuario') or not obj.usuario:
                logger.warning(f"?? Cliente {obj.id} no tiene usuario asociado")
                return None
            
            logger.info(f"? Cliente {obj.id} tiene usuario: {obj.usuario.id}")
            
            # Verificar si el usuario tiene foto_perfil
            if not hasattr(obj.usuario, 'foto_perfil') or not obj.usuario.foto_perfil:
                logger.warning(f"?? Usuario {obj.usuario.id} no tiene foto_perfil")
                return None
            
            # Verificar que el campo tiene un valor v?lido (no string vac?o)
            foto_perfil_value = obj.usuario.foto_perfil
            if not foto_perfil_value or str(foto_perfil_value).strip() == '':
                logger.warning(f"?? Usuario {obj.usuario.id} tiene foto_perfil vac?o o None")
                return None
            
            logger.info(f"? Usuario {obj.usuario.id} tiene foto_perfil: {foto_perfil_value}")
            
            # Obtener request del contexto
            request = self.context.get('request')
            if request:
                try:
                    # Construir URL absoluta usando el request
                    foto_url = request.build_absolute_uri(foto_perfil_value.url)
                    logger.info(f"? URL construida (ClienteCompleto): {foto_url}")
                    return foto_url
                except (AttributeError, ValueError) as e:
                    logger.error(f"? Error construyendo URL absoluta: {e}")
                    # Fallback: intentar con URL relativa
                    try:
                        return foto_perfil_value.url
                    except (AttributeError, ValueError):
                        logger.error(f"? Error obteniendo URL relativa de foto_perfil")
                        return None
            else:
                # Fallback: construir URL relativa
                logger.warning(f"?? No hay request en contexto, usando URL relativa")
                try:
                    return foto_perfil_value.url
                except (AttributeError, ValueError) as e:
                    logger.error(f"? Error obteniendo URL relativa: {e}")
                    return None
        except Exception as e:
            logger.error(f"? Error obteniendo foto_perfil del cliente {obj.id}: {e}", exc_info=True)
        return None

class VehiculoProtegidoSerializer(serializers.ModelSerializer):
    """
    Serializador de veh?culo con informaci?n b?sica
    """
    marca = serializers.StringRelatedField()
    modelo = serializers.StringRelatedField()
    
    class Meta:
        model = Vehiculo
        fields = ('marca', 'modelo', 'year', 'patente')

class SolicitudServicioProveedorSeguroSerializer(serializers.ModelSerializer):
    """
    Serializador SEGURO para proveedores con protecci?n progresiva de datos
    """
    cliente_detail = serializers.SerializerMethodField()
    vehiculo_detail = VehiculoProtegidoSerializer(source='vehiculo', read_only=True)
    lineas_detail = serializers.SerializerMethodField()
    estado_display = serializers.SerializerMethodField()
    puede_gestionar = serializers.SerializerMethodField()
    lineas = serializers.SerializerMethodField()
    ubicacion_servicio = serializers.SerializerMethodField()
    ubicacion_servicio_segura = serializers.SerializerMethodField()
    tiempo_respuesta_requerido = serializers.SerializerMethodField()
    informacion_disponible = serializers.SerializerMethodField()
    oferta_proveedor_id = serializers.SerializerMethodField()
    
    class Meta:
        model = SolicitudServicio
        fields = (
            'id', 'cliente_detail', 'vehiculo_detail', 'fecha_hora_solicitud',
            'ubicacion_servicio', 'ubicacion_servicio_segura', 'tipo_servicio', 'fecha_servicio', 'hora_servicio', 
            'metodo_pago', 'total', 'estado', 'estado_display',
            'notas_cliente', 'notas_proveedor', 'motivo_rechazo', 
            'lineas_detail', 'lineas', 'puede_gestionar', 'tiempo_respuesta_requerido',
            'informacion_disponible', 'oferta_proveedor_id'
        )
    
    def get_cliente_detail(self, obj):
        """
        Retorna informaci?n del cliente seg?n el nivel de autorizaci?n
        """
        nivel_acceso = self._determinar_nivel_acceso(obj)
        logger.info(f"?? get_cliente_detail para orden {obj.id} - nivel_acceso: {nivel_acceso}")
        logger.info(f"?? Contexto disponible: {bool(self.context.get('request'))}")
        
        if nivel_acceso == 'completo':
            serializer = ClienteCompletoSerializer(obj.cliente, context=self.context)
        else:
            serializer = ClienteProtegidoSerializer(obj.cliente, context=self.context)
        
        data = serializer.data
        logger.info(f"?? Datos serializados del cliente {obj.cliente.id}: {list(data.keys())}")
        logger.info(f"?? foto_perfil en datos: {data.get('foto_perfil')}")
        return data
    
    def get_ubicacion_servicio(self, obj):
        """
        Retorna la direcci?n completa SOLO si la orden est? aceptada (dato sensible)
        """
        # Solo devolver la direcci?n si la orden est? aceptada
        estados_aceptados = [
            'aceptada_por_proveedor',
            'servicio_iniciado',
            'checklist_en_progreso', 
            'checklist_completado',
            'en_proceso',
            'completado'
        ]
        
        if obj.estado in estados_aceptados and obj.ubicacion_servicio:
            return obj.ubicacion_servicio
        
        # Si la orden no est? aceptada, no devolver la direcci?n (null)
        return None
    
    def get_ubicacion_servicio_segura(self, obj):
        """
        Retorna ubicaci?n seg?n el nivel de acceso (usado para mostrar mensajes informativos)
        """
        nivel_acceso = self._determinar_nivel_acceso(obj)
        
        if nivel_acceso == 'completo':
            # La direcci?n completa se devuelve en ubicacion_servicio si est? aceptada
            return None  # Ya se maneja en get_ubicacion_servicio
        elif nivel_acceso == 'parcial':
            # Para ?rdenes pendientes, no mostrar informaci?n de direcci?n
            return None
        else:
            return None
    
    def get_tiempo_respuesta_requerido(self, obj):
        """
        Calcula tiempo restante para responder (solo para ?rdenes pendientes)
        """
        if obj.estado != 'pendiente_aceptacion_proveedor':
            return None
        
        # Configurar tiempo l?mite (ejemplo: 4 horas desde la solicitud)
        tiempo_limite = obj.fecha_hora_solicitud + timedelta(hours=4)
        tiempo_restante = tiempo_limite - timezone.now()
        
        if tiempo_restante.total_seconds() <= 0:
            return {
                'tiempo_limite': tiempo_limite.isoformat(),
                'horas_restantes': 0,
                'expirado': True
            }
        
        horas_restantes = tiempo_restante.total_seconds() / 3600
        return {
            'tiempo_limite': tiempo_limite.isoformat(),
            'horas_restantes': horas_restantes,
            'expirado': False
        }
    
    def get_informacion_disponible(self, obj):
        """
        Indica qu? nivel de informaci?n est? disponible
        """
        nivel = self._determinar_nivel_acceso(obj)
        return {
            'nivel_acceso': nivel,
            'puede_contactar': nivel == 'completo',
            'razon_restriccion': self._get_razon_restriccion(obj, nivel)
        }
    
    def _determinar_nivel_acceso(self, obj):
        """
        Determina el nivel de acceso a la informaci?n del cliente
        """
        # Estados donde se permite acceso completo
        estados_acceso_completo = [
            'aceptada_por_proveedor',
            'servicio_iniciado',
            'checklist_en_progreso', 
            'checklist_completado',
            'en_proceso',
            'completado'
        ]
        
        # Estados donde se permite acceso parcial
        estados_acceso_parcial = [
            'pendiente_aceptacion_proveedor'
        ]
        
        # Estados donde NO se permite acceso (?rdenes cerradas)
        estados_sin_acceso = [
            'cancelado', 
            'rechazada_por_proveedor'
        ]
        
        # Determinar nivel seg?n estado (verificar acceso completo primero)
        if obj.estado in estados_acceso_completo:
            return 'completo'
        elif obj.estado in estados_acceso_parcial:
            return 'parcial'
        elif obj.estado in estados_sin_acceso:
            # Verificar si la orden fue cancelada/rechazada hace m?s de 24 horas
            if obj.fecha_respuesta_proveedor:
                tiempo_transcurrido = timezone.now() - obj.fecha_respuesta_proveedor
                if tiempo_transcurrido > timedelta(hours=24):
                    return 'restringido'
            # Si no ha pasado 24 horas, puede ver informaci?n parcial
            return 'parcial'
        else:
            return 'restringido'
    
    def _get_razon_restriccion(self, obj, nivel):
        """
        Explica por qu? la informaci?n est? restringida
        """
        if nivel == 'parcial':
            return "Informaci?n completa disponible despu?s de aceptar la orden"
        elif nivel == 'restringido':
            return "Informaci?n no disponible para ?rdenes cerradas o expiradas"
        return None
    
    def get_oferta_proveedor_id(self, obj):
        """Retorna el ID de la oferta de proveedor asociada"""
        if obj.oferta_proveedor:
            return str(obj.oferta_proveedor.id)
        return None
    
    def get_lineas_detail(self, obj):
        """Retorna las l?neas de servicio con detalles para proveedores"""
        lineas = obj.lineas.all()
        return LineaServicioSerializer(lineas, many=True).data
    
    def get_lineas(self, obj):
        """Retorna las l?neas de servicio en formato simplificado para el frontend"""
        lineas = obj.lineas.all()
        return [
            {
                'servicio_nombre': linea.oferta_servicio.servicio.nombre,
                'con_repuestos': linea.con_repuestos,
                'precio_final': str(linea.precio_final)
            }
            for linea in lineas
        ]
    
    def get_estado_display(self, obj):
        """Retorna el estado en formato legible para humanos"""
        estado_dict = {
            'pendiente': 'Pendiente',
            'pago_validado': 'Pago Validado',
            'confirmado': 'Pendiente de iniciar',
            'en_proceso': 'En Proceso',
            'completado': 'Completado',
            'cancelado': 'Cancelado',
            'solicitud_cancelacion': 'Solicitud de Cancelaci?n',
            'pendiente_devolucion': 'Pendiente de Devoluci?n',
            'devuelto': 'Devuelto',
            'pendiente_aceptacion_proveedor': 'Pendiente de Aceptaci?n',
            'aceptada_por_proveedor': 'Aceptada',
            'rechazada_por_proveedor': 'Rechazada',
            'checklist_en_progreso': 'Checklist en Progreso',
            'checklist_completado': 'Checklist Completado',
        }
        return estado_dict.get(obj.estado, obj.estado.replace('_', ' ').title())
    
    def get_puede_gestionar(self, obj):
        """Determina si el proveedor puede gestionar esta orden"""
        # Un proveedor puede gestionar la orden si:
        # 1. La orden est? asignada a su taller/perfil
        # 2. El estado permite gesti?n
        estados_gestionables = [
            'pendiente_aceptacion_proveedor',
            'aceptada_por_proveedor',
            'confirmado',  # Puede abrir e iniciar checklist
            'checklist_en_progreso',
            'checklist_completado',
            'en_proceso'
        ]
        return obj.estado in estados_gestionables

class AcceptOrderSerializer(serializers.Serializer):
    """
    Serializador para aceptar una orden por parte del proveedor
    """
    notas = serializers.CharField(
        max_length=500, 
        required=False, 
        allow_blank=True,
        help_text="Notas adicionales del proveedor"
    )

class RejectOrderSerializer(serializers.Serializer):
    """
    Serializador para rechazar una orden por parte del proveedor
    """
    motivo_rechazo = serializers.CharField(
        max_length=500,
        help_text="Motivo del rechazo"
    )
    notas = serializers.CharField(
        max_length=500, 
        required=False, 
        allow_blank=True,
        help_text="Notas adicionales del proveedor"
    )

class UpdateOrderStatusSerializer(serializers.Serializer):
    """
    Serializador para actualizar el estado de una orden
    """
    estado = serializers.ChoiceField(
        choices=[
            ('en_proceso', 'En Proceso'),
            ('completado', 'Completado'),
        ]
    )
    notas = serializers.CharField(
        max_length=500, 
        required=False, 
        allow_blank=True,
        help_text="Notas sobre el cambio de estado"
    )

class OrdenEstadisticasSerializer(serializers.Serializer):
    """
    Serializador para estad?sticas de ?rdenes del proveedor
    """
    total_ordenes = serializers.IntegerField()
    ordenes_pendientes = serializers.IntegerField()
    ordenes_completadas = serializers.IntegerField()
    ingresos_mes_actual = serializers.DecimalField(max_digits=10, decimal_places=2)
    calificacion_promedio = serializers.DecimalField(max_digits=3, decimal_places=2)


class ProveedorKpisResumenSerializer(serializers.Serializer):
    """Resumen de KPIs para dashboard proveedor (ventana móvil, sin PII)."""

    ventana_dias = serializers.IntegerField()
    desde = serializers.CharField()
    ofertas_dirigidas_muestra = serializers.IntegerField()
    ofertas_globales_muestra = serializers.IntegerField()
    ofertas_total_en_periodo = serializers.IntegerField()
    tiempo_respuesta_dirigida_media_minutos = serializers.FloatField(allow_null=True)
    tiempo_respuesta_global_media_minutos = serializers.FloatField(allow_null=True)
    ordenes_mercado_en_periodo = serializers.IntegerField()
    ordenes_mercado_completadas = serializers.IntegerField()
    ordenes_con_checklist = serializers.IntegerField()
    checklist_completados = serializers.IntegerField()
    checklist_cumplimiento_pct = serializers.FloatField(allow_null=True)
    checklist_tiempo_promedio_minutos = serializers.FloatField(allow_null=True)
    tiempo_ejecucion_vs_estimado_promedio = serializers.FloatField(allow_null=True)
    tiempo_ejecucion_vs_estimado_muestra = serializers.IntegerField()
    resenas_muestra = serializers.IntegerField()
    resenas_totales_proveedor = serializers.IntegerField()
    calificacion_cliente_promedio = serializers.FloatField(allow_null=True)
    calificacion_promedio_todas_resenas = serializers.FloatField(allow_null=True)
    calificacion_servicios_promedio = serializers.FloatField(allow_null=True)
    calificacion_servicios_lineas_muestra = serializers.IntegerField()
    calificacion_servicios_lineas_total = serializers.IntegerField()
    score_tiempo_respuesta = serializers.IntegerField(allow_null=True)
    score_calificacion_cliente = serializers.IntegerField(allow_null=True)
    score_calidad_servicio = serializers.IntegerField(allow_null=True)
    score_checklist = serializers.IntegerField(allow_null=True)
    score_tiempo_ejecucion = serializers.IntegerField(allow_null=True)
    score_rendimiento = serializers.IntegerField()
    suscripcion_mensual_activa = serializers.BooleanField()
    insignia_visible_a_clientes = serializers.BooleanField()
    sugerencia_suscripcion_para_insignia = serializers.BooleanField()
    mensaje_sugerencia_suscripcion = serializers.CharField(
        allow_null=True, allow_blank=True, required=False
    )

class SolicitudServicioProveedorLegacySerializer(serializers.ModelSerializer):
    """
    Serializador LEGACY espec?fico para la vista de proveedores (SIN PROTECCIONES)
    Mantener solo para compatibilidad con c?digo existente
    """
    cliente_detail = ClienteSerializer(source='cliente', read_only=True)
    vehiculo_detail = VehiculoProtegidoSerializer(source='vehiculo', read_only=True)
    lineas_detail = serializers.SerializerMethodField()
    estado_display = serializers.SerializerMethodField()
    puede_gestionar = serializers.SerializerMethodField()
    lineas = serializers.SerializerMethodField()
    
    class Meta:
        model = SolicitudServicio
        fields = (
            'id', 'cliente_detail', 'vehiculo_detail', 'fecha_hora_solicitud',
            'ubicacion_servicio', 'tipo_servicio', 'fecha_servicio', 'hora_servicio', 
            'metodo_pago', 'total', 'estado', 'estado_display',
            'notas_cliente', 'notas_proveedor', 'motivo_rechazo', 
            'lineas_detail', 'lineas', 'puede_gestionar'
        )
    
    def get_lineas_detail(self, obj):
        """Retorna las l?neas de servicio con detalles para proveedores"""
        lineas = obj.lineas.all()
        return LineaServicioSerializer(lineas, many=True).data
    
    def get_lineas(self, obj):
        """Retorna las l?neas de servicio en formato simplificado para el frontend"""
        lineas = obj.lineas.all()
        return [
            {
                'servicio_nombre': linea.oferta_servicio.servicio.nombre,
                'con_repuestos': linea.con_repuestos,
                'precio_final': str(linea.precio_final)
            }
            for linea in lineas
        ]
    
    def get_estado_display(self, obj):
        """Retorna el estado en formato legible para humanos"""
        estado_dict = {
            'pendiente': 'Pendiente',
            'pago_validado': 'Pago Validado',
            'confirmado': 'Pendiente de iniciar',
            'en_proceso': 'En Proceso',
            'completado': 'Completado',
            'cancelado': 'Cancelado',
            'solicitud_cancelacion': 'Solicitud de Cancelaci?n',
            'pendiente_devolucion': 'Pendiente de Devoluci?n',
            'devuelto': 'Devuelto',
            'pendiente_aceptacion_proveedor': 'Pendiente de Aceptaci?n',
            'aceptada_por_proveedor': 'Aceptada',
            'rechazada_por_proveedor': 'Rechazada',
            'checklist_en_progreso': 'Checklist en Progreso',
            'checklist_completado': 'Checklist Completado',
        }
        return estado_dict.get(obj.estado, obj.estado.replace('_', ' ').title())
    
    def get_puede_gestionar(self, obj):
        """Determina si el proveedor puede gestionar esta orden"""
        estados_gestionables = [
            'pendiente_aceptacion_proveedor',
            'aceptada_por_proveedor',
            'confirmado',  # Puede abrir e iniciar checklist
            'checklist_en_progreso',
            'checklist_completado',
            'en_proceso'
        ]
        return obj.estado in estados_gestionables

# Alias para compatibilidad - USAR EL SEGURO POR DEFECTO
SolicitudServicioProveedorSerializer = SolicitudServicioProveedorSeguroSerializer

# ============================================================================
# SERIALIZERS DEL SISTEMA DE POSTULACIONES
# ============================================================================

class DetalleServicioOfertaSerializer(serializers.ModelSerializer):
    """Serializer para detalles de servicios en ofertas"""
    servicio_nombre = serializers.CharField(source='servicio.nombre', read_only=True)
    repuestos_info = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = DetalleServicioOferta
        fields = [
            'id', 'servicio', 'servicio_nombre', 'precio_servicio',
            'tiempo_estimado', 'notas', 'repuestos_seleccionados', 'repuestos_info'
        ]
    
    def get_repuestos_info(self, obj):
        """Retorna informaci?n detallada de los repuestos seleccionados"""
        import logging
        logger = logging.getLogger(__name__)
        
        if not obj.repuestos_seleccionados:
            logger.debug(f"DetalleServicioOferta {obj.id}: No tiene repuestos_seleccionados")
            return []
        
        from mecanimovilapp.apps.servicios.models import Repuesto
        from mecanimovilapp.apps.servicios.serializers import RepuestoSerializer
        
        logger.debug(f"DetalleServicioOferta {obj.id}: Procesando {len(obj.repuestos_seleccionados)} repuestos")
        
        repuestos_info = []
        for repuesto_data in obj.repuestos_seleccionados:
            repuesto_id = repuesto_data.get('id')
            cantidad = repuesto_data.get('cantidad', 1)
            # CORRECCI?N: Incluir precio personalizado del proveedor si existe
            precio_personalizado = repuesto_data.get('precio')
            
            if repuesto_id:
                try:
                    repuesto = Repuesto.objects.get(id=repuesto_id)
                    # Pasar el contexto del request si est? disponible
                    request = self.context.get('request')
                    repuesto_serializer = RepuestoSerializer(repuesto, context={'request': request} if request else {})
                    
                    repuesto_info = {
                        **repuesto_serializer.data,
                        'cantidad': cantidad,
                        # CORRECCI?N: Incluir precio personalizado del proveedor (si difiere del precio_referencia)
                        'precio': precio_personalizado
                    }
                    repuestos_info.append(repuesto_info)
                    logger.debug(f"Repuesto {repuesto_id} agregado con cantidad {cantidad}, precio personalizado: {precio_personalizado}")
                except Repuesto.DoesNotExist:
                    logger.warning(f"Repuesto con ID {repuesto_id} no encontrado")
                    continue
            else:
                logger.warning(f"Repuesto sin ID v?lido: {repuesto_data}")
        
        logger.debug(f"DetalleServicioOferta {obj.id}: Retornando {len(repuestos_info)} repuestos con informaci?n completa")
        return repuestos_info

class OfertaProveedorSerializer(serializers.ModelSerializer):
    """Serializer completo para ofertas de proveedores"""
    detalles_servicios = DetalleServicioOfertaSerializer(many=True, read_only=True)
    servicios_ofertados = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
        help_text='Lista de IDs de servicios ofertados (se usa para validaci?n, pero se crean a trav?s de detalles_servicios)'
    )
    nombre_proveedor = serializers.SerializerMethodField()
    rating_proveedor = serializers.SerializerMethodField()
    tiempo_restante_solicitud = serializers.SerializerMethodField()
    total_mensajes_chat = serializers.SerializerMethodField()
    mensajes_no_leidos = serializers.SerializerMethodField()
    proveedor_id_detail = serializers.SerializerMethodField()
    antiguedad_proveedor = serializers.SerializerMethodField()
    servicios_realizados_proveedor = serializers.SerializerMethodField()
    proveedor_verificado = serializers.SerializerMethodField()
    solicitud_detail = serializers.SerializerMethodField()
    proveedor_foto = serializers.SerializerMethodField()
    ofertas_secundarias = serializers.SerializerMethodField()
    oferta_original_info = serializers.SerializerMethodField()
    solicitud_servicio_id = serializers.SerializerMethodField()
    solicitud_estado = serializers.CharField(source='solicitud.estado', read_only=True)
    rechazada_por_expiracion = serializers.SerializerMethodField()
    fecha_limite_pago = serializers.SerializerMethodField()
    tiempo_restante_pago = serializers.SerializerMethodField()
    
    # Campos para informaci?n de pago directo al proveedor
    proveedor_puede_recibir_pagos = serializers.SerializerMethodField()
    # Créditos para confirmar adjudicación (solo proveedor dueño, oferta pendiente_creditos)
    fecha_limite_confirmacion_creditos = serializers.SerializerMethodField()
    creditos_necesarios_adjudicacion = serializers.SerializerMethodField()
    saldo_creditos_proveedor = serializers.SerializerMethodField()
    creditos_faltantes_para_confirmar = serializers.SerializerMethodField()
    desglose_iva = serializers.SerializerMethodField()
    
    class Meta:
        model = OfertaProveedor
        fields = [
            'id', 'solicitud', 'solicitud_detail', 'solicitud_estado', 'proveedor', 'proveedor_id_detail', 'tipo_proveedor', 'nombre_proveedor',
            'rating_proveedor', 'precio_total_ofrecido', 'incluye_repuestos',
            'tiempo_estimado_total', 'descripcion_oferta', 'garantia_ofrecida',
            'fecha_disponible', 'hora_disponible', 'es_fecha_alternativa', 'motivo_fecha_alternativa', 'estado', 'fecha_envio',
            'fecha_visualizacion_cliente', 'detalles_servicios', 'servicios_ofertados',
            'total_mensajes_chat', 'mensajes_no_leidos', 'tiempo_restante_solicitud',
            'antiguedad_proveedor', 'servicios_realizados_proveedor', 'proveedor_verificado',
            'proveedor_foto', 'oferta_original', 'es_oferta_secundaria', 'motivo_servicio_adicional',
            'ofertas_secundarias', 'oferta_original_info', 'solicitud_servicio_id', 'rechazada_por_expiracion',
            # Campos de desglose de costos
            'costo_repuestos', 'costo_mano_obra', 'costo_gestion_compra', 'foto_cotizacion_repuestos',
            'desglose_iva',
            'metodo_pago_cliente', 'estado_pago_repuestos', 'estado_pago_servicio',
            'proveedor_puede_recibir_pagos',
            # Campos de tiempo para pago
            'fecha_limite_pago', 'tiempo_restante_pago',
            # Reserva por créditos (confirmación post-selección)
            'fecha_limite_confirmacion_creditos',
            'creditos_necesarios_adjudicacion', 'saldo_creditos_proveedor', 'creditos_faltantes_para_confirmar',
        ]
        read_only_fields = ['estado', 'fecha_envio', 'fecha_visualizacion_cliente', 'proveedor', 'tipo_proveedor', 'es_oferta_secundaria']
    
    def get_desglose_iva(self, obj):
        """Subtotal sin IVA, IVA y total coherentes con precio_total_ofrecido (misma lógica que apps)."""
        return desglose_iva_oferta_proveedor(obj)
    
    def _contexto_creditos_adjudicacion(self, obj):
        """
        Créditos para adjudicar el primer servicio de la oferta (misma regla que seleccionar_oferta).
        Solo visible para el proveedor dueño y cuando la oferta está pendiente de compra de créditos.
        """
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        if getattr(obj, 'proveedor_id', None) != request.user.pk:
            return None
        if obj.estado != 'pendiente_creditos':
            return None
        if obj.es_oferta_secundaria:
            return None
        try:
            det = obj.detalles_servicios.first()
            if not det or not det.servicio_id:
                return None
            from mecanimovilapp.apps.suscripciones.creditos_services import (
                validar_creditos_suficientes,
                obtener_credito_proveedor,
            )
            _ok, _msg, necesarios = validar_creditos_suficientes(obj.proveedor, det.servicio)
            saldo = obtener_credito_proveedor(obj.proveedor).saldo_creditos
            nec = int(necesarios)
            s = int(saldo)
            return {'necesarios': nec, 'saldo': s, 'faltantes': max(0, nec - s)}
        except Exception:
            return None
    
    def get_fecha_limite_confirmacion_creditos(self, obj):
        if obj.estado != 'pendiente_creditos' or not obj.solicitud_id:
            return None
        sol = obj.solicitud
        fl = getattr(sol, 'fecha_limite_confirmacion_creditos', None)
        if fl:
            return fl.isoformat()
        return None
    
    def get_creditos_necesarios_adjudicacion(self, obj):
        ctx = self._contexto_creditos_adjudicacion(obj)
        return ctx['necesarios'] if ctx else None
    
    def get_saldo_creditos_proveedor(self, obj):
        ctx = self._contexto_creditos_adjudicacion(obj)
        return ctx['saldo'] if ctx else None
    
    def get_creditos_faltantes_para_confirmar(self, obj):
        ctx = self._contexto_creditos_adjudicacion(obj)
        return ctx['faltantes'] if ctx else None
    
    def get_nombre_proveedor(self, obj):
        return obj.nombre_proveedor
    
    def get_rating_proveedor(self, obj):
        return obj.rating_proveedor
    
    def get_proveedor_id_detail(self, obj):
        """Retorna el ID del taller o mec?nico (no del usuario) para navegaci?n"""
        if obj.tipo_proveedor == 'taller' and hasattr(obj.proveedor, 'taller'):
            return obj.proveedor.taller.id
        elif obj.tipo_proveedor == 'mecanico' and hasattr(obj.proveedor, 'mecanico_domicilio'):
            return obj.proveedor.mecanico_domicilio.id
        return None
    
    def get_tiempo_restante_solicitud(self, obj):
        return obj.solicitud.tiempo_restante
    
    def get_total_mensajes_chat(self, obj):
        return obj.mensajes_chat.count()
    
    def get_mensajes_no_leidos(self, obj):
        # Contar mensajes no le?dos del proveedor (para el cliente)
        request = self.context.get('request')
        if request and request.user:
            if hasattr(request.user, 'cliente'):
                # Cliente viendo: contar mensajes del proveedor no le?dos
                return obj.mensajes_chat.filter(es_proveedor=True, leido=False).count()
            else:
                # Proveedor viendo: contar mensajes del cliente no le?dos
                return obj.mensajes_chat.filter(es_proveedor=False, leido=False).count()
        return 0
    
    def get_antiguedad_proveedor(self, obj):
        """Retorna la antig?edad del proveedor en d?as desde fecha_registro"""
        try:
            if obj.tipo_proveedor == 'taller' and hasattr(obj.proveedor, 'taller'):
                fecha_registro = obj.proveedor.taller.fecha_registro
            elif obj.tipo_proveedor == 'mecanico' and hasattr(obj.proveedor, 'mecanico_domicilio'):
                fecha_registro = obj.proveedor.mecanico_domicilio.fecha_registro
            else:
                return 0
            
            if fecha_registro:
                delta = timezone.now().date() - (fecha_registro.date() if hasattr(fecha_registro, 'date') else fecha_registro)
                return delta.days
            return 0
        except Exception:
            return 0
    
    def get_servicios_realizados_proveedor(self, obj):
        """Retorna el n?mero de servicios completados por el proveedor"""
        try:
            from mecanimovilapp.apps.ordenes.models import SolicitudServicio
            
            if obj.tipo_proveedor == 'taller' and hasattr(obj.proveedor, 'taller'):
                taller = obj.proveedor.taller
                servicios_completados = SolicitudServicio.objects.filter(
                    taller=taller,
                    estado='completado'
                ).count()
                return servicios_completados
            elif obj.tipo_proveedor == 'mecanico' and hasattr(obj.proveedor, 'mecanico_domicilio'):
                mecanico = obj.proveedor.mecanico_domicilio
                servicios_completados = SolicitudServicio.objects.filter(
                    mecanico=mecanico,
                    estado='completado'
                ).count()
                return servicios_completados
            return 0
        except Exception:
            return 0
    
    def get_proveedor_verificado(self, obj):
        """Retorna si el proveedor est? verificado"""
        try:
            from mecanimovilapp.apps.usuarios.verification_utils import proveedor_visible_como_verificado

            if obj.tipo_proveedor == 'taller' and hasattr(obj.proveedor, 'taller'):
                return proveedor_visible_como_verificado(obj.proveedor.taller)
            elif obj.tipo_proveedor == 'mecanico' and hasattr(obj.proveedor, 'mecanico_domicilio'):
                return proveedor_visible_como_verificado(obj.proveedor.mecanico_domicilio)
            return False
        except Exception:
            return False
    
    def get_proveedor_foto(self, obj):
        """Retorna la foto del perfil del proveedor usando cPanel si est? configurado"""
        try:
            request = self.context.get('request')
            proveedor = obj.proveedor
            if proveedor and proveedor.foto_perfil:
                return get_image_url(proveedor.foto_perfil, request)
            return None
        except Exception:
            return None
    
    def get_proveedor_puede_recibir_pagos(self, obj):
        """
        Verifica si el proveedor tiene su cuenta de Mercado Pago configurada
        y puede recibir pagos directos.
        """
        try:
            from mecanimovilapp.apps.pagos.models import CuentaMercadoPagoProveedor
            
            # Verificar si el proveedor tiene cuenta de Mercado Pago conectada
            cuenta = CuentaMercadoPagoProveedor.objects.filter(
                usuario=obj.proveedor,
                estado='conectada'
            ).first()
            
            if cuenta and cuenta.access_token:
                return True
            return False
        except Exception:
            return False
    
    def get_ofertas_secundarias(self, obj):
        """Retorna las ofertas secundarias relacionadas si esta es una oferta original"""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"?? OfertaProveedorSerializer.get_ofertas_secundarias - Oferta ID: {obj.id}, es_oferta_secundaria: {obj.es_oferta_secundaria}")
        
        if obj.es_oferta_secundaria:
            logger.info(f"  - Es oferta secundaria, retornando []")
            return []
        
        ofertas_secundarias = obj.ofertas_secundarias.all()
        logger.info(f"  - Ofertas secundarias encontradas: {ofertas_secundarias.count()}")
        for oferta_sec in ofertas_secundarias:
            logger.info(f"    - Oferta secundaria ID: {oferta_sec.id}, Estado: {oferta_sec.estado}, es_oferta_secundaria: {oferta_sec.es_oferta_secundaria}")
        
        resultado = OfertaProveedorSerializer(ofertas_secundarias, many=True, context=self.context).data
        logger.info(f"  - Resultado serializado: {len(resultado)} ofertas")
        return resultado
    
    def get_solicitud_servicio_id(self, obj):
        """Retorna el ID de la SolicitudServicio asociada a esta oferta"""
        try:
            solicitud_servicio = obj.solicitudes_servicio.first()
            if solicitud_servicio:
                return solicitud_servicio.id
            return None
        except Exception:
            return None
    
    def get_rechazada_por_expiracion(self, obj):
        """
        Determina si la oferta fue rechazada por expiraci?n de pago (no por selecci?n de otra oferta).
        Retorna True si:
        - La oferta est? rechazada
        - La solicitud est? cancelada
        - Y (la fecha_limite_pago pas? O han pasado m?s de 48 horas desde fecha_respuesta_cliente)
        """
        from django.utils import timezone
        from datetime import timedelta
        
        if obj.estado != 'rechazada':
            return False
        
        solicitud = obj.solicitud
        if not solicitud:
            return False
        
        # Si la solicitud est? cancelada, verificar si fue por expiraci?n
        if solicitud.estado == 'cancelada':
            ahora = timezone.now()
            PLAZO_MAXIMO_PAGO_HORAS = 48
            plazo_maximo_pago = timedelta(hours=PLAZO_MAXIMO_PAGO_HORAS)
            
            # Verificar si fue rechazada por expiraci?n de fecha l?mite
            if solicitud.fecha_limite_pago and solicitud.fecha_limite_pago < ahora:
                return True
            
            # Verificar si fue rechazada por plazo de 48 horas desde aceptaci?n
            if obj.fecha_respuesta_cliente:
                fecha_limite_aceptacion = obj.fecha_respuesta_cliente + plazo_maximo_pago
                if ahora > fecha_limite_aceptacion:
                    return True
        
        return False
    
    def get_fecha_limite_pago(self, obj):
        """Retorna la fecha l?mite de pago de la solicitud asociada"""
        if obj.solicitud and obj.solicitud.fecha_limite_pago:
            return obj.solicitud.fecha_limite_pago.isoformat()
        return None
    
    def get_tiempo_restante_pago(self, obj):
        """Retorna el tiempo restante para pagar en formato legible"""
        if not obj.solicitud:
            return None
        
        tiempo_restante = obj.solicitud.tiempo_restante_pago()
        if not tiempo_restante:
            return None
        
        total_seconds = tiempo_restante.total_seconds()
        horas = int(total_seconds // 3600)
        
        if horas < 1:
            minutos = int((total_seconds % 3600) // 60)
            return f"{minutos} minutos"
        elif horas < 24:
            return f"{horas} horas"
        else:
            dias = horas // 24
            horas_restantes = horas % 24
            if horas_restantes > 0:
                return f"{dias}d {horas_restantes}h"
            return f"{dias} d?as"
    
    def get_oferta_original_info(self, obj):
        """Retorna informaci?n de la oferta original si esta es una oferta secundaria"""
        if not obj.es_oferta_secundaria or not obj.oferta_original:
            return None
        return {
            'id': str(obj.oferta_original.id),
            'precio_total_ofrecido': str(obj.oferta_original.precio_total_ofrecido),
            'fecha_envio': obj.oferta_original.fecha_envio.isoformat() if obj.oferta_original.fecha_envio else None,
            'estado': obj.oferta_original.estado,
        }
    
    def get_solicitud_detail(self, obj):
        """Retorna informaci?n detallada de la solicitud, cliente y veh?culo"""
        try:
            solicitud = obj.solicitud
            request = self.context.get('request')
            
            # Información del cliente
            cliente_nombre = "Cliente"
            cliente_foto = None
            try:
                if solicitud.cliente and solicitud.cliente.usuario:
                    cliente_nombre = solicitud.cliente.usuario.get_full_name()
                    cliente_foto = get_image_url(solicitud.cliente.usuario.foto_perfil, request)
            except (AttributeError, Exception):
                pass
            
            # Informaci?n del veh?culo
            vehiculo_info = None
            try:
                if solicitud.vehiculo:
                    marca_nombre = 'Sin marca'
                    try:
                        if solicitud.vehiculo.marca:
                            marca_nombre = solicitud.vehiculo.marca.nombre
                    except AttributeError:
                        pass
                    
                    # Obtener nombre del modelo
                    modelo_nombre = 'Sin modelo'
                    try:
                        if solicitud.vehiculo.modelo:
                            # Si modelo es un objeto con atributo 'nombre', usar eso
                            if hasattr(solicitud.vehiculo.modelo, 'nombre'):
                                modelo_nombre = solicitud.vehiculo.modelo.nombre
                            # Si modelo es un string, usar directamente
                            elif isinstance(solicitud.vehiculo.modelo, str):
                                modelo_nombre = solicitud.vehiculo.modelo
                    except AttributeError:
                        pass
                    
                    vehiculo_info = {
                        'id': solicitud.vehiculo.id,
                        'marca': marca_nombre,
                        'modelo': modelo_nombre,
                        'a?o': getattr(solicitud.vehiculo, 'year', None),
                        'patente': getattr(solicitud.vehiculo, 'patente', '') or '',
                        'kilometraje': getattr(solicitud.vehiculo, 'kilometraje', None),
                    }
            except (AttributeError, Exception):
                pass
            
            # Informaci?n de servicios solicitados
            servicios_solicitados = []
            try:
                for servicio in solicitud.servicios_solicitados.all():
                    servicios_solicitados.append({
                        'id': servicio.id,
                        'nombre': servicio.nombre,
                    })
            except (AttributeError, Exception):
                pass

            fotos_necesidad = []
            try:
                for f in solicitud.fotos_necesidad.all().order_by('orden', 'fecha_subida'):
                    fotos_necesidad.append({
                        'id': str(f.id),
                        'imagen_url': get_image_url(f.imagen, request) if f.imagen else None,
                        'orden': f.orden,
                    })
            except (AttributeError, Exception):
                pass
            
            return {
                'id': str(solicitud.id),
                'cliente_nombre': cliente_nombre,
                'cliente_foto': cliente_foto,
                'vehiculo': vehiculo_info,
                'descripcion_problema': solicitud.descripcion_problema or '',
                'urgencia': solicitud.urgencia or 'normal',
                'servicios_solicitados': servicios_solicitados,
                'fecha_preferida': str(solicitud.fecha_preferida) if solicitud.fecha_preferida else None,
                'hora_preferida': str(solicitud.hora_preferida) if solicitud.hora_preferida else None,
                'direccion_servicio_texto': solicitud.direccion_servicio_texto or '',
                'detalles_ubicacion': solicitud.detalles_ubicacion or '',
                'fotos_necesidad': fotos_necesidad,
            }
        except Exception as e:
            # En caso de error, retornar estructura m?nima
            return {
                'id': None,
                'cliente_nombre': 'Cliente',
                'cliente_foto': None,
                'vehiculo': None,
                'descripcion_problema': '',
                'urgencia': 'normal',
                'servicios_solicitados': [],
                'fecha_preferida': None,
                'hora_preferida': None,
                'direccion_servicio_texto': '',
                'detalles_ubicacion': '',
                'fotos_necesidad': [],
            }
    
    def to_internal_value(self, data):
        """
        Convierte tiempo_estimado_total de string "HH:MM:SS" a timedelta si es necesario
        """
        if isinstance(data, dict) and 'tiempo_estimado_total' in data:
            tiempo_str = data['tiempo_estimado_total']
            if isinstance(tiempo_str, str):
                # Parsear formato "HH:MM:SS" o "HH:MM"
                try:
                    parts = tiempo_str.split(':')
                    if len(parts) >= 2:
                        horas = int(parts[0])
                        minutos = int(parts[1])
                        segundos = int(parts[2]) if len(parts) > 2 else 0
                        # Convertir a timedelta y luego a string en formato que DRF entiende
                        td = timedelta(hours=horas, minutes=minutos, seconds=segundos)
                        # DRF espera formato "DD HH:MM:SS" o "HH:MM:SS"
                        data['tiempo_estimado_total'] = str(td)
                    else:
                        # Si viene como n?mero de horas
                        horas = float(tiempo_str)
                        td = timedelta(hours=horas)
                        data['tiempo_estimado_total'] = str(td)
                except (ValueError, TypeError) as e:
                    # Si falla, dejar que DRF maneje el error
                    pass
        
        return super().to_internal_value(data)
    
    def validate(self, attrs):
        """
        Validaci?n adicional para la oferta
        """
        # Validar campos requeridos
        campos_requeridos = {
            'solicitud': 'La solicitud es requerida',
            'precio_total_ofrecido': 'El precio total es requerido',
            'tiempo_estimado_total': 'El tiempo estimado total es requerido',
            'descripcion_oferta': 'La descripci?n de la oferta es requerida',
            'fecha_disponible': 'La fecha disponible es requerida',
            'hora_disponible': 'La hora disponible es requerida'
        }
        
        for campo, mensaje in campos_requeridos.items():
            if campo not in attrs or not attrs.get(campo):
                raise serializers.ValidationError({campo: mensaje})
        
        # Validar que descripcion_oferta no est? vac?a
        if attrs.get('descripcion_oferta', '').strip() == '':
            raise serializers.ValidationError({
                'descripcion_oferta': 'La descripci?n de la oferta no puede estar vac?a'
            })
        
        # Validaci?n para ofertas secundarias
        oferta_original = attrs.get('oferta_original')
        motivo_servicio_adicional = attrs.get('motivo_servicio_adicional', '')
        
        if oferta_original:
            # Si tiene oferta_original, debe ser secundaria
            if not attrs.get('es_oferta_secundaria', False):
                attrs['es_oferta_secundaria'] = True
            
            # Validar que el motivo sea proporcionado
            if not motivo_servicio_adicional or motivo_servicio_adicional.strip() == '':
                raise serializers.ValidationError({
                    'motivo_servicio_adicional': 'El motivo del servicio adicional es obligatorio para ofertas secundarias'
                })
        
        return attrs
    
    def create(self, validated_data):
        # Remover servicios_ofertados si est? presente (no es un campo del modelo, se maneja en perform_create)
        validated_data.pop('servicios_ofertados', None)
        
        # Calcular tiempo de respuesta
        solicitud = validated_data['solicitud']
        if solicitud.fecha_publicacion:
            validated_data['tiempo_respuesta_proveedor'] = timezone.now() - solicitud.fecha_publicacion
        
        return super().create(validated_data)

class RechazoSolicitudSerializer(serializers.ModelSerializer):
    """Serializer para rechazos de solicitudes por proveedores"""
    proveedor_nombre = serializers.SerializerMethodField()
    proveedor_info = serializers.SerializerMethodField()
    motivo_display = serializers.CharField(source='get_motivo_display', read_only=True)
    
    class Meta:
        model = RechazoSolicitud
        fields = [
            'id', 'solicitud', 'proveedor', 'proveedor_nombre',
            'proveedor_info', 'tipo_proveedor', 'motivo',
            'motivo_display', 'detalle_motivo', 'fecha_rechazo',
            'tiempo_respuesta'
        ]
        read_only_fields = [
            'id', 'proveedor', 'fecha_rechazo', 'tiempo_respuesta', 'tipo_proveedor'
        ]
    
    def get_proveedor_nombre(self, obj):
        """Retorna el nombre del proveedor"""
        if obj.tipo_proveedor == 'taller' and hasattr(obj.proveedor, 'taller'):
            return obj.proveedor.taller.nombre
        elif obj.tipo_proveedor == 'mecanico' and hasattr(obj.proveedor, 'mecanico_domicilio'):
            return f"{obj.proveedor.first_name} {obj.proveedor.last_name}"
        return obj.proveedor.get_full_name()
    
    def get_proveedor_info(self, obj):
        """Retorna informaci?n del proveedor"""
        if obj.tipo_proveedor == 'taller' and hasattr(obj.proveedor, 'taller'):
            return {
                'id': obj.proveedor.taller.id,
                'nombre': obj.proveedor.taller.nombre,
                'calificacion': obj.proveedor.taller.calificacion_promedio,
            }
        elif obj.tipo_proveedor == 'mecanico' and hasattr(obj.proveedor, 'mecanico_domicilio'):
            return {
                'id': obj.proveedor.mecanico_domicilio.id,
                'nombre': f"{obj.proveedor.first_name} {obj.proveedor.last_name}",
                'calificacion': obj.proveedor.mecanico_domicilio.calificacion_promedio,
            }
        return None
    
    def validate(self, attrs):
        """Validar que el proveedor no haya rechazado ya y no tenga oferta activa"""
        request = self.context.get('request')
        solicitud = attrs.get('solicitud')
        
        if not request or not request.user:
            raise serializers.ValidationError('Usuario no autenticado')
        
        user = request.user
        
        # Validar que el proveedor no haya rechazado ya esta solicitud
        if RechazoSolicitud.objects.filter(solicitud=solicitud, proveedor=user).exists():
            raise serializers.ValidationError(
                'Ya has rechazado esta solicitud anteriormente'
            )
        
        # Validar que el proveedor no tenga una oferta activa
        if OfertaProveedor.objects.filter(
            solicitud=solicitud,
            proveedor=user,
            estado__in=['enviada', 'vista', 'en_chat', 'aceptada', 'pendiente_pago', 'pagada']
        ).exists():
            raise serializers.ValidationError(
                'No puedes rechazar una solicitud donde ya tienes una oferta activa'
            )
        
        return attrs

class SolicitudServicioPublicaSerializer(GeoFeatureModelSerializer):
    """Serializer para solicitudes p?blicas con soporte geoespacial"""
    servicios_solicitados_detail = serializers.SerializerMethodField()
    proveedores_dirigidos_detail = serializers.SerializerMethodField()
    cliente_nombre = serializers.SerializerMethodField()
    cliente_info = serializers.SerializerMethodField()
    vehiculo_info = serializers.SerializerMethodField()
    direccion_usuario_info = serializers.SerializerMethodField()
    tiempo_restante = serializers.SerializerMethodField()
    puede_recibir_ofertas = serializers.SerializerMethodField()
    puede_ver_datos_cliente = serializers.SerializerMethodField()
    total_ofertas = serializers.IntegerField(read_only=True, default=0)
    total_rechazos = serializers.IntegerField(read_only=True, default=0)
    ofertas = serializers.SerializerMethodField()
    ofertas_secundarias = serializers.SerializerMethodField()
    estado_display = serializers.SerializerMethodField()
    tiene_ofertas_secundarias_pendientes = serializers.SerializerMethodField()
    estado_efectivo = serializers.SerializerMethodField()
    estado_display_efectivo = serializers.SerializerMethodField()
    rechazos = serializers.SerializerMethodField()
    oferta_seleccionada_detail = serializers.SerializerMethodField()
    puede_reenviar = serializers.SerializerMethodField()
    fotos_necesidad = serializers.SerializerMethodField()
    fotos_necesidad_data = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=False,
        allow_empty=True,
        max_length=3,
        help_text='Hasta 3 imágenes en base64 o data URI (jpeg/png/webp)',
    )

    class Meta:
        model = SolicitudServicioPublica
        geo_field = 'ubicacion_servicio'
        fields = [
            'id', 'cliente', 'cliente_nombre', 'cliente_info', 'vehiculo', 'vehiculo_info',
            'vehiculo_inspeccion_precompra',
            'descripcion_problema', 'urgencia', 'requiere_repuestos', 'tipo_solicitud',
            'proveedores_dirigidos', 'proveedores_dirigidos_detail',
            'servicios_solicitados', 'servicios_solicitados_detail',
            'direccion_usuario', 'direccion_usuario_info',
            'ubicacion_servicio', 'direccion_servicio_texto', 'detalles_ubicacion',
            'fecha_preferida', 'hora_preferida', 'estado', 'estado_display', 'fecha_creacion',
            'fecha_publicacion', 'fecha_expiracion', 'fecha_limite_pago', 'tiempo_restante',
            'puede_recibir_ofertas', 'puede_ver_datos_cliente', 'total_ofertas', 'total_visualizaciones',
            'total_rechazos', 'oferta_seleccionada', 'oferta_seleccionada_detail', 'ofertas',
            'ofertas_secundarias', 'tiene_ofertas_secundarias_pendientes', 'estado_efectivo', 'estado_display_efectivo',
            'rechazos', 'puede_reenviar', 'fotos_necesidad', 'fotos_necesidad_data',
        ]
        read_only_fields = [
            'estado', 'fecha_creacion', 'fecha_publicacion', 'fecha_limite_pago',
            'total_ofertas', 'total_visualizaciones', 'total_rechazos'
        ]
        extra_kwargs = {
            'fecha_expiracion': {'required': False, 'allow_null': True}
        }
    
    def get_estado_display(self, obj):
        """Retorna el estado en formato legible para humanos (estado real de la solicitud)"""
        estado_dict = {
            'creada': 'Creada',
            'seleccionando_servicios': 'Seleccionando Servicios',
            'publicada': 'Publicada',
            'con_ofertas': 'Con Ofertas',
            'esperando_creditos_proveedor': 'Esperando confirmación del proveedor (créditos)',
            'adjudicada': 'Adjudicada',
            'pendiente_pago': 'Pendiente de Pago',
            'pagada': 'Pagada',
            'en_ejecucion': 'En Ejecución',
            'completada': 'Completada',
            'expirada': 'Expirada',
            'cancelada': 'Cancelada',
        }
        return estado_dict.get(obj.estado, obj.estado.replace('_', ' ').title())

    ESTADOS_OFERTA_SECUNDARIA_PENDIENTES = [
        'enviada', 'vista', 'en_chat', 'pendiente_creditos', 'aceptada', 'pendiente_pago',
        'pagada_parcialmente', 'pagada', 'en_ejecucion'
    ]

    def get_tiene_ofertas_secundarias_pendientes(self, obj):
        """True si hay ofertas secundarias que el usuario aún debe aceptar/rechazar o pagar"""
        return any(
            o.estado in self.ESTADOS_OFERTA_SECUNDARIA_PENDIENTES
            for o in obj.ofertas.all()
            if o.es_oferta_secundaria
        )

    def get_estado_efectivo(self, obj):
        """Estado para UI: si hay ofertas secundarias pendientes, priorizar eso sobre completada/finalizada"""
        if self.get_tiene_ofertas_secundarias_pendientes(obj):
            return 'ofertas_adicionales_pendientes'
        return obj.estado

    def get_estado_display_efectivo(self, obj):
        """Texto del estado efectivo para tags/badges: no mostrar Completada si hay ofertas por revisar"""
        if self.get_tiene_ofertas_secundarias_pendientes(obj):
            return 'Ofertas adicionales por revisar'
        return self.get_estado_display(obj)

    def get_fotos_necesidad(self, obj):
        request = self.context.get('request')
        out = []
        for f in obj.fotos_necesidad.all():
            out.append({
                'id': str(f.id),
                'imagen_url': get_image_url(f.imagen, request) if f.imagen else None,
                'orden': f.orden,
            })
        return out

    def validate_fotos_necesidad_data(self, value):
        if not value:
            return []
        for item in value:
            if not isinstance(item, str) or not str(item).strip():
                raise serializers.ValidationError('Cada foto debe ser una cadena base64 o data URI válida.')
            try:
                decode_foto_solicitud_base64(item)
            except ValueError as e:
                raise serializers.ValidationError(str(e))
        return value

    def get_servicios_solicitados_detail(self, obj):
        """
        Retorna los detalles de los servicios solicitados con información de categoría e imágenes
        """
        servicios = obj.servicios_solicitados.all()
        servicios_data = []
        request = self.context.get('request')
        
        for servicio in servicios:
            servicio_dict = {
                'id': servicio.id,
                'nombre': servicio.nombre,
                'descripcion': servicio.descripcion,
                'foto': get_image_url(servicio.foto, request) if servicio.foto else None
            }
            
            # Obtener la primera categoría principal (sin padre) o la primera categoría disponible
            categorias = servicio.categorias.all()
            if categorias.exists():
                # Buscar categoría principal (sin padre) primero
                categoria_principal = categorias.filter(categoria_padre__isnull=True).first()
                if not categoria_principal:
                    # Si no hay principal, tomar la primera disponible
                    categoria_principal = categorias.first()
                
                if categoria_principal:
                    servicio_dict['categoria'] = categoria_principal.nombre
                    servicio_dict['categoria_id'] = categoria_principal.id
                    servicio_dict['categoria_icono'] = categoria_principal.icono
            else:
                servicio_dict['categoria'] = None
                servicio_dict['categoria_id'] = None
                servicio_dict['categoria_icono'] = None
            
            servicios_data.append(servicio_dict)
        
        return servicios_data
    
    def get_proveedores_dirigidos_detail(self, obj):
        if obj.tipo_solicitud == 'dirigida':
            return UsuarioSerializer(
                obj.proveedores_dirigidos.all(), 
                many=True, 
                context=self.context
            ).data
        return []
    
    def get_cliente_nombre(self, obj):
        """Retorna el nombre del cliente, pero solo si el proveedor puede ver los datos"""
        request = self.context.get('request')
        if request and request.user:
            # Si es el cliente mismo o admin, mostrar nombre completo
            if hasattr(request.user, 'cliente') and request.user.cliente == obj.cliente:
                return obj.cliente.usuario.get_full_name() if obj.cliente.usuario else f"{obj.cliente.nombre} {obj.cliente.apellido}"
            elif request.user.is_staff:
                return obj.cliente.usuario.get_full_name() if obj.cliente.usuario else f"{obj.cliente.nombre} {obj.cliente.apellido}"
            # Si es proveedor, verificar si tiene oferta aceptada
            elif hasattr(request.user, 'taller') or hasattr(request.user, 'mecanico_domicilio'):
                puede_ver = self._proveedor_puede_ver_datos_cliente(request.user, obj)
                if puede_ver:
                    return obj.cliente.usuario.get_full_name() if obj.cliente.usuario else f"{obj.cliente.nombre} {obj.cliente.apellido}"
                else:
                    return "Cliente"  # Nombre gen?rico si no puede ver datos
        return obj.cliente.usuario.get_full_name() if obj.cliente.usuario else f"{obj.cliente.nombre} {obj.cliente.apellido}"
    
    def get_cliente_info(self, obj):
        """Retorna informaci?n del cliente incluyendo nombre y foto de perfil"""
        request = self.context.get('request')
        nombre = "Cliente"  # Valor por defecto
        foto_perfil = None
        
        # Los proveedores pueden ver nombre y foto cuando est?n viendo solicitudes p?blicas
        # para decidir si ofertar. Solo se oculta informaci?n sensible (tel?fono, email, direcci?n exacta)
        puede_ver_info_basica = False
        if request and request.user:
            # Cliente propio, admin, o cualquier proveedor puede ver info b?sica
            if hasattr(request.user, 'cliente') and request.user.cliente == obj.cliente:
                puede_ver_info_basica = True
            elif request.user.is_staff:
                puede_ver_info_basica = True
            elif hasattr(request.user, 'taller') or hasattr(request.user, 'mecanico_domicilio'):
                sel = obj.oferta_seleccionada
                if (
                    sel
                    and sel.proveedor_id == request.user.id
                    and (
                        obj.estado == 'esperando_creditos_proveedor'
                        or sel.estado == 'pendiente_creditos'
                    )
                ):
                    puede_ver_info_basica = False
                else:
                    puede_ver_info_basica = True
        
        # Obtener nombre
        if puede_ver_info_basica:
            nombre = obj.cliente.usuario.get_full_name() if obj.cliente.usuario else f"{obj.cliente.nombre} {obj.cliente.apellido}"
        
        # Obtener foto de perfil si existe
        if puede_ver_info_basica:
            try:
                foto_perfil = get_image_url(obj.cliente.usuario.foto_perfil, request) if obj.cliente and obj.cliente.usuario else None
            except (AttributeError, ValueError):
                foto_perfil = None
        
        return {
            'nombre': nombre,
            'foto_perfil': foto_perfil
        }
    
    def _proveedor_puede_ver_datos_cliente(self, user, solicitud):
        """Proveedor ve datos sensibles solo tras adjudicación confirmada (no en reserva por créditos)."""
        sel = solicitud.oferta_seleccionada
        if not sel or sel.proveedor != user:
            return False
        if solicitud.estado == 'esperando_creditos_proveedor' or sel.estado == 'pendiente_creditos':
            return False
        if solicitud.estado == 'adjudicada' and sel.estado == 'aceptada':
            return True
        if solicitud.estado in ('pendiente_pago', 'pagada', 'en_ejecucion', 'completada'):
            return True
        return False
    
    def get_tiempo_restante(self, obj):
        return obj.tiempo_restante
    
    def get_puede_recibir_ofertas(self, obj):
        return obj.puede_recibir_ofertas
    
    def get_ofertas(self, obj):
        # Solo incluir ofertas originales (no secundarias) si el usuario es el cliente o admin
        request = self.context.get('request')
        if request and request.user:
            if hasattr(request.user, 'cliente') and request.user.cliente == obj.cliente:
                # Filtrar solo ofertas originales (no secundarias) usando python para aprovechar prefetch
                ofertas_originales = [o for o in obj.ofertas.all() if not o.es_oferta_secundaria]
                return OfertaProveedorSerializer(ofertas_originales, many=True, context=self.context).data
            elif request.user.is_staff:
                ofertas_originales = [o for o in obj.ofertas.all() if not o.es_oferta_secundaria]
                return OfertaProveedorSerializer(ofertas_originales, many=True, context=self.context).data
        return []
    
    def get_ofertas_secundarias(self, obj):
        """Retorna todas las ofertas secundarias de la solicitud"""
        import logging
        logger = logging.getLogger(__name__)
        
        request = self.context.get('request')
        
        if request and request.user:
            if hasattr(request.user, 'cliente') and request.user.cliente == obj.cliente:
                # Obtener todas las ofertas secundarias usando python
                ofertas_secundarias = [o for o in obj.ofertas.all() if o.es_oferta_secundaria]
                return OfertaProveedorSerializer(ofertas_secundarias, many=True, context=self.context).data
            elif request.user.is_staff:
                ofertas_secundarias = [o for o in obj.ofertas.all() if o.es_oferta_secundaria]
                return OfertaProveedorSerializer(ofertas_secundarias, many=True, context=self.context).data
        
        return []
    
    def get_oferta_seleccionada_detail(self, obj):
        """Retorna el detalle completo de la oferta seleccionada si existe"""
        if obj.oferta_seleccionada:
            return OfertaProveedorSerializer(obj.oferta_seleccionada, context=self.context).data
        return None
    
    def get_rechazos(self, obj):
        """Retorna los rechazos de la solicitud"""
        request = self.context.get('request')
        if request and request.user:
            # Cliente puede ver todos los rechazos de su solicitud
            if hasattr(request.user, 'cliente') and request.user.cliente == obj.cliente:
                return RechazoSolicitudSerializer(obj.rechazos.all(), many=True, context=self.context).data
            # Admin puede ver todos los rechazos
            elif request.user.is_staff:
                return RechazoSolicitudSerializer(obj.rechazos.all(), many=True, context=self.context).data
            # Proveedor solo puede ver su propio rechazo
            elif hasattr(request.user, 'taller') or hasattr(request.user, 'mecanico_domicilio'):
                rechazos = obj.rechazos.all()
                rechazo_propio = [r for r in rechazos if r.proveedor_id == request.user.id]
                if rechazo_propio:
                    return RechazoSolicitudSerializer(rechazo_propio, many=True, context=self.context).data
        return []
    
    def get_puede_reenviar(self, obj):
        """Indica si el cliente puede reenviar la solicitud"""
        return obj.puede_reenviar()
    
    def get_vehiculo_info(self, obj):
        """Retorna info del vehículo; None si la solicitud no tiene vehículo (ej. vehículo eliminado)."""
        if not obj.vehiculo:
            return None
        return {
            'id': obj.vehiculo.id,
            'marca': obj.vehiculo.marca_nombre if hasattr(obj.vehiculo, 'marca_nombre') else str(obj.vehiculo.marca),
            'modelo': obj.vehiculo.modelo_nombre if hasattr(obj.vehiculo, 'modelo_nombre') else str(obj.vehiculo.modelo),
            'año': obj.vehiculo.year if hasattr(obj.vehiculo, 'year') else None,
            'anio': obj.vehiculo.year if hasattr(obj.vehiculo, 'year') else None,  # Alias para compatibilidad
            'patente': obj.vehiculo.patente if hasattr(obj.vehiculo, 'patente') else None,
            'kilometraje': obj.vehiculo.kilometraje if hasattr(obj.vehiculo, 'kilometraje') else None,
            'tipo_motor': obj.vehiculo.tipo_motor if hasattr(obj.vehiculo, 'tipo_motor') else None,
            'cilindraje': obj.vehiculo.cilindraje if hasattr(obj.vehiculo, 'cilindraje') else None,
        }
    
    def get_direccion_usuario_info(self, obj):
        """Retorna informaci?n de direcci?n, pero oculta datos sensibles si el proveedor no puede verlos"""
        request = self.context.get('request')
        puede_ver = True
        
        if request and request.user:
            # Si es el cliente mismo o admin, mostrar todo
            if hasattr(request.user, 'cliente') and request.user.cliente == obj.cliente:
                puede_ver = True
            elif request.user.is_staff:
                puede_ver = True
            # Si es proveedor, verificar si tiene oferta aceptada
            elif hasattr(request.user, 'taller') or hasattr(request.user, 'mecanico_domicilio'):
                puede_ver = self._proveedor_puede_ver_datos_cliente(request.user, obj)
        
        if obj.direccion_usuario:
            if puede_ver:
                return {
                    'id': obj.direccion_usuario.id,
                    'direccion': obj.direccion_usuario.direccion,
                    'etiqueta': obj.direccion_usuario.etiqueta,
                    'detalles': obj.direccion_usuario.detalles
                }
            else:
                # Solo mostrar direcci?n de texto (ya est? en direccion_servicio_texto)
                return {
                    'id': None,
                    'direccion': obj.direccion_servicio_texto,
                    'etiqueta': None,
                    'detalles': None
                }
        return None
    
    def get_puede_ver_datos_cliente(self, obj):
        """Indica si el usuario actual puede ver los datos completos del cliente"""
        request = self.context.get('request')
        if request and request.user:
            # Si es el cliente mismo o admin, puede ver todo
            if hasattr(request.user, 'cliente') and request.user.cliente == obj.cliente:
                return True
            elif request.user.is_staff:
                return True
            # Si es proveedor, verificar si tiene oferta aceptada
            elif hasattr(request.user, 'taller') or hasattr(request.user, 'mecanico_domicilio'):
                return self._proveedor_puede_ver_datos_cliente(request.user, obj)
        return False
    
    def to_representation(self, instance):
        """Oculta campos sensibles del cliente si el proveedor no puede verlos"""
        data = super().to_representation(instance)
        request = self.context.get('request')
        
        if request and request.user:
            puede_ver = True
            # Si es el cliente mismo o admin, puede ver todo
            if hasattr(request.user, 'cliente') and request.user.cliente == instance.cliente:
                puede_ver = True
            elif request.user.is_staff:
                puede_ver = True
            # Si es proveedor, verificar si tiene oferta aceptada
            elif hasattr(request.user, 'taller') or hasattr(request.user, 'mecanico_domicilio'):
                puede_ver = self._proveedor_puede_ver_datos_cliente(request.user, instance)
            
            # Ocultar campo cliente si no puede ver datos
            if not puede_ver:
                data['cliente'] = None
                # Tambi?n ocultar direccion_usuario (ID) pero mantener direccion_usuario_info con datos limitados
                data['direccion_usuario'] = None
        
        return data
    
    def validate_proveedores_dirigidos(self, value):
        """Validar m?ximo 5 proveedores para solicitud dirigida"""
        if len(value) > 5:
            raise serializers.ValidationError(
                "No puedes seleccionar m?s de 5 proveedores para una solicitud dirigida."
            )
        return value
    
    def validate_fecha_expiracion(self, value):
        """
        Validar fecha_expiracion: si no est? presente o es None, establecer autom?ticamente (48 horas)
        Este m?todo se ejecuta despu?s de to_internal_value() pero antes de validate()
        """
        if value is None:
            # Fallback: usar regla de expiración por defecto basada en fecha_preferida (si viene).
            initial = getattr(self, 'initial_data', None) or {}
            fecha_raw = initial.get('fecha_preferida')
            fecha_pref = None
            try:
                if isinstance(fecha_raw, str) and fecha_raw:
                    fecha_pref = datetime.strptime(fecha_raw, '%Y-%m-%d').date()
            except Exception:
                fecha_pref = None
            return SolicitudServicioPublica.compute_default_fecha_expiracion(
                now=timezone.now(),
                fecha_preferida=fecha_pref,
            )
        return value
    
    def to_internal_value(self, data):
        """
        Convertir ubicacion_servicio a formato GeoJSON Geometry y establecer fecha_expiracion
        antes de la validaci?n. GeoFeatureModelSerializer espera formato: {"type": "Point", "coordinates": [lng, lat]}
        """
        # Establecer fecha_expiracion automáticamente si no está presente.
        # Regla: si fecha_preferida es "mañana", expira en 2 horas; si no, en 48 horas.
        # Esto debe hacerse ANTES de la validaci?n para que DRF no falle
        # Usar formato ISO 8601 que DRF puede parsear correctamente
        if isinstance(data, dict):
            if 'fecha_expiracion' not in data or not data.get('fecha_expiracion'):
                fecha_pref = None
                try:
                    fecha_raw = data.get('fecha_preferida')
                    if isinstance(fecha_raw, str) and fecha_raw:
                        fecha_pref = datetime.strptime(fecha_raw, '%Y-%m-%d').date()
                except Exception:
                    fecha_pref = None

                fecha_expiracion = SolicitudServicioPublica.compute_default_fecha_expiracion(
                    now=timezone.now(),
                    fecha_preferida=fecha_pref,
                )
                # Formato ISO 8601 est?ndar que DRF puede parsear correctamente
                data['fecha_expiracion'] = fecha_expiracion.isoformat()
        
        # Si viene como dict con longitude/latitude, convertir a GeoJSON Geometry
        # GeoFeatureModelSerializer espera formato GeoJSON est?ndar
        if isinstance(data, dict) and 'ubicacion_servicio' in data:
            ubicacion = data['ubicacion_servicio']
            if isinstance(ubicacion, dict):
                # Si ya est? en formato GeoJSON Geometry, validarlo y asegurar que sea correcto
                if ubicacion.get('type') == 'Point' and 'coordinates' in ubicacion:
                    coords = ubicacion['coordinates']
                    if isinstance(coords, list) and len(coords) >= 2:
                        # Validar y normalizar coordenadas
                        try:
                            lng = float(coords[0])
                            lat = float(coords[1])
                            # Validar rango de coordenadas
                            if not (-180 <= lng <= 180) or not (-90 <= lat <= 90):
                                raise serializers.ValidationError({
                                    'ubicacion_servicio': 'Coordenadas fuera de rango v?lido'
                                })
                            # Asegurar formato GeoJSON correcto
                            data['ubicacion_servicio'] = {
                                'type': 'Point',
                                'coordinates': [lng, lat]
                            }
                        except (ValueError, TypeError, IndexError) as e:
                            raise serializers.ValidationError({
                                'ubicacion_servicio': f'Coordenadas inv?lidas: {str(e)}'
                            })
                else:
                    # Intentar convertir desde longitude/latitude
                    lng = ubicacion.get('longitude') or ubicacion.get('lng')
                    lat = ubicacion.get('latitude') or ubicacion.get('lat')
                    
                    if lng is not None and lat is not None:
                        try:
                            lng = float(lng)
                            lat = float(lat)
                            # Validar rango de coordenadas
                            if not (-180 <= lng <= 180) or not (-90 <= lat <= 90):
                                raise serializers.ValidationError({
                                    'ubicacion_servicio': 'Coordenadas fuera de rango v?lido'
                                })
                            # Convertir a formato GeoJSON Geometry
                            data['ubicacion_servicio'] = {
                                'type': 'Point',
                                'coordinates': [lng, lat]
                            }
                        except (ValueError, TypeError) as e:
                            raise serializers.ValidationError({
                                'ubicacion_servicio': f'Error convirtiendo coordenadas: {str(e)}'
                            })
                    else:
                        raise serializers.ValidationError({
                            'ubicacion_servicio': 'Formato de ubicaci?n inv?lido. Se espera GeoJSON Point o {longitude, latitude}'
                        })
        
        return super().to_internal_value(data)
    
    def validate(self, attrs):
        """
        Validaci?n adicional antes de crear la solicitud
        """
        request = self.context.get('request')

        # Flujo opcional sin vehículo registrado (ej. inspección precompra): el cliente
        # debe enviar explícitamente sin_vehiculo_registrado=true para no exigir vehiculo.
        # Así no se afecta el flujo actual que siempre envía vehiculo.
        initial = getattr(self, 'initial_data', None) or {}
        raw_sv = initial.get('sin_vehiculo_registrado')
        sin_vehiculo = raw_sv is True or str(raw_sv).lower() == 'true'

        # Flujo precompra sin vehículo: autocompletar descripción si viene vacía
        # para no bloquear creación por validación de campo requerido.
        descripcion_actual = str(attrs.get('descripcion_problema') or '').strip()
        if sin_vehiculo and not descripcion_actual:
            nombre_servicio = 'servicio'
            servicios = attrs.get('servicios_solicitados') or []
            try:
                primer_servicio = servicios[0] if isinstance(servicios, (list, tuple)) and servicios else None
                if primer_servicio is not None:
                    nombre_servicio = getattr(primer_servicio, 'nombre', None) or str(primer_servicio)
            except Exception:
                pass
            attrs['descripcion_problema'] = f'Solicitud de {nombre_servicio}'

        # Validar campos requeridos (vehiculo solo obligatorio si no es flujo sin vehículo)
        campos_requeridos = {
            'cliente': 'El cliente es requerido',
            'descripcion_problema': 'La descripci?n del problema es requerida',
            'ubicacion_servicio': 'La ubicaci?n del servicio es requerida',
            'fecha_preferida': 'La fecha preferida es requerida'
        }
        if not sin_vehiculo:
            campos_requeridos['vehiculo'] = 'El veh?culo es requerido'
        else:
            # Asegurar None explícito para que create no falle si no vino el campo
            if not attrs.get('vehiculo'):
                attrs['vehiculo'] = None

        for campo, mensaje in campos_requeridos.items():
            if campo not in attrs or not attrs.get(campo):
                raise serializers.ValidationError({campo: mensaje})
        
        # Validar que descripcion_problema no est? vac?a
        if attrs.get('descripcion_problema', '').strip() == '':
            raise serializers.ValidationError({
                'descripcion_problema': 'La descripci?n del problema no puede estar vac?a'
            })
        
        # Validar que fecha_expiracion est? presente (ya establecida en to_internal_value)
        if 'fecha_expiracion' not in attrs or not attrs.get('fecha_expiracion'):
            # Establecer autom?ticamente si no est? presente
            attrs['fecha_expiracion'] = timezone.now() + timedelta(hours=48)
        
        # Validar que direccion_servicio_texto est? presente
        # Si no est? presente, intentar obtenerlo de direccion_usuario si existe
        direccion_texto = attrs.get('direccion_servicio_texto')
        if not direccion_texto or (isinstance(direccion_texto, str) and direccion_texto.strip() == ''):
            if 'direccion_usuario' in attrs and attrs.get('direccion_usuario'):
                # Si hay una direccion_usuario, intentar obtener su direcci?n
                try:
                    from mecanimovilapp.apps.usuarios.models import DireccionUsuario
                    direccion_usuario_id = attrs['direccion_usuario']
                    if isinstance(direccion_usuario_id, int):
                        direccion_usuario = DireccionUsuario.objects.get(id=direccion_usuario_id)
                        attrs['direccion_servicio_texto'] = direccion_usuario.direccion or 'Direcci?n no especificada'
                    elif hasattr(direccion_usuario_id, 'direccion'):
                        attrs['direccion_servicio_texto'] = direccion_usuario_id.direccion or 'Direcci?n no especificada'
                except Exception as e:
                    # Si no se puede obtener, usar valor por defecto
                    logger.warning(f"No se pudo obtener direcci?n de direccion_usuario: {str(e)}")
                    attrs['direccion_servicio_texto'] = 'Direcci?n no especificada'
            else:
                # Si no hay direccion_usuario, validar que ubicacion_servicio tenga coordenadas v?lidas
                if 'ubicacion_servicio' in attrs and attrs.get('ubicacion_servicio'):
                    # Si hay ubicaci?n pero no texto, usar un valor por defecto
                    attrs['direccion_servicio_texto'] = 'Direcci?n no especificada'
                else:
                    raise serializers.ValidationError({
                        'direccion_servicio_texto': 'La direcci?n del servicio es requerida'
                    })
        
        # Validar que fecha_preferida sea una fecha futura o presente
        if 'fecha_preferida' in attrs and attrs.get('fecha_preferida'):
            fecha_preferida = attrs['fecha_preferida']
            if isinstance(fecha_preferida, str):
                try:
                    fecha_preferida = datetime.strptime(fecha_preferida, '%Y-%m-%d').date()
                    attrs['fecha_preferida'] = fecha_preferida
                except ValueError:
                    raise serializers.ValidationError({
                        'fecha_preferida': 'Formato de fecha inv?lido. Use YYYY-MM-DD'
                    })
            
            if isinstance(fecha_preferida, (datetime, date)):
                if isinstance(fecha_preferida, datetime):
                    fecha_preferida = fecha_preferida.date()
                    attrs['fecha_preferida'] = fecha_preferida
                # Permitir fechas presentes o futuras (no pasadas)
                if fecha_preferida < timezone.now().date():
                    raise serializers.ValidationError({
                        'fecha_preferida': 'La fecha preferida no puede ser en el pasado'
                    })

        # Misma solicitud activa: mismo vehículo + al menos un servicio ya pedido en otra solicitud abierta
        estados_bloquean_duplicado = [
            'creada', 'seleccionando_servicios', 'publicada', 'con_ofertas',
            'adjudicada', 'pendiente_pago', 'pagada', 'en_ejecucion',
        ]
        vehiculo_dup = attrs.get('vehiculo')
        servicios_dup = attrs.get('servicios_solicitados') or []
        if (
            not sin_vehiculo
            and vehiculo_dup
            and servicios_dup
            and request
            and hasattr(request.user, 'cliente')
        ):
            servicio_ids = []
            for s in servicios_dup:
                pk = getattr(s, 'pk', None)
                if pk is None and s is not None:
                    pk = getattr(s, 'id', None)
                if pk is not None:
                    servicio_ids.append(pk)
            if servicio_ids:
                existe = SolicitudServicioPublica.objects.filter(
                    cliente=request.user.cliente,
                    vehiculo=vehiculo_dup,
                    estado__in=estados_bloquean_duplicado,
                    servicios_solicitados__id__in=servicio_ids,
                ).distinct().exists()
                if existe:
                    raise serializers.ValidationError({
                        'servicios_solicitados': (
                            'Ya tienes una solicitud activa con uno o más de estos servicios para este '
                            'vehículo. Revisa Mis solicitudes o espera a que finalice.'
                        )
                    })

        # Inspección pre-compra (marketplace): mismo comprador no puede duplicar para el mismo
        # vehículo del vendedor mientras haya una solicitud "activa" (pipeline o completada con
        # ofertas secundarias pendientes).
        veh_ins = attrs.get('vehiculo_inspeccion_precompra')
        if veh_ins is not None and request and hasattr(request.user, 'cliente'):
            vid = getattr(veh_ins, 'pk', None) or getattr(veh_ins, 'id', None)
            if vid:
                base = SolicitudServicioPublica.objects.filter(
                    cliente=request.user.cliente,
                    vehiculo_inspeccion_precompra_id=vid,
                )
                if self.instance:
                    base = base.exclude(pk=self.instance.pk)
                activas_pipeline = base.filter(estado__in=estados_bloquean_duplicado).exists()
                activas_completada_con_secundarias = base.filter(
                    estado='completada',
                    ofertas__es_oferta_secundaria=True,
                    ofertas__estado__in=self.ESTADOS_OFERTA_SECUNDARIA_PENDIENTES,
                ).exists()
                if activas_pipeline or activas_completada_con_secundarias:
                    raise serializers.ValidationError({
                        'vehiculo_inspeccion_precompra': (
                            'Ya tienes una inspección pre-compra activa para este vehículo. '
                            'Revisa Mis solicitudes o espera a que finalice o expire.'
                        )
                    })

        return attrs
    
    def create(self, validated_data):
        # Extraer servicios y proveedores (ManyToMany)
        servicios = validated_data.pop('servicios_solicitados', [])
        proveedores = validated_data.pop('proveedores_dirigidos', [])
        fotos_raw = validated_data.pop('fotos_necesidad_data', None) or []

        # fecha_expiracion ya deber?a estar establecida en to_internal_value() y validate()
        # Si por alguna raz?n no est?, establecerla como respaldo
        if 'fecha_expiracion' not in validated_data or not validated_data.get('fecha_expiracion'):
            validated_data['fecha_expiracion'] = timezone.now() + timedelta(hours=48)
        
        # El campo ubicacion_servicio deber?a estar en formato GeoJSON Geometry
        # GeoFeatureModelSerializer lo convertir? autom?ticamente a Point
        # No necesitamos hacer conversi?n manual aqu?, GeoFeatureModelSerializer lo maneja
        
        # Crear solicitud
        # Nota: El modelo tiene un m?todo save() que tambi?n establece fecha_expiracion si no est? presente
        # Esto es una capa adicional de protecci?n
        try:
            solicitud = super().create(validated_data)
        except Exception as e:
            logger.error(f"Error en serializer.create(): {str(e)}", exc_info=True)
            logger.error(f"validated_data keys: {list(validated_data.keys())}")
            logger.error(f"fecha_expiracion en validated_data: {'fecha_expiracion' in validated_data}")
            if 'fecha_expiracion' in validated_data:
                logger.error(f"fecha_expiracion value: {validated_data['fecha_expiracion']}")
            if 'ubicacion_servicio' in validated_data:
                logger.error(f"ubicacion_servicio type: {type(validated_data['ubicacion_servicio'])}")
                logger.error(f"ubicacion_servicio value: {validated_data['ubicacion_servicio']}")
                # Si es un dict, mostrar el contenido
                if isinstance(validated_data['ubicacion_servicio'], dict):
                    logger.error(f"ubicacion_servicio dict: {validated_data['ubicacion_servicio']}")
            raise
        
        # Asignar servicios y proveedores
        if servicios:
            solicitud.servicios_solicitados.set(servicios)
        if proveedores:
            solicitud.proveedores_dirigidos.set(proveedores)

        for idx, raw in enumerate(fotos_raw[:3]):
            cf = decode_foto_solicitud_base64(raw)
            FotoSolicitudPublica.objects.create(
                solicitud=solicitud,
                imagen=cf,
                orden=idx + 1,
            )

        return solicitud

class ChatSolicitudSerializer(serializers.ModelSerializer):
    """Serializer para mensajes de chat"""
    enviado_por_nombre = serializers.CharField(source='enviado_por.get_full_name', read_only=True)
    solicitud_detail = serializers.SerializerMethodField()
    proveedor_info = serializers.SerializerMethodField()
    cliente_info = serializers.SerializerMethodField()
    
    class Meta:
        model = ChatSolicitud
        fields = [
            'id', 'oferta', 'mensaje', 'enviado_por', 'enviado_por_nombre',
            'es_proveedor', 'fecha_envio', 'leido', 'fecha_lectura',
            'archivo_adjunto', 'solicitud_detail', 'proveedor_info', 'cliente_info'
        ]
        read_only_fields = ['id', 'enviado_por', 'enviado_por_nombre', 'fecha_envio', 'es_proveedor', 'leido', 'fecha_lectura', 'solicitud_detail', 'proveedor_info', 'cliente_info']
    
    def get_solicitud_detail(self, obj):
        """Retorna informaci?n b?sica de la solicitud original asociada a la oferta"""
        solicitud = obj.oferta.solicitud
        servicios_nombres = list(solicitud.servicios_solicitados.values_list('nombre', flat=True))
        
        # Obtener informaci?n del modelo de manera segura
        modelo_nombre = None
        if solicitud.vehiculo and solicitud.vehiculo.modelo:
            if hasattr(solicitud.vehiculo.modelo, 'nombre'):
                modelo_nombre = solicitud.vehiculo.modelo.nombre
            elif isinstance(solicitud.vehiculo.modelo, str):
                modelo_nombre = solicitud.vehiculo.modelo
        
        return {
            'id': str(solicitud.id),
            'descripcion_problema': solicitud.descripcion_problema or '',  # ? Corregido
            'servicios_solicitados': servicios_nombres,
            'direccion_servicio_texto': solicitud.direccion_servicio_texto,
            'detalles_ubicacion': solicitud.detalles_ubicacion or '',
            'fecha_preferida': solicitud.fecha_preferida.strftime('%Y-%m-%d') if solicitud.fecha_preferida else None,
            'hora_preferida': solicitud.hora_preferida.strftime('%H:%M:%S') if solicitud.hora_preferida else None,
            'urgencia': solicitud.urgencia,
            'vehiculo': {
                'marca': solicitud.vehiculo.marca.nombre if solicitud.vehiculo and solicitud.vehiculo.marca else None,
                'modelo': modelo_nombre,
                'year': solicitud.vehiculo.year if solicitud.vehiculo else None,
                'patente': solicitud.vehiculo.patente if solicitud.vehiculo else None,
            } if solicitud.vehiculo else None
        }
    
    def get_proveedor_info(self, obj):
        """Retorna informaci?n del proveedor de la oferta"""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            oferta = obj.oferta
            proveedor = oferta.proveedor
            request = self.context.get('request')
            
            logger.info(f"?? get_proveedor_info - Oferta ID: {oferta.id}")
            logger.info(f"?? Proveedor: {proveedor}")
            logger.info(f"?? Nombre proveedor: {oferta.nombre_proveedor}")
            logger.info(f"?? Request presente: {request is not None}")
            
            # Obtener foto del proveedor usando helper de cPanel
            foto_url = get_image_url(proveedor.foto_perfil, request) if proveedor else None
            
            resultado = {
                'id': proveedor.id if proveedor else None,
                'nombre': oferta.nombre_proveedor or 'Proveedor',
                'foto': foto_url,
                'tipo': oferta.tipo_proveedor,
            }
            logger.info(f"? proveedor_info resultado: {resultado}")
            return resultado
        except Exception as e:
            logger.error(f"? Error en get_proveedor_info: {e}")
            return {
                'id': None,
                'nombre': 'Proveedor',
                'foto': None,
                'tipo': None,
            }
    
    def get_cliente_info(self, obj):
        """Retorna informaci?n del cliente de la solicitud"""
        try:
            solicitud = obj.oferta.solicitud
            cliente = solicitud.cliente
            request = self.context.get('request')
            
            # Obtener foto del cliente usando helper de cPanel
            foto_url = get_image_url(cliente.usuario.foto_perfil, request) if cliente and cliente.usuario else None
            
            # Obtener nombre del cliente
            nombre = 'Cliente'
            try:
                if cliente and cliente.usuario:
                    nombre = cliente.usuario.get_full_name()
            except (AttributeError, Exception):
                pass
            
            return {
                'id': cliente.id if cliente else None,
                'nombre': nombre,
                'foto': foto_url,
            }
        except Exception as e:
            return {
                'id': None,
                'nombre': 'Cliente',
                'foto': None,
            }
    
    def create(self, validated_data):
        mensaje = super().create(validated_data)
        
        # TODO: Enviar notificaci?n push al destinatario
        # TODO: Enviar evento WebSocket
        
        return mensaje 