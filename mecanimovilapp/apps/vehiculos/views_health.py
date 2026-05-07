"""
ViewSets optimizados para el sistema de salud vehicular
Implementa cache-first strategy y lazy loading para máximo rendimiento
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import UserRateThrottle
from django.core.cache import cache
from django.db.models import Prefetch
from django.conf import settings
import logging


class HealthSyncThrottle(UserRateThrottle):
    """Limita POST /sync a 6 peticiones por minuto por usuario (artículo: rate limiting)."""
    rate = '6/min'

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
                    # Cache anterior sin servicios_asociados (modal) → forzar rebuild
                    comp = cached_data.get('componentes') or []
                    if comp and isinstance(comp, list) and len(comp) > 0:
                        if 'servicios_asociados' not in comp[0]:
                            invalidate_vehicle_health_cache(vehicle_id)
                            logger.info(
                                f"Cache sin servicios_asociados para vehículo {vehicle_id}, revalidando"
                            )
                        else:
                            logger.debug(f"Cache HIT para vehículo {vehicle_id}")
                            return Response(cached_data)
                    else:
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

    @action(detail=False, methods=['post'], url_path='vehicle/(?P<vehicle_id>[^/.]+)/sync',
            throttle_classes=[HealthSyncThrottle])
    def vehicle_health_sync(self, request, vehicle_id=None):
        """
        Sincronizar métricas de salud para este vehículo (botón en app).
        Invalida cache y encola recálculo en Celery; responde 202 inmediatamente
        para NO bloquear Daphne (evita los 150s+ de respuesta que causaban caídas).
        El frontend debe re-consultar GET vehicle_health tras unos segundos.
        Rate limited: 6/min por usuario.
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
        logger.info(f"sync salud: vehículo {vehicle_id} invalidado, recálculo encolado")

        if CELERY_AVAILABLE and calcular_salud_vehiculo_async:
            try:
                calcular_salud_vehiculo_async.delay(int(vehicle_id), force_recalculate=True)
            except Exception as e:
                logger.warning(f"sync salud: Celery falló: {e}")

        return Response(
            {
                'ok': True,
                'mensaje': 'Recálculo iniciado. Los datos se actualizarán en unos segundos.',
                'async': True,
            },
            status=status.HTTP_202_ACCEPTED
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
        
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 20))

        cached = get_cached_health(vehicle_id, 'health_components', page=page)
        if cached:
            return Response(cached)

        offset = (page - 1) * page_size
        componentes = (
            ComponenteSaludVehiculo.objects.filter(vehiculo_id=vehicle_id)
            .select_related('componente')
            .prefetch_related('componente__servicios_asociados')[
                offset : offset + page_size
            ]
        )

        data = ComponenteSaludVehiculoSerializer(componentes, many=True).data

        response_data = {
            'results': data,
            'page': page,
            'page_size': page_size,
            'has_more': len(data) == page_size
        }
        set_cached_health(vehicle_id, response_data, 'health_components', page=page)

        return Response(response_data)
    
    @action(detail=False, methods=['get'], url_path='vehicle/(?P<vehicle_id>[^/.]+)/predicciones')
    def vehicle_predictions(self, request, vehicle_id=None):
        """
        Predicciones inteligentes por componente (bootstrap + scikit-learn + similares).
        - Bootstrap: aritmética sobre km/uso/clima del usuario (siempre disponible).
        - ML: si hay modelos entrenados con eventos suficientes, refina la predicción.
        - Similares: vehículos cercanos en marca/modelo/año del dataset colaborativo.
        """
        user = request.user
        from .models import Vehiculo

        if not hasattr(user, 'cliente'):
            return Response(
                {'error': 'Usuario no tiene un cliente asociado'},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            vehiculo = Vehiculo.objects.select_related('marca', 'modelo').get(
                id=vehicle_id, cliente=user.cliente,
            )
        except Vehiculo.DoesNotExist:
            return Response(
                {'error': 'Vehículo no encontrado o no tienes permisos'},
                status=status.HTTP_404_NOT_FOUND,
            )

        force = str(request.query_params.get('force', '0')).lower() in ('1', 'true', 'yes')
        try:
            from .services.predictor_salud import predecir_vehiculo
            predicciones = predecir_vehiculo(vehiculo, force_refresh=force)
        except Exception as e:
            logger.error(f"Error generando predicciones para {vehicle_id}: {e}", exc_info=True)
            return Response(
                {'error': 'No se pudieron generar predicciones', 'detail': str(e) if settings.DEBUG else None},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Resumen ejecutivo: top 3 más urgentes + alertas accionables
        criticos = [p for p in predicciones if p['salud_actual'] < 40]
        proximos_30_dias = [
            p for p in predicciones
            if p.get('dias_hasta_atencion') is not None and p['dias_hasta_atencion'] <= 30
        ]

        return Response({
            'vehicle_id': int(vehicle_id),
            'kilometraje_actual': vehiculo.kilometraje or 0,
            'predicciones': predicciones,
            'resumen': {
                'total_componentes': len(predicciones),
                'componentes_criticos': len(criticos),
                'componentes_atencion_30d': len(proximos_30_dias),
                'top_3_urgentes': [p['componente'] for p in predicciones[:3]],
            },
            'modelo_info': {
                'capa_1_bootstrap': 'siempre activa (datos del usuario)',
                'capa_2_ml': 'activa cuando hay >=30 eventos por componente',
                'capa_3_similares': 'activa cuando hay vehículos similares en el sistema',
            },
        })

    @action(detail=False, methods=['post'], url_path='vehicle/(?P<vehicle_id>[^/.]+)/registrar-mantenimiento')
    def registrar_mantenimiento_retroactivo(self, request, vehicle_id=None):
        """
        Permite al usuario declarar retroactivamente un mantenimiento que olvidó registrar.

        El engine penaliza componentes sin historial porque no puede saber si el
        usuario simplemente olvidó registrarlo. Este endpoint le devuelve el control:
        el usuario puede decir "yo cambié esta pieza en X km el día Y" y el sistema
        recalcula la salud con esos datos, marcando el origen como USUARIO_DECLARADO
        para que el frontend pueda mostrar un indicador de confianza distinto al de
        un dato confirmado por checklist de taller.

        Body esperado:
            {
                "componente_slug": "timing-belt",
                "km_en_el_que_se_hizo": 120000,       // obligatorio
                "fecha_realizado": "2023-06-15",       // opcional (ISO 8601)
                "nota": "Cambié la correa pero no lo registré en su momento"  // opcional
            }

        Restricciones:
            - km_en_el_que_se_hizo debe ser ≤ km actual del vehículo.
            - km_en_el_que_se_hizo debe ser > 0.
            - Si fecha_realizado no se provee, se estima desde el km informado y el
              promedio de km/día del usuario.
        """
        from .models import Vehiculo
        from .models_health import ComponenteSalud, ComponenteSaludVehiculo
        from django.utils import timezone as tz
        from datetime import datetime, date

        user = request.user
        if not hasattr(user, 'cliente'):
            return Response({'error': 'Usuario no tiene un cliente asociado'}, status=status.HTTP_403_FORBIDDEN)

        try:
            vehiculo = Vehiculo.objects.select_related('marca', 'modelo').get(
                id=vehicle_id, cliente=user.cliente
            )
        except Vehiculo.DoesNotExist:
            return Response({'error': 'Vehículo no encontrado o no tienes permisos'}, status=status.HTTP_404_NOT_FOUND)

        # ── Validar input básico ───────────────────────────────────────────
        slug = (request.data.get('componente_slug') or '').strip()
        if not slug:
            return Response({'error': 'componente_slug es obligatorio.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            km_servicio = int(request.data.get('km_en_el_que_se_hizo', 0))
        except (TypeError, ValueError):
            return Response({'error': 'km_en_el_que_se_hizo debe ser un número entero.'}, status=status.HTTP_400_BAD_REQUEST)

        if km_servicio <= 0:
            return Response({'error': 'km_en_el_que_se_hizo debe ser mayor a 0.'}, status=status.HTTP_400_BAD_REQUEST)

        km_actual = vehiculo.kilometraje or 0
        if km_servicio > km_actual:
            return Response(
                {'error': f'El km declarado ({km_servicio:,}) no puede ser mayor al kilometraje actual ({km_actual:,}).'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Guardrail 1: rate limit por vehículo ──────────────────────────
        # Máx 3 declaraciones retroactivas en total por vehículo en 30 días.
        # Evita que un usuario borre todos sus componentes críticos en un solo día.
        from .models_health import EventoSaludVehiculo
        from django.utils import timezone as _tz
        import datetime as _dt

        ventana_30d = _tz.now() - _dt.timedelta(days=30)
        declaraciones_recientes = EventoSaludVehiculo.objects.filter(
            vehiculo=vehiculo,
            tipo_evento='SERVICIO_REALIZADO',
            metadata__fuente='USUARIO_DECLARADO',
            fecha_evento__gte=ventana_30d,
        ).count()
        if declaraciones_recientes >= 3:
            return Response(
                {
                    'error': (
                        'Límite de declaraciones retroactivas alcanzado. '
                        'Puedes realizar hasta 3 por vehículo cada 30 días. '
                        'Para validar más componentes, agenda una revisión con un taller verificado.'
                    ),
                    'codigo': 'RATE_LIMIT_DECLARACIONES',
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # ── Guardrail 2: cooldown por componente ──────────────────────────
        # Un mismo componente no puede ser declarado más de una vez en 90 días.
        # Evita que alguien "renueve" el mismo componente periódicamente sin taller.
        ventana_90d = _tz.now() - _dt.timedelta(days=90)
        ya_declarado = EventoSaludVehiculo.objects.filter(
            vehiculo=vehiculo,
            componente__slug=slug,
            tipo_evento='SERVICIO_REALIZADO',
            metadata__fuente='USUARIO_DECLARADO',
            fecha_evento__gte=ventana_90d,
        ).exists()
        if ya_declarado:
            return Response(
                {
                    'error': (
                        f'Ya declaraste un mantenimiento para este componente en los últimos 90 días. '
                        f'Para actualizar el estado necesitas un checklist confirmado por un taller.'
                    ),
                    'codigo': 'COOLDOWN_COMPONENTE',
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # ── Guardrail 3: plausibilidad del km declarado ───────────────────
        # El km declarado no puede ser demasiado reciente respecto al km actual
        # de forma sospechosa. Si el usuario dice "lo hice a 157.999 km" cuando
        # el auto tiene 158.000 km, eso es claramente una declaración fraudulenta
        # para blanquear el estado. Exigimos que haya al menos 500 km de diferencia.
        KM_MINIMO_DIFERENCIA = 500
        if km_actual - km_servicio < KM_MINIMO_DIFERENCIA:
            return Response(
                {
                    'error': (
                        f'El km declarado ({km_servicio:,} km) está demasiado cerca del '
                        f'km actual ({km_actual:,} km). '
                        f'Debe haber al menos {KM_MINIMO_DIFERENCIA:,} km de diferencia para '
                        f'que la declaración sea válida.'
                    ),
                    'codigo': 'KM_SOSPECHOSO',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Guardrail 4: el km declarado no puede ser anterior al km de registro ──
        # Si el vehículo fue registrado en la app con X km (dato externo o manual),
        # no tiene sentido declarar un mantenimiento anterior a eso — no habría forma
        # de verificarlo y solo sirve para inflar métricas.
        km_referencia_registro = vehiculo.kilometraje_api or 0
        if km_referencia_registro > 500 and km_servicio < km_referencia_registro:
            return Response(
                {
                    'error': (
                        f'El km declarado ({km_servicio:,} km) es anterior al km con que '
                        f'se registró el vehículo ({km_referencia_registro:,} km). '
                        f'Solo puedes declarar mantenimientos realizados a partir de ese km.'
                    ),
                    'codigo': 'KM_ANTERIOR_REGISTRO',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Guardrail 5: no se puede declarar en un vehículo publicado en venta ─
        # Si el vehículo está activamente publicado en el marketplace, el dueño
        # podría usar declaraciones retroactivas para inflar la salud antes de
        # mostrarlo a compradores. Bloqueamos por completo — solo un taller puede
        # mejorar métricas en ese contexto.
        if getattr(vehiculo, 'is_published', False):
            return Response(
                {
                    'error': (
                        'No puedes realizar declaraciones retroactivas mientras el vehículo '
                        'está publicado en venta. Retira la publicación primero, o valida '
                        'el mantenimiento con un checklist de taller verificado.'
                    ),
                    'codigo': 'VEHICULO_EN_VENTA',
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # ── Resolver fecha ─────────────────────────────────────────────────
        fecha_raw = request.data.get('fecha_realizado')
        fecha_servicio = None
        if fecha_raw:
            try:
                parsed = date.fromisoformat(str(fecha_raw))
                fecha_servicio = tz.make_aware(datetime(parsed.year, parsed.month, parsed.day))
                if fecha_servicio > tz.now():
                    return Response({'error': 'La fecha no puede ser futura.'}, status=status.HTTP_400_BAD_REQUEST)
            except ValueError:
                return Response({'error': 'fecha_realizado debe estar en formato YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            # Estimar fecha desde km diferencia y km/día del usuario
            try:
                from .services.predictor_salud import _get_avg_km_per_day
                km_dia = _get_avg_km_per_day(vehiculo)
                km_diff = max(0, km_actual - km_servicio)
                dias_atras = int(km_diff / max(km_dia, 5.0))
                fecha_servicio = tz.now() - __import__('datetime').timedelta(days=dias_atras)
            except Exception:
                fecha_servicio = tz.now()

        # ── Buscar componente maestro ─────────────────────────────────────
        try:
            comp_maestro = ComponenteSalud.objects.get(slug=slug)
        except ComponenteSalud.DoesNotExist:
            slugs_disponibles = list(ComponenteSalud.objects.values_list('slug', flat=True))
            return Response(
                {
                    'error': f'Componente "{slug}" no encontrado.',
                    'slugs_disponibles': slugs_disponibles,
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # ── Actualizar o crear ComponenteSaludVehiculo ────────────────────
        nota = str(request.data.get('nota') or '')[:500]

        comp_estado, _ = ComponenteSaludVehiculo.objects.get_or_create(
            vehiculo=vehiculo,
            componente=comp_maestro,
            defaults={
                'salud_porcentaje': 100,
                'nivel_alerta': 'OPTIMO',
                'km_ultimo_servicio': km_servicio,
                'fecha_ultimo_servicio': fecha_servicio,
                'historial_conocido': True,
                'historial_fuente': 'USUARIO_DECLARADO',
                'mensaje_alerta': '',
            }
        )

        comp_estado.km_ultimo_servicio  = km_servicio
        comp_estado.fecha_ultimo_servicio = fecha_servicio
        comp_estado.historial_conocido  = True
        comp_estado.historial_fuente    = 'USUARIO_DECLARADO'
        # Acumular notas sin borrar las previas
        if nota:
            prev = comp_estado.mensaje_alerta or ''
            comp_estado.mensaje_alerta = f"[Usuario declaró: {nota}] {prev}".strip()[:500]
        comp_estado.save(update_fields=[
            'km_ultimo_servicio', 'fecha_ultimo_servicio',
            'historial_conocido', 'historial_fuente', 'mensaje_alerta',
        ])

        # ── Registrar en EventoSaludVehiculo para el dataset ML ───────────
        try:
            from .models_health import EventoSaludVehiculo
            marca_n  = vehiculo.marca.nombre  if vehiculo.marca  else ''
            modelo_n = vehiculo.modelo.nombre if vehiculo.modelo else ''
            EventoSaludVehiculo.objects.create(
                vehiculo=vehiculo,
                componente=comp_maestro,
                tipo_evento='SERVICIO_REALIZADO',
                marca=marca_n,
                modelo=modelo_n,
                year=getattr(vehiculo, 'year', None),
                tipo_motor=str(getattr(vehiculo, 'tipo_motor', '') or '').upper(),
                kilometraje=km_servicio,
                km_desde_ultimo_servicio=0,
                meses_desde_ultimo_servicio=0,
                metadata={'fuente': 'USUARIO_DECLARADO', 'nota': nota, 'km_actual': km_actual},
                fecha_evento=fecha_servicio,
            )
        except Exception as evt_err:
            logger.warning("registrar_mantenimiento: error creando EventoSaludVehiculo: %s", evt_err)

        # ── Invalidar cache y recalcular ──────────────────────────────────
        invalidate_vehicle_health_cache(vehicle_id)
        if CELERY_AVAILABLE and calcular_salud_vehiculo_async:
            try:
                calcular_salud_vehiculo_async.delay(int(vehicle_id), force_recalculate=True)
            except Exception as e:
                logger.warning("registrar_mantenimiento: Celery falló, recalculando síncronamente: %s", e)
                try:
                    from .tasks import calcular_estado_salud_interno
                    calcular_estado_salud_interno(int(vehicle_id))
                except Exception:
                    pass
        else:
            try:
                from .tasks import calcular_estado_salud_interno
                calcular_estado_salud_interno(int(vehicle_id))
            except Exception as sync_err:
                logger.warning("registrar_mantenimiento: recálculo síncrono falló: %s", sync_err)

        km_recorridos_desde = km_actual - km_servicio
        return Response(
            {
                'ok': True,
                'componente': comp_maestro.nombre,
                'slug': slug,
                'km_servicio_registrado': km_servicio,
                'fecha_servicio': fecha_servicio.date().isoformat(),
                'km_recorridos_desde_servicio': km_recorridos_desde,
                'historial_fuente': 'USUARIO_DECLARADO',
                'mensaje': (
                    f'Mantenimiento de {comp_maestro.nombre} registrado a los {km_servicio:,} km. '
                    f'Llevas {km_recorridos_desde:,} km desde ese servicio. '
                    f'Las métricas se están recalculando.'
                ),
                'nota': 'Los datos declarados por el usuario se muestran con indicador de confianza '
                        'distinto a los confirmados por checklist de taller.',
            },
            status=status.HTTP_200_OK,
        )

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

