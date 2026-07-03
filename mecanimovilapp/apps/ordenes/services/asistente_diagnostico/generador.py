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

    return _armar_contexto(
        marca=marca,
        modelo=modelo,
        anio=anio,
        cilindraje=cilindraje,
        tipo_motor=tipo_motor,
        version=version,
        kilometraje=kilometraje,
        problema_reportado=problema,
    )


def _contexto_desde_cita_personal(cita) -> dict[str, Any]:
    det = getattr(cita, 'detalle', None)
    if det is None:
        return _armar_contexto(
            problema_reportado='Servicio mecánico según cita personal agendada.',
        )

    marca = (det.vehiculo_marca or '').strip()
    modelo = (det.vehiculo_modelo or '').strip()
    anio = det.vehiculo_anio or ''
    cilindraje = (det.vehiculo_cilindraje or '').strip()

    servicio_nombre = (det.servicio_nombre or '').strip()
    oferta_servicio = getattr(det, 'oferta_servicio', None)
    if oferta_servicio is not None:
        servicio_cat = getattr(oferta_servicio, 'servicio', None)
        if servicio_cat is not None and getattr(servicio_cat, 'nombre', None):
            servicio_nombre = servicio_cat.nombre.strip() or servicio_nombre

    descripcion_partes: list[str] = []
    if det.descripcion:
        descripcion_partes.append(str(det.descripcion).strip())
    if servicio_nombre:
        descripcion_partes.append(f'Servicio: {servicio_nombre}')

    problema = ' | '.join(p for p in descripcion_partes if p).strip()
    if not problema:
        problema = 'Servicio mecánico según cita personal agendada.'

    return _armar_contexto(
        marca=marca,
        modelo=modelo,
        anio=anio,
        cilindraje=cilindraje,
        tipo_motor='',
        version='',
        kilometraje='',
        problema_reportado=problema,
    )


def _armar_contexto(
    *,
    marca: str = '',
    modelo: str = '',
    anio: str | int = '',
    cilindraje: str = '',
    tipo_motor: str = '',
    version: str = '',
    kilometraje: str | int = '',
    problema_reportado: str,
) -> dict[str, Any]:
    vehiculo_label = f'{marca} {modelo} {anio} ({cilindraje})'.strip()
    return {
        'marca': str(marca or ''),
        'modelo': str(modelo or ''),
        'anio': str(anio or ''),
        'cilindraje': str(cilindraje or ''),
        'tipo_motor': str(tipo_motor or ''),
        'version': str(version or ''),
        'kilometraje': str(kilometraje or ''),
        'problema_reportado': problema_reportado,
        'vehiculo_label': vehiculo_label or 'Vehículo no especificado',
    }


