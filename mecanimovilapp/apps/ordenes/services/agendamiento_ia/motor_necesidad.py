"""
Análisis de necesidad del usuario (stateless).

No persiste texto consultado. Combina señales de salud, similitud textual con catálogo
de Servicio y léxico de urgencia («temperatura»).
"""
from __future__ import annotations

import math
import re
from typing import Any

from django.db.models import Q

from mecanimovilapp.apps.servicios.models import Servicio
from mecanimovilapp.apps.vehiculos.models import Vehiculo

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
    texto_l = (texto or '').lower().strip()
    score = 0.12

    for term, boost in _URGENCY_TERMS.items():
        if term in texto_l:
            score += boost

    if '!!!' in texto or texto.isupper() and len(texto) > 12:
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


def _servicios_compatibles_queryset(vehiculo: Vehiculo | None):
    qs = Servicio.objects.all()
    if vehiculo and vehiculo.modelo_id:
        por_modelo = qs.filter(modelos_compatibles=vehiculo.modelo).distinct()
        if por_modelo.exists():
            return por_modelo
    return qs[:80]


def _score_texto_servicio(texto: str, servicio: Servicio) -> float:
    texto_l = (texto or '').lower()
    if not texto_l.strip():
        return 0.0

    corpus = f"{servicio.nombre} {servicio.descripcion or ''}".lower()
    palabras = [p for p in re.split(r'\W+', texto_l) if len(p) > 2]
    if not palabras:
        return 0.0

    hits = sum(1 for p in palabras if p in corpus)
    base = hits / max(len(palabras), 1)

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        vec = TfidfVectorizer(max_features=500, ngram_range=(1, 2))
        mat = vec.fit_transform([texto_l, corpus])
        sim = float(cosine_similarity(mat[0:1], mat[1:2])[0][0])
        return _clamp01(0.45 * base + 0.55 * sim)
    except Exception:
        return _clamp01(base)


def _servicios_desde_salud(componentes_salud: list[dict] | None, vehiculo: Vehiculo | None) -> dict[int, tuple[float, str]]:
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

    temperatura, urgencia_label = calcular_temperatura(texto, componentes_salud)

    scores: dict[int, dict[str, Any]] = {}

    for sid, (sc, razon) in _servicios_desde_salud(componentes_salud, vehiculo).items():
        scores[sid] = {
            'score': sc,
            'razon': razon,
            'fuente': 'salud',
        }

    for servicio in _servicios_compatibles_queryset(vehiculo):
        sc_text = _score_texto_servicio(texto, servicio)
        if sc_text <= 0.05:
            continue
        prev = scores.get(servicio.id)
        if prev:
            combined = _clamp01(prev['score'] * 0.5 + sc_text * 0.5)
            scores[servicio.id] = {
                'score': combined,
                'razon': prev['razon'] + '; coincide con tu descripción',
                'fuente': 'salud+texto' if prev['fuente'] == 'salud' else 'texto',
            }
        else:
            scores[servicio.id] = {
                'score': sc_text,
                'razon': 'Coincide con lo que describes',
                'fuente': 'texto',
            }

    if not scores and vehiculo:
        for servicio in _servicios_compatibles_queryset(vehiculo)[:max_servicios]:
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

    preguntas = []
    if servicios_recomendados and servicios_recomendados[0]['score'] < 0.55:
        preguntas.append('¿Puedes describir con más detalle el síntoma o cuándo ocurre?')

    return {
        'temperatura': round(temperatura, 3),
        'urgencia_label': urgencia_label,
        'origen': origen,
        'servicios_recomendados': servicios_recomendados,
        'preguntas_seguimiento': preguntas,
    }
