"""
Utilidades de cache para el sistema de salud vehicular
Usa Redis para cachear datos y evitar cálculos repetidos
"""
from django.core.cache import cache
from django.conf import settings

# Si el snapshot en BD es más viejo que esto, no servir solo desde cache sin revalidar
HEALTH_SUMMARY_MAX_STALE_SECONDS = 25 * 3600  # 25 h: batch diario mantiene frescura

# Tiempos de cache (en segundos)
CACHE_TIMEOUTS = {
    'health_summary': 600,        # 10 min: menos requests repetidas; staleness se valida por ultima_actualizacion
    'health_components': 600,      # 10 minutos - Lista de componentes
    'health_alerts': 180,          # 3 minutos - Alertas activas
    'health_calculation': 3600,    # 1 hora - Cálculo completo (solo si no hay cambios)
}


def get_cache_key(vehicle_id, cache_type='health_summary'):
    """
    Genera clave de cache única para un vehículo y tipo de cache
    
    Args:
        vehicle_id: ID del vehículo
        cache_type: Tipo de cache (health_summary, health_components, health_alerts, health_calculation)
    
    Returns:
        str: Clave de cache formateada
    """
    return f'vehicle_health:{vehicle_id}:{cache_type}'


def invalidate_vehicle_health_cache(vehicle_id):
    """
    Invalida todo el cache relacionado con un vehículo
    
    Args:
        vehicle_id: ID del vehículo
    """
    cache_keys = [
        get_cache_key(vehicle_id, 'health_summary'),
        get_cache_key(vehicle_id, 'health_components'),
        get_cache_key(vehicle_id, 'health_alerts'),
        get_cache_key(vehicle_id, 'health_calculation'),
    ]
    cache.delete_many(cache_keys)


def get_cached_health(vehicle_id, cache_type='health_summary'):
    """
    Obtiene datos de salud desde cache
    
    Args:
        vehicle_id: ID del vehículo
        cache_type: Tipo de cache a obtener
    
    Returns:
        dict o None: Datos cacheados o None si no existe
    """
    cache_key = get_cache_key(vehicle_id, cache_type)
    return cache.get(cache_key)


def set_cached_health(vehicle_id, data, cache_type='health_summary', timeout=None):
    """
    Guarda datos de salud en cache
    
    Args:
        vehicle_id: ID del vehículo
        data: Datos a cachear
        cache_type: Tipo de cache
        timeout: Tiempo de expiración en segundos (None = usar default)
    """
    cache_key = get_cache_key(vehicle_id, cache_type)
    timeout = timeout or CACHE_TIMEOUTS.get(cache_type, 300)
    cache.set(cache_key, data, timeout)

