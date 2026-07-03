"""
Capa semántica (fase 5) sin APIs de pago.

Proveedores (AGENDAMIENTO_IA_SEMANTICO_PROVEEDOR):
- lexico (default): léxico + similitud fuzzy local — sin API, sin costo.
- gemini: Google AI Studio (tier gratuito) — GEMINI_API_KEY.
- huggingface: Inference API (tier gratuito) — HUGGINGFACE_API_TOKEN.
- ollama: servidor propio gratuito — OLLAMA_BASE_URL.
- auto: el primero configurado entre gemini → huggingface → ollama → lexico.

No persiste ni registra el texto del usuario.
"""
from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher
from typing import Any, Callable

import requests
from django.conf import settings

from mecanimovilapp.apps.servicios.models import Servicio
from mecanimovilapp.apps.vehiculos.models import Vehiculo

from .lexico_necesidad import (
    boost_lexico_servicio,
    detectar_sintomas,
    expandir_texto_busqueda,
    normalizar_texto,
    resumen_interpretacion,
)

logger = logging.getLogger(__name__)

_JSON_FENCE = re.compile(r'```(?:json)?\s*([\s\S]*?)\s*```', re.IGNORECASE)
_PROMPT_JSON = (
    'Responde SOLO JSON válido con: interpretacion, urgencia_label (normal|atencion|urgente), '
    'servicio_ids (enteros del catálogo), razones [{servicio_id, razon}], '
    'preguntas_seguimiento (array), sintomas_detectados (array). '
    'No inventes IDs fuera del catálogo.'
)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def semantico_habilitado() -> bool:
    """Fase 5 activa (por defecto sí si el asistente IA está encendido)."""
    if not bool(getattr(settings, 'AGENDAMIENTO_IA_ASISTIDO', False)):
        return False
    return bool(getattr(settings, 'AGENDAMIENTO_IA_SEMANTICO_ENABLED', True))


def _proveedor_configurado() -> str:
    raw = (
        getattr(settings, 'AGENDAMIENTO_IA_SEMANTICO_PROVEEDOR', 'lexico') or 'lexico'
    ).strip().lower()
    if raw != 'auto':
        return raw
    if (getattr(settings, 'GEMINI_API_KEY', '') or '').strip():
        return 'gemini'
    if (getattr(settings, 'HUGGINGFACE_API_TOKEN', '') or '').strip():
        return 'huggingface'
    if (getattr(settings, 'OLLAMA_BASE_URL', '') or '').strip():
        return 'ollama'
    return 'lexico'


# Compatibilidad con código que importaba llm_habilitado
def llm_habilitado() -> bool:
    return _proveedor_configurado() != 'lexico' and semantico_habilitado()


def _vehiculo_contexto(vehiculo: Vehiculo | None) -> str:
    if not vehiculo:
        return 'Vehículo no especificado.'
    marca = getattr(vehiculo.marca, 'nombre', '') or ''
    modelo = getattr(vehiculo.modelo, 'nombre', '') or ''
    year = vehiculo.year or ''
    return f'{marca} {modelo} {year}'.strip()


def _resumen_salud(componentes_salud: list[dict] | None) -> str:
    if not componentes_salud:
        return 'Sin datos de salud del vehículo.'
    lineas: list[str] = []
    for comp in componentes_salud[:10]:
        nombre = comp.get('nombre') or comp.get('slug') or 'componente'
        nivel = comp.get('nivel_alerta') or comp.get('status') or '—'
        salud = comp.get('salud_porcentaje') or comp.get('salud')
        if salud is not None:
            lineas.append(f'- {nombre}: alerta {nivel}, salud {salud}%')
        else:
            lineas.append(f'- {nombre}: alerta {nivel}')
    return '\n'.join(lineas)


def catalogo_para_prompt(servicios: list[Servicio], max_items: int = 45) -> list[dict[str, Any]]:
    return [
        {
            'id': s.id,
            'nombre': (s.nombre or '')[:140],
            'descripcion': ((s.descripcion or '')[:240]),
        }
        for s in servicios[:max_items]
    ]


def parsear_respuesta_semantica(content: str) -> dict[str, Any] | None:
    if not content or not str(content).strip():
        return None
    raw = str(content).strip()
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