def _llamar_gemini(prompt: str) -> tuple[dict[str, Any] | None, dict[str, int | str], str | None]:
    """
    Llama a Gemini. Retorna (json_parseado, uso_tokens, mensaje_error_usuario).
    """
    api_key = (getattr(settings, 'GEMINI_API_KEY', '') or '').strip()
    model = (
        getattr(settings, 'ASISTENTE_DIAGNOSTICO_GEMINI_MODEL', '')
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

    timeout = int(getattr(settings, 'ASISTENTE_DIAGNOSTICO_IA_TIMEOUT', 12) or 12)
    max_retries = max(0, min(int(getattr(settings, 'GEMINI_RETRY_MAX', 2) or 2), 4))
    url = (
        f'https://generativelanguage.googleapis.com/v1beta/models/{model}:'
        f'generateContent?key={api_key}'
    )
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': 0.25,
            'maxOutputTokens': 1400,
            'responseMimeType': 'application/json',
        },
    }

    ultimo_status: int | None = None
    for intento in range(max_retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
        except requests.RequestException:
            logger.warning('Asistente IA: error de red')
            return None, uso_vacio, 'Error de conexión con Gemini. Intenta de nuevo en unos segundos.'

        ultimo_status = resp.status_code
        if resp.status_code == 200:
            try:
                body = resp.json()
                text = body['candidates'][0]['content']['parts'][0]['text']
            except (KeyError, IndexError, TypeError, ValueError):
                return None, uso_vacio, 'Gemini respondió en un formato inesperado. Intenta más tarde.'

            meta = body.get('usageMetadata') or {}
            tokens_entrada = int(meta.get('promptTokenCount') or 0)
            tokens_salida = int(meta.get('candidatesTokenCount') or 0)
            tokens_total = int(meta.get('totalTokenCount') or tokens_entrada + tokens_salida)
            uso = {
                'tokens_entrada': tokens_entrada,
                'tokens_salida': tokens_salida,
                'tokens_total': tokens_total,
                'modelo': model,
            }
            return _parse_json(text), uso, None

        if resp.status_code == 429 and intento < max_retries:
            retry_after_hdr = resp.headers.get('Retry-After')
            try:
                espera = int(retry_after_hdr) if retry_after_hdr else 0
            except (TypeError, ValueError):
                espera = 0
            espera = max(espera, 2 ** intento)
            espera = min(espera, 10)
            logger.warning(
                'Asistente IA: HTTP 429, reintento %s/%s en %ss',
                intento + 1,
                max_retries,
                espera,
            )
            time.sleep(espera)
            continue

        detalle_api = ''
        try:
            err_body = resp.json().get('error') or {}
            detalle_api = str(err_body.get('message') or err_body.get('status') or '').strip()
        except (ValueError, TypeError, AttributeError):
            pass

        if resp.status_code == 429:
            logger.warning('Asistente IA: HTTP 429 (cuota/rate limit)%s', f' — {detalle_api}' if detalle_api else '')
            return None, uso_vacio, (
                'Gemini alcanzó el límite de consultas (cuota o velocidad). '
                'Espera 1–2 minutos e intenta de nuevo. '
                'Si persiste, revisa la cuota en Google AI Studio o el uso en Rendimiento del taller.'
            )

        logger.warning(
            'Asistente IA: HTTP %s%s',
            resp.status_code,
            f' — {detalle_api}' if detalle_api else '',
        )
        return None, uso_vacio, 'No se pudo generar la guía en este momento. Intenta más tarde.'

    if ultimo_status == 429:
        return None, uso_vacio, (
            'Gemini alcanzó el límite de consultas. Espera unos minutos e intenta de nuevo.'
        )
    return None, uso_vacio, 'No se pudo generar la guía en este momento. Intenta más tarde.'


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


def _construir_prompt(ctx: dict[str, Any]) -> str:
    return f"""Eres un ingeniero mecánico automotriz experto en el mercado chileno.
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


def _generar_guia_desde_contexto(ctx: dict[str, Any]) -> dict[str, Any]:
    if not asistente_habilitado():
        return {
            'disponible': False,
            'contenido': None,
            'error': 'El asistente de diagnóstico IA no está habilitado.',
            'latencia_ms': 0,
        }

    prompt = _construir_prompt(ctx)
    inicio = time.monotonic()
    crudo, uso, error_usuario = _llamar_gemini(prompt)
    latencia_ms = int((time.monotonic() - inicio) * 1000)

    if not crudo:
        return {
            'disponible': False,
            'contenido': None,
            'error': error_usuario or 'No se pudo generar la guía en este momento. Intenta más tarde.',
            'latencia_ms': latencia_ms,
            'tokens_entrada': int(uso.get('tokens_entrada') or 0),
            'tokens_salida': int(uso.get('tokens_salida') or 0),
            'tokens_total': int(uso.get('tokens_total') or 0),
            'modelo': str(uso.get('modelo') or ''),
        }

    contenido = _normalizar_guia(crudo, ctx)
    return {
        'disponible': True,
        'contenido': contenido,
        'error': None,
        'latencia_ms': latencia_ms,
        'tokens_entrada': int(uso.get('tokens_entrada') or 0),
        'tokens_salida': int(uso.get('tokens_salida') or 0),
        'tokens_total': int(uso.get('tokens_total') or 0),
        'modelo': str(uso.get('modelo') or ''),
    }


def generar_guia_reparacion(orden) -> dict[str, Any]:
    """
    Genera guía de reparación para una SolicitudServicio.
    Retorna dict con `disponible`, `contenido`, `error`, `latencia_ms`.
    """
    ctx = _contexto_desde_orden(orden)
    return _generar_guia_desde_contexto(ctx)


def generar_guia_reparacion_cita_personal(cita) -> dict[str, Any]:
    """
    Genera guía de reparación para una CitaAgendaPersonal.
    Retorna dict con `disponible`, `contenido`, `error`, `latencia_ms`.
    """
    ctx = _contexto_desde_cita_personal(cita)
    return _generar_guia_desde_contexto(ctx)
