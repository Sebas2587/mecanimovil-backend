"""
PredictorSalud — Inteligencia predictiva para componentes vehiculares.

Estrategia de aprendizaje colaborativo en 3 capas:

  1. Bootstrap (siempre disponible)
     - Tasa de uso (km/día) calculada desde ViajeRegistrado del usuario.
     - Proyección lineal: cuántos km/meses faltan hasta umbral ATENCIÓN/CRÍTICO.
     - Ajuste por clima (WEAR_MATRIX) si está disponible.
     - Funciona desde el día 1 sin necesidad de datos entrenados.

  2. Modelos scikit-learn (cuando hay >= 30 eventos NIVEL_CRITICO o SERVICIO_REALIZADO
     para un componente)
     - Random Forest Regressor: predice km hasta servicio según
       (marca, modelo, año, km_actual, clima, motor).
     - Linear Regression: ajusta la estimación lineal con datos reales.
     - Decision Tree: clasifica probabilidad de falla en 30/60/90 días.
     - Modelos serializados con joblib en MEDIA_ROOT/ml_models/.

  3. Inferencia colaborativa (similitud por marca/modelo/año)
     - "47 vehículos similares cambiaron este componente entre X y Y km".
     - Se calcula directo de EventoSaludVehiculo aún sin modelo entrenado.

Caching:
  - Predicciones por vehículo cacheadas 30 min (cambian al moverse el km).
  - Modelos cargados en memoria una sola vez por proceso.
"""
import logging
import math
import os
from datetime import timedelta
from django.conf import settings
from django.core.cache import cache
from django.db.models import Avg, Count, Min, Max
from django.utils import timezone

logger = logging.getLogger(__name__)

# ── Bootstrap data: estadísticas de la industria automotriz ──────────────
# Promedios revisados con fuentes de talleres y fabricantes.
# Para componentes de fricción (frenos) la vida útil varía MUCHO según
# perfil de conducción: los valores son para conducción mixta urbana-suburbana.
# Conducción ciudad puro: -30% a -40% de vida útil en pastillas.
# Conducción autopista: +20% a +30%.
INDUSTRY_PRIORS = {
    # slug                  : (vida_util_km, intervalo_meses, std_km)
    'aceite-motor':           (10000,   6,   1500),
    'filtro-aceite':          (10000,   6,   1500),
    'filtro-aire':            (20000,  12,   3000),
    'filtro-combustible':     (40000,  24,   5000),
    'bujias':                 (40000,  24,   5000),
    'bateria':                (50000,  36,   8000),
    'neumaticos':             (40000,  36,   6000),   # age_cap 5 años por goma en engine
    'pastillas-freno':        (18000,  18,   4000),   # CORREGIDO: 18k mixto (era 40k)
    'discos-freno':           (50000,  36,  10000),   # CORREGIDO: 50k / 3 años (era 80k)
    'amortiguadores':         (80000,  48,  12000),   # age_cap 8 años en engine
    'correa-distribucion':    (90000,  60,  12000),   # age_cap 6 años goma en engine
    'liquido-frenos':         (40000,  24,   4000),   # higroscópico: 2 años crit
    'refrigerante':           (40000,  24,   5000),
    'aceite-transmision':     (60000,  48,  10000),
    'embrague':               (100000, 72,  18000),
    # aliases por slug del engine (usan slugs cortos)
    'oil':                    (10000,   6,   1500),
    'oil-filter':             (10000,   6,   1500),
    'air-filter':             (20000,  12,   3000),
    'cabin-filter':           (20000,  12,   3000),
    'spark-plug':             (40000,  24,   5000),
    'brakes':                 (18000,  18,   4000),
    'brake-discs':            (50000,  36,  10000),
    'brake-fluid':            (40000,  24,   4000),
    'battery':                (50000,  36,   8000),
    'tires':                  (40000,  36,   6000),
    'coolant':                (40000,  24,   5000),
    'shocks':                 (80000,  48,  12000),
    'timing-belt':            (90000,  60,  12000),
}

PREDICTION_CACHE_TTL = 60 * 30  # 30 min
ML_MODEL_DIR = os.path.join(getattr(settings, 'MEDIA_ROOT', '/tmp'), 'ml_models')
ML_TRAINING_THRESHOLD = 30  # Mínimo de eventos para entrenar un modelo por componente

