"""Broadcast de eventos del agente IA al WebSocket del taller."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _resolver_taller_id(*, taller_id: int | None = None, proveedor_user_id: int | None = None) -> int | None:
    if taller_id:
        return int(taller_id)
    if not proveedor_user_id:
        return None
    from mecanimovilapp.apps.usuarios.models import Taller

    taller = Taller.objects.filter(usuario_id=proveedor_user_id).values_list('id', flat=True).first()
    return int(taller) if taller else None


def emitir_evento_ws_agente_ia(
    *,
    event_type: str,
    taller_id: int | None = None,
    proveedor_user_id: int | None = None,
    **payload: Any,
) -> None:
    """Envía evento al grupo proveedor_{taller_id} vía Channels."""
    resolved_taller_id = _resolver_taller_id(
        taller_id=taller_id,
        proveedor_user_id=proveedor_user_id,
    )
    if not resolved_taller_id:
        return

    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        channel_layer = get_channel_layer()
        if not channel_layer:
            return

        async_to_sync(channel_layer.group_send)(
            f'proveedor_{resolved_taller_id}',
            {
                'type': 'agente_ia_event',
                'event_type': event_type,
                **payload,
            },
        )
    except Exception as exc:
        logger.warning('No se pudo emitir WS agente IA (%s): %s', event_type, exc)
