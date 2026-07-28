"""Embeddings vía Gemini embedContent."""
from __future__ import annotations

import logging
from typing import Sequence

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Dimensión canónica del VectorField en TallerConocimientoChunk.
EMBEDDING_DIMENSIONS = 768

# text-embedding-004 fue apagado por Google (ene 2026). gemini-embedding-001
# es el reemplazo GA y soporta outputDimensionality=768 (Matryoshka).
_DEFAULT_EMBEDDING_MODEL = 'gemini-embedding-001'
_DEPRECATED_EMBEDDING_MODELS = frozenset({
    'text-embedding-004',
    'embedding-001',
    'embedding-gecko-001',
})


def embedding_model() -> str:
    configured = (
        getattr(settings, 'AGENTE_IA_EMBEDDING_MODEL', '')
        or _DEFAULT_EMBEDDING_MODEL
    ).strip()
    if configured in _DEPRECATED_EMBEDDING_MODELS:
        logger.warning(
            'Modelo de embedding %s está deprecado/apagado; usando %s',
            configured,
            _DEFAULT_EMBEDDING_MODEL,
        )
        return _DEFAULT_EMBEDDING_MODEL
    return configured or _DEFAULT_EMBEDDING_MODEL


def generar_embedding(texto: str) -> list[float] | None:
    """Genera un vector de embedding para un texto (768 dims)."""
    api_key = (getattr(settings, 'GEMINI_API_KEY', '') or '').strip()
    if not api_key or not (texto or '').strip():
        return None

    model = embedding_model()
    url = (
        f'https://generativelanguage.googleapis.com/v1beta/models/{model}:'
        f'embedContent?key={api_key}'
    )
    payload = {
        'model': f'models/{model}',
        'content': {'parts': [{'text': texto[:8000]}]},
        # gemini-embedding-001 default=3072; pedimos 768 para el VectorField.
        'outputDimensionality': EMBEDDING_DIMENSIONS,
    }
    timeout = int(getattr(settings, 'AGENTE_IA_EMBEDDING_TIMEOUT', 15) or 15)

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning('Error de conexión generando embedding: %s', exc)
        return None

    if resp.status_code != 200:
        logger.warning('Gemini embedding HTTP %s: %s', resp.status_code, resp.text[:300])
        return None

    try:
        body = resp.json()
        values = body['embedding']['values']
    except (KeyError, TypeError, ValueError):
        logger.warning('Respuesta embedding inesperada: %s', resp.text[:300])
        return None

    if not isinstance(values, list) or not values:
        logger.warning('Embedding vacío o inválido: %s', type(values))
        return None

    # Truncar/aceptar si el modelo ignora outputDimensionality en algún caso.
    if len(values) != EMBEDDING_DIMENSIONS:
        if len(values) > EMBEDDING_DIMENSIONS:
            values = values[:EMBEDDING_DIMENSIONS]
        else:
            logger.warning(
                'Dimensión embedding inesperada: %s (esperado %s)',
                len(values),
                EMBEDDING_DIMENSIONS,
            )
            return None

    return [float(v) for v in values]


def generar_embeddings_batch(textos: Sequence[str]) -> list[list[float] | None]:
    """Genera embeddings secuencialmente (Gemini embedContent es por texto)."""
    return [generar_embedding(t) for t in textos]
