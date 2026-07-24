"""URLs firmadas de corta vida para servir adjuntos de chat vía la API.

Evita depender del CORS del bucket R2 (el token a menudo no puede PutBucketCors)
y permite que <img> / <audio> en web carguen sin Authorization header.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

from decouple import config
from django.conf import settings


def _secret() -> bytes:
    # Preferir secreto compartido API↔worker (SECRET_KEY de cada servicio en Render
    # se genera por separado y rompería la firma del WS).
    dedicated = (config('MEDIA_SIGNING_SECRET', default='') or '').strip()
    if dedicated:
        return dedicated.encode('utf-8')
    return (getattr(settings, 'SECRET_KEY', None) or 'dev').encode('utf-8')


def sign_message_attachment(message_id: int, ttl_seconds: int = 6 * 3600) -> tuple[str, int]:
    expires = int(time.time()) + int(ttl_seconds)
    payload = f'{int(message_id)}:{expires}'.encode('utf-8')
    sig = hmac.new(_secret(), payload, hashlib.sha256).hexdigest()[:40]
    return sig, expires


def verify_message_attachment_token(message_id: int, sig: str, expires: str | int) -> bool:
    try:
        exp = int(expires)
    except (TypeError, ValueError):
        return False
    if exp < int(time.time()):
        return False
    if not sig:
        return False
    payload = f'{int(message_id)}:{exp}'.encode('utf-8')
    expected = hmac.new(_secret(), payload, hashlib.sha256).hexdigest()[:40]
    return hmac.compare_digest(expected, str(sig))


def build_message_attachment_url(message_id: int, request=None) -> str:
    sig, expires = sign_message_attachment(message_id)
    path = f'/api/chat/messages/{int(message_id)}/attachment/'
    query = urlencode({'sig': sig, 'expires': expires})
    if request is not None:
        return request.build_absolute_uri(f'{path}?{query}')
    base = config('WEBHOOK_BASE_URL', default='https://mecanimovil-api.onrender.com').rstrip('/')
    return f'{base}{path}?{query}'
