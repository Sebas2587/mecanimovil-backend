"""
Desglose subtotal (sin IVA) + IVA alineado a precio_total_ofrecido.
Misma regla que apps (mecanimovil-prov / mecanimovil-usuarios) en ofertaPrecioDesglose.
"""


def desglose_iva_oferta_proveedor(oferta) -> dict:
    """
    Retorna subtotal sin IVA, IVA y total redondeado (CLP) coherentes con precio_total_ofrecido.

    Args:
        oferta: instancia OfertaProveedor o cualquier objeto con
            costo_mano_obra, costo_repuestos, costo_gestion_compra, precio_total_ofrecido
    """
    def _f(val) -> float:
        if val is None:
            return 0.0
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.0

    mo = _f(getattr(oferta, 'costo_mano_obra', None))
    rep = _f(getattr(oferta, 'costo_repuestos', None))
    gest = _f(getattr(oferta, 'costo_gestion_compra', None))
    total_cliente = int(round(_f(getattr(oferta, 'precio_total_ofrecido', None))))
    sum_sin_iva = mo + rep + gest
    tiene_montos = mo > 0 or rep > 0 or gest > 0
    tol = 2
    total_desde_lineas = int(round(sum_sin_iva * 1.19))
    lineas_cuadran = sum_sin_iva > 0 and abs(total_desde_lineas - total_cliente) <= tol

    if total_cliente <= 0:
        sub_sin_iva = 0
        iva = 0
    elif tiene_montos and lineas_cuadran:
        sub_sin_iva = int(round(sum_sin_iva))
        iva = total_cliente - sub_sin_iva
    else:
        sub_sin_iva = int(round(total_cliente / 1.19))
        iva = total_cliente - sub_sin_iva

    return {
        'subtotal_sin_iva': sub_sin_iva,
        'iva': iva,
        'total': total_cliente,
        'lineas_cuadran_con_total': lineas_cuadran,
        'suma_sin_iva_declarada': int(round(sum_sin_iva)) if sum_sin_iva else 0,
    }
