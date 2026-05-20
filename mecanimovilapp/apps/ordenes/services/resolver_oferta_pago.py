"""Resuelve OfertaProveedor por id de oferta o de solicitud pública adjudicada."""
from __future__ import annotations

from mecanimovilapp.apps.ordenes.models import OfertaProveedor, SolicitudServicioPublica


def resolver_oferta_pago_por_id(oferta_o_solicitud_id, usuario) -> OfertaProveedor:
    """
    - Si el UUID es de una oferta, la devuelve.
    - Si es de una solicitud pública del cliente, usa oferta_seleccionada.
    """
    pk = str(oferta_o_solicitud_id)
    base_qs = OfertaProveedor.objects.select_related('solicitud', 'solicitud__cliente')

    try:
        oferta = base_qs.get(id=pk)
        if oferta.solicitud.cliente.usuario_id != usuario.id:
            raise OfertaProveedor.DoesNotExist
        return oferta
    except OfertaProveedor.DoesNotExist:
        pass

    try:
        solicitud = SolicitudServicioPublica.objects.select_related(
            'cliente', 'oferta_seleccionada', 'oferta_seleccionada__solicitud__cliente',
        ).get(id=pk)
    except SolicitudServicioPublica.DoesNotExist:
        raise OfertaProveedor.DoesNotExist from None

    if solicitud.cliente.usuario_id != usuario.id:
        raise OfertaProveedor.DoesNotExist

    if not solicitud.oferta_seleccionada_id:
        raise OfertaProveedor.DoesNotExist

    return base_qs.get(id=solicitud.oferta_seleccionada_id)
