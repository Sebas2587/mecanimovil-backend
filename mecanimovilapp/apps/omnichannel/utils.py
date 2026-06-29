"""Utilidades Meta omnicanal."""
import hashlib
import hmac
import secrets
from urllib.parse import urlencode

from django.conf import settings
from decouple import config


def omnichannel_enabled():
    return config('OMNICHANNEL_ENABLED', default=False, cast=bool)


def meta_app_id():
    return config('META_APP_ID', default='')


def meta_app_secret():
    return config('META_APP_SECRET', default='')


def meta_verify_token():
    return config('META_VERIFY_TOKEN', default='')


def meta_graph_version():
    return config('META_GRAPH_API_VERSION', default='v21.0')


def meta_oauth_redirect_uri():
    return config(
        'META_OAUTH_REDIRECT_URI',
        default='http://localhost:8000/api/omnichannel/oauth/callback/',
    )


def meta_embedded_signup_config_id():
    return config('META_EMBEDDED_SIGNUP_CONFIG_ID', default='')


def meta_embedded_signup_config_id_for_channel(channel: str) -> str:
    """Configuration ID de Embedded Signup / Login for Business por canal."""
    channel = (channel or '').upper()
    env_map = {
        'WHATSAPP': 'META_EMBEDDED_SIGNUP_CONFIG_ID_WHATSAPP',
        'MESSENGER': 'META_EMBEDDED_SIGNUP_CONFIG_ID_MESSENGER',
        'INSTAGRAM': 'META_EMBEDDED_SIGNUP_CONFIG_ID_INSTAGRAM',
    }
    env_key = env_map.get(channel)
    if env_key:
        specific = config(env_key, default='')
        if specific:
            return specific
    return meta_embedded_signup_config_id()


def meta_app_id_public():
    return meta_app_id()


def build_embedded_config_payload(channel: str) -> dict | None:
    app_id = meta_app_id()
    config_id = meta_embedded_signup_config_id_for_channel(channel)
    if not app_id or not config_id:
        return None
    return {
        'enabled': True,
        'app_id': app_id,
        'config_id': config_id,
        'redirect_uri': meta_oauth_redirect_uri(),
        'graph_version': meta_graph_version(),
    }


def generate_oauth_state():
    return secrets.token_urlsafe(32)


class MetaOAuthExchangeError(Exception):
    """Error al intercambiar code OAuth por token (sin exponer secretos al cliente)."""

    def __init__(self, status_code: int, body: str = ''):
        self.status_code = status_code
        self.body = body
        super().__init__(f'OAuth exchange failed ({status_code})')


def friendly_oauth_error(exc: Exception) -> str:
    """Mensaje seguro para mostrar al taller (sin URLs, tokens ni secrets)."""
    if isinstance(exc, MetaOAuthExchangeError):
        if exc.status_code == 400:
            return (
                'La autorización expiró o ya fue usada. '
                'Cierra el navegador, vuelve a la app y pulsa Conectar otra vez.'
            )
        return 'Meta rechazó la conexión. Intenta de nuevo en unos minutos.'
    raw = str(exc)
    if any(x in raw for x in ('http://', 'https://', 'graph.facebook', 'client_secret', 'Client Error')):
        return 'No pudimos completar la conexión con Meta. Pulsa Conectar e intenta de nuevo.'
    if len(raw) > 180:
        return 'No pudimos completar la conexión con Meta. Pulsa Conectar e intenta de nuevo.'
    return raw


def verify_meta_signature(raw_body: bytes, signature_header: str | None) -> bool:
    secret = meta_app_secret()
    if not secret or not signature_header:
        return False
    if not signature_header.startswith('sha256='):
        return False
    expected = hmac.new(
        secret.encode('utf-8'),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    received = signature_header.split('=', 1)[1]
    return hmac.compare_digest(expected, received)


def channel_to_api_slug(channel: str) -> str:
    return {
        'WHATSAPP': 'whatsapp',
        'MESSENGER': 'messenger',
        'INSTAGRAM': 'instagram',
        'APP': 'app',
    }.get(channel, channel.lower())


def build_embedded_signup_url(state: str, channel: str) -> str | None:
    app_id = meta_app_id()
    redirect_uri = meta_oauth_redirect_uri()
    if not app_id:
        return None
    config_id = meta_embedded_signup_config_id_for_channel(channel)
    params = {
        'client_id': app_id,
        'redirect_uri': redirect_uri,
        'state': state,
        'response_type': 'code',
    }
    # Con config_id (Facebook Login for Business), los permisos vienen del Dashboard.
    # Pasar scope en la URL duplica permisos y Meta rechaza instagram_basic /
    # instagram_manage_messages con "Invalid Scopes".
    if not config_id:
        params['scope'] = _scopes_for_channel(channel)
    if config_id:
        params['config_id'] = config_id
    return f'https://www.facebook.com/{meta_graph_version()}/dialog/oauth?{urlencode(params)}'


def _scopes_for_channel(channel: str) -> str:
    """
    Scopes para OAuth sin config_id (fallback móvil / popup).

    Instagram: no incluir instagram_basic ni instagram_manage_messages aquí;
    deben declararse en META_EMBEDDED_SIGNUP_CONFIG_ID_INSTAGRAM.
    """
    base = 'business_management,pages_show_list,pages_messaging,pages_read_engagement'
    if channel == 'WHATSAPP':
        return f'{base},whatsapp_business_management,whatsapp_business_messaging'
    if channel == 'INSTAGRAM':
        return base
    return base
