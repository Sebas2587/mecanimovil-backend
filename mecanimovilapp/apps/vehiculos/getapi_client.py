"""
Cliente auxiliar para consultas GetAPI.cl (patente y tasación).
"""
import logging

import requests

from .catalogo_resolver import normalizar_tipo_motor_vehiculo
from .kilometraje_validation import mileage_from_getapi_payload

logger = logging.getLogger(__name__)

GETAPI_KEY = "28054a51-09f6-4687-a4a7-ecf3ead55ef4"
GETAPI_HEADERS = {"x-api-key": GETAPI_KEY, "Content-Type": "application/json"}


def fetch_plate_basic_info(patente: str) -> dict:
    """
    Datos básicos del vehículo desde GetAPI plate.
    Retorna dict vacío si falla. tipo_motor viene normalizado (GASOLINA, DIESEL, etc.).
    """
    patente_norm = (patente or "").upper().strip()
    if not patente_norm:
        return {}

    url = f"https://chile.getapi.cl/v1/vehicles/plate/{patente_norm}"
    try:
        response = requests.get(url, headers=GETAPI_HEADERS, timeout=8)
        if response.status_code != 200:
            return {}

        json_response = response.json()
        if json_response.get("success") is False:
            return {}

        data = json_response.get("data", json_response) or {}
        fuel_raw = data.get("fuel") or data.get("tipo_motor") or ""
        tipo_motor = normalizar_tipo_motor_vehiculo(fuel_raw) if str(fuel_raw).strip() else None

        return {
            "patente": data.get("licensePlate", patente_norm),
            "marca_nombre": data.get("model", {}).get("brand", {}).get("name", ""),
            "modelo_nombre": data.get("model", {}).get("name", ""),
            "year": data.get("year", ""),
            "cilindraje": data.get("engine", ""),
            "tipo_motor": tipo_motor,
            "vin": data.get("vinNumber", ""),
        }
    except Exception as exc:
        logger.warning("GetAPI plate falló para patente %s: %s", patente_norm, exc)
        return {}


def fetch_appraisal_for_plate(patente):
    """
    Tasación usada / fiscal desde GetAPI appraisal.
    Returns dict con precios y tiene_tasacion_mercado (bool).
    """
    patente_norm = (patente or "").upper().strip()
    if not patente_norm:
        return {"tiene_tasacion_mercado": False}

    url = f"https://chile.getapi.cl/v1/vehicles/appraisal/{patente_norm}"
    try:
        response = requests.get(url, headers=GETAPI_HEADERS, timeout=10)
        if response.status_code != 200:
            return {"tiene_tasacion_mercado": False}

        payload = response.json()
        if payload.get("success") is False:
            return {"tiene_tasacion_mercado": False}

        appraisal_data = payload.get("data", {}) or {}
        info_fiscal = appraisal_data.get("informacionFiscal", {}) or {}
        precio_usado = appraisal_data.get("precioUsado", {}) or {}

        precio = int(precio_usado.get("precio", 0) or 0)
        banda_min = int(precio_usado.get("banda_min", 0) or 0)
        banda_max = int(precio_usado.get("banda_max", 0) or 0)
        tasacion_fiscal = int(info_fiscal.get("tasacion", 0) or 0)

        tiene_tasacion = any(v > 0 for v in (precio, banda_min, banda_max, tasacion_fiscal))
        mileage_appraisal = mileage_from_getapi_payload(appraisal_data)

        return {
            "precio_mercado_promedio": precio,
            "precio_mercado_min": banda_min,
            "precio_mercado_max": banda_max,
            "tasacion_fiscal": tasacion_fiscal,
            "permiso_circulacion": int(info_fiscal.get("permiso", 0) or 0),
            "year_tasacion_fiscal": int(info_fiscal.get("ano_info_fiscal", 0) or 0) or None,
            "precio_retoma": int(appraisal_data.get("precioRetoma", 0) or 0),
            "tiene_tasacion_mercado": tiene_tasacion,
            "mileage": mileage_appraisal,
        }
    except Exception as exc:
        logger.warning("GetAPI appraisal falló para patente %s: %s", patente_norm, exc)
        return {"tiene_tasacion_mercado": False, "mileage": None}
