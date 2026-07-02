"""
Asistente de diagnóstico / guía de reparación para técnicos (Gemini vía HTTP).
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_JSON_FENCE = re.compile(r'```(?:json)?\s*([\s\S]*?)\s*```', re.IGNORECASE)


def asistente_habilitado() -> bool:
    return bool(getattr(settings, 'ASISTENTE_DIAGNOSTICO_IA_ENABLED', False))


def _parse_json(text: str) -> dict[str, Any] | None:
    if not text or not str(text).strip():
        return None
    raw = str(text).strip()
    fence = _JSON_FENCE.search(raw)
    if fence:
        raw = fence.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find('{')
        end = raw.rfind('}')
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def _contexto_desde_orden(orden) -> dict[str, Any]:
    vehiculo = getattr(orden, 'vehiculo', None)
    marca = getattr(getattr(vehiculo, 'marca', None), 'nombre', '') or ''
    modelo = getattr(getattr(vehiculo, 'modelo', None), 'nombre', '') or ''
    anio = getattr(vehiculo, 'year', '') or ''
    cilindraje = getattr(vehiculo, 'cilindraje', '') or ''
    tipo_motor = getattr(vehiculo, 'tipo_motor', '') or ''
    version = getattr(vehiculo, 'version', '') or ''
    kilometraje = getattr(vehiculo, 'kilometraje', '') or ''

    descripcion_partes: list[str] = []
    if getattr(orden, 'notas_cliente', None):
        descripcion_partes.append(str(orden.notas_cliente).strip())

    oferta = getattr(orden, 'oferta_proveedor', None)
    if oferta is not None:
        solicitud = getattr(oferta, 'solicitud', None)
        if solicitud is not None and getattr(solicitud, 'descripcion_problema', None):
            descripcion_partes.append(str(solicitud.descripcion_problema).strip())

    servicios: list[str] = []
    try:
        for linea in orden.lineas.select_related('oferta_servicio__servicio').all():
            servicio = getattr(getattr(linea, 'oferta_servicio', None), 'servicio', None)
            if servicio and servicio.nombre:
                servicios.append(servicio.nombre)
                if servicio.descripcion:
                    servicios.append(servicio.descripcion[:240])
    except Exception:
        pass

    if servicios:
        descripcion_partes.append('Servicios: ' + '; '.join(dict.fromkeys(servicios)))

    problema = ' | '.join(p for p in descripcion_partes if p).strip()
    if not problema:
        problema = 'Servicio mecánico general según la orden asignada.'

    return {
        'marca': marca,
        'modelo': modelo,
        'anio': anio,
        'cilindraje': cilindraje,
        'tipo_motor': tipo_motor,
        'version': version,
        'kilometraje': kilometraje,
        'problema_reportado': problema,
        'vehiculo_label': f'{marca} {modelo} {anio} ({cilindraje})'.strip(),
    }


def _llamar_gemini(prompt: str) -> dict[str, Any] | None:
    api_key = (getattr(settings, 'GEMINI_API_KEY', '') or '').strip()
    if not api_key:
        return None
    model = getattr(settings, 'GEMINI_MODEL', 'gemini-2.0-flash') or 'gemini-2.0-flash'
    timeout = int(getattr(settings, 'ASISTENTE_DIAGNOSTICO_IA_TIMEOUT', 12) or 12)
    url = (
        f'https://generativelanguage.googleapis.com/v1beta/models/{model}:'
        f'generateContent?key={api_key}'
    )
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': 0.25,
            'maxOutputTokens': 1800,
            'responseMimeType': 'application/json',
        },
    }
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException:
        logger.warning('Asistente IA: error de red')
        return None
    if resp.status_code != 200:
        logger.warning('Asistente IA: HTTP %s', resp.status_code)
        return None
    try:
        text = resp.json()['candidates'][0]['content']['parts'][0]['text']
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return _parse_json(text)


def _normalizar_guia(data: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    causas = data.get('causas_probables') or []
    if not isinstance(causas, list):
        causas = [str(causas)]
    causas = [str(c).strip() for c in causas if str(c).strip()][:8]

    pasos = data.get('procedimiento_reparacion_detallado') or []
    if not isinstance(pasos, list):
        pasos = [str(pasos)]
    pasos = [str(p).strip() for p in pasos if str(p).strip()][:20]

    ref = data.get('referencia_manual') or {}
    if isinstance(ref, str):
        ref = {'titulo': 'Referencia sugerida', 'url': ref}
    if not isinstance(ref, dict):
        ref = {}
    referencia = {
        'titulo': str(ref.get('titulo') or 'Manual / guía de procedimiento').strip()[:200],
        'url': str(ref.get('url') or '').strip()[:500],
    }

    advertencias = data.get('advertencias_seguridad') or []
    if not isinstance(advertencias, list):
        advertencias = [str(advertencias)]
    advertencias = [str(a).strip() for a in advertencias if str(a).strip()][:8]

    return {
        'vehiculo': str(data.get('vehiculo') or ctx['vehiculo_label']).strip(),
        'problema_reportado': str(data.get('problema_reportado') or ctx['problema_reportado']).strip(),
        'causas_probables': causas,
        'procedimiento_reparacion_detallado': pasos,
        'referencia_manual': referencia,
        'advertencias_seguridad': advertencias,
    }


def generar_guia_reparacion(orden) -> dict[str, Any]:
    """
    Genera guía de reparación para una SolicitudServicio.
    Retorna dict con `disponible`, `contenido`, `error`, `latencia_ms`.
    """
    if not asistente_habilitado():
        return {
            'disponible': False,
            'contenido': None,
            'error': 'El asistente de diagnóstico IA no está habilitado.',
            'latencia_ms': 0,
        }

    ctx = _contexto_desde_orden(orden)
    prompt = f"""Eres un ingeniero mecánico automotriz experto en el mercado chileno.
Genera una guía práctica para un técnico que va a reparar el siguiente vehículo y problema.

Vehículo:
- Marca: {ctx['marca']}
- Modelo: {ctx['modelo']}
- Año: {ctx['anio']}
- Cilindraje: {ctx['cilindraje']}
- Tipo motor: {ctx['tipo_motor']}
- Versión: {ctx['version']}
- Kilometraje: {ctx['kilometraje']} km

Problema / servicio a realizar:
{ctx['problema_reportado']}

Responde SOLO JSON válido en español con esta estructura exacta:
{{
  "vehiculo": "Marca Modelo Año (Cilindraje)",
  "problema_reportado": "resumen del problema",
  "causas_probables": ["causa 1", "causa 2"],
  "procedimiento_reparacion_detallado": [
    "Paso 1: instrucción específica para este modelo",
    "Paso 2: ..."
  ],
  "referencia_manual": {{
    "titulo": "Título descriptivo del manual o video guía",
    "url": "URL de búsqueda YouTube o manual técnico (https://www.youtube.com/results?search_query=...)"
  }},
  "advertencias_seguridad": ["advertencia 1"]
}}

Sé específico para el modelo indicado. No inventes datos del vehículo que no fueron entregados."""

    inicio = time.monotonic()
    crudo = _llamar_gemini(prompt)
    latencia_ms = int((time.monotonic() - inicio) * 1000)

    if not crudo:
        return {
            'disponible': False,
            'contenido': None,
            'error': 'No se pudo generar la guía en este momento. Intenta más tarde.',
            'latencia_ms': latencia_ms,
        }

    contenido = _normalizar_guia(crudo, ctx)
    return {
        'disponible': True,
        'contenido': contenido,
        'error': None,
        'latencia_ms': latencia_ms,
    }
