"""
Consulta de patente para flujo invitado: cache Redis + respuesta recortada.
Reutiliza la misma normalización que el endpoint autenticado.
"""
import logging

import requests
from django.core.cache import cache

from mecanimovilapp.apps.vehiculos.getapi_client import fetch_appraisal_for_plate, get_getapi_headers
from mecanimovilapp.apps.vehiculos.kilometraje_validation import merge_mileage_metadata

logger = logging.getLogger(__name__)

GUEST_PATENTE_CACHE_TTL = 60 * 60 * 24  # 24h
GUEST_PATENTE_CACHE_PREFIX = 'guest_patente:v1:'


def _cache_key(patente: str) -> str:
    return f'{GUEST_PATENTE_CACHE_PREFIX}{patente.upper().strip()}'


def _resolve_marca_modelo_ids(normalized_data: dict) -> None:
    try:
        from mecanimovilapp.apps.vehiculos.catalogo_resolver import resolve_marca, resolve_modelo

        marca_obj = resolve_marca(normalized_data.get('marca_nombre') or '')
        if marca_obj:
            normalized_data['marca_id'] = marca_obj.id
            modelo_obj = resolve_modelo(marca_obj, normalized_data.get('modelo_nombre') or '')
            if modelo_obj:
                normalized_data['modelo_id'] = modelo_obj.id
    except Exception as exc:
        logger.warning('Error mapping marca/modelo guest patente: %s', exc)


def fetch_patente_normalized(patente: str, *, include_private_fields: bool = True) -> tuple[dict | None, int | None, str | None]:
    """
    Consulta GetAPI y normaliza la respuesta.
    Returns: (payload, http_status, error_code)
    """
    patente_norm = (patente or '').upper().strip()
    if not patente_norm:
        return None, 400, 'patente_requerida'

    url = f'https://chile.getapi.cl/v1/vehicles/plate/{patente_norm}'
    try:
        response = requests.get(url, headers=get_getapi_headers(), timeout=10)
    except Exception as exc:
        logger.error('Error connecting to GetAPI: %s', exc)
        return None, 503, 'servicio_externo'

    if response.status_code != 200:
        return None, 404, 'patente_no_encontrada'

    json_response = response.json()
    if json_response.get('success') is False:
        return None, 404, 'patente_no_encontrada'

    data = json_response.get('data', json_response)
    marca_nombre = data.get('model', {}).get('brand', {}).get('name', '')
    modelo_nombre = data.get('model', {}).get('name', '')

    normalized_data = {
        'patente': data.get('licensePlate', patente_norm),
        'marca_nombre': marca_nombre,
        'modelo_nombre': modelo_nombre,
        'year': data.get('year', ''),
        'color': data.get('color', ''),
        'motor': data.get('engine', ''),
        'tipo_motor': data.get('fuel', 'GASOLINA'),
        'cilindraje': data.get('engine', ''),
    }

    if include_private_fields:
        normalized_data['vin'] = data.get('vinNumber', '')
        normalized_data['raw_data'] = data

    _resolve_marca_modelo_ids(normalized_data)

    appraisal_extra = fetch_appraisal_for_plate(patente_norm)
    normalized_data.update(appraisal_extra)
    if 'tiene_tasacion_mercado' not in normalized_data:
        normalized_data['tiene_tasacion_mercado'] = False
    normalized_data.update(merge_mileage_metadata(data, appraisal_extra))

    return normalized_data, 200, None


def to_public_patente_payload(full_payload: dict) -> dict:
    """Recorta campos sensibles para respuesta pública."""
    return {
        'patente': full_payload.get('patente'),
        'marca_nombre': full_payload.get('marca_nombre'),
        'modelo_nombre': full_payload.get('modelo_nombre'),
        'marca_id': full_payload.get('marca_id'),
        'modelo_id': full_payload.get('modelo_id'),
        'year': full_payload.get('year'),
        'color': full_payload.get('color'),
        'motor': full_payload.get('motor'),
        'tipo_motor': full_payload.get('tipo_motor'),
        'cilindraje': full_payload.get('cilindraje'),
        'precio_mercado_promedio': full_payload.get('precio_mercado_promedio'),
        'precio_mercado_min': full_payload.get('precio_mercado_min'),
        'precio_mercado_max': full_payload.get('precio_mercado_max'),
        'tasacion_fiscal': full_payload.get('tasacion_fiscal'),
        'tiene_tasacion_mercado': full_payload.get('tiene_tasacion_mercado', False),
    }


def get_guest_patente_public(patente: str) -> tuple[dict | None, int, str | None]:
    """
    Cache-first lookup para invitados.
    Returns: (public_payload, http_status, error_code)
    """
    patente_norm = (patente or '').upper().strip()
    if not patente_norm:
        return None, 400, 'patente_requerida'

    cache_key = _cache_key(patente_norm)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached, 200, None

    full_payload, status_code, error_code = fetch_patente_normalized(
        patente_norm,
        include_private_fields=False,
    )
    if full_payload is None:
        return None, status_code, error_code

    public_payload = to_public_patente_payload(full_payload)
    cache.set(cache_key, public_payload, GUEST_PATENTE_CACHE_TTL)
    return public_payload, 200, None
