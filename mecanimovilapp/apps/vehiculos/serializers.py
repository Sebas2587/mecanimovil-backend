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
    foto = serializers.SerializerMethodField()  # Cambiar a SerializerMethodField para devolver URL completa
    
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
            'cliente': {'write_only': True}
        }
    
    def get_foto(self, obj):
        """Retorna la URL completa de la foto del vehículo"""
        import logging
        logger = logging.getLogger(__name__)
        
        if obj.foto:
            request = self.context.get('request')
            if request:
                # Construir URL completa
                foto_url = obj.foto.url  # Esto devuelve algo como '/media/vehiculos/vehicle_xxx.jpg'
                absolute_url = request.build_absolute_uri(foto_url)
                logger.info(f"📸 [VehiculoSerializer] Vehículo {obj.id} - Foto URL relativa: {foto_url}")
                logger.info(f"📸 [VehiculoSerializer] Vehículo {obj.id} - Foto URL absoluta: {absolute_url}")
                logger.info(f"📸 [VehiculoSerializer] Vehículo {obj.id} - Foto name: {obj.foto.name}")
                return absolute_url
            # Fallback si no hay request (por ejemplo, en tests)
            from django.conf import settings
            if hasattr(settings, 'MEDIA_URL'):
                fallback_url = f"{settings.MEDIA_URL}{obj.foto.name}"
                logger.warning(f"⚠️ [VehiculoSerializer] Vehículo {obj.id} - Sin request, usando fallback: {fallback_url}")
                return fallback_url
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