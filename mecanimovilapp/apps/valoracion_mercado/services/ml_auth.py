"""
OAuth MercadoLibre: access token + refresh automático.

Env:
  MERCADOLIBRE_ACCESS_TOKEN   (opcional si hay refresh)
  MERCADOLIBRE_REFRESH_TOKEN
  MERCADOLIBRE_CLIENT_ID
  MERCADOLIBRE_CLIENT_SECRET
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

CACHE_KEY = 'valoracion_ml_access_token_v1'
CACHE_TTL_FALLBACK = 60 * 60 * 5  # 5h


def _setting(name: str, default: str = '') -> str:
    try:
        from django.conf import settings

        val = getattr(settings, name, None)
        if val:
            return str(val).strip()
    except Exception:
        pass
    return (os.environ.get(name) or default).strip()


def get_mercadolibre_access_token() -> str:
    """Token usable para /sites/MLC/search. Refresca si hay refresh_token."""
    from django.core.cache import cache

    cached = cache.get(CACHE_KEY)
    if isinstance(cached, str) and cached:
        return cached

    static = _setting('MERCADOLIBRE_ACCESS_TOKEN')
    refresh = _setting('MERCADOLIBRE_REFRESH_TOKEN')
    client_id = _setting('MERCADOLIBRE_CLIENT_ID')
    client_secret = _setting('MERCADOLIBRE_CLIENT_SECRET')

    if refresh and client_id and client_secret:
        token, expires = _refresh_access_token(client_id, client_secret, refresh)
        if token:
            ttl = max(60, int(expires) - 120) if expires else CACHE_TTL_FALLBACK
            cache.set(CACHE_KEY, token, ttl)
            return token

    if static:
        cache.set(CACHE_KEY, static, CACHE_TTL_FALLBACK)
        return static
    return ''


def _refresh_access_token(
    client_id: str, client_secret: str, refresh_token: str
) -> tuple[str, int | None]:
    import requests

    try:
        resp = requests.post(
            'https://api.mercadolibre.com/oauth/token',
            data={
                'grant_type': 'refresh_token',
                'client_id': client_id,
                'client_secret': client_secret,
                'refresh_token': refresh_token,
            },
            headers={'Accept': 'application/json'},
            timeout=20,
        )
        if resp.status_code >= 400:
            logger.warning(
                'ML oauth refresh falló status=%s body=%s',
                resp.status_code,
                (resp.text or '')[:200],
            )
            return '', None
        data: dict[str, Any] = resp.json() or {}
        token = (data.get('access_token') or '').strip()
        expires = data.get('expires_in')
        new_refresh = (data.get('refresh_token') or '').strip()
        if new_refresh and new_refresh != refresh_token:
            logger.info(
                'ML oauth devolvió refresh_token nuevo; actualiza MERCADOLIBRE_REFRESH_TOKEN en Render'
            )
        return token, int(expires) if expires else None
    except Exception as exc:
        logger.warning('ML oauth refresh error: %s', exc)
        return '', None
