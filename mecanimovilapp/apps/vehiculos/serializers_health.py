from rest_framework import serializers
from .models_health import (
    ComponenteSaludConfig,
    EstadoSaludVehiculo,
    ComponenteSaludVehiculo,
    AlertaMantenimiento
)
from .serializers import VehiculoSerializer
from mecanimovilapp.apps.servicios.serializers import ServicioSerializer


class ComponenteSaludConfigSerializer(serializers.ModelSerializer):
    """
    Serializador para ComponenteSaludConfig
    """
    tipo_medicion_display = serializers.CharField(
        source='get_tipo_medicion_display', 
        read_only=True
    )
    servicio_asociado_nombre = serializers.CharField(
        source='servicio_asociado.nombre',
        read_only=True
    )
    
    class Meta:
        model = ComponenteSaludConfig
        fields = (
            'id', 'nombre', 'descripcion', 'tipo_medicion', 'tipo_medicion_display',
            'beta', 'eta', 'km_critico', 'meses_critico', 'factor_edad_vehiculo',
            'factor_uso_intensivo', 'servicio_asociado', 'servicio_asociado_nombre',
            'activo', 'orden_visualizacion', 'icono', 'fecha_creacion', 'fecha_actualizacion'
        )


class ComponenteSaludVehiculoSerializer(serializers.ModelSerializer):
    """
    Serializador para ComponenteSaludVehiculo
    Incluye información del componente config y colores según nivel de alerta
    """
    componente_config_detail = ComponenteSaludConfigSerializer(
        source='componente_config',
        read_only=True
    )
    nivel_alerta_display = serializers.CharField(
        source='get_nivel_alerta_display',
        read_only=True
    )
    color = serializers.SerializerMethodField()
    nombre = serializers.CharField(
        source='componente_config.nombre',
        read_only=True
    )
    icono = serializers.CharField(
        source='componente_config.icono',
        read_only=True
    )
    
    class Meta:
        model = ComponenteSaludVehiculo
        fields = (
            'id', 'vehiculo', 'componente_config', 'componente_config_detail',
            'salud_porcentaje', 'nivel_alerta', 'nivel_alerta_display', 'color',
            'km_ultimo_servicio', 'fecha_ultimo_servicio', 'km_estimados_restantes',
            'dias_estimados_restantes', 'fecha_estimada_servicio',
            'requiere_servicio_inmediato', 'mensaje_alerta', 'nombre', 'icono',
            'ultima_actualizacion', 'actualizado_automaticamente'
        )
    
    def get_color(self, obj):
        """
        Retorna el color según el nivel de alerta
        """
        nivel = obj.nivel_alerta
        if nivel == 'OPTIMO':
            return '#4CAF50'  # Verde
        elif nivel == 'ATENCION':
            return '#FF9800'  # Naranja
        elif nivel == 'URGENTE':
            return '#F44336'  # Rojo
        elif nivel == 'CRITICO':
            return '#D32F2F'  # Rojo oscuro
        return '#9E9E9E'  # Gris por defecto


class AlertaMantenimientoSerializer(serializers.ModelSerializer):
    """
    Serializador para AlertaMantenimiento
    Incluye servicios recomendados y prioridad formateada
    """
    servicios_recomendados_detail = ServicioSerializer(
        source='servicios_recomendados',
        many=True,
        read_only=True
    )
    tipo_alerta_display = serializers.CharField(
        source='get_tipo_alerta_display',
        read_only=True
    )
    prioridad_display = serializers.SerializerMethodField()
    componente_salud_detail = ComponenteSaludVehiculoSerializer(
        source='componente_salud',
        read_only=True
    )
    
    class Meta:
        model = AlertaMantenimiento
        fields = (
            'id', 'vehiculo', 'componente_salud', 'componente_salud_detail',
            'tipo_alerta', 'tipo_alerta_display', 'titulo', 'descripcion',
            'prioridad', 'prioridad_display', 'servicios_recomendados',
            'servicios_recomendados_detail', 'costo_estimado', 'activa',
            'vista_por_usuario', 'fecha_vista', 'fecha_creacion', 'fecha_resolucion'
        )
    
    def get_prioridad_display(self, obj):
        """
        Retorna la prioridad en formato legible
        """
        prioridades = {
            1: 'Baja',
            2: 'Media-Baja',
            3: 'Media',
            4: 'Alta',
            5: 'Crítica'
        }
        return prioridades.get(obj.prioridad, 'Media')


class EstadoSaludVehiculoSerializer(serializers.ModelSerializer):
    """
    Serializador para EstadoSaludVehiculo
    Incluye información del vehículo y fecha formateada
    """
    vehiculo_detail = VehiculoSerializer(source='vehiculo', read_only=True)
    fecha_calculo_formatted = serializers.SerializerMethodField()
    
    class Meta:
        model = EstadoSaludVehiculo
        fields = (
            'id', 'vehiculo', 'vehiculo_detail', 'salud_general_porcentaje',
            'kilometraje_snapshot', 'fecha_calculo', 'fecha_calculo_formatted',
            'total_componentes_evaluados', 'componentes_optimos', 'componentes_atencion',
            'componentes_urgentes', 'componentes_criticos', 'tiene_alertas_activas',
            'costo_estimado_mantenimiento'
        )
    
    def get_fecha_calculo_formatted(self, obj):
        """
        Retorna la fecha de cálculo formateada
        """
        if obj.fecha_calculo:
            return obj.fecha_calculo.strftime('%Y-%m-%d %H:%M:%S')
        return None

