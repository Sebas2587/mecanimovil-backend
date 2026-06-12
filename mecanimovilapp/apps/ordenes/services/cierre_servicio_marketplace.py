"""
Cuando una SolicitudServicio (orden) queda en estado `completado`, alinear
OfertaProveedor y SolicitudServicioPublica (mismo contrato que terminar-servicio).

Idempotente y segura ante llamadas repetidas (reintentos del cliente, despliegues
tardíos del fix, etc.).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Tuple

from django.db import transaction
from django.utils import timezone

if TYPE_CHECKING:
    from mecanimovilapp.apps.ordenes.models import OfertaProveedor


def sincronizar_cierre_marketplace(orden_id: int) -> Tuple[bool, Optional['OfertaProveedor']]:
    """
    Si la orden está `completado` y tiene oferta marketplace, pasa oferta y
    solicitud pública de `en_ejecucion` a `completada` y rellena
    `fecha_respuesta_proveedor` si falta.

    Returns:
        (hubo_cambio_en_bd, oferta_con_relaciones_para_ws_o_None)
    """
    from mecanimovilapp.apps.ordenes.models import OfertaProveedor, SolicitudServicio

    with transaction.atomic():
        orden = SolicitudServicio.objects.select_for_update().get(pk=orden_id)
        if orden.estado != 'completado':
            return False, None

        hubo_cambio = False

        if orden.fecha_respuesta_proveedor is None:
            orden.fecha_respuesta_proveedor = timezone.now()
            orden.save(update_fields=['fecha_respuesta_proveedor'])
            hubo_cambio = True

        if not orden.oferta_proveedor_id:
            return hubo_cambio, None

        oferta = (
            OfertaProveedor.objects.select_for_update()
            .select_related(
                'solicitud',
                'solicitud__cliente__usuario',
                'proveedor',
            )
            .get(pk=orden.oferta_proveedor_id)
        )

        # Incluye 'pagada'/'pagada_parcialmente' para sanear órdenes cuyo estado de
        # oferta quedó regresado por una confirmación de pago previa al fix.
        if oferta.estado in ('en_ejecucion', 'pagada', 'pagada_parcialmente'):
            oferta.estado = 'completada'
            oferta.save(update_fields=['estado'])
            hubo_cambio = True

        solicitud_pub = oferta.solicitud
        if solicitud_pub and solicitud_pub.estado in ('en_ejecucion', 'pagada'):
            solicitud_pub.estado = 'completada'
            solicitud_pub.save(update_fields=['estado'])
            hubo_cambio = True

        return hubo_cambio, oferta
