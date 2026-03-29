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
import logging
# Mover imports pesados adentro de las tareas/funciones

from .models_health import (
    ComponenteSalud,
    EstadoSaludVehiculo,
    ComponenteSaludVehiculo,
    AlertaMantenimiento
)
from .services.health_engine import HealthEngine
from .utils.cache_health import (
    invalidate_vehicle_health_cache,
    set_cached_health,
    get_cache_key
)
from mecanimovilapp.apps.checklists.km_extraction import extraer_kilometraje_desde_checklist_instance

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
    # Capturar estado previo para alertas de caida abrupta
    # TODO: Optimizar: esto hace query, HealthEngine hace query.
    prev_components = {
        c.componente.id: c.salud_porcentaje 
        for c in ComponenteSaludVehiculo.objects.filter(vehiculo_id=vehicle_id)
    }

    # =========================================================
    # DELEGACIÓN AL HEALTH ENGINE (Arquitectura Cascada)
    # =========================================================
    reporte = HealthEngine.calcular_salud_vehiculo(vehicle_id)
    
    # Recuperar el estado global calculado por el engine
    try:
        estado_global = EstadoSaludVehiculo.objects.filter(vehiculo_id=vehicle_id).latest('fecha_calculo')
    except EstadoSaludVehiculo.DoesNotExist:
        logger.error(f"HealthEngine no generó estado para vehiculo {vehicle_id}")
        return None

    # =========================================================
    # LÓGICA DE NOTIFICACIONES (PUSH)
    # =========================================================
    vehiculo = estado_global.vehiculo
    
    # Check for abrupt drops or zero health in individual components
    # Re-fetch updated components to access alert flags set by Engine
    updated_components = ComponenteSaludVehiculo.objects.filter(vehiculo_id=vehicle_id).select_related('componente')
    
    for comp in updated_components:
        prev_salud = prev_components.get(comp.componente.id, 100.0)
        current_salud = comp.salud_porcentaje
        caida = prev_salud - current_salud
        
        # Enviar push si corresponde
        if current_salud == 0 and prev_salud > 0:
            enviar_alerta_salud_push(vehiculo, comp, "ha llegado al 0%")
        elif caida >= 50.0:
            enviar_alerta_salud_push(vehiculo, comp, f"ha bajado un {caida:.0f}% abruptamente")

    # Alertas Globales
    salud_global = estado_global.salud_general_porcentaje
    if salud_global == 0:
         enviar_alerta_salud_global_push(vehiculo, "es de 0%", es_critico=True)
    elif salud_global < 50.0 and salud_global > 0:
         enviar_alerta_salud_global_push(vehiculo, f"es baja ({salud_global:.0f}%)", es_critico=False)

    enviar_salud_actualizada_push(vehiculo, salud_global)

    return estado_global


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
        if not estado:
            return None
        # Refrescar snapshot por si ultima_actualizacion se actualizó vía update() en HealthEngine
        estado.refresh_from_db()

        # Guardar en cache
        data = {
            'salud_general_porcentaje': estado.salud_general_porcentaje,
            'componentes_optimos': estado.componentes_optimos,
            'componentes_atencion': estado.componentes_atencion,
            'componentes_urgentes': estado.componentes_urgentes,
            'componentes_criticos': estado.componentes_criticos,
            'fecha_calculo': estado.fecha_calculo.isoformat() if estado.fecha_calculo else None,
            'ultima_actualizacion': (
                estado.ultima_actualizacion.isoformat()
                if getattr(estado, 'ultima_actualizacion', None) else None
            ),
        }
        
        # Tras recálculo forzado, invalidar resumen para que el próximo GET reconstruya desde BD
        invalidate_vehicle_health_cache(vehicle_id)
        set_cached_health(vehicle_id, data, 'health_calculation', timeout=3600)
        
        logger.info(f"Salud de vehículo {vehicle_id} calculada exitosamente")
        return data
        
    except Exception as exc:
        logger.error(f"Error calculando salud de vehículo {vehicle_id}: {str(exc)}")
        # Reintentar después de 30 segundos
        raise self.retry(exc=exc, countdown=30)


