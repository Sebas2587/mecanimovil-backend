"""Análisis multimodal (imagen / audio / video) para enriquecer el contexto del agente IA.

Basado en experiments/investigacion-problemas comunes-autos/analizador_fallas.py,
adaptado a producción: REST Gemini + Pillow (sin OpenCV/librosa).
"""
from __future__ import annotations

import base64
import io
import json
import logging
import mimetypes
import re
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_JSON_FENCE = re.compile(r'```(?:json)?\s*([\s\S]*?)\s*```', re.IGNORECASE)

_MEDIA_LABELS = frozenset(
    {'imagen', 'audio', 'video', 'documento', 'archivo', 'sticker', 'adjunto'}
)

# Límite de bytes para inline_data a Gemini (evita timeouts / payloads enormes).
_MAX_INLINE_BYTES = 12 * 1024 * 1024


def es_solo_etiqueta_media(texto: str | None) -> bool:
    t = (texto or '').strip().lower()
    return (not t) or t in _MEDIA_LABELS


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


def _mime_from_message(message, kind: str | None) -> str:
    name = ''
    if getattr(message, 'attachment', None):
        name = getattr(message.attachment, 'name', '') or ''
    guessed, _ = mimetypes.guess_type(name)
    if guessed:
        return guessed
    kind = (kind or '').lower()
    return {
        'image': 'image/jpeg',
        'audio': 'audio/ogg',
        'video': 'video/mp4',
        'document': 'application/octet-stream',
    }.get(kind, 'application/octet-stream')


def _comprimir_imagen_si_aplica(raw: bytes, mime: str) -> tuple[bytes, str]:
    if not mime.startswith('image/'):
        return raw, mime
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        img = img.convert('RGB')
        max_side = 1280
        w, h = img.size
        if max(w, h) > max_side:
            ratio = max_side / float(max(w, h))
            img = img.resize((int(w * ratio), int(h * ratio)), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=85, optimize=True)
        return buf.getvalue(), 'image/jpeg'
    except Exception:
        logger.debug('No se pudo comprimir imagen; se envía original', exc_info=True)
        return raw, mime


def _leer_adjunto_bytes(message) -> tuple[bytes | None, str, str]:
    """Devuelve (bytes, mime, kind)."""
    meta = message.channel_metadata or {}
    media = meta.get('media') or {}
    kind = (media.get('kind') or '').lower()

    if message.attachment:
        try:
            message.attachment.open('rb')
            raw = message.attachment.read()
        except Exception:
            logger.exception('No se pudo leer attachment mensaje %s', message.id)
            return None, '', kind or 'document'
        finally:
            try:
                message.attachment.close()
            except Exception:
                pass
        mime = media.get('mime_type') or _mime_from_message(message, kind)
        if not kind:
            from mecanimovilapp.apps.omnichannel.services.meta_media import infer_media_kind

            kind = infer_media_kind(mime, getattr(message.attachment, 'name', None))
        if len(raw) > _MAX_INLINE_BYTES:
            logger.warning(
                'Adjunto mensaje %s demasiado grande (%s bytes); se omite multimodal',
                message.id,
                len(raw),
            )
            return None, mime, kind
        if kind == 'image' or mime.startswith('image/'):
            raw, mime = _comprimir_imagen_si_aplica(raw, mime)
        return raw, mime, kind

    return None, media.get('mime_type') or '', kind


def _prompt_analisis(*, vehiculo: dict[str, Any], caption: str, kind: str) -> str:
    marca = (vehiculo.get('marca') or '').strip() or 'desconocida'
    modelo = (vehiculo.get('modelo') or '').strip() or 'desconocido'
    anio = (vehiculo.get('anio') or '').strip() or 'desconocido'
    patente = (vehiculo.get('patente') or '').strip() or 'sin patente'
    return f"""Eres un mecánico automotriz chileno experto. Analiza el adjunto ({kind}) del cliente.

Vehículo conocido (puede estar incompleto): {marca} {modelo} {anio}, patente {patente}.
Texto/caption del mensaje: {caption or '(sin texto)'}

Si es AUDIO:
- Si hay voz: transcribe fielmente (español chileno) y resume el problema.
- Si hay ruido de motor/chasis: describe patrón, cuándo ocurre y posibles causas.

Si es IMAGEN:
- Clasifica: vano_motor | tablero | pieza_individual | dano_carroceria | documento | otro.
- Describe solo lo visible (sin inventar). Luces del tablero, fugas, piezas, daños.
- Sintetiza el síntoma o hallazgo principal.

Si es VIDEO:
- Resume qué se ve/oye y el síntoma probable.

Responde SOLO JSON:
{{
  "tipo_medio": "{kind}",
  "tipo_imagen_detectada": "vano_motor|tablero|pieza_individual|dano_carroceria|documento|otro|null",
  "transcripcion_voz": "texto o null",
  "analisis_acustico_ruidos": "texto o null",
  "hallazgos_visuales": ["..."],
  "luces_tablero": ["..."],
  "sintoma_sintetizado": "frase corta del problema detectado",
  "resumen_para_chat": "1-3 oraciones en español chileno que el asistente usará como si el cliente lo hubiera escrito",
  "confianza": 0.0
}}"""


