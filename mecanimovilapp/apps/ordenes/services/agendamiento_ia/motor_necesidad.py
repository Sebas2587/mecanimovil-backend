"""
Análisis de necesidad del usuario (stateless).

No persiste texto consultado. Combina señales de salud, léxico de síntomas,
similitud textual con catálogo de Servicio y urgencia («temperatura»).

v1 léxico + TF-IDF; fase 5: motor_semantico.py (local gratuito u opcional gemini/hf/ollama).
"""
from __future__ import annotations

import re
from typing import Any

from django.db.models import QuerySet

from mecanimovilapp.apps.servicios.models import Servicio
from mecanimovilapp.apps.vehiculos.models import Vehiculo

from .lexico_necesidad import (
    boost_lexico_servicio,
    detectar_sintomas,
    expandir_texto_busqueda,
    normalizar_texto,
    resumen_interpretacion,
)
from .motor_aprendizaje import boost_servicios_desde_aprendizaje, contar_patrones_activos
from .motor_salud_cruzada import (
    cruzar_salud_con_texto,
    fusionar_componentes_salud,
    interpretar_metricas_salud,
)
from .motor_semantico import (
    analizar_semantico_llm,
    integrar_llm_en_resultado,
    semantico_habilitado,
)

# Palabras que elevan urgencia (temperatura)
_URGENCY_TERMS = {
    'urgente': 0.35,
    'emergencia': 0.4,
    'no frena': 0.45,
    'no arranca': 0.4,
    'humo': 0.35,
    'varado': 0.45,
    'accidente': 0.4,
    'peligro': 0.35,
    'inmediato': 0.3,
    'grave': 0.25,
    'falla': 0.15,
    'ruido': 0.1,
}

