"""Generador de cotización IA vía Gemini."""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import requests
from django.conf import settings

from .contexto import armar_contexto_cotizacion
from .normalizar import normalizar_cotizacion_ia

logger = logging.getLogger(__name__)

_JSON_FENCE = re.compile(r'```(?:json)?\s*([\s\S]*?)\s*```', re.IGNORECASE)


def asistente_cotizacion_habilitado() -> bool:
    return bool(getattr(settings, 'ASISTENTE_COTIZACION_IA_ENABLED', False))


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


def _llamar_gemini(prompt: str) -> tuple[dict[str, Any] | None, dict[str, int | str], str | None]:
    api_key = (getattr(settings, 'GEMINI_API_KEY', '') or '').strip()
    model = (
        getattr(settings, 'ASISTENTE_COTIZACION_GEMINI_MODEL', '')
        or getattr(settings, 'ASISTENTE_DIAGNOSTICO_GEMINI_MODEL', '')
        or getattr(settings, 'GEMINI_MODEL', 'gemini-3.1-flash-lite')
        or 'gemini-3.1-flash-lite'
    ).strip()
    uso_vacio: dict[str, int | str] = {
        'tokens_entrada': 0,
        'tokens_salida': 0,
        'tokens_total': 0,
        'modelo': model,
    }
    if not api_key:
        return None, uso_vacio, 'El asistente IA no está configurado en el servidor (falta GEMINI_API_KEY).'

    timeout = int(getattr(settings, 'ASISTENTE_COTIZACION_IA_TIMEOUT', 15) or 15)
    max_retries = max(0, min(int(getattr(settings, 'GEMINI_RETRY_MAX', 2) or 2), 4))
    url = (
        f'https://generativelanguage.googleapis.com/v1beta/models/{model}:'
        f'generateContent?key={api_key}'
    )
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': 0.3,
            'maxOutputTokens': 1800,
            'responseMimeType': 'application/json',
        },
    }

    for intento in range(max_retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
        except requests.RequestException:
            return None, uso_vacio, 'Error de conexión con Gemini. Intenta de nuevo.'

        if resp.status_code == 200:
            try:
                body = resp.json()
                text = body['candidates'][0]['content']['parts'][0]['text']
            except (KeyError, IndexError, TypeError, ValueError):
                return None, uso_vacio, 'Gemini respondió en un formato inesperado.'

            meta = body.get('usageMetadata') or {}
            uso = {
                'tokens_entrada': int(meta.get('promptTokenCount') or 0),
                'tokens_salida': int(meta.get('candidatesTokenCount') or 0),
                'tokens_total': int(meta.get('totalTokenCount') or 0),
                'modelo': model,
            }
            return _parse_json(text), uso, None

        if resp.status_code == 429 and intento < max_retries:
            time.sleep(min(10, max(2, 2 ** intento)))
            continue

        if resp.status_code == 429:
            return None, uso_vacio, 'Gemini alcanzó el límite de consultas. Espera unos minutos.'
        return None, uso_vacio, 'No se pudo generar la cotización en este momento.'

    return None, uso_vacio, 'No se pudo generar la cotización en este momento.'


def _construir_prompt(ctx: dict[str, Any]) -> str:
    efectivo = ctx.get('tipo_motor_efectivo_label') or 'No especificado'
    motor_bloque = (
        f"- Motor del vehículo (patente/modelo): {efectivo}\n"
        f"- Aviso motor: {ctx.get('aviso_motor') or ctx.get('tipo_motor_conflicto_detalle') or 'Ninguno'}"
    )
    chat = ctx.get('chat_reciente') or 'Sin mensajes previos.'
    return f"""Eres un asesor de taller mecánico en Chile. Genera una cotización referencial en pesos chilenos (CLP enteros, sin decimales).

Vehículo:
- Marca: {ctx.get('marca', '')}
- Modelo: {ctx.get('modelo', '')}
- Año: {ctx.get('anio', '')}
- Patente: {ctx.get('patente', '')}
- Cilindraje: {ctx.get('cilindraje', '')}
- Modalidad: {ctx.get('modalidad', 'taller')}

{motor_bloque}

Servicio solicitado: {ctx.get('servicio_nombre', '')}
Descripción del problema: {ctx.get('descripcion_problema', '')}

Contexto del chat reciente:
{chat}

REGLAS:
1. Precios referenciales mercado Chile (CLP). Usa valores realistas para el servicio y repuestos típicos.
2. El motor efectivo de la cotización es {efectivo}. No mezcles repuestos diésel/bencina.
3. Incluye mano de obra separada de repuestos.
4. Lista repuestos probables con cantidad y precio unitario estimado.
5. duracion_minutos_estimada razonable para el servicio.

Responde SOLO JSON válido en español:
{{
  "servicio_nombre": "...",
  "descripcion_resumen": "...",
  "tipo_motor_efectivo": "GASOLINA|DIESEL|ELECTRICO|HIBRIDO",
  "tipo_motor_label": "...",
  "duracion_minutos_estimada": 90,
  "mano_obra_clp": 45000,
  "repuestos": [
    {{"nombre": "...", "cantidad": 1, "precio_unitario_clp": 65000, "comentario": "..."}}
  ],
  "advertencias": ["Precios referenciales, sujetos a confirmación en taller"]
}}"""


def generar_cotizacion_ia(
    *,
    conversation=None,
    servicio_nombre: str = '',
    descripcion_problema: str = '',
    modalidad: str = 'taller',
    vehiculo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not asistente_cotizacion_habilitado():
        return {
            'disponible': False,
            'contenido': None,
            'error': 'El asistente de cotización IA no está habilitado.',
            'latencia_ms': 0,
        }

    ctx = armar_contexto_cotizacion(
        conversation=conversation,
        servicio_nombre=servicio_nombre,
        descripcion_problema=descripcion_problema,
        modalidad=modalidad,
        vehiculo=vehiculo,
    )
    prompt = _construir_prompt(ctx)
    inicio = time.monotonic()
    crudo, uso, error = _llamar_gemini(prompt)
    latencia_ms = int((time.monotonic() - inicio) * 1000)

    if not crudo:
        return {
            'disponible': False,
            'contenido': None,
            'error': error or 'No se pudo generar la cotización.',
            'latencia_ms': latencia_ms,
            'tokens_entrada': int(uso.get('tokens_entrada') or 0),
            'tokens_salida': int(uso.get('tokens_salida') or 0),
            'modelo': str(uso.get('modelo') or ''),
        }

    contenido = normalizar_cotizacion_ia(crudo, ctx)
    return {
        'disponible': True,
        'contenido': contenido,
        'contenido_ia': crudo,
        'contexto': {
            'vehiculo_marca': ctx.get('marca', ''),
            'vehiculo_modelo': ctx.get('modelo', ''),
            'vehiculo_anio': ctx.get('anio', ''),
            'vehiculo_patente': ctx.get('patente', ''),
            'vehiculo_cilindraje': ctx.get('cilindraje', ''),
            'tipo_motor': ctx.get('tipo_motor_efectivo', ''),
            'tipo_motor_label': ctx.get('tipo_motor_efectivo_label', ''),
            'aviso_motor': ctx.get('tipo_motor_conflicto_detalle', ''),
        },
        'error': None,
        'latencia_ms': latencia_ms,
        'tokens_entrada': int(uso.get('tokens_entrada') or 0),
        'tokens_salida': int(uso.get('tokens_salida') or 0),
        'modelo': str(uso.get('modelo') or ''),
    }