@shared_task(bind=True, max_retries=2, default_retry_delay=15)
def procesar_post_viaje(self, vehicle_id, viaje_id, km_recorridos, km_anterior, km_nuevo):
    """
    Procesa todo lo que sigue al registro de un viaje, fuera del request HTTP:
    1. Recálculo de salud del vehículo
    2. Push notification al usuario
    3. Notificación in-app
    """
    try:
        from .models import Vehiculo

        vehiculo = Vehiculo.objects.select_related('marca', 'modelo', 'cliente__usuario').get(id=vehicle_id)
        nombre_vehiculo = (
            f"{vehiculo.marca} {vehiculo.modelo}" if vehiculo.marca
            else f"Vehículo {vehiculo.patente or ''}"
        )

        # 1. Recálculo de salud (puede tardar 1-5s, no importa aquí)
        try:
            calcular_estado_salud_interno(vehicle_id)
            logger.info(f"Salud recalculada para vehículo {vehicle_id} post-viaje")
        except Exception as e:
            logger.error(f"Error recalculando salud post-viaje para {vehicle_id}: {e}")

        # 2. Push + notificación in-app
        user_id = None
        try:
            if vehiculo.cliente and vehiculo.cliente.usuario:
                user_id = vehiculo.cliente.usuario.id
        except Exception:
            pass

        if user_id:
            try:
                from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification
                from mecanimovilapp.apps.usuarios.models import Notificacion

                send_expo_push_notification.delay(
                    user_id,
                    f"Viaje registrado: {nombre_vehiculo}",
                    f"Se registraron {km_recorridos:.1f} km. Odómetro: {km_anterior:,} → {km_nuevo:,} km.",
                    {
                        "type": "viaje_registrado",
                        "vehicle_id": str(vehicle_id),
                        "viaje_id": str(viaje_id),
                        "km_recorridos": str(km_recorridos),
                    },
                )

                Notificacion.crear_unica(
                    usuario=vehiculo.cliente.usuario,
                    tipo='viaje_registrado',
                    titulo=f"Viaje registrado: {nombre_vehiculo}",
                    mensaje=(
                        f"Se registraron {km_recorridos:.1f} km. "
                        f"Odómetro: {km_anterior:,} → {km_nuevo:,} km. "
                        f"Las métricas de salud se actualizarán automáticamente."
                    ),
                    data={
                        "vehicle_id": str(vehicle_id),
                        "viaje_id": str(viaje_id),
                    },
                    ventana_horas=1,
                    dedup_key={"viaje_id": str(viaje_id)},
                )
            except Exception as push_err:
                logger.warning(f"Error enviando push de viaje: {push_err}")

    except Exception as exc:
        logger.error(f"Error en procesar_post_viaje ({vehicle_id}): {exc}")
        raise self.retry(exc=exc)


