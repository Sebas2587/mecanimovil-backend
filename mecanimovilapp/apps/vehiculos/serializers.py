from rest_framework import serializers
from .models import Vehiculo, Marca, MarcaVehiculo, Modelo
from mecanimovilapp.apps.usuarios.serializers import ClienteSerializer


class MarcaVehiculoSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo MarcaVehiculo
    """
    class Meta:
        model = MarcaVehiculo
        fields = ('id', 'nombre')


# Mantenemos el serializador Marca para compatibilidad
class MarcaSerializer(MarcaVehiculoSerializer):
    """
    Serializador para el modelo Marca (Proxy de MarcaVehiculo)
    """
    class Meta(MarcaVehiculoSerializer.Meta):
        model = Marca


class ModeloSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo Modelo
    """
    marca_nombre = serializers.StringRelatedField(source='marca', read_only=True)
    
    class Meta:
        model = Modelo
        fields = ('id', 'nombre', 'marca', 'marca_nombre')


class VehiculoSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo Vehiculo
    """
    cliente_detail = ClienteSerializer(source='cliente', read_only=True)
    marca_nombre = serializers.ReadOnlyField()
    modelo_nombre = serializers.ReadOnlyField()
    
    # Mapeo de campos para compatibilidad con frontend
    año = serializers.ReadOnlyField(source='year')  # Mapear year -> año
    placa = serializers.ReadOnlyField(source='patente')  # Mapear patente -> placa
    
    # Campos adicionales que pueden no estar en el modelo pero el frontend espera
    color = serializers.SerializerMethodField()
    numero_motor = serializers.SerializerMethodField()
    numero_chasis = serializers.SerializerMethodField()
    
    # Campo foto: usar el campo del modelo directamente para escritura
    # Sobrescribir to_representation para devolver URL completa en lectura
    
    def __init__(self, *args, **kwargs):
        """Inicialización del serializer con logging"""
        super().__init__(*args, **kwargs)
        import logging
        logger = logging.getLogger(__name__)
        logger.warning("🔄 [VehiculoSerializer.__init__] Serializer inicializado - Código actualizado con soporte cPanel")
    
    class Meta:
        model = Vehiculo
        fields = (
            'id', 'marca', 'modelo', 'cilindraje', 'tipo_motor', 
            'year', 'año', 'patente', 'placa', 'kilometraje', 'foto', 'cliente',
            'cliente_detail', 'marca_nombre', 'modelo_nombre',
            'color', 'numero_motor', 'numero_chasis',
            'fecha_creacion', 'fecha_actualizacion'
        )
        extra_kwargs = {
            'cliente': {'write_only': True},
            'foto': {'required': False, 'allow_null': True}
        }
    
    def to_representation(self, instance):
        """
        Sobrescribir para devolver URL completa de foto en lectura
        """
        representation = super().to_representation(instance)
        # Reemplazar el valor de foto con la URL completa usando get_foto
        representation['foto'] = self.get_foto(instance)
        return representation
    
    def get_foto(self, obj):
        """Retorna la URL completa de la foto del vehículo"""
        import logging
        logger = logging.getLogger(__name__)
        
        # Log muy visible para verificar que el método se ejecuta
        logger.warning(f"🖼️ [VehiculoSerializer.get_foto] INICIANDO para vehículo {obj.id}")
        
        if obj.foto:
            from django.conf import settings
            
            # Verificar el tipo de storage configurado
            storage_type = getattr(settings, 'STORAGE_TYPE', 'local')
            default_storage = getattr(settings, 'DEFAULT_FILE_STORAGE', None)
            cpanel_media_url = getattr(settings, 'CPANEL_MEDIA_URL', '')
            cpanel_ftp_host = getattr(settings, 'CPANEL_FTP_HOST', '')
            
            logger.warning(f"🖼️ [VehiculoSerializer.get_foto] Vehículo {obj.id} - STORAGE_TYPE: {storage_type}")
            logger.warning(f"🖼️ [VehiculoSerializer.get_foto] Vehículo {obj.id} - DEFAULT_FILE_STORAGE: {default_storage}")
            logger.warning(f"🖼️ [VehiculoSerializer.get_foto] Vehículo {obj.id} - CPANEL_MEDIA_URL: {cpanel_media_url}")
            logger.warning(f"🖼️ [VehiculoSerializer.get_foto] Vehículo {obj.id} - CPANEL_FTP_HOST: {cpanel_ftp_host}")
            logger.warning(f"🖼️ [VehiculoSerializer.get_foto] Vehículo {obj.id} - Foto name: {obj.foto.name}")
            logger.warning(f"🖼️ [VehiculoSerializer.get_foto] Vehículo {obj.id} - Foto storage: {type(obj.foto.storage).__name__}")
            
            # Obtener la URL del storage
            try:
                foto_url = obj.foto.url
                logger.info(f"📸 [VehiculoSerializer] Vehículo {obj.id} - URL desde storage: {foto_url}")
                
                # Si la URL es relativa (empieza con /media), necesitamos construirla
                if foto_url and foto_url.startswith('/media/'):
                    # PRIORIDAD 1: Verificar si tenemos configuración de cPanel disponible
                    # (incluso si STORAGE_TYPE no está configurado, pero hay variables de entorno)
                    cpanel_media_url = getattr(settings, 'CPANEL_MEDIA_URL', '')
                    cpanel_ftp_host = getattr(settings, 'CPANEL_FTP_HOST', '')
                    
                    logger.warning(f"🖼️ [VehiculoSerializer.get_foto] Vehículo {obj.id} - Verificando cPanel: CPANEL_MEDIA_URL={bool(cpanel_media_url)}, CPANEL_FTP_HOST={bool(cpanel_ftp_host)}")
                    
                    # Si hay configuración de cPanel, usarla siempre
                    if cpanel_media_url:
                        # Construir URL completa de cPanel
                        relative_path = foto_url.replace('/media/', '')
                        full_url = f"{cpanel_media_url.rstrip('/')}/{relative_path}"
                        logger.warning(f"✅ [VehiculoSerializer.get_foto] Vehículo {obj.id} - URL CONSTRUIDA DE CPANEL: {full_url}")
                        logger.warning(f"✅ [VehiculoSerializer.get_foto] Vehículo {obj.id} - STORAGE_TYPE: {storage_type}, pero usando cPanel por configuración disponible")
                        return full_url
                    elif cpanel_ftp_host:
                        # Si hay FTP configurado pero no MEDIA_URL, intentar construirla
                        logger.warning(f"⚠️ [VehiculoSerializer.get_foto] Vehículo {obj.id} - CPANEL_FTP_HOST configurado pero CPANEL_MEDIA_URL no. Verifica variables de entorno.")
                    
                    # PRIORIDAD 2: Si STORAGE_TYPE es cpanel pero no hay CPANEL_MEDIA_URL
                    if storage_type == 'cpanel' and not cpanel_media_url:
                        logger.warning(f"⚠️ [VehiculoSerializer] Vehículo {obj.id} - STORAGE_TYPE=cpanel pero CPANEL_MEDIA_URL no está configurado")
                    
                    # PRIORIDAD 3: Si no hay cPanel, usar request para construir URL de Render
                    request = self.context.get('request')
                    if request:
                        absolute_url = request.build_absolute_uri(foto_url)
                        logger.warning(f"⚠️ [VehiculoSerializer.get_foto] Vehículo {obj.id} - URL absoluta construida (Render/local): {absolute_url}")
                        logger.warning(f"❌ [VehiculoSerializer.get_foto] Vehículo {obj.id} - ⚠️ USANDO URL DE RENDER. Las imágenes NO persistirán. Configura STORAGE_TYPE=cpanel y CPANEL_MEDIA_URL.")
                        return absolute_url
                    else:
                        # Fallback: usar MEDIA_URL
                        media_url = getattr(settings, 'MEDIA_URL', '/media/')
                        fallback_url = f"{media_url.rstrip('/')}/{obj.foto.name}"
                        logger.warning(f"⚠️ [VehiculoSerializer] Vehículo {obj.id} - Sin request, usando fallback: {fallback_url}")
                        return fallback_url
                else:
                    # La URL ya es completa (de cPanel o S3)
                    logger.info(f"✅ [VehiculoSerializer] Vehículo {obj.id} - URL completa desde storage: {foto_url}")
                    return foto_url
                    
            except Exception as e:
                logger.error(f"❌ [VehiculoSerializer] Vehículo {obj.id} - Error obteniendo URL: {e}")
                # Fallback: construir URL manualmente
                request = self.context.get('request')
                if request:
                    fallback_url = request.build_absolute_uri(f'/media/{obj.foto.name}')
                    logger.warning(f"⚠️ [VehiculoSerializer] Vehículo {obj.id} - Usando fallback con request: {fallback_url}")
                    return fallback_url
                return None
        else:
            logger.info(f"ℹ️ [VehiculoSerializer] Vehículo {obj.id} - No tiene foto")
        return None
    
    def get_color(self, obj):
        """Retorna el color del vehículo si está disponible"""
        # Por ahora retorna None ya que no existe en el modelo
        # En el futuro se puede agregar el campo al modelo
        return getattr(obj, 'color', None)
    
    def get_numero_motor(self, obj):
        """Retorna el número de motor si está disponible"""
        # Por ahora retorna None ya que no existe en el modelo
        # En el futuro se puede agregar el campo al modelo
        return getattr(obj, 'numero_motor', None)
    
    def get_numero_chasis(self, obj):
        """Retorna el número de chasis si está disponible"""
        # Por ahora retorna None ya que no existe en el modelo
        # En el futuro se puede agregar el campo al modelo
        return getattr(obj, 'numero_chasis', None)
    
    def validate(self, data):
        """
        Validar que el modelo pertenezca a la marca
        """
        if 'marca' in data and 'modelo' in data:
            if data['modelo'].marca != data['marca']:
                raise serializers.ValidationError(
                    {"modelo": "El modelo seleccionado no pertenece a la marca indicada."}
                )
        return data
    
    def create(self, validated_data):
        """
        Crear vehículo asegurando que la foto use el storage correcto
        """
        import logging
        from django.conf import settings
        
        logger = logging.getLogger(__name__)
        
        # Extraer la foto si existe
        foto_file = validated_data.pop('foto', None)
        
        # Crear el vehículo sin la foto primero
        vehiculo = Vehiculo.objects.create(**validated_data)
        
        # Si hay una foto, guardarla usando el storage correcto
        if foto_file:
            logger.warning(f"📸 [VehiculoSerializer.create] Guardando foto para vehículo {vehiculo.id}")
            
            # Obtener el storage configurado
            storage_class = getattr(settings, 'DEFAULT_FILE_STORAGE', None)
            if storage_class:
                from django.utils.module_loading import import_string
                try:
                    storage = import_string(storage_class)()
                    logger.warning(f"📸 [VehiculoSerializer.create] Usando storage: {type(storage).__name__}")
                    # Guardar el archivo usando el storage correcto
                    filename = storage.save(foto_file.name, foto_file)
                    vehiculo.foto = filename
                    vehiculo.save()
                    logger.warning(f"✅ [VehiculoSerializer.create] Foto guardada: {filename}")
                except Exception as e:
                    logger.error(f"❌ [VehiculoSerializer.create] Error guardando foto: {e}")
                    # Fallback: guardar normalmente
                    vehiculo.foto = foto_file
                    vehiculo.save()
            else:
                # Sin storage personalizado, guardar normalmente
                vehiculo.foto = foto_file
                vehiculo.save()
        
        return vehiculo
    
    def update(self, instance, validated_data):
        """
        Actualizar vehículo asegurando que la foto use el storage correcto
        """
        import logging
        from django.conf import settings
        
        logger = logging.getLogger(__name__)
        
        # Extraer la foto si existe
        foto_file = validated_data.pop('foto', None)
        
        # Actualizar otros campos
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        # Si hay una nueva foto, guardarla usando el storage correcto
        if foto_file:
            logger.warning(f"📸 [VehiculoSerializer.update] Guardando nueva foto para vehículo {instance.id}")
            
            # Eliminar la foto anterior si existe
            if instance.foto:
                try:
                    instance.foto.delete()
                except:
                    pass
            
            # Obtener el storage configurado
            storage_class = getattr(settings, 'DEFAULT_FILE_STORAGE', None)
            if storage_class:
                from django.utils.module_loading import import_string
                try:
                    storage = import_string(storage_class)()
                    logger.warning(f"📸 [VehiculoSerializer.update] Usando storage: {type(storage).__name__}")
                    # Guardar el archivo usando el storage correcto
                    filename = storage.save(foto_file.name, foto_file)
                    instance.foto = filename
                    logger.warning(f"✅ [VehiculoSerializer.update] Foto guardada: {filename}")
                except Exception as e:
                    logger.error(f"❌ [VehiculoSerializer.update] Error guardando foto: {e}")
                    # Fallback: guardar normalmente
                    instance.foto = foto_file
            else:
                # Sin storage personalizado, guardar normalmente
                instance.foto = foto_file
        
        instance.save()
        return instance 