_loaded_models = {}  # cache en memoria del proceso


def _industry_prior(slug):
    """Retorna prior de la industria para un slug. None si no hay."""
    return INDUSTRY_PRIORS.get(slug)


# Slugs sensibles al perfil de conducción (mismos que en health_engine)
_WEAR_BY_DRIVING_SLUGS = {'brakes', 'brake-discs', 'tires', 'brake-fluid', 'shocks',
                           'pastillas-freno', 'discos-freno', 'neumaticos', 'liquido-frenos',
                           'amortiguadores'}

# Componentes con degradación por antigüedad (goma/química)
_AGE_HARD_CAPS_PREDICTOR = {
    'tires':             (5,  10),
    'neumaticos':        (5,  10),
    'timing-belt':       (6,  10),
    'correa-distribucion': (6, 10),
    'brake-fluid':       (2,   4),
    'liquido-frenos':    (2,   4),
    'coolant':           (3,   5),
    'refrigerante':      (3,   5),
    'shocks':            (8,  15),
    'amortiguadores':    (8,  15),
}


def _predictor_driving_factor(km_por_dia: float, slug: str) -> float:
    """
    Factor de aceleración de desgaste para el predictor bootstrap.
    Afecta la proyección de km/días restantes en componentes de fricción.
    """
    if slug not in _WEAR_BY_DRIVING_SLUGS:
        return 1.0
    if km_por_dia <= 15:
        return 1.35   # uso urbano intenso
    elif km_por_dia <= 30:
        return 1.15
    elif km_por_dia <= 60:
        return 1.0
    else:
        return 0.90   # largo recorrido autopista


def _predictor_vehicle_age_years(vehiculo) -> int | None:
    """Años de vida del vehículo desde su año de fabricación."""
    year = getattr(vehiculo, 'year', None)
    if not year:
        return None
    return max(0, timezone.now().year - int(year))


