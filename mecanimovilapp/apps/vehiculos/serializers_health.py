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
    slug = serializers.CharField(
        source='componente.slug',
        read_only=True
    )
    icono = serializers.CharField(
        source='componente.icono',
        read_only=True
    )
    # Servicios ligados al componente maestro (Admin: ComponenteSalud.servicios_asociados)
    servicios_asociados = serializers.SerializerMethodField()

    # Fuente del historial en formato legible para el frontend
    historial_fuente_display = serializers.CharField(
        source='get_historial_fuente_display',
        read_only=True,
    )
    # Nivel de confianza derivado de la fuente
    confianza_historial = serializers.SerializerMethodField()

    class Meta:
        model = ComponenteSaludVehiculo
        fields = (
            'id', 'vehiculo', 'componente', 'componente_detail',
            'salud_porcentaje', 'nivel_alerta', 'nivel_alerta_display', 'color',
            'km_ultimo_servicio', 'fecha_ultimo_servicio', 'km_estimados_restantes',
            'requiere_servicio_inmediato', 'mensaje_alerta', 'nombre', 'slug', 'icono',
            'historial_conocido', 'historial_fuente', 'historial_fuente_display',
            'confianza_historial', 'ultima_actualizacion', 'servicios_asociados',
            'salud_anclada_pct',
        )

    def get_servicios_asociados(self, obj):
        """Lista ligera ordenada por relevancia al componente (no genéricos primero)."""
        if not obj.componente_id:
            return []
        try:
            from .services.componente_servicio_sugerido import ordenar_servicios_asociados

            vehiculo = getattr(obj, 'vehiculo', None)
            tipo_motor_vehiculo = getattr(vehiculo, 'tipo_motor', None)
            slug = getattr(obj.componente, 'slug', None)
            qs = obj.componente.servicios_asociados.all()
            return ordenar_servicios_asociados(slug, qs, tipo_motor_vehiculo)
        except Exception:
            return []
    
    def get_confianza_historial(self, obj):
        """
        Nivel de confianza del historial para el frontend.
        Permite mostrar íconos/badges distintos según la fuente del dato.
        - alta:   Confirmado por checklist de taller (dato duro)
        - media:  Declarado por el usuario retroactivamente
        - baja:   Estimado automáticamente por el engine sin historial real
        """
        fuente = getattr(obj, 'historial_fuente', 'ENGINE')
        return {
            'CHECKLIST':         'alta',
            'REGISTRO_INICIAL':  'alta',
            'USUARIO_DECLARADO': 'media',
            'ENGINE':            'baja',
        }.get(fuente, 'baja')

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
    # Métricas de integridad: qué porcentaje de los componentes tiene datos
    # verificados por un taller (vs. estimados o declarados por el usuario).
    integridad_datos = serializers.SerializerMethodField()

    class Meta:
        model = EstadoSaludVehiculo
        fields = (
            'id', 'vehiculo', 'vehiculo_detail', 'salud_general_porcentaje',
            'kilometraje_snapshot', 'fecha_calculo', 'fecha_calculo_formatted',
            'total_componentes_evaluados', 'componentes_optimos', 'componentes_atencion',
            'componentes_urgentes', 'componentes_criticos', 'tiene_alertas_activas',
            'costo_estimado_mantenimiento', 'integridad_datos',
        )

    def get_fecha_calculo_formatted(self, obj):
        if obj.fecha_calculo:
            return obj.fecha_calculo.strftime('%Y-%m-%d %H:%M:%S')
        return None

    def get_integridad_datos(self, obj):
        """
        Resumen de integridad para el frontend y para compradores en el marketplace.

        Calcula cuántos componentes tienen datos verificados (CHECKLIST o REGISTRO_INICIAL)
        vs. declarados por el usuario vs. estimados automáticamente.

        Esto le permite a un comprador saber qué tan confiable es el historial
        que está viendo — es imposible de falsificar porque es derivado de la fuente
        real de cada dato en ComponenteSaludVehiculo.
        """
        try:
            componentes = ComponenteSaludVehiculo.objects.filter(
                vehiculo=obj.vehiculo
            ).values_list('historial_fuente', flat=True)

            total = len(componentes)
            if total == 0:
                return {'total': 0, 'verificados': 0, 'declarados': 0, 'estimados': 0, 'porcentaje_verificado': 0}

            fuentes_verificadas = {'CHECKLIST', 'REGISTRO_INICIAL'}
            verificados  = sum(1 for f in componentes if f in fuentes_verificadas)
            declarados   = sum(1 for f in componentes if f == 'USUARIO_DECLARADO')
            estimados    = sum(1 for f in componentes if f == 'ENGINE')

            porcentaje = round((verificados / total) * 100, 1)

            nivel_confianza = 'alta' if porcentaje >= 70 else ('media' if porcentaje >= 40 else 'baja')

            return {
                'total_componentes':      total,
                'verificados_taller':     verificados,
                'declarados_usuario':     declarados,
                'estimados_engine':       estimados,
                'porcentaje_verificado':  porcentaje,
                'nivel_confianza':        nivel_confianza,
                'advertencia': (
                    None if declarados == 0 else
                    f'{declarados} componente(s) con datos declarados por el propietario sin verificación de taller.'
                ),
            }
        except Exception:
            return None