@shared_task
def actualizar_salud_desde_checklist(checklist_id, vehicle_id):
    """
    Actualiza salud cuando se completa un checklist
    Se ejecuta automáticamente vía signal
    
    IMPORTANTE: Esta función puede ejecutarse tanto con Celery (.delay()) 
    como directamente (sincrónicamente) como fallback.
    
    Para checklists ya completados ANTES de que esta lógica esté correcta,
    ejecutar: python manage.py procesar_checklists_historicos
    (reprocesa todos los checklists completados y actualiza métricas).
    
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
            checklist = ChecklistInstance.objects.prefetch_related(
                'respuestas__item_template__catalog_item'
            ).get(id=checklist_id)
            vehiculo = Vehiculo.objects.get(id=vehicle_id)
        except (ChecklistInstance.DoesNotExist, Vehiculo.DoesNotExist):
            logger.error(f"Checklist {checklist_id} o vehículo {vehicle_id} no encontrado")
            return
        
        # ============================================
        # 1. ACTUALIZAR KILOMETRAJE DEL VEHÍCULO
        # ============================================
        kilometraje_checklist = extraer_kilometraje_desde_checklist_instance(checklist)
        if kilometraje_checklist is not None:
            logger.info(
                "Checklist %s: km leído para vehículo %s → %s km",
                checklist_id,
                vehicle_id,
                kilometraje_checklist,
            )
        else:
            logger.warning(
                "Checklist %s (vehículo %s): sin km reconocible en respuestas "
                "(se espera KILOMETER_INPUT o NUMBER con nombre/texto de odómetro).",
                checklist_id,
                vehicle_id,
            )

        # Si se encontró kilometraje en el checklist, actualizar el vehículo
        if kilometraje_checklist is not None:
            kilometraje_anterior = int(vehiculo.kilometraje or 0)
            diferencia_km = abs(kilometraje_checklist - kilometraje_anterior)

            # Actualizar si hay al menos 1 km de diferencia y el checklist no reduce el odómetro
            if diferencia_km >= 1:
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
        # La clave es el nombre del ComponenteSalud (debe coincidir exactamente).
        # Cada valor es lista de subcadenas: si alguna está contenida en el nombre del ítem del catálogo, se asocia.
        # Incluye nombres del catálogo (ej. populate_checklists_por_servicio) para máxima cobertura.
        mapeo_componentes = {
            'Aceite Motor': [
                'Cambio de Aceite', 'Nivel de aceite', 'Aceite motor', 'Nivel Aceite', 'Nivel aceite', 'Aceite Motor',
                'Aceite Motor Reemplazado', 'Nivel Aceite Antes', 'Nivel Aceite Después', 'Nivel de Fluidos',
            ],
            'Filtro de Aire': ['Filtro de Aire', 'Filtro aire', 'Filtro de Aire Reemplazado'],
            'Filtro de Aceite': ['Filtro de Aceite', 'Filtro aceite', 'Filtro de Aceite Reemplazado'],
            'Bujías': ['Bujías', 'Bujias', 'Cambio de bujías', 'Bujías Reemplazadas', 'Estado Cables Bujías'],
            'Batería': ['Batería', 'Bateria', 'Cambio de batería', 'Batería Reemplazada', 'Estado de Batería'],
            'Neumáticos': ['Neumáticos', 'Neumaticos', 'Llantas', 'Cambio de neumáticos', 'Estado de Neumáticos'],
            'Pastillas de Freno': ['Pastillas de Freno', 'Pastillas freno', 'Estado Pastillas', 'Pastillas y Discos Reemplazados'],
            'Discos de Freno': ['Discos de Freno', 'Discos freno', 'Estado Discos', 'Rectificado Realizado'],
            'Amortiguadores': [
                'Amortiguadores', 'Suspensión', 'Amortiguador Reemplazado', 'Estado Amortiguadores',
            ],
            'Correa de Distribución': [
                'Correa de Distribución', 'Correa distribución', 'Correa Reemplazada', 'Correa Distribución Revisada',
            ],
            'Líquido de Frenos': [
                'Líquido de Frenos', 'Liquido frenos', 'Líquido Frenos Reemplazado', 'Líquido Frenos Revisado', 'Estado de Frenos',
            ],
            'Refrigerante': [
                'Refrigerante', 'Líquido refrigerante', 'Refrigerante Rellenado', 'Refrigerante Revisado',
            ],
        }
        
        # Actualizar componentes basados en el checklist
        componentes_para_actualizar = {}
        respuestas_count = 0
        
        for respuesta in checklist.respuestas.all():
            respuestas_count += 1
            item_nombre = respuesta.item_template.catalog_item.nombre if respuesta.item_template.catalog_item else ''
            
            for nombre_config, items_relacionados in mapeo_componentes.items():
                if any(item.lower() in item_nombre.lower() for item in items_relacionados):
                    try:
                        # Buscar el componente maestro por su nombre exacto
                        config = ComponenteSalud.objects.filter(
                            nombre=nombre_config
                        ).first()
                        
                        if config:
                            # Usar el kilometraje del checklist si está disponible, sino el del vehículo
                            km_para_servicio = kilometraje_checklist if kilometraje_checklist else vehiculo.kilometraje

                            comp_salud, created = ComponenteSaludVehiculo.objects.get_or_create(
                                vehiculo=vehiculo,
                                componente=config,
                                defaults={
                                    'km_ultimo_servicio': km_para_servicio,
                                    'fecha_ultimo_servicio': checklist.fecha_finalizacion or timezone.now(),
                                    'salud_porcentaje': 100.0,
                                    'nivel_alerta': 'OPTIMO',
                                }
                            )
                            
                            if not created:
                                comp_salud.km_ultimo_servicio = km_para_servicio
                                comp_salud.fecha_ultimo_servicio = checklist.fecha_finalizacion or timezone.now()
                                comp_salud.salud_porcentaje = 100.0
                                comp_salud.nivel_alerta = 'OPTIMO'
                                comp_salud.requiere_servicio_inmediato = False
                                comp_salud.mensaje_alerta = ''
                            
                            componentes_para_actualizar[comp_salud.id] = comp_salud
                    except Exception as e:
                        logger.warning(f"Error actualizando componente {nombre_config}: {str(e)}")
        
        if not componentes_para_actualizar and respuestas_count > 0:
            logger.warning(
                f"Checklist {checklist_id}: {respuestas_count} respuestas pero ningún ítem coincidió con el mapeo de salud. "
                f"Revisar nombres de ítems del catálogo o ejecutar: python manage.py procesar_checklists_historicos"
            )
        
        # ✅ OPTIMIZACIÓN: bulk_update
        if componentes_para_actualizar:
            ComponenteSaludVehiculo.objects.bulk_update(
                list(componentes_para_actualizar.values()),
                ['km_ultimo_servicio', 'fecha_ultimo_servicio',
                 'salud_porcentaje', 'nivel_alerta', 'km_estimados_restantes',
                 'requiere_servicio_inmediato', 'mensaje_alerta']
            )
        
        # Recalcular salud (cola o mismo proceso si Celery no entrega el trabajo)
        try:
            calcular_salud_vehiculo_async.delay(vehicle_id, force_recalculate=True)
        except Exception as celery_err:
            logger.warning(
                "No se pudo encolar calcular_salud_vehiculo_async para vehículo %s: %s — recalculando en proceso",
                vehicle_id,
                celery_err,
            )
            try:
                calcular_estado_salud_interno(vehicle_id)
            except Exception as sync_err:
                logger.error(
                    "Recálculo síncrono de salud falló para vehículo %s: %s",
                    vehicle_id,
                    sync_err,
                    exc_info=True,
                )
        
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
    Recálculo periódico ligero: vehículos con actividad reciente.
    Usa force_recalculate=False para no martillar Redis si el worker ya corrió hace poco.
    """
    return _recalcular_salud_vehiculos_core(
        dias_actividad=30,
        force_recalculate=False,
        incluir_publicados=False,
        stagger_seconds=0,
    )


