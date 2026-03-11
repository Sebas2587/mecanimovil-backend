from rest_framework import serializers
from .models_health import (
    ComponenteSalud,
    EstadoSaludVehiculo,
    ComponenteSaludVehiculo,
    AlertaMantenimiento
)
from .serializers import VehiculoSerializer
from mecanimovilapp.apps.servicios.serializers import ServicioSerializer


class ComponenteSaludSerializer(serializers.ModelSerializer):
    """
    Serializador para ComponenteSalud (Maestro)
    """
    class Meta:
        model = ComponenteSalud
        fields = (
            'id', 'nombre', 'slug', 'descripcion', 'es_critico', 
            'icono', 'orden_visualizacion'
        )


class ComponenteSaludVehiculoSerializer(serializers.ModelSerializer):
    """
    Serializador para ComponenteSaludVehiculo
    Incluye información del componente maestro y colores según nivel de alerta
    """
    componente_detail = ComponenteSaludSerializer(
        source='componente',
        read_only=True
    )
    nivel_alerta_display = serializers.CharField(
        source='get_nivel_alerta_display',
        read_only=True
    )
    color = serializers.SerializerMethodField()
    nombre = serializers.CharField(
        source='componente.nombre',
        read_only=True
    )
    icono = serializers.CharField(
        source='componente.icono',
        read_only=True
    )
    # Servicios ligados al componente maestro (Admin: ComponenteSalud.servicios_asociados)
    servicios_asociados = serializers.SerializerMethodField()

    class Meta:
        model = ComponenteSaludVehiculo
        fields = (
            'id', 'vehiculo', 'componente', 'componente_detail',
            'salud_porcentaje', 'nivel_alerta', 'nivel_alerta_display', 'color',
            'km_ultimo_servicio', 'fecha_ultimo_servicio', 'km_estimados_restantes',
            'requiere_servicio_inmediato', 'mensaje_alerta', 'nombre', 'icono',
            'ultima_actualizacion', 'servicios_asociados'
        )

    def get_servicios_asociados(self, obj):
        """Lista ligera para cards en modal (id, nombre, descripcion, precio_referencia)."""
        if not obj.componente_id:
            return []
        try:
            qs = obj.componente.servicios_asociados.all()
        except Exception:
            return []
        out = []
        for s in qs:
            out.append({
                'id': s.id,
                'nombre': s.nombre,
                'descripcion': (s.descripcion or '')[:300],
                'precio_referencia': float(s.precio_referencia) if s.precio_referencia is not None else None,
            })
        return out
    
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

