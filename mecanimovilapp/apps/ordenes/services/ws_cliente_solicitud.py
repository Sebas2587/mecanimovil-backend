"""WebSocket al cliente autenticado (grupo `cliente_{user_id}`)."""
from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

logger = logging.getLogger(__name__)


def notificar_cliente_ws(usuario_id, event_type: str, payload: dict) -> None:
    if not usuario_id:
        return
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            return
        async_to_sync(channel_layer.group_send)(
            f'cliente_{usuario_id}',
            {
                'type': event_type,
                'timestamp': timezone.now().isoformat(),
                **payload,
            },
        )
    except Exception as exc:
        logger.warning('WS cliente_%s %s falló: %s', usuario_id, event_type, exc)


def notificar_cliente_pago_completado(oferta, solicitud, tipo_pago: str) -> None:
    usuario = getattr(getattr(solicitud, 'cliente', None), 'usuario', None)
    if not usuario:
        return
    notificar_cliente_ws(
        usuario.id,
        'pago_completado',
        {
            'oferta_id': str(oferta.id),
            'solicitud_id': str(solicitud.id),
            'tipo_pago': tipo_pago,
            'estado_oferta': oferta.estado,
            'estado_solicitud': solicitud.estado,
        },
    )


def notificar_cliente_pendiente_firma(orden) -> None:
    usuario = getattr(getattr(orden, 'cliente', None), 'usuario', None)
    if not usuario:
        return
    solicitud_id = None
    oferta = getattr(orden, 'oferta_proveedor', None)
    if oferta and getattr(oferta, 'solicitud_id', None):
        solicitud_id = str(oferta.solicitud_id)
    notificar_cliente_ws(
        usuario.id,
        'servicio_pendiente_firma',
        {
            'orden_id': str(orden.id),
            'solicitud_id': solicitud_id,
            'mensaje': 'El técnico cerró el checklist. Revisa y firma para terminar el servicio.',
        },
    )