_HEALTH_LEVEL_BOOST = {
    'CRITICO': 0.45,
    'CRITICAL': 0.45,
    'URGENTE': 0.4,
    'ATENCION': 0.25,
    'WARNING': 0.25,
    'PREVENTIVO': 0.05,
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def calcular_temperatura(texto: str, componentes_salud: list[dict] | None) -> tuple[float, str]:
    """Score 0-1 y etiqueta de urgencia."""
    texto_l = normalizar_texto(texto)
    score = 0.12

    for term, boost in _URGENCY_TERMS.items():
        if term in texto_l:
            score += boost

    raw = texto or ''
    if '!!!' in raw or (raw.isupper() and len(raw) > 12):
        score += 0.08

    for comp in componentes_salud or []:
        level = (comp.get('nivel_alerta') or comp.get('status') or '').upper()
        score += _HEALTH_LEVEL_BOOST.get(level, 0.0)
        salud = comp.get('salud_porcentaje') or comp.get('salud')
        if salud is not None:
            try:
                if float(salud) < 30:
                    score += 0.2
                elif float(salud) < 50:
                    score += 0.1
            except (TypeError, ValueError):
                pass

    score = _clamp01(score)
    if score >= 0.75:
        label = 'urgente'
    elif score >= 0.45:
        label = 'atencion'
    else:
        label = 'normal'
    return score, label


def _servicios_compatibles_queryset(vehiculo: Vehiculo | None) -> QuerySet[Servicio]:
    qs = Servicio.objects.all()
    if vehiculo and vehiculo.modelo_id:
        por_modelo = qs.filter(modelos_compatibles=vehiculo.modelo).distinct()
        if por_modelo.exists():
            return por_modelo
    return qs[:120]


def _overlap_palabras(texto: str, corpus: str) -> float:
    texto_l = normalizar_texto(texto)
    corpus_l = normalizar_texto(corpus)
    palabras = [p for p in re.split(r'\W+', texto_l) if len(p) > 2]
    if not palabras:
        return 0.0
    hits = sum(1 for p in palabras if p in corpus_l)
    return hits / max(len(palabras), 1)


def _scores_tfidf_batch(texto: str, servicios: list[Servicio]) -> dict[int, float]:
    """Similitud coseno texto vs cada servicio (un solo fit del vectorizador)."""
    if not texto.strip() or not servicios:
        return {}

    documentos = [texto]
    ids: list[int] = []
    for servicio in servicios:
        documentos.append(f'{servicio.nombre} {servicio.descripcion or ""}')
        ids.append(servicio.id)

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        vec = TfidfVectorizer(max_features=800, ngram_range=(1, 2), min_df=1)
        mat = vec.fit_transform(documentos)
        sims = cosine_similarity(mat[0:1], mat[1:])[0]
        out: dict[int, float] = {}
        for idx, sid in enumerate(ids):
            overlap = _overlap_palabras(
                texto,
                f'{servicios[idx].nombre} {servicios[idx].descripcion or ""}',
            )
            sim = float(sims[idx]) if idx < len(sims) else 0.0
            out[sid] = _clamp01(0.35 * overlap + 0.65 * sim)
        return out
    except Exception:
        return {
            s.id: _clamp01(
                _overlap_palabras(texto, f'{s.nombre} {s.descripcion or ""}')
            )
            for s in servicios
        }


def _servicios_desde_salud(
    componentes_salud: list[dict] | None,
    vehiculo: Vehiculo | None,
) -> dict[int, tuple[float, str]]:
    """servicio_id -> (score, razon)."""
    out: dict[int, tuple[float, str]] = {}
    if not componentes_salud:
        return out

    disponibles = set()
    if vehiculo and vehiculo.modelo_id:
        disponibles = set(
            _servicios_compatibles_queryset(vehiculo).values_list('id', flat=True)
        )

    for comp in componentes_salud:
        nombre = comp.get('nombre') or comp.get('slug') or 'componente'
        salud = comp.get('salud_porcentaje') or comp.get('salud') or 100
        try:
            salud_f = float(salud)
        except (TypeError, ValueError):
            salud_f = 100.0
        boost = _clamp01(1.0 - salud_f / 100.0)

        for svc in comp.get('servicios_asociados') or []:
            sid = svc.get('id') if isinstance(svc, dict) else svc
            if sid is None:
                continue
            sid = int(sid)
            if disponibles and sid not in disponibles:
                continue
            prev = out.get(sid, (0.0, ''))[0]
            score = _clamp01(max(prev, 0.5 + 0.5 * boost))
            out[sid] = (score, f'Salud de {nombre} sugiere este servicio')

    return out


def analizar_necesidad(
    *,
    texto: str = '',
    vehiculo_id: int | None = None,
    componentes_salud: list[dict] | None = None,
    origen: str = 'texto',
    max_servicios: int = 8,
) -> dict[str, Any]:
    """
    Análisis stateless. No escribe en BD.
    """
    vehiculo = None
    if vehiculo_id:
        vehiculo = (
            Vehiculo.objects.select_related('marca', 'modelo')
            .filter(pk=vehiculo_id)
            .first()
        )

    componentes_salud = fusionar_componentes_salud(componentes_salud, vehiculo_id)
    salud_info = interpretar_metricas_salud(componentes_salud)
    cruce = cruzar_salud_con_texto(texto, componentes_salud, salud_info)

    reglas = detectar_sintomas(texto)
    texto_expandido = expandir_texto_busqueda(texto, reglas)
    interpretacion = resumen_interpretacion(reglas)
    if cruce.get('interpretacion_cruzada'):
        interpretacion = cruce['interpretacion_cruzada']
    elif not interpretacion and salud_info.get('resumen_salud'):
        interpretacion = salud_info['resumen_salud']
    sintomas_ids = [r.id for r in reglas]

    temperatura, urgencia_label = calcular_temperatura(texto, componentes_salud)

    scores: dict[int, dict[str, Any]] = {}

    for sid, (sc, razon) in _servicios_desde_salud(componentes_salud, vehiculo).items():
        scores[sid] = {
            'score': sc,
            'razon': razon,
            'fuente': 'salud',
        }

    servicios_list = list(_servicios_compatibles_queryset(vehiculo))
    tfidf_scores = _scores_tfidf_batch(texto_expandido or texto, servicios_list)
    modelo_id = vehiculo.modelo_id if vehiculo else None
    boosts_aprendizaje = boost_servicios_desde_aprendizaje(
        texto,
        servicios_list,
        modelo_id=modelo_id,
        componentes_salud=componentes_salud,
    )

    for servicio in servicios_list:
        sc_text = tfidf_scores.get(servicio.id, 0.0)
        sc_lex, razon_lex = boost_lexico_servicio(
            servicio.nombre,
            servicio.descripcion or '',
            reglas,
        )
        sc_apr, razon_apr = boosts_aprendizaje.get(servicio.id, (0.0, ''))
        sc_final = _clamp01(max(sc_text, sc_lex, sc_apr))
        if sc_final <= 0.05 and sc_lex <= 0 and sc_apr <= 0:
            continue

        razon = razon_apr or razon_lex or (
            'Relacionado con lo que describes'
            if sc_text >= 0.2
            else 'Coincide con palabras de tu descripción'
        )
        if sc_apr >= sc_lex and sc_apr >= sc_text and sc_apr > 0:
            fuente = 'aprendizaje'
        elif sc_lex >= sc_text:
            fuente = 'lexico'
        else:
            fuente = 'texto'
        if sc_lex > 0 and sc_text > 0.15:
            fuente = 'lexico+texto' if fuente == 'texto' else fuente

        prev = scores.get(servicio.id)
        if prev:
            combined = _clamp01(max(prev['score'], sc_final * 0.85 + prev['score'] * 0.15))
            scores[servicio.id] = {
                'score': combined,
                'razon': razon_lex or prev['razon'],
                'fuente': prev['fuente'] if not razon_lex else f"{prev['fuente']}+{fuente}",
            }
        else:
            scores[servicio.id] = {
                'score': sc_final,
                'razon': razon,
                'fuente': fuente,
            }

    if not scores and vehiculo:
        for servicio in servicios_list[:max_servicios]:
            scores[servicio.id] = {
                'score': 0.35,
                'razon': 'Servicio compatible con tu vehículo',
                'fuente': 'vehiculo',
            }

    ranked = sorted(scores.items(), key=lambda x: x[1]['score'], reverse=True)[:max_servicios]

    servicios_ids = [sid for sid, _ in ranked]
    servicios_map = {
        s.id: s
        for s in Servicio.objects.filter(id__in=servicios_ids)
    }

    servicios_recomendados = []
    for sid, meta in ranked:
        s = servicios_map.get(sid)
        if not s:
            continue
        servicios_recomendados.append({
            'servicio_id': sid,
            'nombre': s.nombre,
            'descripcion': (s.descripcion or '')[:300],
            'score': round(meta['score'], 3),
            'razon': meta['razon'],
            'fuente': meta['fuente'],
        })

    preguntas: list[str] = list(cruce.get('alertas_cruce') or [])
    if not reglas and texto.strip() and len(preguntas) < 3:
        preguntas.append(
            '¿Puedes indicar qué parte del auto falla (frenos, motor, batería, etc.) o cuándo ocurre el problema?'
        )
    elif servicios_recomendados and servicios_recomendados[0]['score'] < 0.55 and len(preguntas) < 3:
        preguntas.append('¿Puedes describir con más detalle el síntoma o cuándo ocurre?')

    resultado = {
        'temperatura': round(temperatura, 3),
        'urgencia_label': urgencia_label,
        'origen': origen,
        'interpretacion': interpretacion,
        'resumen_salud': salud_info.get('resumen_salud'),
        'alertas_cruce': cruce.get('alertas_cruce') or [],
        'coherencia_salud_texto': cruce.get('coherencia_salud_texto'),
        'sintomas_detectados': sintomas_ids,
        'servicios_recomendados': servicios_recomendados,
        'preguntas_seguimiento': preguntas[:3],
        'patrones_aprendizaje_en_sistema': contar_patrones_activos(),
        'motor_analisis': 'lexico',
    }

    if semantico_habilitado() and texto.strip():
        llm_out = analizar_semantico_llm(
            texto=texto,
            vehiculo=vehiculo,
            servicios=servicios_list,
            componentes_salud=componentes_salud,
            max_servicios=max_servicios,
        )
        resultado = integrar_llm_en_resultado(
            resultado,
            llm_out,
            servicios_list,
            max_servicios=max_servicios,
        )

    return resultado
