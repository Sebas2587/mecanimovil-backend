"""
Registro de liquidaciones al proveedor cuando un pago MP queda aprobado.
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.contenttypes.models import ContentType

from mecanimovilapp.apps.pagos.models import LiquidacionProveedor, Pago

logger = logging.getLogger(__name__)

COMISION_RATE = Decimal('0.20')
IVA_RATE = Decimal('0.19')


def _clp(value: Decimal) -> Decimal:
    return value.quantize(Decimal('1'), rounding=ROUND_HALF_UP)


def _parse_oferta_id(external_reference: str | None) -> uuid.UUID | None:
    if not external_reference:
        return None
    ref = external_reference.strip()
    if ref.startswith('oferta_'):
        parts = ref.split('_')
        if len(parts) >= 2:
            try:
                return uuid.UUID(parts[1])
            except ValueError:
                return None
    try:
        return uuid.UUID(ref)
    except ValueError:
        return None


def _resolver_proveedor_desde_pago(pago: Pago):
    """Retorna (usuario_proveedor, content_type, object_id, oferta_id, orden_id)."""
    from mecanimovilapp.apps.ordenes.models import OfertaProveedor

    oferta_id = _parse_oferta_id(pago.external_reference)
    if oferta_id:
        try:
            oferta = OfertaProveedor.objects.select_related('proveedor').get(id=oferta_id)
        except OfertaProveedor.DoesNotExist:
            logger.warning('Liquidación: oferta %s no encontrada para pago %s', oferta_id, pago.id)
            return None, None, None, None, None

        proveedor_user = oferta.proveedor
        taller = getattr(proveedor_user, 'taller', None)
        mecanico = getattr(proveedor_user, 'mecanico_domicilio', None)
        entidad = taller or mecanico
        if entidad is None:
            return None, None, None, str(oferta.id), None

        ct = ContentType.objects.get_for_model(entidad)
        return proveedor_user, ct, entidad.pk, str(oferta.id), None

    if pago.carrito_id:
        from mecanimovilapp.apps.ordenes.models import ItemCarritoAgendamiento

        item = (
            ItemCarritoAgendamiento.objects.filter(carrito_id=pago.carrito_id)
            .select_related(
                'oferta_servicio__taller__usuario',
                'oferta_servicio__mecanico__usuario',
            )
            .first()
        )
        oferta_serv = getattr(item, 'oferta_servicio', None) if item else None
        if oferta_serv:
            if oferta_serv.taller_id:
                ct = ContentType.objects.get_for_model(oferta_serv.taller)
                return oferta_serv.taller.usuario, ct, oferta_serv.taller_id, None, None
            if oferta_serv.mecanico_id:
                ct = ContentType.objects.get_for_model(oferta_serv.mecanico)
                return oferta_serv.mecanico.usuario, ct, oferta_serv.mecanico_id, None, None

    return None, None, None, None, None


def calcular_montos_liquidacion(monto_cobrado: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """Calcula comisión plataforma (20% + IVA) y neto al proveedor."""
    monto = _clp(monto_cobrado)
    comision = _clp(monto * COMISION_RATE)
    iva_comision = _clp(comision * IVA_RATE)
    comision_total = comision + iva_comision
    neto = monto - comision_total
    return monto, comision_total, neto


def registrar_liquidacion_desde_pago(pago: Pago) -> LiquidacionProveedor | None:
    """
    Crea LiquidacionProveedor idempotente cuando el pago queda approved.
    """
    if pago.status != 'approved':
        return None

    if LiquidacionProveedor.objects.filter(pago=pago).exists():
        return LiquidacionProveedor.objects.filter(pago=pago).first()

    usuario, content_type, object_id, oferta_id, orden_id = _resolver_proveedor_desde_pago(pago)
    if usuario is None or content_type is None or object_id is None:
        logger.info('Liquidación omitida: no se resolvió proveedor para pago %s', pago.id)
        return None

    monto_cobrado, comision_total, neto = calcular_montos_liquidacion(
        Decimal(str(pago.transaction_amount or 0)),
    )

    liquidacion = LiquidacionProveedor.objects.create(
        usuario=usuario,
        content_type=content_type,
        object_id=object_id,
        pago=pago,
        oferta_id=uuid.UUID(oferta_id) if oferta_id else None,
        orden_id=orden_id,
        monto_cobrado_cliente=monto_cobrado,
        comision_plataforma=comision_total,
        monto_neto_proveedor=neto,
        moneda=pago.currency_id or 'CLP',
        estado='pendiente',
    )
    logger.info(
        'Liquidación %s creada para pago %s — neto $%s',
        liquidacion.id,
        pago.id,
        neto,
    )
    return liquidacion