def analizar_adjunto_mensaje(
    message,
    *,
    vehiculo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Analiza attachment del mensaje con Gemini multimodal.
    Idempotente: si channel_metadata ya tiene media_analisis, lo reutiliza.
    """
    meta = dict(message.channel_metadata or {})
    cached = meta.get('media_analisis')
    if isinstance(cached, dict) and cached.get('resumen_para_chat'):
        return cached

    media = meta.get('media') or {}
    if not message.attachment and not media:
        return {}

    raw, mime, kind = _leer_adjunto_bytes(message)
    if not raw:
        # Adjunto aún no descargado o demasiado grande.
        return {'pendiente': True, 'kind': kind or media.get('kind')}

    api_key = (getattr(settings, 'GEMINI_API_KEY', '') or '').strip()
    if not api_key:
        return {'error': 'GEMINI_API_KEY no configurada'}

    model = (
        getattr(settings, 'AGENTE_IA_MULTIMODAL_MODEL', '')
        or getattr(settings, 'AGENTE_IA_GEMINI_MODEL', '')
        or 'gemini-2.5-flash'
    ).strip()
    timeout = int(getattr(settings, 'AGENTE_IA_MULTIMODAL_TIMEOUT', 45) or 45)
    caption = (message.content or '').strip()
    prompt = _prompt_analisis(vehiculo=vehiculo or {}, caption=caption, kind=kind or 'adjunto')

    b64 = base64.b64encode(raw).decode('ascii')
    url = (
        f'https://generativelanguage.googleapis.com/v1beta/models/{model}:'
        f'generateContent?key={api_key}'
    )
    payload = {
        'contents': [
            {
                'parts': [
                    {'text': prompt},
                    {'inline_data': {'mime_type': mime, 'data': b64}},
                ]
            }
        ],
        'generationConfig': {
            'temperature': 0.2,
            'maxOutputTokens': 2048,
            'responseMimeType': 'application/json',
        },
    }

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning('Error multimodal Gemini msg=%s: %s', message.id, exc)
        return {'error': 'conexion_gemini'}

    if resp.status_code != 200:
        logger.warning(
            'Gemini multimodal HTTP %s msg=%s: %s',
            resp.status_code,
            message.id,
            (resp.text or '')[:300],
        )
        return {'error': f'http_{resp.status_code}'}

    try:
        body = resp.json()
        text = body['candidates'][0]['content']['parts'][0]['text']
    except (KeyError, IndexError, TypeError, ValueError):
        return {'error': 'respuesta_inesperada'}

    data = _parse_json(text) or {}
    resumen = (data.get('resumen_para_chat') or data.get('sintoma_sintetizado') or '').strip()
    transcripcion = (data.get('transcripcion_voz') or '').strip()
    if not resumen and transcripcion:
        resumen = transcripcion

    resultado = {
        'tipo_medio': kind or data.get('tipo_medio') or 'adjunto',
        'tipo_imagen_detectada': data.get('tipo_imagen_detectada'),
        'transcripcion_voz': transcripcion or None,
        'analisis_acustico_ruidos': data.get('analisis_acustico_ruidos'),
        'hallazgos_visuales': data.get('hallazgos_visuales') or [],
        'luces_tablero': data.get('luces_tablero') or [],
        'sintoma_sintetizado': (data.get('sintoma_sintetizado') or '').strip() or None,
        'resumen_para_chat': resumen,
        'confianza': data.get('confianza'),
    }

    # Persiste para no reanalizar y para historial del chat.
    meta['media_analisis'] = resultado
    update_fields = ['channel_metadata']
    message.channel_metadata = meta
    if resumen and es_solo_etiqueta_media(message.content):
        message.content = resumen[:2000]
        update_fields.append('content')
    message.save(update_fields=update_fields)
    return resultado


def texto_cliente_enriquecido(message, analisis: dict[str, Any] | None) -> str:
    """Texto efectivo del turno: caption + análisis multimodal."""
    base = (message.content or '').strip()
    if not analisis or analisis.get('pendiente') or analisis.get('error'):
        return base

    partes: list[str] = []
    if base and not es_solo_etiqueta_media(base):
        partes.append(base)

    resumen = (analisis.get('resumen_para_chat') or '').strip()
    if resumen and resumen not in partes:
        partes.append(f'[Adjunto {analisis.get("tipo_medio") or "media"}] {resumen}')

    transcripcion = (analisis.get('transcripcion_voz') or '').strip()
    if transcripcion and transcripcion not in resumen and transcripcion not in base:
        partes.append(f'Transcripción: {transcripcion}')

    return '\n'.join(partes).strip() or base
