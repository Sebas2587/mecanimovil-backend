"""
Utilidades de cache para el sistema de salud vehicular
Usa Redis para cachear datos y evitar cálculos repetidos.

Patrones aplicados (ref: Redis best-practices):
- TTL con jitter para prevenir cache stampede
- Claves paginadas para componentes
- Fail-open: IGNORE_EXCEPTIONS=True en settings deja pasar requests si Redis falla
"""
import random
from django.core.cache import cache
from django.conf import settings

HEALTH_SUMMARY_MAX_STALE_SECONDS = 25 * 3600  # 25 h

CACHE_TIMEOUTS = {
    'health_summary': 600,
    'health_components': 600,
    'health_alerts': 180,
    'health_calculation': 3600,
}

# ±15% jitter para que claves de distintos vehículos no expiren al mismo tiempo
_JITTER_FACTOR = 0.15


def _jittered_timeout(base_timeout):
    jitter = int(base_timeout * _JITTER_FACTOR)
    return base_timeout + random.randint(-jitter, jitter)


def get_cache_key(vehicle_id, cache_type='health_summary', page=None):
    key = f'vehicle_health:{vehicle_id}:{cache_type}'
    if page is not None:
        key = f'{key}:p{page}'
    return key


def invalidate_vehicle_health_cache(vehicle_id):
    base_keys = [
        get_cache_key(vehicle_id, 'health_summary'),
        get_cache_key(vehicle_id, 'health_alerts'),
        get_cache_key(vehicle_id, 'health_calculation'),
    ]
    # Invalidar las primeras 5 páginas de componentes (cubre caso común)
    for p in range(1, 6):
        base_keys.append(get_cache_key(vehicle_id, 'health_components', page=p))
    # Clave legacy sin página
    base_keys.append(get_cache_key(vehicle_id, 'health_components'))
    cache.delete_many(base_keys)


def get_cached_health(vehicle_id, cache_type='health_summary', page=None):
    cache_key = get_cache_key(vehicle_id, cache_type, page=page)
    return cache.get(cache_key)


def set_cached_health(vehicle_id, data, cache_type='health_summary', timeout=None, page=None):
    cache_key = get_cache_key(vehicle_id, cache_type, page=page)
    base = timeout or CACHE_TIMEOUTS.get(cache_type, 300)
    cache.set(cache_key, data, _jittered_timeout(base))

