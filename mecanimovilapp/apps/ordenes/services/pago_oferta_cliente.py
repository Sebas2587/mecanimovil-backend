"""Actualización coherente de metodo_pago_cliente al confirmar pagos de oferta."""
from __future__ import annotations


def oferta_tiene_repuestos_cotizados(oferta) -> bool:
    if not getattr(oferta, 'incluye_repuestos', False):
        return False
    costo_rep = float(oferta.costo_repuestos or 0)
    costo_gest = float(oferta.costo_gestion_compra or 0)
    return costo_rep > 0 or costo_gest > 0


def aplicar_confirmacion_pago_servicio(oferta, solicitud) -> None:
    """
    Pago de mano de obra (tipo_pago=servicio).
    - Si ya pagó repuestos por la plataforma: cierra el plan «repuestos adelantado».
    - Si no: el cliente eligió comprar sus propios repuestos (solo MO por MP).
    """
    oferta.estado_pago_servicio = 'pagado'

    if oferta.estado_pago_repuestos == 'pagado':
        oferta.estado = 'pagada'
        return

    if oferta_tiene_repuestos_cotizados(oferta):
        oferta.metodo_pago_cliente = 'cliente_compra_repuestos'
        oferta.estado_pago_repuestos = 'no_aplica'

    oferta.estado = 'pagada'
    if solicitud.estado not in ('en_ejecucion', 'completada'):
        solicitud.estado = 'pagada'
