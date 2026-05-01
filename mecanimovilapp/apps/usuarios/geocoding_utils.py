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


def reverse_geocode_chile(lat: float, lng: float, *, timeout: int = 10):
    """
    Nominatim reverse (lat/lng → display_name en Chile).
    Usado cuando el cliente envía solo coordenadas y debemos persistir texto en Usuario.direccion.
    """
    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (TypeError, ValueError):
        return None
    if not (CL_LAT_MIN <= lat_f <= CL_LAT_MAX and CL_LNG_MIN <= lng_f <= CL_LNG_MAX):
        return None

    reverse_url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "lat": lat_f,
        "lon": lng_f,
        "format": "json",
        "addressdetails": "1",
        "accept-language": "es",
        "zoom": "18",
    }
    headers = {"User-Agent": "MecaniMovil/1.0 (contacto@app)"}
    try:
        response = requests.get(reverse_url, params=params, headers=headers, timeout=timeout)
        time.sleep(1)
        if response.status_code != 200:
            logger.warning("Nominatim reverse HTTP %s", response.status_code)
            return None
        data = response.json()
        addr = data.get("address") or {}
        cc = (addr.get("country_code") or "").lower()
        if cc and cc != "cl":
            return None
        display = data.get("display_name") or ""
        if not display.strip():
            return None
        return {"display_name": display.strip()}
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        logger.warning("reverse_geocode_chile error: %s", e)
        return None
