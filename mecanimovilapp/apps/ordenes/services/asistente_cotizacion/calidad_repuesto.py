"""Eje de calidad de la pieza: original / OEM / alternativo.

Ortogonal a `especificacion` (iridio, cerámica, 5W-30). La calidad mueve el
precio por origen de la pieza, no por la variante técnica.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

CALIDAD_ORIGINAL = 'original'
CALIDAD_OEM = 'oem'
CALIDAD_ALTERNATIVO = 'alternativo'
CALIDADES = (CALIDAD_ORIGINAL, CALIDAD_OEM, CALIDAD_ALTERNATIVO)

CALIDAD_META: dict[str, dict[str, Any]] = {
    CALIDAD_ORIGINAL: {
        'label': 'Original',
        'keywords': (
            'original',
            'genuine',
            'concesionario',
            'agencia',
            'de la marca',
            'oem original',
        ),
    },
    CALIDAD_OEM: {
        'label': 'Equivalente OEM',
        'keywords': (
            'equivalente oem',
            'equiv oem',
            'oem equivalente',
            'mismo fabricante',
            'calidad oem',
            'oem',
            'equivalente',
        ),
    },
    CALIDAD_ALTERNATIVO: {
        'label': 'Alternativo',
        'keywords': (
            'alternativo',
            'alternativa',
            'aftermarket',
            'generico',
            'generica',
            'economico',
            'economica',
        ),
    },
}

CALIDAD_LABEL = {k: v['label'] for k, v in CALIDAD_META.items()}


def _norm(texto: str) -> str:
    t = unicodedata.normalize('NFD', (texto or '').strip().lower())
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    t = re.sub(r'[^a-z0-9]+', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def _menciones(texto: str) -> list[str]:
    n = _norm(texto)
    if not n:
        return []
    encontradas: list[str] = []
    for clave, meta in CALIDAD_META.items():
        if any(re.search(rf'\b{re.escape(k)}\b', n) for k in meta['keywords']):
            encontradas.append(clave)
    return encontradas


def detectar_calidad(texto: str) -> str | None:
    """Devuelve UNA calidad si el texto la decide. Ambigua o vacía → None."""
    encontradas = _menciones(texto)
    if len(encontradas) == 1:
        return encontradas[0]
    return None


def calidad_valida(texto: str) -> bool:
    return detectar_calidad(texto) in CALIDADES


def calidad_pendiente_en_texto(texto: str) -> bool:
    """True si el texto nombra dos calidades (ej. 'original o equivalente OEM')."""
    return len(_menciones(texto)) >= 2


def label_calidad(calidad: str | None) -> str:
    return CALIDAD_LABEL.get(str(calidad or '').strip().lower(), '')


def anotar_calidad_en_linea(
    rep: dict[str, Any],
    *,
    descartar_invalida: bool = True,
) -> dict[str, Any]:
    """Rellena `calidad` / `calidad_pendiente` sobre una copia."""
    next_rep = dict(rep)
    actual = str(next_rep.get('calidad') or '').strip().lower()
    if actual in CALIDADES:
        next_rep['calidad'] = actual
        next_rep['calidad_pendiente'] = False
        return next_rep

    blob = ' '.join(
        str(next_rep.get(k) or '')
        for k in ('calidad', 'especificacion', 'marca_repuesto', 'nombre', 'comentario')
    )
    if calidad_pendiente_en_texto(blob) and actual not in CALIDADES:
        next_rep['calidad_pendiente'] = True
        if descartar_invalida:
            next_rep.pop('calidad', None)
        return next_rep

    detectada = detectar_calidad(blob)
    if detectada:
        next_rep['calidad'] = detectada
        next_rep['calidad_pendiente'] = False
        return next_rep

    if actual and actual not in CALIDADES:
        next_rep['calidad_pendiente'] = True
        if descartar_invalida:
            next_rep.pop('calidad', None)
        return next_rep

    if next_rep.get('calidad_pendiente') is True:
        return next_rep
    next_rep.pop('calidad_pendiente', None)
    return next_rep