def _predictor_component_age_years(vehiculo, componente_estado) -> tuple[int | None, bool]:
    """
    Edad efectiva del componente en años (espejo de health_engine._component_age_years).

    - Si hay historial de servicio confirmado, se mide desde el último servicio
      (una pieza recién cambiada es "nueva" aunque el auto sea antiguo).
    - Si no, cae a la antigüedad de fabricación del vehículo (conservador).

    Retorna (años | None, basado_en_servicio: bool).
    """
    fecha_serv = getattr(componente_estado, 'fecha_ultimo_servicio', None)
    historial = bool(getattr(componente_estado, 'historial_conocido', False))
    if historial and fecha_serv:
        if timezone.is_naive(fecha_serv):
            fecha_serv = timezone.make_aware(fecha_serv)
        return max(0, int((timezone.now() - fecha_serv).days // 365)), True
    return _predictor_vehicle_age_years(vehiculo), False


def _get_avg_km_per_day(vehiculo):
    """
    Calcula km/día promedio del usuario a partir de viajes registrados de los
    últimos 60 días. Si no hay viajes, usa promedio nacional (~30 km/día).
    """
    from ..models import ViajeRegistrado

    cache_key = f"avg_km_day_{vehiculo.id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    desde = timezone.now() - timedelta(days=60)
    viajes = ViajeRegistrado.objects.filter(
        vehiculo=vehiculo, fecha_registro__gte=desde,
    )

    total_km = 0.0
    dias_distintos = set()
    for v in viajes.only('km_recorridos', 'fecha_inicio', 'fecha_registro'):
        total_km += float(getattr(v, 'km_recorridos', 0) or 0)
        fecha = v.fecha_inicio or v.fecha_registro
        if fecha:
            dias_distintos.add(fecha.date())

    if dias_distintos and total_km > 0:
        promedio = total_km / max(len(dias_distintos), 1)
    else:
        # Default Chile: ~30 km/día urbano según ANAC.
        promedio = 30.0

    cache.set(cache_key, promedio, 60 * 60)  # 1h
    return max(promedio, 5.0)


def _climate_factor_for_component(vehiculo, slug):
    """
    Devuelve el multiplicador de desgaste climático para un componente,
    si hay coordenadas o ubicación reciente; 1.0 si no aplica.
    """
    try:
        from .weather_prediction import (
            fetch_weather_by_coords, determine_climate_condition, WEAR_MATRIX,
        )
    except Exception:
        return 1.0

    matrix_key = None
    sl = (slug or '').lower()
    if 'freno' in sl or 'pastilla' in sl or 'disco' in sl:
        matrix_key = 'frenos'
    elif 'neumat' in sl or 'llanta' in sl:
        matrix_key = 'neumaticos'
    elif 'bater' in sl:
        matrix_key = 'bateria'
    elif 'refrig' in sl:
        matrix_key = 'refrigerante'
    if not matrix_key:
        return 1.0

    # Buscar coordenadas: viaje más reciente (últimos 30 días).
    try:
        from ..models import ViajeRegistrado
        viaje = (
            ViajeRegistrado.objects
            .filter(vehiculo=vehiculo, coordenadas_fin__isnull=False)
            .order_by('-fecha_registro')
            .only('coordenadas_fin', 'coordenadas_inicio')
            .first()
        )
        coords_dict = None
        if viaje:
            coords_dict = viaje.coordenadas_fin or viaje.coordenadas_inicio
        if not coords_dict:
            return 1.0

        lat = coords_dict.get('latitude') or coords_dict.get('lat')
        lng = coords_dict.get('longitude') or coords_dict.get('lng') or coords_dict.get('lon')
        if lat is None or lng is None:
            return 1.0

        weather = fetch_weather_by_coords(lat, lng)
        cond = determine_climate_condition(weather) if weather else 'normal'
        return float(WEAR_MATRIX.get(matrix_key, {}).get(cond, 1.0))
    except Exception:
        return 1.0


# ─────────────────────────────────────────────────────────────────────────
# 1. BOOTSTRAP PREDICTION (siempre disponible)
# ─────────────────────────────────────────────────────────────────────────

def predecir_componente_bootstrap(vehiculo, componente_estado, regla_eta_km, regla_intervalo_meses=None):
    """
    Predicción base sin ML, solo aritmética + datos del usuario.

    Args:
        vehiculo: Vehiculo
        componente_estado: ComponenteSaludVehiculo
        regla_eta_km: vida útil km de la regla aplicada
        regla_intervalo_meses: intervalo en meses opcional

    Returns:
        dict con keys:
            km_estimados_hasta_servicio, dias_estimados_hasta_servicio,
            probabilidad_falla_30, probabilidad_falla_60, probabilidad_falla_90,
            recomendacion, basado_en, confianza
    """
    salud = float(componente_estado.salud_porcentaje or 100)
    km_total = int(vehiculo.kilometraje or 0)
    km_ultimo = int(componente_estado.km_ultimo_servicio or 0)
    eta = max(int(regla_eta_km or 0), 1)

    if componente_estado.historial_conocido and km_ultimo > 0:
        km_recorridos = max(0, km_total - km_ultimo)
        confianza = 'alta'
        basado_en = 'historial registrado del vehículo'
    else:
        # Estimación inteligente: ciclo actual basado en módulo
        km_en_ciclo = km_total % eta
        km_recorridos = max(km_en_ciclo, int(eta * 0.5))
        confianza = 'media-baja'
        basado_en = (
            f'estimación por kilometraje actual ({km_total:,} km, '
            f'sin historial registrado)'
        )

    # km hasta umbral ATENCION (≈ 60 % salud → exp(-(km/eta)^2)=0.6 → km≈eta*0.71)
    km_hasta_atencion = max(0, int(eta * 0.71) - km_recorridos)
    km_hasta_critico  = max(0, eta - km_recorridos)

    # km/día del usuario y proyección temporal
    km_por_dia = _get_avg_km_per_day(vehiculo)

    slug = componente_estado.componente.slug if componente_estado.componente else ''

    # Ajuste climático (puede acelerar el desgaste hasta 1.9x según WEAR_MATRIX)
    factor_clima = _climate_factor_for_component(vehiculo, slug)

    # Factor de intensidad de conducción para componentes de fricción
    factor_conduccion = _predictor_driving_factor(km_por_dia, slug)

    # Factor combinado: clima × conducción (ambos aceleran desgaste si > 1)
    factor_total = factor_clima * factor_conduccion

    km_hasta_atencion_aj = int(km_hasta_atencion / max(factor_total, 1.0))
    km_hasta_critico_aj  = int(km_hasta_critico  / max(factor_total, 1.0))

    dias_atencion = int(km_hasta_atencion_aj / km_por_dia) if km_por_dia > 0 else None
    dias_critico  = int(km_hasta_critico_aj  / km_por_dia) if km_por_dia > 0 else None

    # Probabilidades de falla (Weibull CDF a 30/60/90 días en base a uso del usuario)
    beta = 2.0  # default Weibull
    def cdf_falla(dias):
        if dias is None or km_por_dia <= 0:
            return None
        km_proyectado = km_recorridos + dias * km_por_dia * factor_total
        return min(1.0, max(0.0, 1 - math.exp(-((km_proyectado / eta) ** beta))))

    p30 = cdf_falla(30)
    p60 = cdf_falla(60)
    p90 = cdf_falla(90)

    # Recomendación legible
    if salud < 10:
        recomendacion = 'Servicio inmediato recomendado.'
    elif km_hasta_critico_aj <= 0:
        recomendacion = (
            f'Tu kilometraje actual sugiere que este componente necesita '
            f'mantención lo antes posible.'
        )
    elif dias_atencion is not None and dias_atencion <= 30:
        recomendacion = (
            f'Programar mantención dentro de los próximos {dias_atencion} días '
            f'(~{km_hasta_atencion_aj:,} km a tu ritmo de uso).'
        )
    elif dias_critico is not None:
        recomendacion = (
            f'En óptimo estado. Próxima mantención estimada en '
            f'{km_hasta_critico_aj:,} km (~{dias_critico} días).'
        )
    else:
        recomendacion = 'Sin proyección disponible.'

    if factor_clima > 1.0:
        recomendacion += (
            f' El clima local acelera el desgaste un '
            f'{int((factor_clima - 1) * 100)} %.'
        )

    if factor_conduccion > 1.0:
        recomendacion += (
            f' Tu patrón de uso ({round(km_por_dia, 0):.0f} km/día) '
            f'sugiere conducción urbana que acelera el desgaste en este componente.'
        )

    # Aviso por antigüedad del COMPONENTE (tiempo desde su último cambio, no la
    # antigüedad de fabricación del vehículo) para componentes de goma/química.
    age_cap = _AGE_HARD_CAPS_PREDICTOR.get(slug)
    if age_cap:
        años_componente, desde_servicio = _predictor_component_age_years(vehiculo, componente_estado)
        if años_componente is not None:
            max_optimo, max_critico = age_cap
            if años_componente > max_critico:
                if desde_servicio:
                    recomendacion += (
                        f' ATENCIÓN: último cambio hace ~{años_componente} años — '
                        f'supera su vida útil por antigüedad '
                        f'(máximo recomendado {max_critico} años). '
                        f'Conviene reemplazarlo independientemente del kilometraje.'
                    )
                else:
                    recomendacion += (
                        f' ATENCIÓN: sin registro de cambio en un vehículo de '
                        f'{años_componente} años — este componente probablemente supera '
                        f'su vida útil por antigüedad (máximo recomendado {max_critico} años).'
                    )
            elif años_componente > max_optimo:
                if desde_servicio:
                    recomendacion += (
                        f' Último cambio hace ~{años_componente} años: '
                        f'revisar por antigüedad (se recomienda cada {max_optimo} años).'
                    )
                else:
                    recomendacion += (
                        f' Vehículo de {años_componente} años sin registro de cambio: '
                        f'revisar este componente por antigüedad '
                        f'(se recomienda cada {max_optimo} años).'
                    )

    return {
        'km_recorridos_componente':   km_recorridos,
        'km_hasta_atencion':          km_hasta_atencion_aj,
        'km_hasta_critico':           km_hasta_critico_aj,
        'dias_hasta_atencion':        dias_atencion,
        'dias_hasta_critico':         dias_critico,
        'probabilidad_falla_30':      round(p30 * 100, 1) if p30 is not None else None,
        'probabilidad_falla_60':      round(p60 * 100, 1) if p60 is not None else None,
        'probabilidad_falla_90':      round(p90 * 100, 1) if p90 is not None else None,
        'km_por_dia_usuario':         round(km_por_dia, 1),
        'factor_clima':               round(factor_clima, 2),
        'factor_conduccion':          round(factor_conduccion, 2),
        'factor_total_desgaste':      round(factor_total, 2),
        'recomendacion':              recomendacion,
        'basado_en':                  basado_en,
        'confianza':                  confianza,
        'modelo':                     'bootstrap',
    }


# ─────────────────────────────────────────────────────────────────────────
# 2. ML PREDICTION (scikit-learn cuando hay datos)
# ─────────────────────────────────────────────────────────────────────────

def _model_path(slug):
    return os.path.join(ML_MODEL_DIR, f'{slug}.joblib')


def _cargar_modelo(slug):
    """Carga modelo .joblib desde disco con cache en memoria."""
    if slug in _loaded_models:
        return _loaded_models[slug]
    try:
        import joblib
    except ImportError:
        return None

    path = _model_path(slug)
    if not os.path.exists(path):
        _loaded_models[slug] = None
        return None
    try:
        modelo = joblib.load(path)
        _loaded_models[slug] = modelo
        return modelo
    except Exception as e:
        logger.warning("PredictorSalud: error cargando modelo %s: %s", slug, e)
        _loaded_models[slug] = None
        return None


def predecir_componente_ml(vehiculo, componente_estado):
    """
    Si hay modelo entrenado para este componente, retorna predicción ML.
    Caso contrario None.

    Returns:
        dict | None: predicción enriquecida con km_predicho, confianza, etc.
    """
    slug = componente_estado.componente.slug if componente_estado.componente else None
    if not slug:
        return None
    bundle = _cargar_modelo(slug)
    if not bundle:
        return None

    try:
        import numpy as np
        regressor = bundle['regressor']
        encoders  = bundle['encoders']
        feat_cols = bundle['features']

        # Construir vector de features con encoders ya entrenados
        marca = vehiculo.marca.nombre if vehiculo.marca else ''
        modelo = vehiculo.modelo.nombre if vehiculo.modelo else ''
        tipo_motor = (vehiculo.tipo_motor or 'GASOLINA').upper()

        def _safe_encode(enc, value, fallback=0):
            try:
                return int(enc.transform([value])[0])
            except Exception:
                return fallback

        row = []
        for col in feat_cols:
            if col == 'marca':
                row.append(_safe_encode(encoders['marca'], marca))
            elif col == 'modelo':
                row.append(_safe_encode(encoders['modelo'], modelo))
            elif col == 'tipo_motor':
                row.append(_safe_encode(encoders['tipo_motor'], tipo_motor))
            elif col == 'year':
                row.append(int(vehiculo.year or 2020))
            elif col == 'kilometraje':
                row.append(int(vehiculo.kilometraje or 0))
            elif col == 'salud_inicial':
                row.append(float(componente_estado.salud_porcentaje or 100))
            else:
                row.append(0)

        X = np.array([row])
        km_predichos = float(regressor.predict(X)[0])
        # Saneamos: jamás negativo, jamás absurdamente alto.
        km_predichos = max(0, min(km_predichos, 200000))

        return {
            'km_estimados_hasta_servicio': int(km_predichos),
            'modelo': 'random_forest_v1',
            'confianza': 'alta' if bundle.get('n_samples', 0) >= 100 else 'media',
            'basado_en': (
                f"{bundle.get('n_samples', 0)} casos de vehículos similares"
            ),
        }
    except Exception as e:
        logger.warning("PredictorSalud: error infiriendo ML para %s: %s", slug, e)
        return None


# ─────────────────────────────────────────────────────────────────────────
# 3. SIMILARITY-BASED INFERENCE (sin necesidad de modelo entrenado)
# ─────────────────────────────────────────────────────────────────────────

def estadisticas_similares(vehiculo, slug_componente):
    """
    Estadísticas de vehículos similares (misma marca+modelo+año±2)
    que ya tuvieron eventos para este componente. Útil incluso sin modelo ML.

    Returns:
        dict | None: { n_casos, km_promedio_servicio, km_min, km_max, marca, modelo }
    """
    from ..models_health import EventoSaludVehiculo

    if not (vehiculo.marca and vehiculo.modelo):
        return None
    marca = vehiculo.marca.nombre
    modelo = vehiculo.modelo.nombre
    year_target = vehiculo.year or 2020

    qs = EventoSaludVehiculo.objects.filter(
        componente__slug=slug_componente,
        tipo_evento__in=['SERVICIO_REALIZADO', 'NIVEL_CRITICO'],
        marca=marca,
        modelo=modelo,
        year__gte=year_target - 2,
        year__lte=year_target + 2,
        km_desde_ultimo_servicio__gt=0,
    )
    agg = qs.aggregate(
        n=Count('id'),
        prom=Avg('km_desde_ultimo_servicio'),
        mn=Min('km_desde_ultimo_servicio'),
        mx=Max('km_desde_ultimo_servicio'),
    )
    if not agg.get('n'):
        return None

    return {
        'n_casos': int(agg['n']),
        'km_promedio_servicio': int(agg['prom'] or 0),
        'km_min': int(agg['mn'] or 0),
        'km_max': int(agg['mx'] or 0),
        'marca': marca,
        'modelo': modelo,
        'rango_year': f"{year_target - 2}-{year_target + 2}",
    }


# ─────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────

def predecir_vehiculo(vehiculo, force_refresh=False):
    """
    Pipeline completo: para cada componente del vehículo, combina
    bootstrap + ML (si hay) + similares. Cachea por 30 min.

    Returns:
        list[dict]: predicciones por componente, ordenadas por urgencia.
    """
    from ..models_health import ComponenteSaludVehiculo

    cache_key = f"prediccion_salud_v1_{vehiculo.id}"
    if not force_refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    componentes = (
        ComponenteSaludVehiculo.objects
        .filter(vehiculo=vehiculo)
        .select_related('componente')
    )

    predicciones = []
    for cs in componentes:
        if not cs.componente:
            continue
        # Reutilizamos vida_util_proyectada que el Engine ya guardó en el último cálculo.
        eta = cs.vida_util_proyectada or 40000

        bootstrap = predecir_componente_bootstrap(
            vehiculo, cs, regla_eta_km=eta,
        )
        ml = predecir_componente_ml(vehiculo, cs)
        similares = estadisticas_similares(vehiculo, cs.componente.slug)

        # Si hay modelo ML, sus km predichos pisan los del bootstrap (más precisos).
        km_estimado_final = bootstrap['km_hasta_atencion']
        modelo_usado = bootstrap['modelo']
        confianza = bootstrap['confianza']
        if ml and ml.get('km_estimados_hasta_servicio'):
            km_estimado_final = ml['km_estimados_hasta_servicio']
            modelo_usado = ml['modelo']
            confianza = ml['confianza']

        servicio_sugerido = None
        try:
            from .componente_servicio_sugerido import resolver_servicio_sugerido
            servicio_sugerido = resolver_servicio_sugerido(
                cs.componente.slug,
                cs.componente.servicios_asociados.all(),
                getattr(vehiculo, 'tipo_motor', None),
            )
        except Exception:
            pass

        predicciones.append({
            'componente_id':   cs.componente.id,
            'componente':      cs.componente.nombre,
            'slug':            cs.componente.slug,
            'icono':           cs.componente.icono,
            'salud_actual':    round(float(cs.salud_porcentaje or 0), 1),
            'nivel_alerta':    cs.nivel_alerta,
            'km_hasta_servicio': km_estimado_final,
            'dias_hasta_atencion':   bootstrap['dias_hasta_atencion'],
            'dias_hasta_critico':    bootstrap['dias_hasta_critico'],
            'probabilidad_falla_30': bootstrap['probabilidad_falla_30'],
            'probabilidad_falla_60': bootstrap['probabilidad_falla_60'],
            'probabilidad_falla_90': bootstrap['probabilidad_falla_90'],
            'km_por_dia_usuario':    bootstrap['km_por_dia_usuario'],
            'factor_clima':          bootstrap['factor_clima'],
            'recomendacion':         bootstrap['recomendacion'],
            'servicio_sugerido':     servicio_sugerido,
            'basado_en':             ml['basado_en'] if ml else bootstrap['basado_en'],
            'confianza':             confianza,
            'modelo_usado':          modelo_usado,
            'similares':             similares,
        })

    # Ordenar por urgencia: salud asc, luego km_hasta_servicio asc
    predicciones.sort(
        key=lambda p: (p['salud_actual'], p['km_hasta_servicio'])
    )

    cache.set(cache_key, predicciones, PREDICTION_CACHE_TTL)
    return predicciones


def invalidar_predicciones_vehiculo(vehiculo_id):
    """Invalida cache de predicciones (llamar cuando cambia salud/km)."""
    cache.delete(f"prediccion_salud_v1_{vehiculo_id}")