def normalizar_salida_semantica(
    data: dict[str, Any],
    ids_validos: set[int],
    max_servicios: int = 8,
) -> dict[str, Any] | None:
    servicio_ids: list[int] = []
    for raw in data.get('servicio_ids') or []:
        try:
            sid = int(raw)
        except (TypeError, ValueError):
            continue
        if sid in ids_validos and sid not in servicio_ids:
            servicio_ids.append(sid)
        if len(servicio_ids) >= max_servicios:
            break

    razones: dict[int, str] = {}
    for item in data.get('razones') or []:
        if not isinstance(item, dict):
            continue
        try:
            sid = int(item.get('servicio_id'))
        except (TypeError, ValueError):
            continue
        if sid not in ids_validos:
            continue
        razon = (item.get('razon') or '').strip()
        if razon:
            razones[sid] = razon[:400]

    interpretacion = (data.get('interpretacion') or '').strip()[:600]
    urgencia = (data.get('urgencia_label') or '').strip().lower()
    if urgencia not in ('normal', 'atencion', 'urgente'):
        urgencia = ''

    preguntas: list[str] = []
    for p in data.get('preguntas_seguimiento') or []:
        if isinstance(p, str) and p.strip():
            preguntas.append(p.strip()[:300])
        if len(preguntas) >= 3:
            break

    sintomas: list[str] = []
    for s in data.get('sintomas_detectados') or []:
        if isinstance(s, str) and s.strip():
            sintomas.append(s.strip()[:64])
        if len(sintomas) >= 8:
            break

    if not servicio_ids and not interpretacion:
        return None

    return {
        'servicio_ids': servicio_ids,
        'razones_por_servicio': razones,
        'interpretacion': interpretacion or None,
        'urgencia_label': urgencia or None,
        'preguntas_seguimiento': preguntas,
        'sintomas_detectados': sintomas,
        'proveedor': data.get('_proveedor'),
    }


def _prompt_usuario(
    texto: str,
    vehiculo: Vehiculo | None,
    componentes_salud: list[dict] | None,
    catalogo: list[dict[str, Any]],
) -> str:
    catalogo_json = json.dumps(catalogo, ensure_ascii=False)
    return (
        f'{_PROMPT_JSON}\n\n'
        f'Vehículo: {_vehiculo_contexto(vehiculo)}\n'
        f'Salud:\n{_resumen_salud(componentes_salud)}\n'
        f'Catálogo:\n{catalogo_json}\n'
        f'Necesidad:\n{texto.strip()[:2000]}'
    )


def _score_fuzzy_servicio(texto: str, servicio: Servicio) -> float:
    corpus = f'{servicio.nombre} {servicio.descripcion or ""}'
    norm_t = normalizar_texto(texto)
    norm_c = normalizar_texto(corpus)
    if not norm_t or not norm_c:
        return 0.0
    ratio_completo = SequenceMatcher(None, norm_t, norm_c).ratio()
    palabras = [p for p in re.split(r'\W+', norm_t) if len(p) > 2]
    if not palabras:
        return _clamp01(ratio_completo)
    corpus_tokens = [tok for tok in re.split(r'\W+', norm_c) if len(tok) > 2]
    token_scores = []
    for p in palabras:
        if not corpus_tokens:
            token_scores.append(0.0)
        else:
            token_scores.append(
                max(SequenceMatcher(None, p, tok).ratio() for tok in corpus_tokens)
            )
    token_avg = sum(token_scores) / len(token_scores)
    return _clamp01(0.4 * ratio_completo + 0.6 * token_avg)


def analizar_semantico_lexico_local(
    *,
    texto: str,
    servicios: list[Servicio],
    max_servicios: int = 8,
) -> dict[str, Any] | None:
    """
    Motor gratuito local: léxico de síntomas + fuzzy matching al catálogo.
    """
    texto = (texto or '').strip()
    if len(texto) < 4 or not servicios:
        return None

    reglas = detectar_sintomas(texto)
    texto_exp = expandir_texto_busqueda(texto, reglas)
    candidatos: list[tuple[int, float, str]] = []

    for servicio in servicios:
        sc_lex, razon_lex = boost_lexico_servicio(
            servicio.nombre,
            servicio.descripcion or '',
            reglas,
        )
        sc_fuzzy = _score_fuzzy_servicio(texto_exp, servicio)
        sc = _clamp01(max(sc_lex, sc_fuzzy * 0.92))
        if sc < 0.2:
            continue
        if razon_lex:
            razon = razon_lex
        elif sc_fuzzy >= 0.35:
            razon = f'Coincide con «{servicio.nombre}» según tu descripción'
        else:
            razon = 'Relacionado con lo que describes'
        candidatos.append((servicio.id, sc, razon))

    candidatos.sort(key=lambda x: x[1], reverse=True)
    top = candidatos[:max_servicios]
    if not top and not reglas:
        return None

    razones = {sid: razon for sid, _, razon in top}
    interpretacion = resumen_interpretacion(reglas)
    if not interpretacion and top:
        interpretacion = (
            f'Según tu descripción, lo más probable es que necesites '
            f'revisar: {top[0][2].split("«")[-1].rstrip("»") if "«" in top[0][2] else "servicios relacionados"}.'
        )

    return {
        'servicio_ids': [sid for sid, _, _ in top],
        'razones_por_servicio': razones,
        'interpretacion': interpretacion,
        'urgencia_label': None,
        'preguntas_seguimiento': [],
        'sintomas_detectados': [r.id for r in reglas],
        'proveedor': 'lexico',
    }


