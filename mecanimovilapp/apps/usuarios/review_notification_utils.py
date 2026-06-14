"""
Notificaciones in-app y push para recordar reseñas pendientes tras un servicio completado.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _service_display_name(orden) -> str:
    try:
        if hasattr(orden, 'lineas') and orden.lineas.exists():
            linea = orden.lineas.select_related('oferta_servicio__servicio').first()
            if linea and linea.oferta_servicio and linea.oferta_servicio.servicio:
                return str(linea.oferta_servicio.servicio.nombre)
    except Exception:
        pass
    return 'tu servicio'


def _provider_display_name(orden) -> str:
    try:
        if getattr(orden, 'taller', None):
            return str(orden.taller.nombre)
        if getattr(orden, 'mecanico', None):
            return str(orden.mecanico.nombre)
    except Exception:
        pass
    return 'el proveedor'


def notificar_resena_pendiente_si_aplica(orden_id: int) -> bool:
    """
    Si la orden está completada y el cliente aún no dejó reseña, crea notificación
    in-app (tipo review_reminder) y envía push. Idempotente por service_order_id.

    Returns True si se creó o ya existía una notificación reciente equivalente.
    """
    from mecanimovilapp.apps.ordenes.models import SolicitudServicio
    from mecanimovilapp.apps.usuarios.models import Notificacion, Review

    try:
        orden = (
            SolicitudServicio.objects.select_related(
                'cliente__usuario',
                'taller',
                'mecanico',
                'vehiculo__marca',
                'vehiculo__modelo',
            )
            .get(pk=orden_id)
        )
    except SolicitudServicio.DoesNotExist:
        return False

    if orden.estado != 'completado':
        return False

    cliente_usuario = getattr(getattr(orden, 'cliente', None), 'usuario', None)
    if not cliente_usuario:
        return False

    if Review.objects.filter(client=cliente_usuario, service_order=orden).exists():
        return False

    servicio = _service_display_name(orden)
    proveedor = _provider_display_name(orden)
    titulo = 'Califica tu servicio'
    mensaje = (
        f'Tu servicio "{servicio}" con {proveedor} ya finalizó. '
        'Cuéntanos cómo fue tu experiencia — ayuda a otros usuarios y mejora el rendimiento del proveedor.'
    )

    data = {
        'service_order_id': orden.id,
        'provider_name': proveedor,
        'service_name': servicio,
        'screen': 'PendingReviews',
    }

    _, created = Notificacion.crear_unica(
        usuario=cliente_usuario,
        tipo='review_reminder',
        titulo=titulo,
        mensaje=mensaje,
        data=data,
        ventana_horas=72,
        dedup_key={'service_order_id': orden.id},
    )

    try:
        from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification

        send_expo_push_notification.delay(
            cliente_usuario.id,
            titulo,
            mensaje,
            {
                'type': 'review_reminder',
                'service_order_id': str(orden.id),
                'screen': 'PendingReviews',
            },
        )
    except Exception as exc:
        logger.warning('Push review_reminder no enviado (orden %s): %s', orden_id, exc)

    return created
