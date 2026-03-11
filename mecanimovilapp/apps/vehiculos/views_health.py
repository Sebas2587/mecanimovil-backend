"""
ViewSets optimizados para el sistema de salud vehicular
Implementa cache-first strategy y lazy loading para máximo rendimiento
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.core.cache import cache
from django.db.models import Prefetch
from django.conf import settings
import logging

from .models_health import (
    EstadoSaludVehiculo,
    ComponenteSaludVehiculo,
    AlertaMantenimiento
)
from .serializers_health import (
    EstadoSaludVehiculoSerializer,
    ComponenteSaludVehiculoSerializer,
    AlertaMantenimientoSerializer
)
from .utils.cache_health import (
    get_cached_health,
    set_cached_health,
    invalidate_vehicle_health_cache,
    HEALTH_SUMMARY_MAX_STALE_SECONDS,
)

# Verificar si Celery está disponible y importar tarea
try:
    from celery import shared_task
    from .tasks import calcular_salud_vehiculo_async
    CELERY_AVAILABLE = True
except (ImportError, AttributeError):
    CELERY_AVAILABLE = False
    calcular_salud_vehiculo_async = None

logger = logging.getLogger(__name__)


class VehicleHealthViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet optimizado para salud vehicular
    - Cache-first: 99% de requests desde Redis
    - Async calculation: Cálculos pesados en background
    - Lazy loading: Solo carga lo necesario
    """
    permission_classes = [IsAuthenticated]
    serializer_class = EstadoSaludVehiculoSerializer
    
    def get_queryset(self):
        """
        Filtra estados de salud por vehículos del usuario autenticado
        """
        user = self.request.user
        if hasattr(user, 'cliente'):
            return EstadoSaludVehiculo.objects.filter(
                vehiculo__cliente=user.cliente
            ).select_related('vehiculo').only(
                'id', 'salud_general_porcentaje', 'fecha_calculo', 'vehiculo__id'
            )
        # Si no es cliente, devolver vacío (o todos si es staff)
        if user.is_staff:
            return EstadoSaludVehiculo.objects.all().select_related('vehiculo').only(
                'id', 'salud_general_porcentaje', 'fecha_calculo', 'vehiculo__id'
            )
        return EstadoSaludVehiculo.objects.none()
    
    @action(detail=False, methods=['get'], url_path='vehicle/(?P<vehicle_id>[^/.]+)')
    def vehicle_health(self, request, vehicle_id=None):
        """
        Obtener salud del vehículo (ULTRA OPTIMIZADO)
        
        Estrategia:
        1. Intentar obtener desde cache (99% de casos)
        2. Si no existe, devolver datos básicos y calcular en background
        3. Usar select_related/prefetch_related para minimizar queries
        """
        try:
            # Validar que el vehículo pertenezca al usuario
            user = request.user
            from .models import Vehiculo
            
            # Obtener el cliente del usuario
            if not hasattr(user, 'cliente'):
                return Response(
                    {'error': 'Usuario no tiene un cliente asociado'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            try:
                vehiculo = Vehiculo.objects.get(
                    id=vehicle_id,
                    cliente=user.cliente
                )
            except Vehiculo.DoesNotExist:
                return Response(
                    {'error': 'Vehículo no encontrado o no tienes permisos'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # PASO 1: Cache solo si el snapshot no está obsoleto (evita días sin conectar = datos viejos)
            cached_data = get_cached_health(vehicle_id, 'health_summary')
            if cached_data:
                stale = True
                try:
                    from datetime import datetime, timezone as dt_tz
                    ts = cached_data.get('ultima_actualizacion') or cached_data.get('fecha_calculo')
                    if ts:
                        if isinstance(ts, str) and ts.endswith('Z'):
                            ts = ts.replace('Z', '+00:00')
                        parsed = datetime.fromisoformat(ts)
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=dt_tz.utc)
                        age = (datetime.now(dt_tz.utc) - parsed).total_seconds()
                        stale = age > HEALTH_SUMMARY_MAX_STALE_SECONDS
                except Exception:
                    stale = True  # Ante duda, revalidar desde BD
                if not stale:
                    logger.debug(f"Cache HIT para vehículo {vehicle_id}")
                    return Response(cached_data)
                invalidate_vehicle_health_cache(vehicle_id)
                logger.info(f"Cache STALE para vehículo {vehicle_id}, revalidando desde BD")
            
            # PASO 2: Obtener datos básicos desde DB (1 query optimizada)
            estado = EstadoSaludVehiculo.objects.filter(
                vehiculo_id=vehicle_id
            ).select_related('vehiculo').first()
            
            # PASO 3: Si no existe estado, crear uno básico y calcular en background
            if not estado:
                # Intentar iniciar cálculo asíncrono (NO bloquea)
                calculo_exitoso = False
                try:
                    if CELERY_AVAILABLE and calcular_salud_vehiculo_async:
                        calcular_salud_vehiculo_async.delay(vehicle_id, force_recalculate=True)
                        calculo_exitoso = True
                        logger.info(f"Cálculo asíncrono iniciado para vehículo {vehicle_id}")
                except Exception as e:
                    logger.warning(f"No se pudo iniciar cálculo asíncrono: {str(e)}")
                
                # Si el cálculo asíncrono falló, intentar sincrónicamente
                if not calculo_exitoso:
                    try:
                        from .tasks import calcular_estado_salud_interno
                        logger.info(f"Intentando cálculo síncrono para vehículo {vehicle_id}")
                        estado = calcular_estado_salud_interno(vehicle_id)
                        if estado:
                            # Si se calculó exitosamente, devolver los datos
                            logger.info(f"Cálculo síncrono exitoso para vehículo {vehicle_id}")
                            # Continuar al PASO 4 para devolver datos completos
                        else:
                            logger.warning(f"Cálculo síncrono retornó None para vehículo {vehicle_id}")
                    except Exception as e:
                        logger.error(f"Error calculando salud sincrónicamente: {str(e)}", exc_info=True)
                
                # Si ningún cálculo funcionó, devolver respuesta con datos por defecto
                if not estado:
                    # Devolver respuesta inmediata con datos por defecto
                    return Response({
                        'salud_general_porcentaje': 100,
                        'componentes_optimos': 0,
                        'componentes_atencion': 0,
                        'componentes_urgentes': 0,
                        'componentes_criticos': 0,
                        'tiene_alertas_activas': False,
                        'costo_estimado_mantenimiento': 0,
                        'componentes': [],
                        'alertas': [],
                        'calculando': True,  # Flag para frontend
                        'mensaje': 'Calculando estado de salud...'
                    }, status=status.HTTP_202_ACCEPTED)
            
            # PASO 4: Cargar componentes y alertas con prefetch (solo 2 queries más)
            componentes = (
                ComponenteSaludVehiculo.objects.filter(vehiculo_id=vehicle_id)
                .select_related('componente')
                .prefetch_related('componente__servicios_asociados')[:20]
            )
            
            alertas = AlertaMantenimiento.objects.filter(
                vehiculo_id=vehicle_id,
                activa=True
            ).prefetch_related(
                'servicios_recomendados'
            )[:10]  # Limitar a 10 alertas
            
            # PASO 5: Serializar datos
            try:
                componentes_data = ComponenteSaludVehiculoSerializer(componentes, many=True).data
            except Exception as e:
                logger.error(f"Error serializando componentes: {str(e)}")
                componentes_data = []
            
            try:
                alertas_data = AlertaMantenimientoSerializer(alertas, many=True).data
            except Exception as e:
                logger.error(f"Error serializando alertas: {str(e)}")
                alertas_data = []
            
            ultima = getattr(estado, 'ultima_actualizacion', None)
            data = {
                'salud_general_porcentaje': estado.salud_general_porcentaje or 0,
                'componentes_optimos': estado.componentes_optimos or 0,
                'componentes_atencion': estado.componentes_atencion or 0,
                'componentes_urgentes': estado.componentes_urgentes or 0,
                'componentes_criticos': estado.componentes_criticos or 0,
                'tiene_alertas_activas': estado.tiene_alertas_activas or False,
                'costo_estimado_mantenimiento': float(estado.costo_estimado_mantenimiento or 0),
                'componentes': componentes_data,
                'alertas': alertas_data,
                'fecha_calculo': estado.fecha_calculo.isoformat() if estado.fecha_calculo else None,
                'ultima_actualizacion': ultima.isoformat() if ultima else None,
            }
            
            # PASO 6: Guardar en cache para próximas requests
            set_cached_health(vehicle_id, data, 'health_summary')
            
            logger.debug(f"Cache MISS para vehículo {vehicle_id}, datos cargados desde DB")
            return Response(data)
            
        except Exception as e:
            import traceback
            error_detail = str(e)
            error_traceback = traceback.format_exc()
            logger.error(f"Error obteniendo salud de vehículo {vehicle_id}: {error_detail}")
            logger.error(f"Traceback: {error_traceback}")
            return Response(
                {
                    'error': 'Error al obtener estado de salud',
                    'detail': error_detail if settings.DEBUG else None
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['post'], url_path='vehicle/(?P<vehicle_id>[^/.]+)/sync')
    def vehicle_health_sync(self, request, vehicle_id=None):
        """
        Sincronizar métricas de salud para este vehículo (botón en app).
        Invalida cache, encola recálculo forzado. Respuesta 202: el cliente puede
        reconsultar GET vehicle_health tras unos segundos.
        Marketplace: los serializers leen ComponenteSaludVehiculo/EstadoSaludVehiculo
        desde BD; al terminar la tarea, listados/detalle muestran valores actualizados
        (no quedan "desactualizados" respecto al dueño: es la misma fuente).
        """
        user = request.user
        from .models import Vehiculo
        if not hasattr(user, 'cliente'):
            return Response(
                {'error': 'Usuario no tiene un cliente asociado'},
                status=status.HTTP_403_FORBIDDEN
            )
        try:
            Vehiculo.objects.get(id=vehicle_id, cliente=user.cliente)
        except Vehiculo.DoesNotExist:
            return Response(
                {'error': 'Vehículo no encontrado o no tienes permisos'},
                status=status.HTTP_404_NOT_FOUND
            )
        invalidate_vehicle_health_cache(vehicle_id)
        logger.info(f"sync salud: vehículo {vehicle_id} invalidado, recálculo forzado")

        # Siempre recalcular en este request para que GET siguiente (o el mismo cliente
        # al refrescar) vea ya BD actualizada. Solo encolar Celery adicional para pushes
        # duplicaría trabajo; la tasync invalida cache otra vez al terminar.
        try:
            from .tasks import calcular_estado_salud_interno
            calcular_estado_salud_interno(int(vehicle_id))
        except Exception as e:
            logger.error(f"sync salud síncrono falló: {e}", exc_info=True)
            # Fallback: encolar por si el síncrono falló por timeout/memoria
            if CELERY_AVAILABLE and calcular_salud_vehiculo_async:
                try:
                    calcular_salud_vehiculo_async.delay(int(vehicle_id), force_recalculate=True)
                except Exception as e2:
                    logger.warning(f"sync salud: Celery fallback falló: {e2}")
            return Response(
                {'error': 'No se pudo actualizar ahora. Intenta de nuevo.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        # Refrescar resumen desde BD y devolverlo para que la app no dependa de "esperar al worker"
        invalidate_vehicle_health_cache(vehicle_id)
        estado = EstadoSaludVehiculo.objects.filter(vehiculo_id=vehicle_id).select_related('vehiculo').first()
        if estado:
            componentes = (
                ComponenteSaludVehiculo.objects.filter(vehiculo_id=vehicle_id)
                .select_related('componente')
                .prefetch_related('componente__servicios_asociados')[:20]
            )
            try:
                componentes_data = ComponenteSaludVehiculoSerializer(componentes, many=True).data
            except Exception:
                componentes_data = []
            ultima = getattr(estado, 'ultima_actualizacion', None)
            payload = {
                'ok': True,
                'mensaje': 'Salud actualizada.',
                'async': False,
                'salud_general_porcentaje': estado.salud_general_porcentaje or 0,
                'componentes_optimos': estado.componentes_optimos or 0,
                'componentes_atencion': estado.componentes_atencion or 0,
                'componentes_urgentes': estado.componentes_urgentes or 0,
                'componentes_criticos': estado.componentes_criticos or 0,
                'ultima_actualizacion': ultima.isoformat() if ultima else None,
                'componentes': componentes_data,
            }
            set_cached_health(vehicle_id, {
                'salud_general_porcentaje': payload['salud_general_porcentaje'],
                'componentes_optimos': payload['componentes_optimos'],
                'componentes_atencion': payload['componentes_atencion'],
                'componentes_urgentes': payload['componentes_urgentes'],
                'componentes_criticos': payload['componentes_criticos'],
                'fecha_calculo': estado.fecha_calculo.isoformat() if estado.fecha_calculo else None,
                'ultima_actualizacion': payload['ultima_actualizacion'],
                'tiene_alertas_activas': estado.tiene_alertas_activas or False,
                'costo_estimado_mantenimiento': float(estado.costo_estimado_mantenimiento or 0),
                'componentes': componentes_data,
                'alertas': [],
            }, 'health_summary')
            return Response(payload, status=status.HTTP_200_OK)

        return Response(
            {
                'ok': True,
                'mensaje': 'Recálculo ejecutado; vuelve a cargar la pantalla.',
                'async': False,
            },
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['get'], url_path='vehicle/(?P<vehicle_id>[^/.]+)/components')
    def vehicle_components(self, request, vehicle_id=None):
        """
        Obtener solo componentes (lazy loading)
        Carga separada para mejorar tiempo inicial
        """
        # Validar permisos
        user = request.user
        from .models import Vehiculo
        
        # Obtener el cliente del usuario
        if not hasattr(user, 'cliente'):
            return Response(
                {'error': 'Usuario no tiene un cliente asociado'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            vehiculo = Vehiculo.objects.get(
                id=vehicle_id,
                cliente=user.cliente
            )
        except Vehiculo.DoesNotExist:
            return Response(
                {'error': 'Vehículo no encontrado o no tienes permisos'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Intentar cache
        cached = get_cached_health(vehicle_id, 'health_components')
        if cached:
            return Response(cached)
        
        # Cargar desde DB con paginación
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 20))
        offset = (page - 1) * page_size
        
        componentes = (
            ComponenteSaludVehiculo.objects.filter(vehiculo_id=vehicle_id)
            .select_related('componente')
            .prefetch_related('componente__servicios_asociados')[
                offset : offset + page_size
            ]
        )
        
        data = ComponenteSaludVehiculoSerializer(componentes, many=True).data
        
        # Cache por 10 minutos
        set_cached_health(vehicle_id, data, 'health_components')
        
        return Response({
            'results': data,
            'page': page,
            'page_size': page_size,
            'has_more': len(data) == page_size
        })
    
    @action(detail=False, methods=['post'], url_path='vehicle/(?P<vehicle_id>[^/.]+)/procesar-historicos')
    def procesar_checklists_historicos(self, request, vehicle_id=None):
        """
        Procesa todos los checklists completados históricos de un vehículo
        para actualizar las métricas de salud retroactivamente.
        
        Útil cuando:
        - Se agrega un nuevo componente de salud al sistema
        - Se quiere recalcular métricas basándose en historial completo
        - Se detectan discrepancias en los datos
        """
        try:
            # Validar permisos
            user = request.user
            from .models import Vehiculo
            
            if not hasattr(user, 'cliente'):
                return Response(
                    {'error': 'Usuario no tiene un cliente asociado'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            try:
                vehiculo = Vehiculo.objects.get(
                    id=vehicle_id,
                    cliente=user.cliente
                )
            except Vehiculo.DoesNotExist:
                return Response(
                    {'error': 'Vehículo no encontrado o no tienes permisos'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Importar tarea
            try:
                from .tasks import procesar_checklists_historicos_vehiculo
                
                # Ejecutar en background (Celery) o sincrónicamente
                if CELERY_AVAILABLE:
                    procesar_checklists_historicos_vehiculo.delay(vehicle_id)
                    return Response({
                        'message': 'Procesamiento de checklists históricos iniciado en background',
                        'vehicle_id': vehicle_id,
                        'status': 'processing'
                    }, status=status.HTTP_202_ACCEPTED)
                else:
                    # Ejecutar sincrónicamente si Celery no está disponible
                    resultado = procesar_checklists_historicos_vehiculo(vehicle_id)
                    if resultado:
                        return Response({
                            'message': 'Checklists históricos procesados exitosamente',
                            'vehicle_id': vehicle_id,
                            'resultado': resultado
                        }, status=status.HTTP_200_OK)
                    else:
                        return Response({
                            'error': 'Error procesando checklists históricos'
                        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            except ImportError:
                return Response(
                    {'error': 'Función de procesamiento no disponible'},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )
                
        except Exception as e:
            logger.error(f"Error procesando checklists históricos: {str(e)}", exc_info=True)
            return Response(
                {
                    'error': 'Error al procesar checklists históricos',
                    'detail': str(e) if settings.DEBUG else None
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

