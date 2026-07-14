"""
Bootstrap OAuth de MercadoLibre (una sola vez, hecho por un admin autenticado).

Flujo:
  1. Admin logueado en Django admin visita /api/valoracion-mercado/ml/oauth/authorize/
  2. Se redirige a MercadoLibre, el admin autoriza con su cuenta ML
  3. MercadoLibre redirige a /callback/ con ?code=...
  4. Intercambiamos el code por access_token + refresh_token y los guardamos en DB
     (MercadoLibreOAuthToken, singleton) — persiste entre deploys sin env vars.
"""
from __future__ import annotations

import logging
import urllib.parse

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)

ML_AUTH_URL = 'https://auth.mercadolibre.cl/authorization'


def _redirect_uri(request) -> str:
    from mecanimovilapp.apps.valoracion_mercado.services.ml_auth import _setting

    configured = _setting('MERCADOLIBRE_REDIRECT_URI')
    if configured:
        return configured
    return request.build_absolute_uri('/api/valoracion-mercado/ml/oauth/callback/')


@staff_member_required
@require_GET
def ml_oauth_authorize(request):
    from mecanimovilapp.apps.valoracion_mercado.services.ml_auth import _setting

    client_id = _setting('MERCADOLIBRE_CLIENT_ID')
    if not client_id:
        return HttpResponse(
            'Falta MERCADOLIBRE_CLIENT_ID en las variables de entorno.', status=500
        )
    params = {
        'response_type': 'code',
        'client_id': client_id,
        'redirect_uri': _redirect_uri(request),
    }
    url = f'{ML_AUTH_URL}?{urllib.parse.urlencode(params)}'
    return HttpResponse(
        f'<a href="{url}">Autorizar acceso a MercadoLibre</a> '
        f'(redirect_uri: {params["redirect_uri"]})',
    )


@staff_member_required
@require_GET
def ml_oauth_callback(request):
    from mecanimovilapp.apps.valoracion_mercado.services.ml_auth import (
        exchange_code_for_token,
        save_oauth_tokens,
    )

    code = request.GET.get('code')
    error = request.GET.get('error')
    if error:
        return HttpResponse(f'MercadoLibre devolvió error: {error}', status=400)
    if not code:
        return HttpResponse('Falta parámetro code en el callback.', status=400)

    try:
        data = exchange_code_for_token(code, _redirect_uri(request))
    except Exception as exc:
        logger.exception('ML oauth callback: exchange falló')
        return HttpResponse(f'No se pudo intercambiar el código: {exc}', status=502)

    if not data.get('access_token'):
        return HttpResponse(f'Respuesta sin access_token: {data}', status=502)

    save_oauth_tokens(data)
    logger.info('ML oauth: token guardado (user_id=%s)', data.get('user_id'))
    return HttpResponse(
        '✅ Token de MercadoLibre guardado correctamente. '
        'El scraper ya puede usar la API oficial. Puedes cerrar esta pestaña.'
    )


@staff_member_required
@require_GET
def ml_oauth_status(request):
    from mecanimovilapp.apps.valoracion_mercado.services.ml_auth import has_valid_oauth

    ok = has_valid_oauth()
    return HttpResponse(
        'Autorizado ✅' if ok else 'Sin autorizar ❌ — visita /api/valoracion-mercado/ml/oauth/authorize/'
    )
