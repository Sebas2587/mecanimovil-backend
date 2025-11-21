"""
Tareas asíncronas de Celery para el sistema de salud vehicular
Permiten calcular la salud de vehículos sin bloquear requests HTTP
"""
try:
    from celery import shared_task
    CELERY_AVAILABLE = True
except ImportError:
    # Celery no está disponible, crear decorador dummy
    def shared_task(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    CELERY_AVAILABLE = False

from django.core.cache import cache
from django.utils import timezone
from django.db.models import Avg, Count, Q
from datetime import timedelta
import logging

from .models_health import (
    ComponenteSaludConfig,
    EstadoSaludVehiculo,
    ComponenteSaludVehiculo,
    AlertaMantenimiento
)
from .utils.cache_health import (
    invalidate_vehicle_health_cache,
    set_cached_health,
    get_cache_key
)

logger = logging.getLogger(__name__)


def calcular_estado_salud_interno(vehicle_id):
    """
    Función helper para calcular el estado de salud de un vehículo
    Esta función puede ser llamada desde tareas Celery o sincrónicamente
    
    Args:
        vehicle_id: ID del vehículo
    
    Returns:
        EstadoSaludVehiculo: Objeto con el estado calculado
    """
    from .models import Vehiculo
    
    try:
        vehiculo = Vehiculo.objects.get(id=vehicle_id)
    except Vehiculo.DoesNotExist:
        logger.error(f"Vehículo {vehicle_id} no encontrado")
        raise
    
    # Obtener o crear componentes de salud para todos los configs activos
    configs = ComponenteSaludConfig.objects.filter(activo=True)
    
    for config in configs:
        ComponenteSaludVehiculo.objects.get_or_create(
            vehiculo=vehiculo,
            componente_config=config,
            defaults={
                'km_ultimo_servicio': 0,
                'salud_porcentaje': 100,
                'nivel_alerta': 'OPTIMO',
            }
        )
    
    # Recalcular todos los componentes
    componentes = ComponenteSaludVehiculo.objects.filter(vehiculo=vehiculo)
    for comp in componentes:
        comp.calcular_salud()
    
    # Calcular métricas generales usando agregación
    stats = componentes.aggregate(
        salud_promedio=Avg('salud_porcentaje'),
        total=Count('id'),
        optimos=Count('id', filter=Q(nivel_alerta='OPTIMO')),
        atencion=Count('id', filter=Q(nivel_alerta='ATENCION')),
        urgentes=Count('id', filter=Q(nivel_alerta='URGENTE')),
        criticos=Count('id', filter=Q(nivel_alerta='CRITICO')),
    )
    
    # Calcular costo estimado de alertas activas
    alertas = AlertaMantenimiento.objects.filter(vehiculo=vehiculo, activa=True)
    costo_total = sum(float(a.costo_estimado) for a in alertas)
    
    # Crear o actualizar snapshot del estado
    estado, created = EstadoSaludVehiculo.objects.update_or_create(
        vehiculo=vehiculo,
        defaults={
            'salud_general_porcentaje': stats['salud_promedio'] or 0,
            'kilometraje_snapshot': vehiculo.kilometraje,
            'total_componentes_evaluados': stats['total'],
            'componentes_optimos': stats['optimos'],
            'componentes_atencion': stats['atencion'],
            'componentes_urgentes': stats['urgentes'],
            'componentes_criticos': stats['criticos'],
            'tiene_alertas_activas': alertas.exists(),
            'costo_estimado_mantenimiento': costo_total,
        }
    )
    
    return estado


@shared_task(bind=True, max_retries=3)
def calcular_salud_vehiculo_async(self, vehicle_id, force_recalculate=False):
    """
    Calcula la salud del vehículo de forma asíncrona
    NO bloquea el request HTTP
    
    Args:
        vehicle_id: ID del vehículo
        force_recalculate: Si True, recalcula aunque esté en cache
    
    Returns:
        dict: Datos de salud calculados
    """
    try:
        # Verificar si ya está en cache y no se fuerza recálculo
        if not force_recalculate:
            cached = cache.get(get_cache_key(vehicle_id, 'health_calculation'))
            if cached:
                logger.info(f"Salud de vehículo {vehicle_id} ya está en cache")
                return cached
        
        # Calcular salud (esto puede tardar 1-2 segundos)
        estado = calcular_estado_salud_interno(vehicle_id)
        
        # Guardar en cache
        data = {
            'salud_general_porcentaje': estado.salud_general_porcentaje,
            'componentes_optimos': estado.componentes_optimos,
            'componentes_atencion': estado.componentes_atencion,
            'componentes_urgentes': estado.componentes_urgentes,
            'componentes_criticos': estado.componentes_criticos,
            'fecha_calculo': estado.fecha_calculo.isoformat(),
        }
        
        set_cached_health(vehicle_id, data, 'health_calculation', timeout=3600)
        
        logger.info(f"Salud de vehículo {vehicle_id} calculada exitosamente")
        return data
        
    except Exception as exc:
        logger.error(f"Error calculando salud de vehículo {vehicle_id}: {str(exc)}")
        # Reintentar después de 30 segundos
        raise self.retry(exc=exc, countdown=30)


@shared_task
def actualizar_salud_desde_checklist(checklist_id, vehicle_id):
    """
    Actualiza salud cuando se completa un checklist
    Se ejecuta automáticamente vía signal
    
    Args:
        checklist_id: ID del checklist completado
        vehicle_id: ID del vehículo
    """
    try:
        from .models_health import ComponenteSaludVehiculo
        from .models import Vehiculo
        from ..checklists.models import ChecklistInstance
        
        # Invalidar cache
        invalidate_vehicle_health_cache(vehicle_id)
        
        # Obtener checklist y vehículo
        try:
            checklist = ChecklistInstance.objects.get(id=checklist_id)
            vehiculo = Vehiculo.objects.get(id=vehicle_id)
        except (ChecklistInstance.DoesNotExist, Vehiculo.DoesNotExist):
            logger.error(f"Checklist {checklist_id} o vehículo {vehicle_id} no encontrado")
            return
        
        # Mapeo de items del checklist a componentes de salud
        mapeo_componentes = {
            'aceite_motor': ['Cambio de Aceite', 'Nivel de aceite', 'Aceite motor'],
            'filtro_aire': ['Filtro de Aire', 'Filtro aire'],
            'filtro_aceite': ['Filtro de Aceite', 'Filtro aceite'],
            'bujias': ['Bujías', 'Bujias', 'Cambio de bujías'],
            'bateria': ['Batería', 'Bateria', 'Cambio de batería'],
            'neumaticos': ['Neumáticos', 'Neumaticos', 'Llantas', 'Cambio de neumáticos'],
            'pastillas_freno': ['Pastillas de Freno', 'Pastillas freno'],
            'discos_freno': ['Discos de Freno', 'Discos freno'],
            'amortiguadores': ['Amortiguadores', 'Suspensión'],
            'correa_distribucion': ['Correa de Distribución', 'Correa distribución'],
            'liquido_frenos': ['Líquido de Frenos', 'Liquido frenos'],
            'refrigerante': ['Refrigerante', 'Líquido refrigerante'],
        }
        
        # Actualizar componentes basados en el checklist
        for respuesta in checklist.respuestas.all():
            item_nombre = respuesta.item_template.catalog_item.nombre if respuesta.item_template.catalog_item else ''
            
            for componente_key, items_relacionados in mapeo_componentes.items():
                if any(item.lower() in item_nombre.lower() for item in items_relacionados):
                    try:
                        config = ComponenteSaludConfig.objects.filter(
                            nombre__icontains=componente_key
                        ).first()
                        
                        if config:
                            comp_salud, created = ComponenteSaludVehiculo.objects.get_or_create(
                                vehiculo=vehiculo,
                                componente_config=config,
                                defaults={
                                    'km_ultimo_servicio': vehiculo.kilometraje,
                                    'fecha_ultimo_servicio': checklist.fecha_finalizacion or timezone.now(),
                                    'checklist_ultimo_servicio': checklist,
                                    'salud_porcentaje': 100,
                                    'nivel_alerta': 'OPTIMO',
                                }
                            )
                            
                            if not created:
                                comp_salud.km_ultimo_servicio = vehiculo.kilometraje
                                comp_salud.fecha_ultimo_servicio = checklist.fecha_finalizacion or timezone.now()
                                comp_salud.checklist_ultimo_servicio = checklist
                            
                            comp_salud.calcular_salud()
                    except Exception as e:
                        logger.warning(f"Error actualizando componente {componente_key}: {str(e)}")
        
        # Recalcular de forma asíncrona
        calcular_salud_vehiculo_async.delay(vehicle_id, force_recalculate=True)
        
        logger.info(f"Salud de vehículo {vehicle_id} actualizada desde checklist {checklist_id}")
        
    except Exception as e:
        logger.error(f"Error actualizando salud desde checklist: {str(e)}")


@shared_task
def recalcular_salud_vehiculos_batch():
    """
    Tarea periódica para recalcular salud de vehículos
    Se ejecuta cada 6 horas (no en cada request)
    Solo recalcula vehículos con actividad reciente
    """
    from .models import Vehiculo
    
    try:
        # Solo recalcular vehículos que han tenido actividad reciente (últimos 30 días)
        fecha_limite = timezone.now() - timedelta(days=30)
        
        vehiculos = Vehiculo.objects.filter(
            fecha_actualizacion__gte=fecha_limite
        ).values_list('id', flat=True)
        
        count = 0
        for vehicle_id in vehiculos:
            calcular_salud_vehiculo_async.delay(vehicle_id, force_recalculate=False)
            count += 1
        
        logger.info(f"Recálculo batch iniciado para {count} vehículos")
        return count
        
    except Exception as e:
        logger.error(f"Error en recálculo batch: {str(e)}")
        return 0

