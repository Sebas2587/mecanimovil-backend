"""
Geocodificación de direcciones en Chile (Nominatim).
Usada para convertir texto de dirección en coordenadas guardadas en `ubicacion` (PostGIS).
"""
import logging
import time

import requests

logger = logging.getLogger(__name__)

# Bounding box aproximado Chile continental (lat, lng)
CL_LAT_MIN, CL_LAT_MAX = -56.0, -17.0
CL_LNG_MIN, CL_LNG_MAX = -76.0, -66.0


def geocode_address_chile(address: str, *, timeout: int = 10):
    """
    Devuelve dict con lat, lng, display_name o None si falla.
    Respeta rate limit básico de Nominatim (sleep 1s después de la petición).
    """
    text = (address or "").strip()
    if not text:
        return None

    geocode_url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": f"{text}, Chile",
        "format": "json",
        "limit": 1,
        "countrycodes": "cl",
    }
    headers = {"User-Agent": "MecaniMovil/1.0 (contacto@app)"}

    try:
        response = requests.get(geocode_url, params=params, headers=headers, timeout=timeout)
        time.sleep(1)
        if response.status_code != 200:
            logger.warning("Nominatim HTTP %s", response.status_code)
            return None
        results = response.json()
        if not results:
            return None
        result = results[0]
        lat = float(result["lat"])
        lng = float(result["lon"])
        if not (CL_LAT_MIN <= lat <= CL_LAT_MAX and CL_LNG_MIN <= lng <= CL_LNG_MAX):
            logger.info("Resultado fuera de Chile: %s, %s", lat, lng)
            return None
        return {
            "lat": lat,
            "lng": lng,
            "display_name": result.get("display_name", ""),
        }
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        logger.warning("geocode_address_chile error: %s", e)
        return None
