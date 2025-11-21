from rest_framework import serializers
from .models import VehiculoActivo, PerfilVehiculo, RecomendacionPersonalizada
from mecanimovilapp.apps.vehiculos.serializers import VehiculoSerializer
from mecanimovilapp.apps.servicios.serializers import ServicioListSerializer, OfertaServicioSerializer


class VehiculoActivoSerializer(serializers.ModelSerializer):
    """
    Serializer para el modelo VehiculoActivo
    """
    vehiculo_detalle = VehiculoSerializer(source='vehiculo', read_only=True)
    
    class Meta:
        model = VehiculoActivo
        fields = ('id', 'vehiculo', 'vehiculo_detalle', 'fecha_seleccion')
        read_only_fields = ('fecha_seleccion',)


class PerfilVehiculoSerializer(serializers.ModelSerializer):
    """
    Serializer para el modelo PerfilVehiculo
    """
    vehiculo_info = VehiculoSerializer(source='vehiculo', read_only=True)
    
    class Meta:
        model = PerfilVehiculo
        fields = (
            'id', 'vehiculo', 'vehiculo_info', 'servicios_realizados',
            'gasto_promedio_mensual', 'frecuencia_mantenimiento',
            'categorias_frecuentes', 'talleres_frecuentes', 'mecanicos_frecuentes',
            'km_ultimo_servicio', 'dias_ultimo_servicio', 'score_mantenimiento_urgente',
            'fecha_actualizacion', 'fecha_calculo'
        )
        read_only_fields = ('fecha_actualizacion', 'fecha_calculo')


class RecomendacionPersonalizadaSerializer(serializers.ModelSerializer):
    """
    Serializer para el modelo RecomendacionPersonalizada
    """
    servicio_detalle = ServicioListSerializer(source='servicio', read_only=True)
    oferta_detalle = OfertaServicioSerializer(source='oferta_servicio', read_only=True)
    tipo_display = serializers.CharField(source='get_tipo_display', read_only=True)
    ctr = serializers.FloatField(read_only=True)
    
    class Meta:
        model = RecomendacionPersonalizada
        fields = (
            'id', 'tipo', 'tipo_display', 'servicio', 'servicio_detalle',
            'oferta_servicio', 'oferta_detalle', 'score_relevancia',
            'razon_recomendacion', 'fecha_generacion', 'fecha_expiracion',
            'veces_mostrada', 'veces_clickeada', 'convertida', 'ctr'
        )
        read_only_fields = (
            'fecha_generacion', 'veces_mostrada', 'veces_clickeada', 'convertida'
        ) 