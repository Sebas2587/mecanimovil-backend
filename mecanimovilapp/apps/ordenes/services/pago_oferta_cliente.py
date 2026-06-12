"""Actualización coherente de estados al confirmar pagos de oferta.

Regla central: confirmar un pago NUNCA debe regresar el estado de ejecución.
Si el proveedor ya inició el servicio (oferta `en_ejecucion`) y/o llenó y firmó
el checklist (orden `pendiente_firma_cliente`/`completado`), el pago del saldo
restante solo marca `estado_pago_servicio='pagado'` — no devuelve la oferta a
`pagada`, lo que desincronizaría la app del proveedor (creería que debe reiniciar
el servicio) y la del cliente (perdería la tarjeta de firma).
"""
from __future__ import annotations

# Estados de OfertaProveedor que representan ejecución ya iniciada o terminada.
# Un pago jamás debe hacer retroceder la oferta desde estos estados.
ESTADOS_OFERTA_EN_CURSO = {'en_ejecucion', 'completada'}

# Estados de SolicitudServicioPublica equivalentes (no regresar).
ESTADOS_SOLICITUD_EN_CURSO = {'en_ejecucion', 'completada'}


def oferta_tiene_repuestos_cotizados(oferta) -> bool:
    if not getattr(oferta, 'incluye_repuestos', False):
        return False
    costo_rep = float(oferta.costo_repuestos or 0)
    costo_gest = float(oferta.costo_gestion_compra or 0)
    return costo_rep > 0 or costo_gest > 0


def avanzar_estado_oferta(oferta, nuevo_estado: str) -> None:
    """Asigna oferta.estado salvo que ya esté en ejecución/terminada (no regresar)."""
    if oferta.estado not in ESTADOS_OFERTA_EN_CURSO:
        oferta.estado = nuevo_estado


def avanzar_estado_solicitud(solicitud, nuevo_estado: str) -> None:
    """Asigna solicitud.estado salvo que ya esté en ejecución/terminada (no regresar)."""
    if solicitud is not None and solicitud.estado not in ESTADOS_SOLICITUD_EN_CURSO:
        solicitud.estado = nuevo_estado


def aplicar_confirmacion_pago_servicio(oferta, solicitud) -> None:
    """
    Pago de mano de obra (tipo_pago=servicio).
    - Si ya pagó repuestos por la plataforma: cierra el plan «repuestos adelantado».
    - Si no: el cliente eligió comprar sus propios repuestos (solo MO por MP).

    Importante: solo marca el pago como realizado y avanza el estado SIN regresar
    la ejecución. Si la oferta ya está `en_ejecucion` (servicio iniciado, checklist
    en curso o `pendiente_firma_cliente`), conserva ese estado para no desincronizar
    al proveedor; el cliente quedará habilitado para firmar gracias a
    `estado_pago_servicio='pagado'`.
    """
    oferta.estado_pago_servicio = 'pagado'

    # Cliente compra sus propios repuestos (no pagó repuestos por la plataforma).
    if oferta.estado_pago_repuestos != 'pagado' and oferta_tiene_repuestos_cotizados(oferta):
        oferta.metodo_pago_cliente = 'cliente_compra_repuestos'
        oferta.estado_pago_repuestos = 'no_aplica'

    # Avanzar el estado de pago sin pisar la ejecución ya iniciada.
    avanzar_estado_oferta(oferta, 'pagada')
    avanzar_estado_solicitud(solicitud, 'pagada')
