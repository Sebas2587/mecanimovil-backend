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


def generate_oauth_state():
    return secrets.token_urlsafe(32)


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
    params = {
        'client_id': app_id,
        'redirect_uri': redirect_uri,
        'state': state,
        'response_type': 'code',
        'scope': _scopes_for_channel(channel),
    }
    config_id = meta_embedded_signup_config_id()
    if config_id:
        params['config_id'] = config_id
    return f'https://www.facebook.com/{meta_graph_version()}/dialog/oauth?{urlencode(params)}'


def _scopes_for_channel(channel: str) -> str:
    base = 'business_management,pages_show_list,pages_messaging'
    if channel == 'WHATSAPP':
        return f'{base},whatsapp_business_management,whatsapp_business_messaging'
    if channel == 'INSTAGRAM':
        return f'{base},instagram_basic,instagram_manage_messages'
    return base