@shared_task(queue='heavy', time_limit=1800, soft_time_limit=1200)
def recalcular_salud_vehiculos_diario():
    """
    Recálculo diario: asegura métricas frescas aunque el usuario no abra la app.
    Incluye vehículos publicados en marketplace (misma fuente BD que listados).
    force_recalculate=True + invalidación en tarea → DB y serializers marketplace coherentes.
    Encola con countdown escalonado para no saturar la cola default.
    """
    return _recalcular_salud_vehiculos_core(
        dias_actividad=365,
        force_recalculate=True,
        incluir_publicados=True,
        stagger_seconds=3,
    )


def _recalcular_salud_vehiculos_core(
    dias_actividad=30,
    force_recalculate=False,
    incluir_publicados=False,
    stagger_seconds=0,
):
    """
    Núcleo compartido: arma el conjunto de vehículos y encola calcular_salud_vehiculo_async.
    """
    from django.utils import timezone
    from datetime import timedelta
    from django.db.models import Q
    from .models import Vehiculo

    try:
        fecha_limite = timezone.now() - timedelta(days=dias_actividad)
        q = Q(fecha_actualizacion__gte=fecha_limite)
        if incluir_publicados:
            q |= Q(is_published=True)
        vehiculos = Vehiculo.objects.filter(q).values_list('id', flat=True).distinct()
        ids = list(vehiculos)
        count = 0
        for i, vehicle_id in enumerate(ids):
            if stagger_seconds and i > 0:
                calcular_salud_vehiculo_async.apply_async(
                    args=[vehicle_id, force_recalculate],
                    countdown=min(i * stagger_seconds, 3600),
                )
            else:
                calcular_salud_vehiculo_async.delay(vehicle_id, force_recalculate)
            count += 1
        logger.info(
            f"Recálculo batch: {count} vehículos encolados "
            f"(force={force_recalculate}, publicados={incluir_publicados})"
        )
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
        from .models_health import ComponenteSaludVehiculo, ComponenteSalud
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
        
        # Mapeo idéntico al de actualizar_salud_desde_checklist (misma lógica de coincidencia por nombre)
        mapeo_componentes = {
            'Aceite Motor': [
                'Cambio de Aceite', 'Nivel de aceite', 'Aceite motor', 'Nivel Aceite', 'Nivel aceite', 'Aceite Motor',
                'Aceite Motor Reemplazado', 'Nivel Aceite Antes', 'Nivel Aceite Después', 'Nivel de Fluidos',
            ],
            'Filtro de Aire': ['Filtro de Aire', 'Filtro aire', 'Filtro de Aire Reemplazado'],
            'Filtro de Aceite': ['Filtro de Aceite', 'Filtro aceite', 'Filtro de Aceite Reemplazado'],
            'Bujías': ['Bujías', 'Bujias', 'Cambio de bujías', 'Bujías Reemplazadas', 'Estado Cables Bujías'],
            'Batería': ['Batería', 'Bateria', 'Cambio de batería', 'Batería Reemplazada', 'Estado de Batería'],
            'Neumáticos': ['Neumáticos', 'Neumaticos', 'Llantas', 'Cambio de neumáticos', 'Estado de Neumáticos'],
            'Pastillas de Freno': ['Pastillas de Freno', 'Pastillas freno', 'Estado Pastillas', 'Pastillas y Discos Reemplazados'],
            'Discos de Freno': ['Discos de Freno', 'Discos freno', 'Estado Discos', 'Rectificado Realizado'],
            'Amortiguadores': [
                'Amortiguadores', 'Suspensión', 'Amortiguador Reemplazado', 'Estado Amortiguadores',
            ],
            'Correa de Distribución': [
                'Correa de Distribución', 'Correa distribución', 'Correa Reemplazada', 'Correa Distribución Revisada',
            ],
            'Líquido de Frenos': [
                'Líquido de Frenos', 'Liquido frenos', 'Líquido Frenos Reemplazado', 'Líquido Frenos Revisado', 'Estado de Frenos',
            ],
            'Refrigerante': [
                'Refrigerante', 'Líquido refrigerante', 'Refrigerante Rellenado', 'Refrigerante Revisado',
            ],
        }
        
        componentes_actualizados = 0
        kilometraje_maximo_encontrado = int(vehiculo.kilometraje or 0)

        # Procesar cada checklist en orden cronológico
        for checklist in checklists_completados:
            kilometraje_checklist = extraer_kilometraje_desde_checklist_instance(checklist)
            if kilometraje_checklist is not None and kilometraje_checklist > kilometraje_maximo_encontrado:
                kilometraje_maximo_encontrado = kilometraje_checklist

            # Procesar componentes del checklist
            for respuesta in checklist.respuestas.all():
                item_nombre = respuesta.item_template.catalog_item.nombre if respuesta.item_template.catalog_item else ''
                
                for nombre_config, items_relacionados in mapeo_componentes.items():
                    if any(item.lower() in item_nombre.lower() for item in items_relacionados):
                        try:
                            # Buscar el config por su nombre exacto
                            # Buscar el componente maestro por su nombre exacto
                            componente_maestro = ComponenteSalud.objects.filter(
                                nombre=nombre_config
                            ).first()
                            
                            if componente_maestro:
                                # Usar kilometraje del checklist si está disponible, sino el del vehículo
                                km_para_servicio = kilometraje_checklist if kilometraje_checklist else vehiculo.kilometraje
                                
                                # Obtener o crear componente asociado a este vehículo
                                comp_salud, created = ComponenteSaludVehiculo.objects.get_or_create(
                                    vehiculo=vehiculo,
                                    componente=componente_maestro,
                                    defaults={
                                        'km_ultimo_servicio': km_para_servicio,
                                        'fecha_ultimo_servicio': checklist.fecha_finalizacion or timezone.now(),
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
                                        # NO guardamos todavía, lo haremos en bulk al final del proceso cronológico o por vehículo
                                        # NO calculamos salud individualmente aquí, delegamos al HealthEngine al final
                                        # comp_salud.calcular_salud(commit=False) # DEPRECATED
                                        comp_salud.save()  # Guardamos el km actualizado para que el Engine lo use
                                        componentes_actualizados += 1
                                        logger.info(
                                            f"✅ Componente {nombre_config} preparado para actualización desde checklist histórico "
                                            f"{checklist.id}"
                                        )
                                else:
                                    comp_salud.save()
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
        # Recalcular usando Health Engine en lugar de lógica manual
        # El Engine leerá los km_ultimo_servicio que acabamos de actualizar
        HealthEngine.calcular_salud_vehiculo(vehicle_id)
        
        # componentes = list(ComponenteSaludVehiculo.objects.filter(vehiculo=vehiculo))
        # for comp in componentes:
        #    comp.calcular_salud(commit=False)
        
        # if componentes:
        #    ComponenteSaludVehiculo.objects.bulk_update(...)
        
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
    Función de apoyo para enviar notificaciones push de salud por componente.
    """
    try:
        if not (vehiculo.cliente and vehiculo.cliente.usuario):
            return

        user_id = vehiculo.cliente.usuario.id
        nombre_vehiculo = f"{vehiculo.marca} {vehiculo.modelo}" if vehiculo.marca else f"Vehículo {vehiculo.patente or ''}"
        nombre_componente = componente.componente.nombre

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
                "salud": str(componente.salud_porcentaje),
            },
        )

        from mecanimovilapp.apps.usuarios.models import Notificacion
        Notificacion.crear_unica(
            usuario=vehiculo.cliente.usuario,
            tipo='health_alert',
            titulo=title,
            mensaje=body,
            data={
                "vehicle_id": str(vehiculo.id),
                "componente": nombre_componente,
            },
            ventana_horas=24,
            dedup_key={"vehicle_id": str(vehiculo.id), "componente": nombre_componente},
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
        
        # También crear notificación in-app.
        # dedup_key usa solo vehicle_id para que un cambio en es_critico entre
        # runs de Celery no genere una notificación nueva mientras la ventana esté abierta.
        # ventana_horas=72: si el usuario descarta la alerta no reaparece en 3 días.
        from mecanimovilapp.apps.usuarios.models import Notificacion
        Notificacion.crear_unica(
            usuario=vehiculo.cliente.usuario,
            tipo='health_alert',
            titulo=title,
            mensaje=body,
            data={
                "vehicle_id": str(vehiculo.id),
                "es_critico": es_critico,
            },
            ventana_horas=72,
            dedup_key={"vehicle_id": str(vehiculo.id)},
        )
        
        logger.info(f"📲 Alerta Push de salud GLOBAL enviada a usuario {user_id} para {nombre_vehiculo}")
    except Exception as e:
        logger.error(f"Error en enviar_alerta_salud_global_push: {e}")


def enviar_salud_actualizada_push(vehiculo, salud_global):
    """
    Notificación informativa: recálculo de salud completado.
    Se envía con throttle de 30 min por vehículo para no saturar.
    """
    try:
        if not (vehiculo.cliente and vehiculo.cliente.usuario):
            return

        user_id = vehiculo.cliente.usuario.id
        nombre_vehiculo = f"{vehiculo.marca} {vehiculo.modelo}" if vehiculo.marca else f"Vehículo {vehiculo.patente or ''}"

        title = f"Salud actualizada: {nombre_vehiculo}"
        body = f"La salud general de tu {nombre_vehiculo} es de {salud_global:.0f}%."

        from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification

        send_expo_push_notification.delay(
            user_id,
            title,
            body,
            {
                "type": "salud_actualizada",
                "vehicle_id": str(vehiculo.id),
                "salud_global": str(salud_global),
            },
        )

        from mecanimovilapp.apps.usuarios.models import Notificacion
        Notificacion.crear_unica(
            usuario=vehiculo.cliente.usuario,
            tipo='salud_actualizada',
            titulo=title,
            mensaje=body,
            data={"vehicle_id": str(vehiculo.id)},
            ventana_horas=1,
            dedup_key={"vehicle_id": str(vehiculo.id)},
        )
    except Exception as e:
        logger.error(f"Error en enviar_salud_actualizada_push: {e}")

