"""Embeddings vía Gemini embedContent."""
from __future__ import annotations

import logging
from typing import Sequence

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSIONS = 768


def embedding_model() -> str:
    return (
        getattr(settings, 'AGENTE_IA_EMBEDDING_MODEL', '')
        or 'text-embedding-004'
    ).strip()


def generar_embedding(texto: str) -> list[float] | None:
    """Genera un vector de embedding para un texto."""
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

    if not isinstance(values, list) or len(values) != EMBEDDING_DIMENSIONS:
        logger.warning('Dimensión embedding inesperada: %s', len(values) if isinstance(values, list) else type(values))
        return None

    return [float(v) for v in values]


def generar_embeddings_batch(textos: Sequence[str]) -> list[list[float] | None]:
    """Genera embeddings secuencialmente (Gemini embedContent es por texto)."""
    return [generar_embedding(t) for t in textos]
