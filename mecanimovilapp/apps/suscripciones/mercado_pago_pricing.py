"""
Precios frente a retenciones Mercado Pago (Chile).

Se asume comisión del 3,19% sobre el monto del cobro, más IVA del 19% aplicado
sobre esa comisión (costo total sobre el bruto ≈ 3,19% × 1,19).

Para que la liquidación neta en cuenta se acerque a un objetivo `neto`,
el monto bruto a cobrar al usuario debe ser: neto / (1 - retención_efectiva).
"""
from decimal import Decimal, ROUND_HALF_UP

# Comisión informada por MP sobre el pago (sin incluir IVA en el porcentaje base).
MP_COMISION_SOBRE_PAGO = Decimal('0.0319')
# IVA Chile aplicado sobre la comisión.
MP_IVA = Decimal('0.19')


def retencion_efectiva_sobre_bruto() -> Decimal:
    """Fracción del cobro que no queda como neto disponible (comisión + IVA sobre comisión)."""
    return MP_COMISION_SOBRE_PAGO * (Decimal('1') + MP_IVA)


def monto_bruto_para_neto(neto: Decimal) -> Decimal:
    """
    Monto bruto (CLP) a cobrar para que, tras retención MP, quede ~`neto` en cuenta.

    `neto` es el objetivo de liquidación; el precio publicado / enviado a MP es el retorno.
    """
    r = retencion_efectiva_sobre_bruto()
    if r >= 1:
        raise ValueError('retención MP inválida (>= 100%)')
    return (neto / (Decimal('1') - r)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def monto_bruto_para_neto_pesos_enteros(neto: Decimal) -> Decimal:
    """Igual que `monto_bruto_para_neto` pero redondeado a peso entero (planes mensuales)."""
    return monto_bruto_para_neto(neto).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
