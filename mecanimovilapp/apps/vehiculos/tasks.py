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
import logging
# Mover imports pesados adentro de las tareas/funciones

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
    from django.db.models import Avg, Count, Q
    from .models import Vehiculo
    
    try:
        vehiculo = Vehiculo.objects.get(id=vehicle_id)
    except Vehiculo.DoesNotExist:
        logger.error(f"Vehículo {vehicle_id} no encontrado")
        raise
    
    # Determinar el tipo de motor del vehículo para filtrar componentes
    tipo_motor = vehiculo.tipo_motor
    
    # Mapear tipo de motor del vehículo a tipo de motor de componentes
    if tipo_motor and 'diesel' in tipo_motor.lower() or tipo_motor == 'Diésel':
        tipo_motor_filtro = 'DIESEL'
    else:
        tipo_motor_filtro = 'GASOLINA'
    
    logger.info(f"Calculando salud para vehículo {vehicle_id} con motor: {tipo_motor} -> filtro: {tipo_motor_filtro}")
    
    # Obtener configs activos que aplican a este tipo de motor
    # Incluir: TODOS + tipo específico del vehículo
    configs = ComponenteSaludConfig.objects.filter(
        activo=True
    ).filter(
        Q(tipo_motor_aplicable='TODOS') | Q(tipo_motor_aplicable=tipo_motor_filtro)
    )
    
    logger.info(f"Se encontraron {configs.count()} componentes aplicables para tipo motor {tipo_motor_filtro}")
    
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
    
    # NUEVO: Guardar salud previa para detectar caídas bruscas del 50%
    salud_previa = {comp.id: comp.salud_porcentaje for comp in componentes}
    
    for comp in componentes:
        comp.calcular_salud(commit=False)
        
        # ✅ NUEVO: Lógica de Alertas Push según requerimientos del usuario
        # 1. Si la salud baja a 0%
        # 2. Si la salud baja un 50% o más respecto al cálculo anterior
        prev_salud = salud_previa.get(comp.id, 100.0)
        caida = prev_salud - comp.salud_porcentaje
        
        if comp.salud_porcentaje == 0:
            enviar_alerta_salud_push(vehiculo, comp, "ha llegado al 0%")
        elif caida >= 50.0:
            enviar_alerta_salud_push(vehiculo, comp, f"ha bajado un {caida:.0f}% abruptamente")
            
    # ✅ OPTIMIZACIÓN: Guardar todos los componentes en una sola query
    ComponenteSaludVehiculo.objects.bulk_update(
        componentes, 
        [
            'salud_porcentaje', 'nivel_alerta', 'km_estimados_restantes', 
            'dias_estimados_restantes', 'requiere_servicio_inmediato', 'mensaje_alerta'
        ]
    )
    
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
    salud_global = stats['salud_promedio'] or 0
    estado, created = EstadoSaludVehiculo.objects.update_or_create(
        vehiculo=vehiculo,
        defaults={
            'salud_general_porcentaje': salud_global,
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

    # ✅ NUEVO: Alertas de Salud Global según requerimientos del usuario
    if salud_global == 0:
        enviar_alerta_salud_global_push(vehiculo, "es de 0%", es_critico=True)
    elif salud_global < 50.0:
        enviar_alerta_salud_global_push(vehiculo, f"es baja ({salud_global:.0f}%)", es_critico=False)
    
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
    
    IMPORTANTE: Esta función puede ejecutarse tanto con Celery (.delay()) 
    como directamente (sincrónicamente) como fallback.
    
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
        
        # ============================================
        # 1. ACTUALIZAR KILOMETRAJE DEL VEHÍCULO
        # ============================================
        # Buscar respuestas de tipo KILOMETER_INPUT en el checklist
        kilometraje_checklist = None
        for respuesta in checklist.respuestas.all():
            if respuesta.item_template.catalog_item and \
               respuesta.item_template.catalog_item.tipo_pregunta == 'KILOMETER_INPUT' and \
               respuesta.respuesta_numero is not None:
                kilometraje_checklist = int(float(respuesta.respuesta_numero))
                break
        
        # Si se encontró kilometraje en el checklist, actualizar el vehículo
        if kilometraje_checklist is not None:
            kilometraje_anterior = vehiculo.kilometraje
            diferencia_km = abs(kilometraje_checklist - kilometraje_anterior)
            
            # Actualizar si hay diferencia significativa (más de 1 km)
            if diferencia_km > 1:
                # Si el kilometraje del checklist es mayor, actualizar automáticamente
                if kilometraje_checklist > kilometraje_anterior:
                    vehiculo.kilometraje = kilometraje_checklist
                    vehiculo.save(update_fields=['kilometraje', 'fecha_actualizacion'])
                    logger.info(
                        f"✅ Kilometraje actualizado para vehículo {vehicle_id}: "
                        f"{kilometraje_anterior} km → {kilometraje_checklist} km "
                        f"(diferencia: +{diferencia_km} km)"
                    )
                else:
                    # Si el kilometraje del checklist es menor, crear alerta
                    logger.warning(
                        f"⚠️ Kilometraje del checklist ({kilometraje_checklist} km) es menor "
                        f"que el actual del vehículo ({kilometraje_anterior} km). "
                        f"No se actualiza automáticamente."
                    )
                    
                    # Crear alerta de mantenimiento si la diferencia es grande (>100 km)
                    if diferencia_km > 100:
                        try:
                            from .models_health import AlertaMantenimiento
                            
                            # Verificar si ya existe una alerta similar reciente
                            alerta_existente = AlertaMantenimiento.objects.filter(
                                vehiculo=vehiculo,
                                tipo_alerta='MANTENCION_POR_KM',
                                activa=True,
                                titulo__icontains='Kilometraje'
                            ).first()
                            
                            if not alerta_existente:
                                AlertaMantenimiento.objects.create(
                                    vehiculo=vehiculo,
                                    tipo_alerta='MANTENCION_POR_KM',
                                    titulo='⚠️ Discrepancia en Kilometraje Detectada',
                                    descripcion=(
                                        f"El kilometraje registrado en el checklist ({kilometraje_checklist:,} km) "
                                        f"es significativamente menor que el kilometraje actual del vehículo "
                                        f"({kilometraje_anterior:,} km). Diferencia: {diferencia_km:,} km. "
                                        f"Por favor, verifica y actualiza el kilometraje del vehículo si es necesario."
                                    ),
                                    prioridad=3,
                                    activa=True
                                )
                                logger.info(f"Alerta de discrepancia de kilometraje creada para vehículo {vehicle_id}")
                        except Exception as e:
                            logger.warning(f"Error creando alerta de kilometraje: {str(e)}")
        
        # Mapeo de items del checklist a componentes de salud
        # La clave es el nombre del ComponenteSaludConfig (debe coincidir exactamente)
        mapeo_componentes = {
            'Aceite Motor': ['Cambio de Aceite', 'Nivel de aceite', 'Aceite motor'],
            'Filtro de Aire': ['Filtro de Aire', 'Filtro aire'],
            'Filtro de Aceite': ['Filtro de Aceite', 'Filtro aceite'],
            'Bujías': ['Bujías', 'Bujias', 'Cambio de bujías'],
            'Batería': ['Batería', 'Bateria', 'Cambio de batería'],
            'Neumáticos': ['Neumáticos', 'Neumaticos', 'Llantas', 'Cambio de neumáticos'],
            'Pastillas de Freno': ['Pastillas de Freno', 'Pastillas freno'],
            'Discos de Freno': ['Discos de Freno', 'Discos freno'],
            'Amortiguadores': ['Amortiguadores', 'Suspensión'],
            'Correa de Distribución': ['Correa de Distribución', 'Correa distribución'],
            'Líquido de Frenos': ['Líquido de Frenos', 'Liquido frenos'],
            'Refrigerante': ['Refrigerante', 'Líquido refrigerante'],
        }
        
        # Actualizar componentes basados en el checklist
        componentes_para_actualizar = {}
        
        for respuesta in checklist.respuestas.all():
            item_nombre = respuesta.item_template.catalog_item.nombre if respuesta.item_template.catalog_item else ''
            
            for nombre_config, items_relacionados in mapeo_componentes.items():
                if any(item.lower() in item_nombre.lower() for item in items_relacionados):
                    try:
                        # Buscar el config por su nombre exacto
                        config = ComponenteSaludConfig.objects.filter(
                            nombre=nombre_config,
                            activo=True
                        ).first()
                        
                        if config:
                            comp_salud, created = ComponenteSaludVehiculo.objects.get_or_create(
                                vehiculo=vehiculo,
                                componente_config=config,
                                defaults={
                                    'km_ultimo_servicio': kilometraje_checklist if kilometraje_checklist else vehiculo.kilometraje,
                                    'fecha_ultimo_servicio': checklist.fecha_finalizacion or timezone.now(),
                                    'checklist_ultimo_servicio': checklist,
                                    'salud_porcentaje': 100,
                                    'nivel_alerta': 'OPTIMO',
                                }
                            )
                            
                            if not created:
                                # Usar el kilometraje del checklist si está disponible, sino el del vehículo
                                km_para_servicio = kilometraje_checklist if kilometraje_checklist else vehiculo.kilometraje
                                comp_salud.km_ultimo_servicio = km_para_servicio
                                comp_salud.fecha_ultimo_servicio = checklist.fecha_finalizacion or timezone.now()
                                comp_salud.checklist_ultimo_servicio = checklist
                            
                            comp_salud.calcular_salud(commit=False)
                            componentes_para_actualizar[comp_salud.id] = comp_salud
                    except Exception as e:
                        logger.warning(f"Error actualizando componente {nombre_config}: {str(e)}")
        
        # ✅ OPTIMIZACIÓN: bulk_update
        if componentes_para_actualizar:
            ComponenteSaludVehiculo.objects.bulk_update(
                list(componentes_para_actualizar.values()),
                ['km_ultimo_servicio', 'fecha_ultimo_servicio', 'checklist_ultimo_servicio', 
                 'salud_porcentaje', 'nivel_alerta', 'km_estimados_restantes', 
                 'dias_estimados_restantes', 'requiere_servicio_inmediato', 'mensaje_alerta']
            )
        
        # Recalcular de forma asíncrona
        calcular_salud_vehiculo_async.delay(vehicle_id, force_recalculate=True)
        
        # Obtener usuario del vehículo para notificaciones
        usuario = None
        try:
            if vehiculo.cliente and vehiculo.cliente.usuario:
                usuario = vehiculo.cliente.usuario
        except Exception as e:
            logger.warning(f"No se pudo obtener usuario del vehículo {vehicle_id}: {e}")
        
        # Enviar notificaciones WebSocket y Push
        if usuario:
            try:
                from channels.layers import get_channel_layer
                from asgiref.sync import async_to_sync
                
                channel_layer = get_channel_layer()
                if channel_layer:
                    # Obtener información del vehículo para el mensaje
                    vehiculo_info = f"{vehiculo.marca} {vehiculo.modelo}" if vehiculo.marca else f"Vehículo {vehicle_id}"
                    
                    # Contar componentes actualizados
                    componentes_actualizados = sum(
                        1 for respuesta in checklist.respuestas.all()
                        for nombre_config, items_relacionados in mapeo_componentes.items()
                        if any(item.lower() in (respuesta.item_template.catalog_item.nombre if respuesta.item_template.catalog_item else '').lower() 
                               for item in items_relacionados)
                    )
                    
                    # Enviar notificación WebSocket
                    async_to_sync(channel_layer.group_send)(
                        f"cliente_{usuario.id}",
                        {
                            'type': 'salud_vehiculo_actualizada',
                            'vehicle_id': str(vehicle_id),
                            'checklist_id': str(checklist_id),
                            'vehiculo_info': vehiculo_info,
                            'componentes_actualizados': componentes_actualizados,
                            'mensaje': f'Las métricas de salud de tu {vehiculo_info} han sido actualizadas',
                            'timestamp': timezone.now().isoformat()
                        }
                    )
                    logger.info(f"Notificación WebSocket enviada al usuario {usuario.id} para vehículo {vehicle_id}")
            except Exception as e:
                logger.error(f"Error enviando notificación WebSocket: {e}", exc_info=True)
        
        logger.info(f"Salud de vehículo {vehicle_id} actualizada desde checklist {checklist_id}")
        
    except Exception as e:
        logger.error(f"Error actualizando salud desde checklist: {str(e)}")


@shared_task(queue='heavy', time_limit=600, soft_time_limit=300)
def recalcular_salud_vehiculos_batch():
    """
    Tarea periódica para recalcular salud de vehículos
    Se ejecuta cada 6 horas (no en cada request)
    Solo recalcula vehículos con actividad reciente
    
    TAREA PESADA: Asignada a cola 'heavy' con límites de tiempo
    """
    from django.utils import timezone
    from datetime import timedelta
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


@shared_task(queue='heavy', time_limit=1200, soft_time_limit=900)
def procesar_checklists_historicos_batch(vehicle_ids=None, batch_size=10):
    """
    Procesa checklists históricos para múltiples vehículos en lotes
    
    TAREA PESADA: Asignada a cola 'heavy' con límites de tiempo extendidos
    
    Args:
        vehicle_ids: Lista de IDs de vehículos a procesar. Si es None, procesa todos.
        batch_size: Tamaño del lote para procesamiento
    
    Returns:
        dict: Estadísticas del procesamiento
    """
    from .models import Vehiculo
    from ..checklists.models import ChecklistInstance
    
    try:
        logger.info(f"🔄 Iniciando procesamiento batch de checklists históricos")
        
        # Determinar vehículos a procesar
        if vehicle_ids:
            vehiculos = Vehiculo.objects.filter(id__in=vehicle_ids)
        else:
            # Obtener todos los vehículos que tienen checklists completados
            checklists_completados = ChecklistInstance.objects.filter(
                estado='COMPLETADO',
                orden__isnull=False
            ).values_list('orden__vehiculo_id', flat=True).distinct()
            
            vehiculos = Vehiculo.objects.filter(id__in=checklists_completados).distinct()
        
        total_vehiculos = vehiculos.count()
        logger.info(f"📋 Encontrados {total_vehiculos} vehículos para procesar")
        
        if total_vehiculos == 0:
            return {
                'vehiculos_procesados': 0,
                'checklists_procesados': 0,
                'componentes_actualizados': 0,
                'errores': 0
            }
        
        # Procesar en lotes
        total_procesados = 0
        total_errores = 0
        total_checklists = 0
        total_componentes = 0
        
        for i in range(0, total_vehiculos, batch_size):
            batch = vehiculos[i:i + batch_size]
            
            for vehiculo in batch:
                try:
                    resultado = procesar_checklists_historicos_vehiculo(vehiculo.id)
                    if resultado:
                        total_checklists += resultado.get('checklists_procesados', 0)
                        total_componentes += resultado.get('componentes_actualizados', 0)
                        total_procesados += 1
                    else:
                        total_errores += 1
                except Exception as e:
                    total_errores += 1
                    logger.error(f"Error procesando vehículo {vehiculo.id}: {str(e)}")
        
        logger.info(
            f"✅ Procesamiento batch completado: {total_procesados} vehículos, "
            f"{total_checklists} checklists, {total_componentes} componentes actualizados"
        )
        
        return {
            'vehiculos_procesados': total_procesados,
            'checklists_procesados': total_checklists,
            'componentes_actualizados': total_componentes,
            'errores': total_errores
        }
        
    except Exception as e:
        logger.error(f"Error en procesamiento batch: {str(e)}", exc_info=True)
        return {
            'vehiculos_procesados': 0,
            'checklists_procesados': 0,
            'componentes_actualizados': 0,
            'errores': 1,
            'error': str(e)
        }


def _procesar_checklists_historicos_vehiculo_interno(vehicle_id):
    """
    Función interna que procesa checklists históricos.
    Esta función NO está decorada con @shared_task para poder ejecutarse
    directamente sin problemas cuando Celery está disponible.
    
    Args:
        vehicle_id: ID del vehículo
    
    Returns:
        dict: Resultado del procesamiento con estadísticas
    """
    try:
        from django.utils import timezone
        from .models_health import ComponenteSaludVehiculo, ComponenteSaludConfig
        from .models import Vehiculo
        from ..checklists.models import ChecklistInstance
        from ..ordenes.models import SolicitudServicio
        
        logger.info(f"🔄 Iniciando procesamiento de checklists históricos para vehículo {vehicle_id}")
        
        # Obtener vehículo
        try:
            vehiculo = Vehiculo.objects.get(id=vehicle_id)
        except Vehiculo.DoesNotExist:
            logger.error(f"Vehículo {vehicle_id} no encontrado")
            return {
                'checklists_procesados': 0,
                'componentes_actualizados': 0,
                'kilometraje_actualizado': False,
                'error': 'Vehículo no encontrado'
            }
        
        # Obtener todas las órdenes completadas del vehículo
        ordenes_completadas = SolicitudServicio.objects.filter(
            vehiculo=vehiculo,
            estado='completado'
        ).order_by('fecha_servicio')
        
        # Obtener checklists completados asociados a esas órdenes
        checklists_completados = ChecklistInstance.objects.filter(
            orden__in=ordenes_completadas,
            estado='COMPLETADO'
        ).select_related('orden', 'checklist_template').prefetch_related(
            'respuestas__item_template__catalog_item'
        ).order_by('fecha_finalizacion')
        
        checklists_count = checklists_completados.count()
        logger.info(f"📋 Encontrados {checklists_count} checklists completados para procesar")
        
        # Si no hay checklists, retornar resultado vacío pero válido
        if checklists_count == 0:
            logger.info(f"⚠️ No hay checklists completados para procesar en vehículo {vehicle_id}")
            return {
                'checklists_procesados': 0,
                'componentes_actualizados': 0,
                'kilometraje_actualizado': False
            }
        
        # Mapeo de items del checklist a componentes de salud
        # La clave es el nombre del ComponenteSaludConfig (debe coincidir exactamente)
        mapeo_componentes = {
            'Aceite Motor': ['Cambio de Aceite', 'Nivel de aceite', 'Aceite motor'],
            'Filtro de Aire': ['Filtro de Aire', 'Filtro aire'],
            'Filtro de Aceite': ['Filtro de Aceite', 'Filtro aceite'],
            'Bujías': ['Bujías', 'Bujias', 'Cambio de bujías'],
            'Batería': ['Batería', 'Bateria', 'Cambio de batería'],
            'Neumáticos': ['Neumáticos', 'Neumaticos', 'Llantas', 'Cambio de neumáticos'],
            'Pastillas de Freno': ['Pastillas de Freno', 'Pastillas freno'],
            'Discos de Freno': ['Discos de Freno', 'Discos freno'],
            'Amortiguadores': ['Amortiguadores', 'Suspensión'],
            'Correa de Distribución': ['Correa de Distribución', 'Correa distribución'],
            'Líquido de Frenos': ['Líquido de Frenos', 'Liquido frenos'],
            'Refrigerante': ['Refrigerante', 'Líquido refrigerante'],
        }
        
        componentes_actualizados = 0
        kilometraje_maximo_encontrado = vehiculo.kilometraje
        
        # Procesar cada checklist en orden cronológico
        for checklist in checklists_completados:
            # Extraer kilometraje del checklist si está disponible
            kilometraje_checklist = None
            for respuesta in checklist.respuestas.all():
                if respuesta.item_template.catalog_item and \
                   respuesta.item_template.catalog_item.tipo_pregunta == 'KILOMETER_INPUT' and \
                   respuesta.respuesta_numero is not None:
                    kilometraje_checklist = int(float(respuesta.respuesta_numero))
                    if kilometraje_checklist > kilometraje_maximo_encontrado:
                        kilometraje_maximo_encontrado = kilometraje_checklist
                    break
            
            # Procesar componentes del checklist
            for respuesta in checklist.respuestas.all():
                item_nombre = respuesta.item_template.catalog_item.nombre if respuesta.item_template.catalog_item else ''
                
                for nombre_config, items_relacionados in mapeo_componentes.items():
                    if any(item.lower() in item_nombre.lower() for item in items_relacionados):
                        try:
                            # Buscar el config por su nombre exacto
                            config = ComponenteSaludConfig.objects.filter(
                                nombre=nombre_config,
                                activo=True
                            ).first()
                            
                            if config:
                                # Usar kilometraje del checklist si está disponible, sino el del vehículo
                                km_para_servicio = kilometraje_checklist if kilometraje_checklist else vehiculo.kilometraje
                                
                                # Obtener o crear componente
                                comp_salud, created = ComponenteSaludVehiculo.objects.get_or_create(
                                    vehiculo=vehiculo,
                                    componente_config=config,
                                    defaults={
                                        'km_ultimo_servicio': km_para_servicio,
                                        'fecha_ultimo_servicio': checklist.fecha_finalizacion or timezone.now(),
                                        'checklist_ultimo_servicio': checklist,
                                        'salud_porcentaje': 100,
                                        'nivel_alerta': 'OPTIMO',
                                    }
                                )
                                
                                # Si el componente ya existía, actualizar solo si este checklist es más reciente
                                if not created:
                                    # Verificar si este checklist es más reciente que el último servicio registrado
                                    from datetime import datetime as dt
                                    fecha_ultimo = comp_salud.fecha_ultimo_servicio or timezone.make_aware(dt.min)
                                    fecha_checklist = checklist.fecha_finalizacion or timezone.now()
                                    
                                    if fecha_checklist >= fecha_ultimo:
                                        comp_salud.km_ultimo_servicio = km_para_servicio
                                        comp_salud.fecha_ultimo_servicio = fecha_checklist
                                        comp_salud.checklist_ultimo_servicio = checklist
                                        # NO guardamos todavía, lo haremos en bulk al final del proceso cronológico o por vehículo
                                        comp_salud.calcular_salud(commit=False)
                                        componentes_actualizados += 1
                                        logger.info(
                                            f"✅ Componente {config.nombre} preparado para actualización desde checklist histórico "
                                            f"{checklist.id}"
                                        )
                                else:
                                    comp_salud.calcular_salud(commit=False)
                                    componentes_actualizados += 1
                        except Exception as e:
                            logger.warning(f"Error procesando componente {nombre_config} del checklist {checklist.id}: {str(e)}")
        
        # Actualizar kilometraje del vehículo si se encontró uno mayor en los checklists
        kilometraje_actualizado = False
        if kilometraje_maximo_encontrado > vehiculo.kilometraje:
            diferencia = kilometraje_maximo_encontrado - vehiculo.kilometraje
            kilometraje_anterior = vehiculo.kilometraje
            vehiculo.kilometraje = kilometraje_maximo_encontrado
            vehiculo.save(update_fields=['kilometraje', 'fecha_actualizacion'])
            kilometraje_actualizado = True
            logger.info(
                f"✅ Kilometraje del vehículo actualizado desde checklists históricos: "
                f"{kilometraje_anterior} km → {kilometraje_maximo_encontrado} km "
                f"(diferencia: +{diferencia} km)"
            )
        
        # Recalcular salud de todos los componentes y guardar en bulk
        componentes = list(ComponenteSaludVehiculo.objects.filter(vehiculo=vehiculo))
        for comp in componentes:
            comp.calcular_salud(commit=False)
        
        if componentes:
            ComponenteSaludVehiculo.objects.bulk_update(
                componentes,
                ['km_ultimo_servicio', 'fecha_ultimo_servicio', 'checklist_ultimo_servicio',
                 'salud_porcentaje', 'nivel_alerta', 'km_estimados_restantes',
                 'dias_estimados_restantes', 'requiere_servicio_inmediato', 'mensaje_alerta']
            )
        
        # Recalcular estado general (usar Celery si está disponible, sino calcular directamente)
        try:
            if CELERY_AVAILABLE:
                calcular_salud_vehiculo_async.delay(vehicle_id, force_recalculate=True)
            else:
                # Si Celery no está disponible, calcular directamente
                calcular_estado_salud_interno(vehicle_id)
        except Exception as e:
            logger.warning(f"Error recalculando salud del vehículo {vehicle_id}: {str(e)}")
            # Intentar calcular directamente como fallback
            try:
                calcular_estado_salud_interno(vehicle_id)
            except Exception as e2:
                logger.error(f"Error calculando salud directamente: {str(e2)}")
        
        logger.info(
            f"✅ Procesamiento de checklists históricos completado para vehículo {vehicle_id}. "
            f"Componentes actualizados: {componentes_actualizados}"
        )
        
        return {
            'checklists_procesados': checklists_completados.count(),
            'componentes_actualizados': componentes_actualizados,
            'kilometraje_actualizado': kilometraje_actualizado
        }
        
    except Exception as e:
        logger.error(f"Error procesando checklists históricos para vehículo {vehicle_id}: {str(e)}", exc_info=True)
        return {
            'checklists_procesados': 0,
            'componentes_actualizados': 0,
            'kilometraje_actualizado': False,
            'error': str(e)
        }


@shared_task(queue='heavy', time_limit=600, soft_time_limit=300)
def procesar_checklists_historicos_vehiculo(vehicle_id):
    """
    Tarea Celery que procesa todos los checklists completados históricos de un vehículo.
    
    TAREA PESADA: Asignada a cola 'heavy' con límites de tiempo
    
    Esta función está decorada con @shared_task para ejecutarse con Celery.
    Internamente llama a _procesar_checklists_historicos_vehiculo_interno().
    
    Args:
        vehicle_id: ID del vehículo
    
    Returns:
        dict: Resultado del procesamiento con estadísticas
    """
    return _procesar_checklists_historicos_vehiculo_interno(vehicle_id)


def enviar_alerta_salud_push(vehiculo, componente, motivo_texto):
    """
    Función de apoyo para enviar notificaciones push de salud
    """
    try:
        if not (vehiculo.cliente and vehiculo.cliente.usuario):
            return
            
        user_id = vehiculo.cliente.usuario.id
        nombre_vehiculo = f"{vehiculo.marca} {vehiculo.modelo}" if vehiculo.marca else f"Vehículo {vehiculo.patente or ''}"
        nombre_componente = componente.componente_config.nombre
        
        # Evitar ruidos excesivos enviando alertas muy seguidas (throttling básico opcional)
        # Por ahora enviamos directamente como lo pide el usuario
        
        title = f"⚠️ Alerta de Salud: {nombre_componente}"
        body = f"La salud de {nombre_componente} en tu {nombre_vehiculo} {motivo_texto}. Te recomendamos agendar una revisión."
        
        from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification
        
        send_expo_push_notification.delay(
            user_id,
            title,
            body,
            {
                "type": "health_alert",
                "vehicle_id": str(vehiculo.id),
                "componente": nombre_componente,
                "salud": str(componente.salud_porcentaje)
            }
        )
        logger.info(f"📲 Alerta Push de salud enviada a usuario {user_id} para {nombre_componente}")
    except Exception as e:
        logger.error(f"Error en enviar_alerta_salud_push: {e}")


def enviar_alerta_salud_global_push(vehiculo, motivo_texto, es_critico=False):
    """
    Función de apoyo para enviar notificaciones push de salud global (recordatorios)
    """
    try:
        if not (vehiculo.cliente and vehiculo.cliente.usuario):
            return
            
        user_id = vehiculo.cliente.usuario.id
        nombre_vehiculo = f"{vehiculo.marca} {vehiculo.modelo}" if vehiculo.marca else f"Vehículo {vehiculo.patente or ''}"
        
        emoji = "🚨" if es_critico else "⚠️"
        nivel = "CRÍTICA" if es_critico else "Recordatorio"
        
        title = f"{emoji} Salud Global {nivel}: {nombre_vehiculo}"
        body = f"La salud general de tu {nombre_vehiculo} {motivo_texto}. Te recomendamos revisar los componentes afectados pronto."
        
        from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification
        
        send_expo_push_notification.delay(
            user_id,
            title,
            body,
            {
                "type": "global_health_alert",
                "vehicle_id": str(vehiculo.id),
                "es_critico": es_critico
            }
        )
        logger.info(f"📲 Alerta Push de salud GLOBAL enviada a usuario {user_id} para {nombre_vehiculo}")
    except Exception as e:
        logger.error(f"Error en enviar_alerta_salud_global_push: {e}")