def _http_json_post(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: int,
    extract_text: Callable[[dict], str | None],
) -> dict[str, Any] | None:
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException:
        logger.warning('Semántico: error de red (sin texto usuario)')
        return None
    if resp.status_code != 200:
        logger.warning('Semántico: HTTP %s (sin texto usuario)', resp.status_code)
        return None
    try:
        body = resp.json()
        text = extract_text(body)
    except (TypeError, ValueError):
        return None
    if not text:
        return None
    parsed = parsear_respuesta_semantica(text)
    if parsed:
        parsed['_proveedor'] = headers.get('X-Proveedor-Semantico')
    return parsed


def _llamar_gemini(prompt: str) -> dict[str, Any] | None:
    api_key = (getattr(settings, 'GEMINI_API_KEY', '') or '').strip()
    if not api_key:
        return None
    model = getattr(settings, 'GEMINI_MODEL', 'gemini-3.1-flash-lite') or 'gemini-3.1-flash-lite'
    timeout = int(getattr(settings, 'AGENDAMIENTO_IA_SEMANTICO_TIMEOUT', 15) or 15)
    url = (
        f'https://generativelanguage.googleapis.com/v1beta/models/{model}:'
        f'generateContent?key={api_key}'
    )
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': 0.2,
            'maxOutputTokens': 900,
            'responseMimeType': 'application/json',
        },
    }

    def extract(body: dict) -> str | None:
        try:
            return body['candidates'][0]['content']['parts'][0]['text']
        except (KeyError, IndexError, TypeError):
            return None

    result = _http_json_post(
        url,
        headers={'Content-Type': 'application/json', 'X-Proveedor-Semantico': 'gemini'},
        payload=payload,
        timeout=timeout,
        extract_text=extract,
    )
    if result:
        result['proveedor'] = 'gemini'
    return result


def _llamar_huggingface(prompt: str) -> dict[str, Any] | None:
    token = (getattr(settings, 'HUGGINGFACE_API_TOKEN', '') or '').strip()
    if not token:
        return None
    model = (
        getattr(settings, 'HUGGINGFACE_MODEL', 'Qwen/Qwen2.5-1.5B-Instruct')
        or 'Qwen/Qwen2.5-1.5B-Instruct'
    )
    timeout = int(getattr(settings, 'AGENDAMIENTO_IA_SEMANTICO_TIMEOUT', 20) or 20)
    url = f'https://api-inference.huggingface.co/models/{model}'

    payload = {
        'inputs': prompt,
        'parameters': {'max_new_tokens': 700, 'temperature': 0.2, 'return_full_text': False},
    }

    def extract(body: dict | list) -> str | None:
        if isinstance(body, list) and body:
            item = body[0]
            if isinstance(item, dict):
                return item.get('generated_text') or item.get('text')
        if isinstance(body, dict):
            return body.get('generated_text')
        return None

    result = _http_json_post(
        url,
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'X-Proveedor-Semantico': 'huggingface',
        },
        payload=payload,
        timeout=timeout,
        extract_text=extract,
    )
    if result:
        result['proveedor'] = 'huggingface'
    return result


def _llamar_ollama(prompt: str) -> dict[str, Any] | None:
    base = (getattr(settings, 'OLLAMA_BASE_URL', '') or 'http://localhost:11434').rstrip('/')
    model = getattr(settings, 'OLLAMA_MODEL', 'llama3.2') or 'llama3.2'
    timeout = int(getattr(settings, 'AGENDAMIENTO_IA_SEMANTICO_TIMEOUT', 25) or 25)
    url = f'{base}/api/chat'
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': 'Asistente automotriz Chile. ' + _PROMPT_JSON},
            {'role': 'user', 'content': prompt},
        ],
        'stream': False,
        'format': 'json',
    }

    def extract(body: dict) -> str | None:
        try:
            return body['message']['content']
        except (KeyError, TypeError):
            return None

    result = _http_json_post(
        url,
        headers={'Content-Type': 'application/json', 'X-Proveedor-Semantico': 'ollama'},
        payload=payload,
        timeout=timeout,
        extract_text=extract,
    )
    if result:
        result['proveedor'] = 'ollama'
    return result


def _llamar_proveedor_externo(
    proveedor: str,
    prompt: str,
) -> dict[str, Any] | None:
    if proveedor == 'gemini':
        return _llamar_gemini(prompt)
    if proveedor == 'huggingface':
        return _llamar_huggingface(prompt)
    if proveedor == 'ollama':
        return _llamar_ollama(prompt)
    return None


