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
        """Retorna la URL completa de la foto del vehículo usando cPanel si está configurado"""
        # Usar el helper centralizado para construir URLs
        from mecanimovilapp.storage.utils import get_image_url
        request = self.context.get('request')
        return get_image_url(obj.foto, request)
    
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
        Crear vehículo asegurando que la foto use el storage correcto (cPanel)
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
            storage_class = getattr(settings, 'DEFAULT_FILE_STORAGE', None)
            if storage_class:
                from django.utils.module_loading import import_string
                try:
                    storage = import_string(storage_class)()
                    filename = storage.save(foto_file.name, foto_file)
                    vehiculo.foto = filename
                    vehiculo.save()
                    logger.info(f"✅ Foto de vehículo {vehiculo.id} guardada en storage: {filename}")
                except Exception as e:
                    logger.error(f"❌ Error guardando foto de vehículo: {e}")
                    vehiculo.foto = foto_file
                    vehiculo.save()
            else:
                vehiculo.foto = foto_file
                vehiculo.save()
        
        return vehiculo
    
    def update(self, instance, validated_data):
        """
        Actualizar vehículo asegurando que la foto use el storage correcto (cPanel)
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
            # Eliminar la foto anterior si existe
            if instance.foto:
                try:
                    instance.foto.delete()
                except:
                    pass
            
            storage_class = getattr(settings, 'DEFAULT_FILE_STORAGE', None)
            if storage_class:
                from django.utils.module_loading import import_string
                try:
                    storage = import_string(storage_class)()
                    filename = storage.save(foto_file.name, foto_file)
                    instance.foto = filename
                    logger.info(f"✅ Foto de vehículo {instance.id} actualizada: {filename}")
                except Exception as e:
                    logger.error(f"❌ Error actualizando foto de vehículo: {e}")
                    instance.foto = foto_file
            else:
                instance.foto = foto_file
        
        instance.save()
        return instance