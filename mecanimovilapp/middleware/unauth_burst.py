"""Limita ráfagas de GET sin token a endpoints del dashboard proveedor."""
from __future__ import annotations

from django.core.cache import cache
from django.http import JsonResponse

PROTECTED_DASHBOARD_GET_PREFIXES = (
    '/api/ordenes/proveedor-ordenes/ganancias-resumen/',
    '/api/suscripciones/creditos/mi-saldo/mi-saldo/',
    '/api/suscripciones/mi-suscripcion/estado-salud/',
    '/api/mercadopago/cuenta-proveedor/mi-cuenta/',
)

# Por IP + ruta: máx. solicitudes sin Authorization por minuto
UNAUTH_BURST_LIMIT = 20
UNAUTH_BURST_WINDOW_SEC = 60


def _client_ip(request) -> str:
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


def _has_bearer_or_token(request) -> bool:
    auth = (request.META.get('HTTP_AUTHORIZATION') or '').strip()
    return auth.startswith('Token ') or auth.startswith('Bearer ')


class UnauthDashboardBurstMiddleware:
    """
    Cortocircuita GET anónimos repetidos al dashboard antes de DRF.

    Reduce carga en Render cuando un cliente (p. ej. Expo web) dispara decenas
    de requests sin token por segundo.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.method == 'GET'
            and not _has_bearer_or_token(request)
            and any(request.path.startswith(prefix) for prefix in PROTECTED_DASHBOARD_GET_PREFIXES)
        ):
            key = f'unauth_burst:{_client_ip(request)}:{request.path}'
            try:
                count = cache.get(key, 0)
                if count >= UNAUTH_BURST_LIMIT:
                    return JsonResponse(
                        {
                            'detail': (
                                'Demasiadas solicitudes sin autenticación. '
                                'Inicia sesión o cierra pestañas abiertas de la app.'
                            ),
                        },
                        status=429,
                    )
                cache.set(key, count + 1, UNAUTH_BURST_WINDOW_SEC)
            except Exception:
                pass

        return self.get_response(request)