def analizar_semantico_llm(
    *,
    texto: str,
    vehiculo: Vehiculo | None,
    servicios: list[Servicio],
    componentes_salud: list[dict] | None = None,
    max_servicios: int = 8,
) -> dict[str, Any] | None:
    """
    Análisis semántico (nombre legacy). Usa proveedor configurado; fallback a léxico local.
    """
    if not semantico_habilitado():
        return None
    texto = (texto or '').strip()
    if len(texto) < 4 or not servicios:
        return None

    proveedor = _proveedor_configurado()
    catalogo = catalogo_para_prompt(servicios)
    ids_validos = {item['id'] for item in catalogo}

    if proveedor == 'lexico':
        return analizar_semantico_lexico_local(
            texto=texto,
            servicios=servicios,
            max_servicios=max_servicios,
        )

    prompt = _prompt_usuario(texto, vehiculo, componentes_salud, catalogo)
    crudo = _llamar_proveedor_externo(proveedor, prompt)
    if crudo:
        normalizado = normalizar_salida_semantica(crudo, ids_validos, max_servicios=max_servicios)
        if normalizado:
            normalizado['proveedor'] = proveedor
            return normalizado

    logger.info('Semántico: fallback a léxico local (proveedor=%s)', proveedor)
    local = analizar_semantico_lexico_local(
        texto=texto,
        servicios=servicios,
        max_servicios=max_servicios,
    )
    if local:
        local['proveedor'] = 'lexico_fallback'
    return local


def integrar_llm_en_resultado(
    resultado: dict[str, Any],
    llm: dict[str, Any] | None,
    servicios: list[Servicio],
    max_servicios: int = 8,
) -> dict[str, Any]:
    """Fusiona ranking base con capa semántica."""
    if not llm:
        resultado['motor_analisis'] = 'lexico'
        return resultado

    proveedor = llm.get('proveedor') or 'semantico'
    by_id = {s.id: s for s in servicios}
    sem_ids = [sid for sid in llm.get('servicio_ids') or [] if sid in by_id]
    razones = llm.get('razones_por_servicio') or {}

    if llm.get('interpretacion'):
        resultado['interpretacion'] = llm['interpretacion']

    if llm.get('urgencia_label'):
        resultado['urgencia_label'] = llm['urgencia_label']
        if llm['urgencia_label'] == 'urgente':
            resultado['temperatura'] = max(float(resultado.get('temperatura') or 0), 0.75)
        elif llm['urgencia_label'] == 'atencion':
            resultado['temperatura'] = max(float(resultado.get('temperatura') or 0), 0.5)

    if llm.get('sintomas_detectados'):
        resultado['sintomas_detectados'] = llm['sintomas_detectados']

    preguntas = list(llm.get('preguntas_seguimiento') or [])
    if preguntas:
        resultado['preguntas_seguimiento'] = preguntas

    fuente_sem = 'semantico' if proveedor == 'lexico' else proveedor
    existentes = {r['servicio_id']: r for r in resultado.get('servicios_recomendados') or []}
    fusionados: list[dict[str, Any]] = []
    uso_base = False

    for rank, sid in enumerate(sem_ids):
        s = by_id[sid]
        prev = existentes.get(sid, {})
        if prev and prev.get('fuente') not in (fuente_sem, 'llm'):
            uso_base = True
        fusionados.append({
            'servicio_id': sid,
            'nombre': s.nombre,
            'descripcion': (s.descripcion or '')[:300],
            'score': round(max(0.55, 0.96 - rank * 0.05), 3),
            'razon': razones.get(sid) or prev.get('razon') or 'Recomendado según tu descripción',
            'fuente': fuente_sem,
        })

    vistos = {r['servicio_id'] for r in fusionados}
    for rec in sorted(
        resultado.get('servicios_recomendados') or [],
        key=lambda x: x.get('score', 0),
        reverse=True,
    ):
        sid = rec['servicio_id']
        if sid in vistos:
            continue
        fusionados.append({**rec})
        uso_base = True
        vistos.add(sid)
        if len(fusionados) >= max_servicios:
            break

    fusionados.sort(key=lambda x: x.get('score', 0), reverse=True)
    resultado['servicios_recomendados'] = fusionados[:max_servicios]
    if sem_ids:
        resultado['motor_analisis'] = (
            f'{proveedor}+lexico' if uso_base and proveedor != 'lexico' else proveedor
        )
    else:
        resultado['motor_analisis'] = 'lexico'
    return resultado


# Alias público
integrar_semantico_en_resultado = integrar_llm_en_resultado
analizar_semantico = analizar_semantico_llm
