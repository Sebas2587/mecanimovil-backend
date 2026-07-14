"""
OAuth MercadoLibre: access token + refresh automático.

Fuente de verdad: fila única `MercadoLibreOAuthToken` en Postgres (persiste
entre deploys sin depender de env vars). Se completa una sola vez vía
GET /api/valoracion-mercado/ml/oauth/authorize/ (ver oauth_views.py).

Env requeridos solo para el intercambio OAuth (no para el token en sí):
  MERCADOLIBRE_CLIENT_ID
  MERCADOLIBRE_CLIENT_SECRET
  MERCADOLIBRE_REDIRECT_URI  (debe coincidir con el registrado en developers.mercadolibre.cl)
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Any

from django.utils import timezone

logger = logging.getLogger(__name__)

SINGLETON_ID = 1


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
    """Token usable para /sites/MLC/search. Refresca si está vencido/próximo a vencer."""
    from mecanimovilapp.apps.valoracion_mercado.models import MercadoLibreOAuthToken

    row = MercadoLibreOAuthToken.objects.filter(singleton_id=SINGLETON_ID).first()
    if not row or not row.refresh_token:
        # Fallback legado: token estático por env (sin refresh automático).
        return _setting('MERCADOLIBRE_ACCESS_TOKEN')

    needs_refresh = (
        not row.access_token
        or not row.expires_at
        or row.expires_at <= timezone.now() + timedelta(minutes=5)
    )
    if not needs_refresh:
        return row.access_token

    client_id = _setting('MERCADOLIBRE_CLIENT_ID')
    client_secret = _setting('MERCADOLIBRE_CLIENT_SECRET')
    if not client_id or not client_secret:
        logger.warning('ML oauth: faltan MERCADOLIBRE_CLIENT_ID/SECRET para refrescar token')
        return row.access_token or ''

    token, expires_in, new_refresh = _refresh_access_token(
        client_id, client_secret, row.refresh_token
    )
    if not token:
        return row.access_token or ''

    row.access_token = token
    if new_refresh:
        row.refresh_token = new_refresh
    row.expires_at = timezone.now() + timedelta(seconds=expires_in or 21000)
    row.save(update_fields=['access_token', 'refresh_token', 'expires_at', 'updated_at'])
    return token


def save_oauth_tokens(data: dict[str, Any]) -> None:
    from mecanimovilapp.apps.valoracion_mercado.models import MercadoLibreOAuthToken

    expires_in = data.get('expires_in')
    MercadoLibreOAuthToken.objects.update_or_create(
        singleton_id=SINGLETON_ID,
        defaults={
            'access_token': (data.get('access_token') or '').strip(),
            'refresh_token': (data.get('refresh_token') or '').strip(),
            'token_type': (data.get('token_type') or '').strip(),
            'scope': (data.get('scope') or '').strip(),
            'ml_user_id': data.get('user_id'),
            'expires_at': timezone.now() + timedelta(seconds=int(expires_in) if expires_in else 21000),
        },
    )


def exchange_code_for_token(code: str, redirect_uri: str) -> dict[str, Any]:
    import requests

    client_id = _setting('MERCADOLIBRE_CLIENT_ID')
    client_secret = _setting('MERCADOLIBRE_CLIENT_SECRET')
    resp = requests.post(
        'https://api.mercadolibre.com/oauth/token',
        data={
            'grant_type': 'authorization_code',
            'client_id': client_id,
            'client_secret': client_secret,
            'code': code,
            'redirect_uri': redirect_uri,
        },
        headers={'Accept': 'application/json'},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json() or {}


def _refresh_access_token(
    client_id: str, client_secret: str, refresh_token: str
) -> tuple[str, int | None, str]:
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
            return '', None, ''
        data: dict[str, Any] = resp.json() or {}
        token = (data.get('access_token') or '').strip()
        expires = data.get('expires_in')
        new_refresh = (data.get('refresh_token') or '').strip()
        return token, int(expires) if expires else None, new_refresh
    except Exception as exc:
        logger.warning('ML oauth refresh error: %s', exc)
        return '', None, ''


def has_valid_oauth() -> bool:
    """True si hay un refresh_token guardado (independiente de que el access esté vencido)."""
    from mecanimovilapp.apps.valoracion_mercado.models import MercadoLibreOAuthToken

    return MercadoLibreOAuthToken.objects.filter(singleton_id=SINGLETON_ID).exclude(
        refresh_token=''
    ).exists()
