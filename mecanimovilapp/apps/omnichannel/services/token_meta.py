"""Renueva el permiso de Meta antes de que venza, sin pedir de nuevo Facebook al taller."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

VENTANA_RENOVACION = timedelta(days=14)
MENSAJE_VENCIDO = 'El permiso de Meta venció. Pulsa Conectar para renovarlo.'


def anotar_vigencia(conn, client, token: str) -> None:
    info = client.clasificar_expiracion(token)
    if not info.known:
        return
    conn.token_no_expira = info.never
    conn.token_expires_at = None if info.never else info.expires_at


def renovar_conexion(conn, client, ahora=None) -> str:
    """'omitida', 'anotada', 'renovada' o 'fallo'."""
    token = (conn.access_token or '').strip()
    if not token or conn.token_no_expira:
        return 'omitida'
    ahora = ahora or timezone.now()
    if conn.token_expires_at is None:
        anotar_vigencia(conn, client, token)
        conn.save(update_fields=['token_no_expira', 'token_expires_at', 'updated_at'])
        if conn.token_no_expira or conn.token_expires_at is None:
            return 'anotada'
    if conn.token_expires_at - ahora > VENTANA_RENOVACION:
        return 'omitida'

    data = client.extender_token(token)
    nuevo = (data or {}).get('access_token')
    if not nuevo:
        if conn.token_expires_at <= ahora and conn.status == 'conectada':
            conn.status = 'error'
            conn.enabled = False
            conn.mensaje_estado = MENSAJE_VENCIDO
            conn.save(update_fields=['status', 'enabled', 'mensaje_estado', 'updated_at'])
        logger.warning(
            'Permiso Meta sin renovar channel=%s connection=%s',
            conn.channel,
            conn.id,
        )
        return 'fallo'

    conn.access_token = nuevo
    anotar_vigencia(conn, client, nuevo)
    if conn.token_expires_at is None and not conn.token_no_expira:
        expires_in = (data or {}).get('expires_in')
        if expires_in:
            conn.token_expires_at = ahora + timedelta(seconds=int(expires_in))
    conn.save(update_fields=[
        'access_token',
        'token_expires_at',
        'token_no_expira',
        'updated_at',
    ])
    logger.info('Permiso Meta renovado channel=%s connection=%s', conn.channel, conn.id)
    return 'renovada'


def renovar_tokens_por_vencer() -> dict[str, int]:
    from mecanimovilapp.apps.omnichannel.models import ProviderChannelConnection
    from mecanimovilapp.apps.omnichannel.services.meta_graph import MetaGraphClient

    client = MetaGraphClient()
    cuentas = {'omitida': 0, 'anotada': 0, 'renovada': 0, 'fallo': 0}
    qs = ProviderChannelConnection.objects.filter(
        status__in=('conectada', 'error'),
    ).exclude(access_token__isnull=True).exclude(access_token='')
    for conn in qs.iterator():
        try:
            resultado = renovar_conexion(conn, client)
        except Exception:
            logger.exception('Error al renovar permiso Meta connection=%s', conn.id)
            resultado = 'fallo'
        cuentas[resultado] = cuentas.get(resultado, 0) + 1
    return cuentas
