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

from .contexto_motor import (
    consolidar_contexto_motor,
    inferir_motor_desde_modelo,
    inferir_tipo_motor_desde_texto,
    motor_desde_oferta,
    parse_tipo_motor_si_presente,
    resolver_motor_vehiculo,
)

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
    patente = getattr(vehiculo, 'patente', '') or ''
    version = getattr(vehiculo, 'version', '') or ''
    kilometraje = getattr(vehiculo, 'kilometraje', '') or ''

    motor_vehiculo = resolver_motor_vehiculo(vehiculo=vehiculo, patente=patente)
    if not cilindraje and patente:
        from mecanimovilapp.apps.vehiculos.getapi_client import fetch_plate_basic_info

        info_patente = fetch_plate_basic_info(patente)
        if not motor_vehiculo:
            motor_vehiculo = parse_tipo_motor_si_presente(info_patente.get('tipo_motor'))
        if not cilindraje and info_patente.get('cilindraje'):
            cilindraje = str(info_patente['cilindraje'])

    descripcion_partes: list[str] = []
    if getattr(orden, 'notas_cliente', None):
        descripcion_partes.append(str(orden.notas_cliente).strip())

    oferta = getattr(orden, 'oferta_proveedor', None)
    if oferta is not None:
        solicitud = getattr(oferta, 'solicitud', None)
        if solicitud is not None and getattr(solicitud, 'descripcion_problema', None):
            descripcion_partes.append(str(solicitud.descripcion_problema).strip())

    servicios: list[str] = []
    motores_servicio: list[str] = []
    try:
        for linea in orden.lineas.select_related('oferta_servicio__servicio').all():
            oferta = getattr(linea, 'oferta_servicio', None)
            servicio = getattr(oferta, 'servicio', None) if oferta else None
            if servicio and servicio.nombre:
                servicios.append(servicio.nombre)
                if servicio.descripcion:
                    servicios.append(servicio.descripcion[:240])
            motor_oferta = motor_desde_oferta(oferta)
            if motor_oferta:
                motores_servicio.append(motor_oferta)
    except Exception:
        pass

    motor_servicio = motores_servicio[0] if len(set(motores_servicio)) == 1 else None
    if motor_servicio is None and servicios:
        motor_servicio = inferir_tipo_motor_desde_texto('; '.join(servicios))

    motor_problema = None
    for parte in descripcion_partes:
        inferido = inferir_tipo_motor_desde_texto(parte)
        if inferido:
            motor_problema = inferido
            break

    if servicios:
        descripcion_partes.append('Servicios: ' + '; '.join(dict.fromkeys(servicios)))

    problema = ' | '.join(p for p in descripcion_partes if p).strip()
    if not problema:
        problema = 'Servicio mecánico general según la orden asignada.'
    if motor_problema is None:
        motor_problema = inferir_tipo_motor_desde_texto(problema)

    motor_modelo = inferir_motor_desde_modelo(marca, modelo, version)

    return _armar_contexto(
        marca=marca,
        modelo=modelo,
        anio=anio,
        cilindraje=cilindraje,
        patente=patente,
        motor_vehiculo=motor_vehiculo,
        motor_servicio=motor_servicio,
        motor_problema=motor_problema,
        motor_modelo=motor_modelo,
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

    patente = (det.vehiculo_patente or '').strip()
    motor_vehiculo = resolver_motor_vehiculo(patente=patente)
    motor_servicio = motor_desde_oferta(oferta_servicio)
    if motor_servicio is None:
        motor_servicio = inferir_tipo_motor_desde_texto(servicio_nombre)
    motor_problema = (
        inferir_tipo_motor_desde_texto(det.descripcion) if det.descripcion else None
    )
    motor_modelo = inferir_motor_desde_modelo(marca, modelo, '')

    if not cilindraje and patente:
        from mecanimovilapp.apps.vehiculos.getapi_client import fetch_plate_basic_info

        info_patente = fetch_plate_basic_info(patente)
        if not motor_vehiculo:
            motor_vehiculo = parse_tipo_motor_si_presente(info_patente.get('tipo_motor'))
        if info_patente.get('cilindraje'):
            cilindraje = str(info_patente['cilindraje'])

    descripcion_partes: list[str] = []
    if det.descripcion:
        descripcion_partes.append(str(det.descripcion).strip())
    if servicio_nombre:
        descripcion_partes.append(f'Servicio: {servicio_nombre}')

    problema = ' | '.join(p for p in descripcion_partes if p).strip()
    if not problema:
        problema = 'Servicio mecánico según cita personal agendada.'
    if motor_problema is None:
        motor_problema = inferir_tipo_motor_desde_texto(problema)

    return _armar_contexto(
        marca=marca,
        modelo=modelo,
        anio=anio,
        cilindraje=cilindraje,
        patente=patente,
        motor_vehiculo=motor_vehiculo,
        motor_servicio=motor_servicio,
        motor_problema=motor_problema,
        motor_modelo=motor_modelo,
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
    patente: str = '',
    motor_vehiculo: str | None = None,
    motor_servicio: str | None = None,
    motor_problema: str | None = None,
    motor_modelo: str | None = None,
    version: str = '',
    kilometraje: str | int = '',
    problema_reportado: str,
) -> dict[str, Any]:
    motor_ctx = consolidar_contexto_motor(
        motor_vehiculo=motor_vehiculo,
        motor_servicio=motor_servicio,
        motor_problema=motor_problema,
        motor_modelo=motor_modelo,
    )
    vehiculo_label = f'{marca} {modelo} {anio} ({cilindraje})'.strip()
    return {
        'marca': str(marca or ''),
        'modelo': str(modelo or ''),
        'anio': str(anio or ''),
        'cilindraje': str(cilindraje or ''),
        'patente': str(patente or ''),
        'version': str(version or ''),
        'kilometraje': str(kilometraje or ''),
        'problema_reportado': problema_reportado,
        'vehiculo_label': vehiculo_label or 'Vehículo no especificado',
        **motor_ctx,
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
        'tipo_motor': ctx.get('tipo_motor_efectivo_label') or '',
        'tipo_motor_codigo': ctx.get('tipo_motor_efectivo') or '',
        'aviso_motor': (
            str(ctx.get('tipo_motor_conflicto_detalle') or '').strip()
            if ctx.get('tipo_motor_conflicto')
            else ''
        ),
        'servicio_motor_incoherente': bool(ctx.get('tipo_motor_servicio_posible_error')),
        'causas_probables': causas,
        'procedimiento_reparacion_detallado': pasos,
        'referencia_manual': referencia,
        'advertencias_seguridad': advertencias,
    }


def _bloque_motor_prompt(ctx: dict[str, Any]) -> str:
    efectivo_label = ctx.get('tipo_motor_efectivo_label') or 'No especificado'
    lineas = [
        f"- Registro/patente (API — fuente autoritativa): "
        f"{ctx.get('tipo_motor_vehiculo_label') or 'No disponible'}",
        f"- Nomenclatura del modelo ({ctx.get('marca', '')} {ctx.get('modelo', '')}): "
        f"{ctx.get('tipo_motor_modelo_label') or 'Sin indicadores claros'}",
        f"- Servicio/oferta asignado: {ctx.get('tipo_motor_servicio_label') or 'No especificado'}",
        f"- Palabras clave en descripción del problema: "
        f"{ctx.get('tipo_motor_problema_label') or 'Ninguna'}",
        f"- Motor efectivo para ESTA guía (usa este): {efectivo_label}",
    ]
    if ctx.get('patente'):
        lineas.append(f"- Patente: {ctx['patente']}")
    if ctx.get('tipo_motor_conflicto'):
        detalle = (ctx.get('tipo_motor_conflicto_detalle') or '').strip()
        lineas.append(
            '- INCOHERENCIA DETECTADA: el servicio asignado y/o la nota del caso NO concuerdan '
            f'con los datos del vehículo (patente/modelo). '
            f'Genera la guía EXCLUSIVAMENTE para {efectivo_label} según el vehículo registrado. '
            'NO sigas el nombre del servicio si contradice la patente. '
            'Incluye en advertencias que el servicio catalogado puede estar mal asignado '
            'y que conviene confirmar con el cliente antes de intervenir.'
        )
        if detalle:
            lineas.append(f'- Detalle: {detalle}')
    reglas = ctx.get('tipo_motor_reglas') or ''
    if reglas:
        lineas.append(f"- Reglas obligatorias para {efectivo_label}: {reglas}")
    return '\n'.join(lineas)


def _construir_prompt(ctx: dict[str, Any]) -> str:
    motor_bloque = _bloque_motor_prompt(ctx)
    efectivo = ctx.get('tipo_motor_efectivo_label') or 'el motor indicado'
    return f"""Eres un ingeniero mecánico automotriz experto en el mercado chileno.
Genera una guía práctica para un técnico que va a reparar el siguiente vehículo y problema.

Vehículo:
- Marca: {ctx['marca']}
- Modelo: {ctx['modelo']}
- Año: {ctx['anio']}
- Cilindraje: {ctx['cilindraje']}
- Versión: {ctx['version']}
- Kilometraje: {ctx['kilometraje']} km

Tipo de motor (OBLIGATORIO — respeta estas restricciones):
{motor_bloque}

Problema / servicio a realizar:
{ctx['problema_reportado']}

REGLAS CRÍTICAS:
1. Los datos de patente/modelo del vehículo son la fuente de verdad. El servicio asignado puede estar mal (ej. "Diagnóstico Diesel" en un T-Jet bencinero).
2. Si hay incoherencia, genera la guía para {efectivo} (motor del vehículo), NO para el servicio mal catalogado.
3. Toda la guía debe ser EXCLUSIVAMENTE para {efectivo}.
4. PROHIBIDO mezclar procedimientos diésel y bencina/gasolina.
5. Si el problema menciona "encendido/inyectores" y el motor es bencinero, habla de bujías/bobina/inyectores gasolina; si es diésel, de glow plugs e inyectores diésel.
6. Si el motor es eléctrico, NO menciones bujías, filtros de combustible ni aceite de motor convencional.
7. Si el motor es híbrido, separa claramente intervenciones ICE vs sistema eléctrico/HV.
8. Sé específico para marca/modelo/año. No inventes datos no entregados.

Responde SOLO JSON válido en español con esta estructura exacta:
{{
  "vehiculo": "Marca Modelo Año (Cilindraje)",
  "problema_reportado": "resumen del problema",
  "causas_probables": ["causa 1", "causa 2"],
  "procedimiento_reparacion_detallado": [
    "Paso 1: instrucción específica para este modelo y tipo de motor",
    "Paso 2: ..."
  ],
  "referencia_manual": {{
    "titulo": "Título descriptivo del manual o video guía",
    "url": "URL de búsqueda YouTube o manual técnico (https://www.youtube.com/results?search_query=...)"
  }},
  "advertencias_seguridad": ["advertencia 1"]
}}"""


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
