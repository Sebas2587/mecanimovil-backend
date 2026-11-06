"""Caja del taller: movimientos confirmados, sin inventar cobros ni bloquear Mercado Pago."""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction

from mecanimovilapp.apps.ordenes.models import (
    CitaAgendaPersonal,
    CotizacionCanal,
    OfertaProveedor,
    SolicitudServicio,
)
from mecanimovilapp.apps.ordenes.models_caja import AnclaCaja, CobroTaller, CostoTaller

logger = logging.getLogger(__name__)

ZONA = ZoneInfo('America/Santiago')
PERIODO_MAX_DIAS = 366
CLAVES_PRIVADAS = (
    'costo_registrado_clp',
    'costo_estimado_clp',
    'margen_real_clp',
    'margen_estimado_clp',
    'margen_contratado_clp',
    'resultado_caja_clp',
    'margen_faltantes',
    'margen_real_pct',
    'margen_estimado_pct',
    'nota',
)
_TRANSICIONES_DESDE = {
    CobroTaller.ESTADO_PENDIENTE: {
        CobroTaller.ESTADO_CONFIRMADO,
        CobroTaller.ESTADO_RECHAZADO,
        CobroTaller.ESTADO_CANCELADO,
    },
    CobroTaller.ESTADO_CONFIRMADO: set(),
    CobroTaller.ESTADO_RECHAZADO: set(),
    CobroTaller.ESTADO_CANCELADO: set(),
}
ESTADOS_OFERTA_EXIGIBLE = {
    'aceptada',
    'pendiente_pago',
    'pagada_parcialmente',
    'pagada',
    'en_ejecucion',
    'completada',
}
ENTRADAS = {CobroTaller.TIPO_ENTRADA}
SALIDAS = {CobroTaller.TIPO_REEMBOLSO, CobroTaller.TIPO_CONTRACARGO}


class CajaError(Exception):
    def __init__(self, code: str, detail: str, status: int = 400):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = status


def fecha_local_de(momento: datetime) -> date:
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=ZONA)
    return momento.astimezone(ZONA).date()


def interpretar_fecha_efectiva(valor) -> tuple[datetime, date]:
    """Devuelve (instante UTC-aware, día local). Una fecha sola cae a las 12:00."""
    if isinstance(valor, datetime):
        momento = valor if valor.tzinfo else valor.replace(tzinfo=ZONA)
        momento = momento.astimezone(ZONA)
        return momento, momento.date()
    if isinstance(valor, date):
        dia = valor
    else:
        texto = str(valor or '').strip()
        if not texto:
            raise CajaError('fecha_requerida', 'Indica la fecha efectiva del movimiento.')
        try:
            if 'T' in texto or ' ' in texto:
                momento = datetime.fromisoformat(texto.replace('Z', '+00:00'))
            else:
                dia = date.fromisoformat(texto[:10])
                momento = None
        except ValueError as exc:
            raise CajaError(
                'fecha_invalida',
                'La fecha efectiva no existe en el calendario.',
            ) from exc
        if momento is not None:
            if momento.tzinfo is None:
                momento = momento.replace(tzinfo=ZONA)
            momento = momento.astimezone(ZONA)
            return momento, momento.date()
    mediodia = datetime(dia.year, dia.month, dia.day, 12, 0, tzinfo=ZONA)
    return mediodia, dia


def rango_periodo(desde: date, hasta: date) -> None:
    if hasta < desde:
        raise CajaError('periodo_invalido', 'La fecha hasta es anterior a desde.')
    dias = (hasta - desde).days + 1
    if dias > PERIODO_MAX_DIAS:
        raise CajaError(
            'periodo_excede_366',
            'El período de caja admite como máximo 366 días.',
        )


def monto_entero_clp(valor, *, permitir_cero: bool = False) -> int:
    if isinstance(valor, bool) or valor is None:
        raise CajaError('monto_invalido', 'El monto debe ser un entero en CLP.')
    try:
        dec = Decimal(str(valor))
    except Exception as exc:
        raise CajaError('monto_invalido', 'El monto debe ser un entero en CLP.') from exc
    if dec != dec.to_integral_value():
        raise CajaError(
            'monto_no_entero',
            'El monto de caja es CLP entero, sin centavos.',
        )
    numero = int(dec)
    if numero < 0 or (numero == 0 and not permitir_cero):
        raise CajaError('monto_invalido', 'El monto debe ser mayor a cero.')
    return numero


def _clp_desde_decimal(valor) -> tuple[int, Decimal, bool]:
    dec = Decimal(str(valor if valor is not None else '0'))
    entero = int(dec.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    redondeado = dec != dec.to_integral_value()
    return max(0, entero), dec, redondeado


def _hash_cuerpo(data: dict) -> str:
    raw = json.dumps(data, sort_keys=True, default=str, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest()


def _ancla_id(valor) -> str:
    return str(valor).strip()


def canonizar_ancla(taller, ancla_tipo: str, ancla_id: str) -> tuple[str, str]:
    """Un caso de solicitud+oferta tiene un solo libro: el de la oferta.

    La cita no se mezcla con la oferta. `nueva_fecha` sigue en la cita hija
    y `misma_visita` sigue sumando en la cita padre. Otro taller no entra.
    """
    obj = resolver_ancla(taller, ancla_tipo, ancla_id)
    if ancla_tipo == CobroTaller.ANCLA_SOLICITUD and getattr(obj, 'oferta_proveedor_id', None):
        oferta = obj.oferta_proveedor
        if oferta is not None and oferta.proveedor_id == taller.usuario_id:
            return CobroTaller.ANCLA_OFERTA, str(oferta.id)
    return ancla_tipo, _ancla_id(ancla_id)


def resolver_ancla(taller, ancla_tipo: str, ancla_id: str):
    ancla_id = _ancla_id(ancla_id)
    if ancla_tipo == CobroTaller.ANCLA_CITA:
        obj = CitaAgendaPersonal.objects.filter(pk=ancla_id, taller=taller).first()
    elif ancla_tipo == CobroTaller.ANCLA_SOLICITUD:
        obj = SolicitudServicio.objects.filter(pk=ancla_id, taller=taller).first()
    elif ancla_tipo == CobroTaller.ANCLA_OFERTA:
        obj = (
            OfertaProveedor.objects.filter(pk=ancla_id, proveedor=taller.usuario)
            .select_related('proveedor')
            .first()
        )
    else:
        raise CajaError('ancla_invalida', 'La ancla debe ser cita, solicitud u oferta.')
    if obj is None:
        raise CajaError('ancla_ajena', 'El caso no pertenece a este taller.', status=404)
    return obj


def ancla_asignada(miembro, ancla_tipo: str, ancla_id: str) -> bool:
    if miembro is None:
        return False
    ancla_id = _ancla_id(ancla_id)
    if ancla_tipo == CobroTaller.ANCLA_CITA:
        return CitaAgendaPersonal.objects.filter(
            pk=ancla_id, miembro_taller_id=miembro.id,
        ).exists()
    if ancla_tipo == CobroTaller.ANCLA_SOLICITUD:
        return SolicitudServicio.objects.filter(
            pk=ancla_id, mecanico_asignado_id=miembro.id,
        ).exists()
    if ancla_tipo == CobroTaller.ANCLA_OFERTA:
        return OfertaProveedor.objects.filter(
            pk=ancla_id, miembro_taller_asignado_id=miembro.id,
        ).exists()
    return False


def _exigible_vacio(fuente: str, faltantes: list | None = None) -> dict:
    return {
        'monto_exigible_clp': None,
        'exigible_conocido': False,
        'exigible_fuente': fuente,
        'exigible_faltantes': list(faltantes or []),
    }


def explicar_exigible(taller, ancla_tipo: str, ancla_id: str) -> dict:
    """Misma obligación que la respuesta de la cotización aceptada. No escribe."""
    try:
        ancla_tipo, ancla_id = canonizar_ancla(taller, ancla_tipo, ancla_id)
    except CajaError:
        return _exigible_vacio('ancla_ajena')
    if ancla_tipo == CobroTaller.ANCLA_CITA:
        return _exigible_cita(taller, ancla_id)
    if ancla_tipo == CobroTaller.ANCLA_OFERTA:
        oferta = OfertaProveedor.objects.filter(
            pk=ancla_id, proveedor=taller.usuario,
        ).first()
        return _exigible_oferta(oferta)
    return _exigible_vacio('sin_aceptacion')


def monto_exigible(taller, ancla_tipo: str, ancla_id: str) -> tuple[int | None, bool]:
    info = explicar_exigible(taller, ancla_tipo, ancla_id)
    return info['monto_exigible_clp'], info['exigible_conocido']


def _exigible_cita(taller, ancla_id: str) -> dict:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
        resolver_obligacion_cotizacion,
    )

    cita = (
        CitaAgendaPersonal.objects.filter(pk=ancla_id, taller=taller)
        .select_related('cotizacion_canal_origen')
        .first()
    )
    if cita is None:
        return _exigible_vacio('ancla_ajena')
    cotizaciones = []
    principal = getattr(cita, 'cotizacion_canal_origen', None)
    if principal is not None and principal.estado == 'aceptada':
        cotizaciones.append(principal)
    extras = CotizacionCanal.objects.filter(
        cita_origen_id=cita.id,
        estado='aceptada',
        es_cotizacion_adicional=True,
    ).exclude(ejecucion_adicional='nueva_fecha')
    cotizaciones.extend(list(extras))
    if not cotizaciones:
        return _exigible_vacio('sin_aceptacion')
    total = 0
    fuentes = []
    for cot in cotizaciones:
        info = resolver_obligacion_cotizacion(cot)
        if not info['obligacion_conocida']:
            return _exigible_vacio(info['obligacion_fuente'], info['obligacion_faltantes'])
        total += int(info['obligacion_clp'])
        fuentes.append(info['obligacion_fuente'])
    fuente = fuentes[0] if len(set(fuentes)) == 1 else 'mixta'
    return {
        'monto_exigible_clp': total,
        'exigible_conocido': True,
        'exigible_fuente': fuente,
        'exigible_faltantes': [],
    }


def _exigible_oferta(oferta) -> dict:
    if oferta is None or oferta.estado not in ESTADOS_OFERTA_EXIGIBLE:
        return _exigible_vacio('sin_aceptacion')
    if oferta.precio_total_ofrecido is None:
        return _exigible_vacio('oferta_sin_precio')
    entero, _dec, _redondeado = _clp_desde_decimal(oferta.precio_total_ofrecido)
    return {
        'monto_exigible_clp': entero,
        'exigible_conocido': True,
        'exigible_fuente': 'oferta_aceptada',
        'exigible_faltantes': [],
    }


def _neto_movimientos(movimientos) -> tuple[int, int, int]:
    bruto = 0
    reembolsos = 0
    for mov in movimientos:
        if mov.estado != CobroTaller.ESTADO_CONFIRMADO or not mov.contabiliza_clp:
            continue
        if mov.tipo in ENTRADAS:
            bruto += int(mov.monto_clp)
        elif mov.tipo in SALIDAS:
            reembolsos += int(mov.monto_clp)
    return bruto, reembolsos, bruto - reembolsos


def _lock_ancla(taller, ancla_tipo, ancla_id):
    """Bloquea la fila del caso, creándola si el libro todavía está vacío.

    La unicidad de la referencia no serializa dos claves distintas.
    """
    ancla_id = _ancla_id(ancla_id)
    try:
        with transaction.atomic():
            fila, _creada = AnclaCaja.objects.get_or_create(
                taller=taller,
                ancla_tipo=ancla_tipo,
                ancla_id=ancla_id,
            )
    except IntegrityError:
        fila = AnclaCaja.objects.get(
            taller=taller,
            ancla_tipo=ancla_tipo,
            ancla_id=ancla_id,
        )
    AnclaCaja.objects.select_for_update().get(pk=fila.pk)


def registrar_movimiento(
    *,
    taller,
    ancla_tipo: str,
    ancla_id: str,
    origen: str,
    ref_externa: str,
    tipo: str,
    estado: str,
    monto_clp: int,
    fecha_efectiva: datetime,
    fecha_local: date,
    componente: str = CobroTaller.COMPONENTE_TOTAL,
    moneda: str = 'CLP',
    contabiliza_clp: bool = True,
    monto_origen=None,
    movimiento_origen: CobroTaller | None = None,
    motivo: str = '',
    cuerpo: dict | None = None,
    pago=None,
    usuario=None,
    metadata: dict | None = None,
    permitir_transicion: bool = False,
    confirmar_sobrepago: bool = False,
) -> tuple[CobroTaller, bool]:
    """Crea o reencuentra el movimiento. Devuelve (fila, creada)."""
    cuerpo = dict(cuerpo or {})
    cuerpo_hash = _hash_cuerpo(cuerpo) if cuerpo else ''
    ancla_id = _ancla_id(ancla_id)
    try:
        with transaction.atomic():
            return _registrar_en_tx(
                taller=taller,
                ancla_tipo=ancla_tipo,
                ancla_id=ancla_id,
                origen=origen,
                ref_externa=ref_externa,
                tipo=tipo,
                estado=estado,
                monto_clp=monto_clp,
                fecha_efectiva=fecha_efectiva,
                fecha_local=fecha_local,
                componente=componente,
                moneda=moneda,
                contabiliza_clp=contabiliza_clp,
                monto_origen=monto_origen,
                movimiento_origen=movimiento_origen,
                motivo=motivo,
                cuerpo_hash=cuerpo_hash,
                pago=pago,
                usuario=usuario,
                metadata=metadata or {},
                permitir_transicion=permitir_transicion,
                confirmar_sobrepago=confirmar_sobrepago,
            )
    except IntegrityError:
        existente = CobroTaller.objects.filter(
            taller=taller, origen=origen, ref_externa=ref_externa,
        ).first()
        if existente is None:
            raise
        if cuerpo_hash and existente.cuerpo_hash == cuerpo_hash:
            return existente, False
        if permitir_transicion:
            return existente, False
        raise CajaError(
            'idempotencia_conflicto',
            'La misma referencia ya existe con otro cuerpo.',
            status=409,
        )


def _registrar_en_tx(
    *,
    taller,
    ancla_tipo,
    ancla_id,
    origen,
    ref_externa,
    tipo,
    estado,
    monto_clp,
    fecha_efectiva,
    fecha_local,
    componente,
    moneda,
    contabiliza_clp,
    monto_origen,
    movimiento_origen,
    motivo,
    cuerpo_hash,
    pago,
    usuario,
    metadata,
    permitir_transicion,
    confirmar_sobrepago,
) -> tuple[CobroTaller, bool]:
    _lock_ancla(taller, ancla_tipo, ancla_id)
    if tipo in SALIDAS and movimiento_origen is not None:
        movimiento_origen = _bloquear_origen_reverso(
            movimiento_origen, taller, ancla_tipo, ancla_id,
        )
    existente = (
        CobroTaller.objects.select_for_update()
        .filter(taller=taller, origen=origen, ref_externa=ref_externa)
        .first()
    )
    if existente is not None:
        if cuerpo_hash and existente.cuerpo_hash == cuerpo_hash:
            if permitir_transicion and existente.estado != estado:
                return _transicionar(existente, estado=estado, metadata=metadata), False
            return existente, False
        if permitir_transicion and existente.tipo == tipo:
            if existente.estado != CobroTaller.ESTADO_CONFIRMADO and monto_clp:
                existente.monto_clp = monto_clp
                existente.monto_origen = monto_origen
                existente.cuerpo_hash = cuerpo_hash
                existente.save(update_fields=['monto_clp', 'monto_origen', 'cuerpo_hash'])
            return _transicionar(existente, estado=estado, metadata=metadata), False
        raise CajaError(
            'idempotencia_conflicto',
            'La misma referencia ya existe con otro cuerpo.',
            status=409,
        )
    if origen == CobroTaller.ORIGEN_MANUAL and tipo in SALIDAS:
        _validar_reverso_manual(movimiento_origen, taller, monto_clp)
    elif tipo in SALIDAS:
        _validar_reverso(movimiento_origen, taller, monto_clp)
    if (
        origen == CobroTaller.ORIGEN_MANUAL
        and tipo == CobroTaller.TIPO_ENTRADA
        and estado == CobroTaller.ESTADO_CONFIRMADO
        and contabiliza_clp
    ):
        _validar_sobrepago(
            taller, ancla_tipo, ancla_id, monto_clp, confirmar_sobrepago, metadata,
        )
    fila = CobroTaller.objects.create(
        taller=taller,
        ancla_tipo=ancla_tipo,
        ancla_id=ancla_id,
        componente=componente,
        origen=origen,
        ref_externa=ref_externa,
        tipo=tipo,
        estado=estado,
        monto_clp=monto_clp,
        moneda=moneda,
        contabiliza_clp=contabiliza_clp,
        monto_origen=monto_origen,
        fecha_efectiva=fecha_efectiva,
        fecha_local=fecha_local,
        movimiento_origen=movimiento_origen,
        motivo=motivo,
        cuerpo_hash=cuerpo_hash,
        pago=pago,
        creado_por=usuario,
        metadata=metadata,
    )
    return fila, True


def _transicionar(fila: CobroTaller, *, estado: str, metadata: dict) -> CobroTaller:
    if fila.estado == estado:
        return fila
    meta = dict(fila.metadata or {})
    if estado not in _TRANSICIONES_DESDE.get(fila.estado, set()):
        ignorados = list(meta.get('eventos_ignorados') or [])
        ignorados.append({
            'desde': fila.estado,
            'hacia_solicitado': estado,
            'efecto': 'ignorado',
            'motivo': 'transicion_no_monotonica',
        })
        meta['eventos_ignorados'] = ignorados[-20:]
        fila.metadata = meta
        fila.save(update_fields=['metadata'])
        return fila
    historial = list(meta.get('transiciones') or [])
    historial.append({'desde': fila.estado, 'hacia': estado})
    meta['transiciones'] = historial
    meta.update({k: v for k, v in (metadata or {}).items() if k != 'transiciones'})
    fila.estado = estado
    fila.metadata = meta
    fila.save(update_fields=['estado', 'metadata'])
    return fila


def _bloquear_origen_reverso(origen: CobroTaller, taller, ancla_tipo: str, ancla_id: str) -> CobroTaller:
    bloqueado = (
        CobroTaller.objects.select_for_update()
        .filter(pk=origen.pk, taller=taller)
        .first()
    )
    if bloqueado is None:
        raise CajaError('reverso_sin_origen', 'No está la entrada que se reversa.', status=404)
    list(
        CobroTaller.objects.select_for_update()
        .filter(movimiento_origen=bloqueado)
        .order_by('creado_en')
    )
    if bloqueado.ancla_tipo != ancla_tipo or bloqueado.ancla_id != _ancla_id(ancla_id):
        raise CajaError(
            'reverso_ancla_distinta',
            'El reverso tiene que ser del mismo caso que la entrada.',
            status=409,
        )
    return bloqueado


def _validar_reverso(origen: CobroTaller | None, taller, monto_clp: int) -> None:
    if origen is None or origen.taller_id != taller.id:
        raise CajaError('reverso_sin_origen', 'El reverso debe apuntar a una entrada del taller.')
    if origen.tipo != CobroTaller.TIPO_ENTRADA:
        raise CajaError('reverso_sin_origen', 'Solo se reversa una entrada.')
    if origen.estado != CobroTaller.ESTADO_CONFIRMADO or not origen.contabiliza_clp:
        raise CajaError('reverso_sin_origen', 'La entrada de origen no está confirmada en CLP.')
    ya = sum(
        int(m.monto_clp)
        for m in origen.reversos.filter(
            estado=CobroTaller.ESTADO_CONFIRMADO,
            contabiliza_clp=True,
        )
    )
    if ya + monto_clp > int(origen.monto_clp):
        raise CajaError(
            'reverso_excede_original',
            'El reverso no puede superar el monto de la entrada original.',
            status=409,
        )


def _validar_reverso_manual(origen: CobroTaller | None, taller, monto_clp: int) -> None:
    _validar_reverso(origen, taller, monto_clp)
    if origen.origen != CobroTaller.ORIGEN_MANUAL:
        raise CajaError(
            'reverso_mp_solo_webhook',
            'Un reembolso de Mercado Pago entra por el webhook, no por un cobro manual.',
            status=409,
        )


def _validar_sobrepago(taller, ancla_tipo, ancla_id, monto_clp, confirmar, metadata) -> None:
    exigible, conocido = monto_exigible(taller, ancla_tipo, ancla_id)
    if not conocido or exigible is None:
        metadata['saldo_desconocido'] = True
        return
    movimientos = CobroTaller.objects.filter(
        taller=taller, ancla_tipo=ancla_tipo, ancla_id=ancla_id,
    )
    _bruto, _reembolsos, neto = _neto_movimientos(movimientos)
    if neto + monto_clp > exigible and not confirmar:
        raise CajaError(
            'sobrepago',
            'El abono supera el saldo exigible. Confírmalo para registrarlo igual.',
            status=409,
        )
    if neto + monto_clp > exigible:
        metadata['sobrepago'] = True


def registrar_manual(
    *,
    taller,
    usuario,
    ancla_tipo: str,
    ancla_id: str,
    tipo: str,
    monto_clp: int,
    fecha_valor,
    idempotency_key: str,
    componente: str = CobroTaller.COMPONENTE_TOTAL,
    movimiento_origen_id: str | None = None,
    motivo: str = '',
    confirmar_sobrepago: bool = False,
) -> tuple[CobroTaller, bool]:
    if not (idempotency_key or '').strip():
        raise CajaError('idempotency_key_requerida', 'Falta el header Idempotency-Key.')
    if tipo not in {CobroTaller.TIPO_ENTRADA, CobroTaller.TIPO_REEMBOLSO}:
        raise CajaError('tipo_invalido', 'Un cobro manual es entrada o reembolso.')
    if componente not in {
        CobroTaller.COMPONENTE_REPUESTOS,
        CobroTaller.COMPONENTE_SERVICIO,
        CobroTaller.COMPONENTE_TOTAL,
    }:
        raise CajaError('componente_invalido', 'El componente no es válido.')
    ancla_tipo, ancla_id = canonizar_ancla(taller, ancla_tipo, ancla_id)
    momento, dia = interpretar_fecha_efectiva(fecha_valor)
    origen_mov = None
    if tipo == CobroTaller.TIPO_REEMBOLSO:
        origen_mov = CobroTaller.objects.filter(
            pk=movimiento_origen_id, taller=taller,
        ).first()
        if origen_mov is None:
            raise CajaError('reverso_sin_origen', 'No está la entrada que se reversa.', status=404)
    ref = f'manual:{idempotency_key.strip()}'
    cuerpo = {
        'ancla_tipo': ancla_tipo,
        'ancla_id': _ancla_id(ancla_id),
        'tipo': tipo,
        'monto_clp': int(monto_clp),
        'fecha_local': dia.isoformat(),
        'componente': componente,
        'movimiento_origen_id': str(origen_mov.id) if origen_mov else '',
        'motivo': motivo or '',
    }
    return registrar_movimiento(
        taller=taller,
        ancla_tipo=ancla_tipo,
        ancla_id=ancla_id,
        origen=CobroTaller.ORIGEN_MANUAL,
        ref_externa=ref,
        tipo=tipo,
        estado=CobroTaller.ESTADO_CONFIRMADO,
        monto_clp=int(monto_clp),
        fecha_efectiva=momento,
        fecha_local=dia,
        componente=componente,
        monto_origen=Decimal(int(monto_clp)),
        movimiento_origen=origen_mov,
        motivo=motivo or '',
        cuerpo=cuerpo,
        usuario=usuario,
        metadata={'sobrepago_confirmado': bool(confirmar_sobrepago)},
        confirmar_sobrepago=confirmar_sobrepago,
    )


def registrar_costo(
    *,
    taller,
    usuario,
    ancla_tipo: str,
    ancla_id: str,
    componente: str,
    tipo: str,
    monto_clp: int,
    nota: str = '',
) -> CostoTaller:
    if tipo not in {CostoTaller.TIPO_REGISTRADO, CostoTaller.TIPO_ESTIMADO}:
        raise CajaError('tipo_costo_invalido', 'El costo es registrado o estimado.')
    if componente not in {CobroTaller.COMPONENTE_REPUESTOS, CobroTaller.COMPONENTE_SERVICIO}:
        raise CajaError('componente_invalido', 'El costo es de repuestos o de servicio.')
    ancla_tipo, ancla_id = canonizar_ancla(taller, ancla_tipo, ancla_id)
    with transaction.atomic():
        _lock_ancla(taller, ancla_tipo, ancla_id)
        CostoTaller.objects.select_for_update().filter(
            taller=taller,
            ancla_tipo=ancla_tipo,
            ancla_id=ancla_id,
            componente=componente,
            tipo=tipo,
            vigente=True,
        ).update(vigente=False)
        return CostoTaller.objects.create(
            taller=taller,
            ancla_tipo=ancla_tipo,
            ancla_id=ancla_id,
            componente=componente,
            tipo=tipo,
            monto_clp=int(monto_clp),
            nota=nota or '',
            vigente=True,
            creado_por=usuario,
        )


def costos_vigentes(taller, ancla_tipo: str, ancla_id: str) -> dict:
    try:
        ancla_tipo, ancla_id = canonizar_ancla(taller, ancla_tipo, ancla_id)
    except CajaError:
        return {'costo_registrado_clp': None, 'costo_estimado_clp': None}
    filas = CostoTaller.objects.filter(
        taller=taller,
        ancla_tipo=ancla_tipo,
        ancla_id=_ancla_id(ancla_id),
        vigente=True,
    )
    registrado = 0
    estimado = 0
    hay_reg = False
    hay_est = False
    for fila in filas:
        if fila.tipo == CostoTaller.TIPO_REGISTRADO:
            registrado += int(fila.monto_clp)
            hay_reg = True
        elif fila.tipo == CostoTaller.TIPO_ESTIMADO:
            estimado += int(fila.monto_clp)
            hay_est = True
    return {
        'costo_registrado_clp': registrado if hay_reg else None,
        'costo_estimado_clp': estimado if hay_est else None,
    }


def persistir_evidencia_reembolso_mp(pago, datos_mp: dict | None) -> None:
    """Deja el acumulado de reembolso en Pago antes de tocar la caja.

    No guarda datos del pagador. Un acumulado menor que el ya persistido
    no pisa al mayor: un webhook atrasado no borra evidencia.
    """
    if pago is None or not getattr(pago, 'pk', None) or not isinstance(datos_mp, dict):
        return
    status = str(datos_mp.get('status') or getattr(pago, 'status', '') or '')
    es_contracargo = status == 'charged_back'
    if datos_mp.get('transaction_amount_refunded') is None and not es_contracargo:
        return
    with transaction.atomic():
        bloqueado = pago.__class__.objects.select_for_update().get(pk=pago.pk)
        meta = dict(bloqueado.metadata or {})
        if datos_mp.get('transaction_amount_refunded') is not None:
            nuevo = Decimal(str(datos_mp.get('transaction_amount_refunded')))
            previo = meta.get('transaction_amount_refunded')
            if previo is not None and Decimal(str(previo)) > nuevo:
                vistos = list(meta.get('reembolsos_observados') or [])
                vistos.append(str(nuevo))
                meta['reembolsos_observados'] = vistos[-20:]
            else:
                meta['transaction_amount_refunded'] = format(nuevo, 'f')
        if es_contracargo:
            meta['contracargo_observado'] = True
        meta['caja_reconciliacion'] = 'pendiente'
        bloqueado.metadata = meta
        bloqueado.save(update_fields=['metadata'])
        pago.metadata = meta


def _marcar_reconciliacion(pago, estado: str) -> None:
    if pago is None or not getattr(pago, 'pk', None):
        return
    with transaction.atomic():
        bloqueado = pago.__class__.objects.select_for_update().get(pk=pago.pk)
        meta = dict(bloqueado.metadata or {})
        meta['caja_reconciliacion'] = estado
        bloqueado.metadata = meta
        bloqueado.save(update_fields=['metadata'])
        pago.metadata = meta


def intentar_contabilizar_pago_mp(pago, oferta, tipo_pago: str, datos_mp: dict | None = None) -> None:
    """Nunca propaga. El pago de Mercado Pago ya quedó guardado."""
    try:
        persistir_evidencia_reembolso_mp(pago, datos_mp)
    except Exception as exc:
        logger.error(
            'Caja: no se guardó la evidencia de reembolso pago_id=%s error=%s',
            getattr(pago, 'id', None),
            type(exc).__name__,
        )
    try:
        contabilizar_desde_pago(pago, oferta, tipo_pago)
    except Exception as exc:
        logger.error(
            'Caja: no se contabilizó el pago pago_id=%s error=%s',
            getattr(pago, 'id', None),
            type(exc).__name__,
        )
        return
    try:
        _marcar_reconciliacion(pago, 'aplicada')
    except Exception as exc:
        logger.error(
            'Caja: la contabilización quedó hecha y no se marcó pago_id=%s error=%s',
            getattr(pago, 'id', None),
            type(exc).__name__,
        )


def _como_datetime(valor, fallback: datetime) -> datetime:
    if valor is None:
        return fallback
    if isinstance(valor, datetime):
        momento = valor
    elif isinstance(valor, str):
        try:
            momento = datetime.fromisoformat(valor.replace('Z', '+00:00'))
        except ValueError:
            return fallback
    else:
        return fallback
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=ZONA)
    return momento


def contabilizar_desde_pago(pago, oferta, tipo_pago: str) -> None:
    from mecanimovilapp.apps.usuarios.models import Taller

    if pago is None or oferta is None or not getattr(pago, 'payment_id_mp', None):
        return
    taller = Taller.objects.filter(usuario_id=oferta.proveedor_id).first()
    if taller is None:
        return
    moneda = str(getattr(pago, 'currency_id', None) or 'CLP').upper()
    componente = tipo_pago if tipo_pago in {
        CobroTaller.COMPONENTE_REPUESTOS,
        CobroTaller.COMPONENTE_SERVICIO,
        CobroTaller.COMPONENTE_TOTAL,
    } else CobroTaller.COMPONENTE_TOTAL
    base = getattr(pago, 'fecha_creacion', None) or datetime.now(ZONA)
    momento = _como_datetime(
        getattr(pago, 'date_approved_mp', None)
        or getattr(pago, 'date_created_mp', None)
        or base,
        base if isinstance(base, datetime) else datetime.now(ZONA),
    )
    dia = fecha_local_de(momento)
    payment_id = pago.payment_id_mp
    estado_mp = str(getattr(pago, 'status', '') or '')
    monto, origen_dec, redondeado = _clp_desde_decimal(getattr(pago, 'transaction_amount', 0))
    meta = {
        'status_mp': estado_mp,
        'moneda_origen': moneda,
        'redondeo_aplicado': redondeado,
    }
    if moneda != 'CLP':
        registrar_movimiento(
            taller=taller,
            ancla_tipo=CobroTaller.ANCLA_OFERTA,
            ancla_id=str(oferta.id),
            origen=CobroTaller.ORIGEN_MP,
            ref_externa=f'mp:{payment_id}:moneda',
            tipo=CobroTaller.TIPO_ENTRADA,
            estado=CobroTaller.ESTADO_CONFIRMADO,
            monto_clp=0,
            fecha_efectiva=momento,
            fecha_local=dia,
            componente=componente,
            moneda=moneda,
            contabiliza_clp=False,
            monto_origen=origen_dec,
            pago=pago,
            cuerpo={
                'payment_id': str(payment_id),
                'moneda': moneda,
                'monto_origen': str(origen_dec),
                'status': estado_mp,
            },
            metadata=meta,
            permitir_transicion=True,
        )
        return

    estado = _estado_desde_mp(estado_mp)
    entrada, _creada = registrar_movimiento(
        taller=taller,
        ancla_tipo=CobroTaller.ANCLA_OFERTA,
        ancla_id=str(oferta.id),
        origen=CobroTaller.ORIGEN_MP,
        ref_externa=f'mp:{payment_id}',
        tipo=CobroTaller.TIPO_ENTRADA,
        estado=estado,
        monto_clp=monto,
        fecha_efectiva=momento,
        fecha_local=dia,
        componente=componente,
        moneda='CLP',
        contabiliza_clp=True,
        monto_origen=origen_dec,
        pago=pago,
        cuerpo={
            'payment_id': str(payment_id),
            'tipo': CobroTaller.TIPO_ENTRADA,
            'monto_clp': monto,
            'componente': componente,
        },
        metadata=meta,
        permitir_transicion=True,
    )
    objetivo = _objetivo_reembolso_acumulado(pago, estado_mp, monto)
    if objetivo is None or objetivo <= 0 or entrada.estado != CobroTaller.ESTADO_CONFIRMADO:
        return
    meta_pago = getattr(pago, 'metadata', None) or {}
    es_contracargo = estado_mp == 'charged_back' or bool(meta_pago.get('contracargo_observado'))
    _aplicar_reembolso_acumulado(
        taller=taller,
        entrada=entrada,
        payment_id=payment_id,
        objetivo=objetivo,
        tipo_salida=(
            CobroTaller.TIPO_CONTRACARGO
            if es_contracargo
            else CobroTaller.TIPO_REEMBOLSO
        ),
        momento=_como_datetime(getattr(pago, 'date_last_updated_mp', None), momento),
        componente=componente,
        pago=pago,
        metadata=meta,
    )


def _estado_desde_mp(status: str) -> str:
    if status == 'approved':
        return CobroTaller.ESTADO_CONFIRMADO
    if status in {'pending', 'authorized', 'in_process', 'in_mediation'}:
        return CobroTaller.ESTADO_PENDIENTE
    if status == 'rejected':
        return CobroTaller.ESTADO_RECHAZADO
    if status == 'cancelled':
        return CobroTaller.ESTADO_CANCELADO
    if status in {'refunded', 'charged_back'}:
        return CobroTaller.ESTADO_CONFIRMADO
    return CobroTaller.ESTADO_PENDIENTE


def _objetivo_reembolso_acumulado(pago, status: str, monto_entrada: int) -> int | None:
    """`transaction_amount_refunded` es acumulado de devoluciones, no del contracargo.

    Un `charged_back` cierra la entrada completa. El reembolso ya contabilizado
    no se vuelve a sumar: el incremento es solo el resto.
    """
    meta = getattr(pago, 'metadata', None) or {}
    if status == 'charged_back' or meta.get('contracargo_observado'):
        return monto_entrada
    bruto = meta.get('transaction_amount_refunded')
    if bruto is None:
        if status == 'refunded':
            return monto_entrada
        return None
    entero, _dec, _redondeado = _clp_desde_decimal(bruto)
    return min(entero, monto_entrada)


def _suma_reversos_confirmados(entrada: CobroTaller) -> int:
    return sum(
        int(m.monto_clp)
        for m in entrada.reversos.all()
        if m.estado == CobroTaller.ESTADO_CONFIRMADO and m.contabiliza_clp
    )


def _aplicar_reembolso_acumulado(
    *,
    taller,
    entrada: CobroTaller,
    payment_id,
    objetivo: int,
    tipo_salida: str,
    momento: datetime,
    componente: str,
    pago,
    metadata: dict,
) -> None:
    """Registra solo el incremento sobre lo ya reversado. Un acumulado menor no resta."""
    ancla_tipo = CobroTaller.ANCLA_OFERTA
    ancla_id = str(entrada.ancla_id)
    with transaction.atomic():
        _lock_ancla(taller, ancla_tipo, ancla_id)
        entrada = CobroTaller.objects.select_for_update().get(pk=entrada.pk)
        list(
            CobroTaller.objects.select_for_update()
            .filter(movimiento_origen=entrada)
            .order_by('creado_en')
        )
        if entrada.estado != CobroTaller.ESTADO_CONFIRMADO:
            return
        ya = _suma_reversos_confirmados(entrada)
        objetivo = min(int(objetivo), int(entrada.monto_clp))
        meta_entrada = dict(entrada.metadata or {})
        vistos = list(meta_entrada.get('reembolsos_acumulados_vistos') or [])
        if objetivo not in vistos:
            vistos.append(objetivo)
        meta_entrada['reembolsos_acumulados_vistos'] = vistos[-20:]
        meta_entrada['reembolso_acumulado_aplicado_clp'] = max(
            int(meta_entrada.get('reembolso_acumulado_aplicado_clp') or 0),
            ya if objetivo <= ya else objetivo,
        )
        entrada.metadata = meta_entrada
        entrada.save(update_fields=['metadata'])
        if objetivo <= ya:
            return
        incremento = objetivo - ya
        registrar_movimiento(
            taller=taller,
            ancla_tipo=ancla_tipo,
            ancla_id=ancla_id,
            origen=CobroTaller.ORIGEN_MP,
            ref_externa=f'mp-refund:{payment_id}:acum:{objetivo}',
            tipo=tipo_salida,
            estado=CobroTaller.ESTADO_CONFIRMADO,
            monto_clp=incremento,
            fecha_efectiva=momento,
            fecha_local=fecha_local_de(momento),
            componente=componente,
            moneda='CLP',
            contabiliza_clp=True,
            monto_origen=Decimal(incremento),
            movimiento_origen=entrada,
            pago=pago,
            cuerpo={
                'payment_id': str(payment_id),
                'tipo': tipo_salida,
                'acumulado_clp': objetivo,
                'incremento_clp': incremento,
                'entrada': str(entrada.id),
            },
            metadata={**metadata, 'acumulado_clp': objetivo, 'incremento_clp': incremento},
            permitir_transicion=True,
        )


def _buckets(desde: date, hasta: date, granularidad: str) -> list[tuple[date, date]]:
    if granularidad == 'semana':
        cursor = desde - timedelta(days=desde.weekday())
        out = []
        while cursor <= hasta:
            fin = cursor + timedelta(days=6)
            out.append((max(cursor, desde), min(fin, hasta)))
            cursor = fin + timedelta(days=1)
        return out
    if granularidad == 'mes':
        cursor = desde.replace(day=1)
        out = []
        while cursor <= hasta:
            if cursor.month == 12:
                siguiente = date(cursor.year + 1, 1, 1)
            else:
                siguiente = date(cursor.year, cursor.month + 1, 1)
            fin = min(siguiente - timedelta(days=1), hasta)
            ini = max(cursor, desde)
            if ini <= fin:
                out.append((ini, fin))
            cursor = siguiente
        return out
    out = []
    cursor = desde
    while cursor <= hasta:
        out.append((cursor, cursor))
        cursor += timedelta(days=1)
    return out


def consultar_periodo(
    *,
    taller,
    desde: date,
    hasta: date,
    granularidad: str = 'dia',
    page: int = 1,
    page_size: int = 50,
    casos_page: int = 1,
    miembro=None,
    rol: str | None = None,
    ancla_tipo: str | None = None,
    ancla_id: str | None = None,
) -> dict:
    if granularidad not in {'dia', 'semana', 'mes'}:
        raise CajaError('granularidad_invalida', 'La granularidad es dia, semana o mes.')
    rango_periodo(desde, hasta)
    page = max(1, int(page or 1))
    casos_page = max(1, int(casos_page or 1))
    page_size = min(100, max(1, int(page_size or 50)))
    if ancla_tipo or ancla_id:
        if not ancla_tipo or not ancla_id:
            raise CajaError('ancla_invalida', 'Indica ancla_tipo y ancla_id juntos.')
        pedido_tipo, pedido_id = ancla_tipo, ancla_id
        ancla_tipo, ancla_id = canonizar_ancla(taller, ancla_tipo, ancla_id)
        if rol == 'mecanico' and not (
            ancla_asignada(miembro, pedido_tipo, pedido_id)
            or ancla_asignada(miembro, ancla_tipo, ancla_id)
        ):
            raise CajaError('ancla_ajena', 'El caso no pertenece a este taller.', status=404)
    qs = CobroTaller.objects.filter(
        taller=taller,
        fecha_local__gte=desde,
        fecha_local__lte=hasta,
    ).order_by('fecha_local', 'creado_en')
    if ancla_tipo and ancla_id:
        qs = qs.filter(ancla_tipo=ancla_tipo, ancla_id=_ancla_id(ancla_id))
    if rol == 'mecanico':
        if miembro is None:
            qs = qs.none()
        else:
            permitidas = _anclas_mecanico(miembro)
            if not permitidas:
                qs = qs.none()
            else:
                from django.db.models import Q
                filtro = Q()
                for tipo, ids in permitidas.items():
                    filtro |= Q(ancla_tipo=tipo, ancla_id__in=ids)
                qs = qs.filter(filtro)
    movimientos = list(qs)
    confirmados = [
        m for m in movimientos
        if m.estado == CobroTaller.ESTADO_CONFIRMADO and m.contabiliza_clp
    ]
    bruto, reembolsos, neto = _neto_movimientos(confirmados)
    pendientes = sum(
        int(m.monto_clp)
        for m in movimientos
        if m.estado == CobroTaller.ESTADO_PENDIENTE and m.contabiliza_clp
    )
    legacy = _contar_legacy(taller, miembro=miembro, rol=rol)
    no_clp = sum(1 for m in movimientos if not m.contabiliza_clp)
    faltantes = []
    if legacy:
        faltantes.append('legacy_sin_movimiento')
    if no_clp:
        faltantes.append('moneda_no_clp')
    serie = []
    for ini, fin in _buckets(desde, hasta, granularidad):
        trozo = [m for m in confirmados if ini <= m.fecha_local <= fin]
        b, r, n = _neto_movimientos(trozo)
        serie.append({
            'inicio': ini.isoformat(),
            'fin': fin.isoformat(),
            'cobros_brutos_clp': b,
            'reembolsos_clp': r,
            'neto_clp': n,
        })
    ver_costos = rol in {'mandante', 'supervisor'}
    casos = _casos_periodo(taller, movimientos, ver_costos=ver_costos)
    data = {
        'zona': 'America/Santiago',
        'desde': desde.isoformat(),
        'hasta': hasta.isoformat(),
        'granularidad': granularidad,
        'resumen': {
            'cobros_brutos_clp': bruto,
            'reembolsos_clp': reembolsos,
            'neto_clp': neto,
            'pendientes_no_sumados_clp': pendientes,
            'moneda': 'CLP',
            'completo': not faltantes,
            'conocido_parcial': bool(faltantes),
            'faltantes': faltantes,
            'legacy_no_contabilizado': legacy,
        },
        'serie': serie,
    }
    movimientos_pagina = _paginar(
        [_movimiento_json(m) for m in movimientos],
        page,
        page_size,
    )
    casos_pagina = _paginar(casos, casos_page, page_size)
    _anotar_identidad(taller, movimientos_pagina['results'], casos_pagina['results'])
    data['movimientos'] = movimientos_pagina
    data['casos'] = casos_pagina
    return data


def _paginar(filas: list, page: int, page_size: int) -> dict:
    total = len(filas)
    ini = (page - 1) * page_size
    fin = ini + page_size
    return {
        'count': total,
        'page': page,
        'page_size': page_size,
        'next': page + 1 if fin < total else None,
        'previous': page - 1 if page > 1 else None,
        'results': filas[ini:fin],
    }


def _movimiento_json(mov: CobroTaller) -> dict:
    return {
        'id': str(mov.id),
        'ancla_tipo': mov.ancla_tipo,
        'ancla_id': mov.ancla_id,
        'componente': mov.componente,
        'origen': mov.origen,
        'ref_externa': mov.ref_externa,
        'tipo': mov.tipo,
        'estado': mov.estado,
        'monto_clp': int(mov.monto_clp),
        'moneda': mov.moneda,
        'contabiliza_clp': bool(mov.contabiliza_clp),
        'monto_origen': str(mov.monto_origen) if mov.monto_origen is not None else None,
        'fecha_efectiva': mov.fecha_efectiva.isoformat(),
        'fecha_local': mov.fecha_local.isoformat(),
        'movimiento_origen_id': str(mov.movimiento_origen_id) if mov.movimiento_origen_id else None,
        'motivo': mov.motivo or '',
    }


def _efecto_contable(mov: CobroTaller) -> bool:
    return (
        mov.estado == CobroTaller.ESTADO_CONFIRMADO
        and mov.contabiliza_clp
        and int(mov.monto_clp) > 0
    )


def _canonizar_anclas_batch(taller, vistos: list[tuple[str, str]]) -> dict[tuple[str, str], tuple[str, str] | None]:
    """Build canonical ancla map in memory without DB calls per row.
    
    Returns dict: (ancla_tipo, ancla_id) -> (canonical_tipo, canonical_id) or None if invalid.
    Solicitud→Oferta mapping applied in memory after batch fetch.
    """
    # Group by type
    citas_set = set()
    solicitudes_set = set()
    ofertas_set = set()
    
    for ancla_tipo, ancla_id in vistos:
        if ancla_tipo == CobroTaller.ANCLA_CITA:
            citas_set.add(_ancla_id(ancla_id))
        elif ancla_tipo == CobroTaller.ANCLA_SOLICITUD:
            solicitudes_set.add(_ancla_id(ancla_id))
        elif ancla_tipo == CobroTaller.ANCLA_OFERTA:
            ofertas_set.add(_ancla_id(ancla_id))
    
    mapa = {}
    
    # Citas: already taller-scoped from movements, just verify existence
    if citas_set:
        citas_existentes = set(
            str(pk) for pk in CitaAgendaPersonal.objects.filter(
                pk__in=citas_set, taller=taller
            ).values_list('pk', flat=True)
        )
        for ancla_tipo, ancla_id in vistos:
            if ancla_tipo == CobroTaller.ANCLA_CITA:
                aid = _ancla_id(ancla_id)
                if aid in citas_existentes:
                    mapa[(ancla_tipo, ancla_id)] = (CobroTaller.ANCLA_CITA, aid)
                else:
                    mapa[(ancla_tipo, ancla_id)] = None
    
    # Solicitudes: batch fetch with oferta relation, canonize to oferta if exists
    if solicitudes_set:
        solicitudes = SolicitudServicio.objects.filter(
            pk__in=solicitudes_set, taller=taller
        ).select_related('oferta_proveedor')
        
        for sol in solicitudes:
            sol_id = str(sol.pk)
            # Apply canonizar logic: if has oferta from this taller, use oferta
            if sol.oferta_proveedor_id and sol.oferta_proveedor.proveedor_id == taller.usuario_id:
                mapa[(CobroTaller.ANCLA_SOLICITUD, sol_id)] = (
                    CobroTaller.ANCLA_OFERTA, str(sol.oferta_proveedor_id)
                )
            else:
                mapa[(CobroTaller.ANCLA_SOLICITUD, sol_id)] = (
                    CobroTaller.ANCLA_SOLICITUD, sol_id
                )
        
        # Mark missing solicitudes
        for ancla_tipo, ancla_id in vistos:
            if ancla_tipo == CobroTaller.ANCLA_SOLICITUD:
                if (ancla_tipo, ancla_id) not in mapa:
                    mapa[(ancla_tipo, ancla_id)] = None
    
    # Ofertas: verify they belong to this taller
    if ofertas_set:
        ofertas_existentes = set(
            str(pk) for pk in OfertaProveedor.objects.filter(
                pk__in=ofertas_set, proveedor=taller.usuario
            ).values_list('pk', flat=True)
        )
        for ancla_tipo, ancla_id in vistos:
            if ancla_tipo == CobroTaller.ANCLA_OFERTA:
                aid = _ancla_id(ancla_id)
                if aid in ofertas_existentes:
                    mapa[(ancla_tipo, ancla_id)] = (CobroTaller.ANCLA_OFERTA, aid)
                else:
                    mapa[(ancla_tipo, ancla_id)] = None
    
    return mapa


def _explicar_exigible_batch(taller, vistos: list[tuple[str, str]], mapa_canon: dict) -> dict[tuple[str, str], dict]:
    """Batch fetch exigible for multiple anclas using pre-built canonical map."""
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
        resolver_obligacion_cotizacion,
    )
    
    resultado = {}
    
    # Group canonical anclas by type
    citas_ids = set()
    ofertas_ids = set()
    
    for ancla_tipo, ancla_id in vistos:
        canon = mapa_canon.get((ancla_tipo, ancla_id))
        if canon is None:
            resultado[(ancla_tipo, ancla_id)] = _exigible_vacio('ancla_ajena')
            continue
        
        canon_tipo, canon_id = canon
        if canon_tipo == CobroTaller.ANCLA_CITA:
            citas_ids.add(canon_id)
        elif canon_tipo == CobroTaller.ANCLA_OFERTA:
            ofertas_ids.add(canon_id)
        else:
            resultado[(ancla_tipo, ancla_id)] = _exigible_vacio('sin_aceptacion')
    
    # Batch fetch citas with related cotizaciones
    citas_dict = {}
    extras_por_cita = {}
    if citas_ids:
        citas = CitaAgendaPersonal.objects.filter(
            pk__in=citas_ids, taller=taller
        ).select_related('cotizacion_canal_origen')
        citas_dict = {str(c.pk): c for c in citas}
        
        # Fetch adicionales for all citas at once
        extras = CotizacionCanal.objects.filter(
            cita_origen_id__in=citas_ids,
            estado='aceptada',
            es_cotizacion_adicional=True,
        ).exclude(ejecucion_adicional='nueva_fecha')
        for extra in extras:
            cita_id = str(extra.cita_origen_id)
            if cita_id not in extras_por_cita:
                extras_por_cita[cita_id] = []
            extras_por_cita[cita_id].append(extra)
    
    # Process citas
    for ancla_tipo, ancla_id in vistos:
        if (ancla_tipo, ancla_id) in resultado:
            continue
        
        canon = mapa_canon.get((ancla_tipo, ancla_id))
        if canon is None:
            continue
        
        canon_tipo, canon_id = canon
        if canon_tipo != CobroTaller.ANCLA_CITA:
            continue
        
        cita = citas_dict.get(canon_id)
        if cita is None:
            resultado[(ancla_tipo, ancla_id)] = _exigible_vacio('ancla_ajena')
            continue
        
        cotizaciones = []
        principal = getattr(cita, 'cotizacion_canal_origen', None)
        if principal is not None and principal.estado == 'aceptada':
            cotizaciones.append(principal)
        cotizaciones.extend(extras_por_cita.get(canon_id, []))
        
        if not cotizaciones:
            resultado[(ancla_tipo, ancla_id)] = _exigible_vacio('sin_aceptacion')
            continue
        
        total = 0
        fuentes = []
        for cot in cotizaciones:
            info = resolver_obligacion_cotizacion(cot)
            if not info['obligacion_conocida']:
                resultado[(ancla_tipo, ancla_id)] = _exigible_vacio(
                    info['obligacion_fuente'], info['obligacion_faltantes']
                )
                break
            total += int(info['obligacion_clp'])
            fuentes.append(info['obligacion_fuente'])
        else:
            fuente = fuentes[0] if len(set(fuentes)) == 1 else 'mixta'
            resultado[(ancla_tipo, ancla_id)] = {
                'monto_exigible_clp': total,
                'exigible_conocido': True,
                'exigible_fuente': fuente,
                'exigible_faltantes': [],
            }
    
    # Batch fetch ofertas
    ofertas_dict = {}
    if ofertas_ids:
        ofertas = OfertaProveedor.objects.filter(
            pk__in=ofertas_ids, proveedor=taller.usuario
        )
        ofertas_dict = {str(o.pk): o for o in ofertas}
    
    # Process ofertas
    for ancla_tipo, ancla_id in vistos:
        if (ancla_tipo, ancla_id) in resultado:
            continue
        
        canon = mapa_canon.get((ancla_tipo, ancla_id))
        if canon is None:
            continue
        
        canon_tipo, canon_id = canon
        if canon_tipo != CobroTaller.ANCLA_OFERTA:
            continue
        
        oferta = ofertas_dict.get(canon_id)
        resultado[(ancla_tipo, ancla_id)] = _exigible_oferta(oferta)
    
    return resultado


def _costos_vigentes_batch(taller, vistos: list[tuple[str, str]], mapa_canon: dict) -> dict[tuple[str, str], dict]:
    """Batch fetch costos for multiple anclas using pre-built canonical map."""
    # Collect unique canonical anclas
    anclas_canon = set()
    for ancla_tipo, ancla_id in vistos:
        canon = mapa_canon.get((ancla_tipo, ancla_id))
        if canon is not None:
            anclas_canon.add(canon)
    
    # Fetch all costos at once
    from django.db.models import Q
    filtro = Q()
    for ancla_tipo_canon, ancla_id_canon in anclas_canon:
        filtro |= Q(ancla_tipo=ancla_tipo_canon, ancla_id=ancla_id_canon)
    
    costos = CostoTaller.objects.filter(
        filtro,
        taller=taller,
        vigente=True,
    ) if anclas_canon else []
    
    # Group by ancla
    costos_por_ancla: dict[tuple[str, str], list] = {}
    for costo in costos:
        key = (costo.ancla_tipo, costo.ancla_id)
        if key not in costos_por_ancla:
            costos_por_ancla[key] = []
        costos_por_ancla[key].append(costo)
    
    # Calculate for each ancla
    resultado = {}
    for ancla_tipo_orig, ancla_id_orig in vistos:
        ancla_canon = mapa_canon.get((ancla_tipo_orig, ancla_id_orig))
        if ancla_canon is None:
            resultado[(ancla_tipo_orig, ancla_id_orig)] = {
                'costo_registrado_clp': None,
                'costo_estimado_clp': None,
            }
            continue
        
        filas = costos_por_ancla.get(ancla_canon, [])
        registrado = 0
        estimado = 0
        hay_reg = False
        hay_est = False
        for fila in filas:
            if fila.tipo == CostoTaller.TIPO_REGISTRADO:
                registrado += int(fila.monto_clp)
                hay_reg = True
            elif fila.tipo == CostoTaller.TIPO_ESTIMADO:
                estimado += int(fila.monto_clp)
                hay_est = True
        
        resultado[(ancla_tipo_orig, ancla_id_orig)] = {
            'costo_registrado_clp': registrado if hay_reg else None,
            'costo_estimado_clp': estimado if hay_est else None,
        }
    
    return resultado


def _margenes_caso_from_costos(*, costos: dict, exigible, neto) -> dict:
    """`margen_real_clp` es caja cobrada menos costo registrado, no la obligación."""
    reg = costos['costo_registrado_clp']
    est = costos['costo_estimado_clp']
    faltantes = []
    if reg is None:
        faltantes.append('costo_registrado')
    if neto is None:
        faltantes.append('neto_no_confirmado')
    if exigible is None:
        faltantes.append('exigible_desconocido')
    resultado = (neto - reg) if neto is not None and reg is not None else None
    contratado = (exigible - reg) if exigible is not None and reg is not None else None
    estimado = (exigible - est) if exigible is not None and est is not None else None
    return {
        'costo_registrado_clp': reg,
        'costo_estimado_clp': est,
        'resultado_caja_clp': resultado,
        'margen_real_clp': resultado,
        'margen_contratado_clp': contratado,
        'margen_estimado_clp': estimado,
        'margen_faltantes': faltantes,
    }


def _casos_periodo(taller, movimientos, *, ver_costos: bool) -> list[dict]:
    vistos: list[tuple[str, str]] = []
    for mov in movimientos:
        clave = (mov.ancla_tipo, mov.ancla_id)
        if clave not in vistos:
            vistos.append(clave)
    
    # Batch 1: Fetch ALL-TIME cobros per ancla (not just period) grouped by type
    # Critical: neto_acumulado_clp must be all-time for the case, not period-filtered
    anclas_por_tipo: dict[str, list[str]] = {}
    for ancla_tipo, ancla_id in vistos:
        if ancla_tipo not in anclas_por_tipo:
            anclas_por_tipo[ancla_tipo] = []
        anclas_por_tipo[ancla_tipo].append(ancla_id)
    
    # One query per ancla type with ancla_id__in (3 queries max: cita, solicitud, oferta)
    cobros_por_ancla: dict[tuple[str, str], list] = {}
    for ancla_tipo, ids in anclas_por_tipo.items():
        cobros = CobroTaller.objects.filter(
            taller=taller,
            ancla_tipo=ancla_tipo,
            ancla_id__in=ids,
        )
        for cobro in cobros:
            key = (cobro.ancla_tipo, cobro.ancla_id)
            if key not in cobros_por_ancla:
                cobros_por_ancla[key] = []
            cobros_por_ancla[key].append(cobro)
    
    # Batch 2: Build canonical ancla map once (no DB calls per row)
    mapa_canon = _canonizar_anclas_batch(taller, vistos)
    
    # Batch 3: Prefetch exigible data (citas, ofertas, cotizaciones) using canonical map
    exigibles = _explicar_exigible_batch(taller, vistos, mapa_canon)
    
    # Batch 4: Prefetch costos if ver_costos, reusing canonical map
    costos_batch = {}
    if ver_costos:
        costos_batch = _costos_vigentes_batch(taller, vistos, mapa_canon)
    
    salida = []
    for ancla_tipo, ancla_id in vistos:
        key = (ancla_tipo, ancla_id)
        todos = cobros_por_ancla.get(key, [])
        contables = [m for m in todos if _efecto_contable(m)]
        sin_efecto = [m for m in todos if not _efecto_contable(m)]
        hay = bool(contables)
        _b, _r, neto = _neto_movimientos(contables) if hay else (0, 0, 0)
        
        explicacion = exigibles.get(key, _exigible_vacio('sin_aceptacion'))
        exigible = explicacion['monto_exigible_clp']
        conocido = explicacion['exigible_conocido']
        saldo = None
        saldo_conocido = False
        if hay and conocido and exigible is not None:
            saldo = exigible - neto
            saldo_conocido = True
        neto_out = neto if hay else None
        pendientes = sum(
            int(m.monto_clp)
            for m in sin_efecto
            if m.estado == CobroTaller.ESTADO_PENDIENTE and m.contabiliza_clp
        )
        fila = {
            'ancla_tipo': ancla_tipo,
            'ancla_id': ancla_id,
            'monto_exigible_clp': exigible if conocido else None,
            'exigible_conocido': bool(conocido),
            'exigible_fuente': explicacion['exigible_fuente'],
            'exigible_faltantes': explicacion['exigible_faltantes'],
            'neto_acumulado_clp': neto_out,
            'saldo_clp': saldo,
            'saldo_conocido': saldo_conocido,
            'estado_pago': _estado_caso(neto_out, exigible if conocido else None, saldo_conocido),
            'filas_sin_efecto_contable': len(sin_efecto),
            'pendientes_no_sumados_clp': pendientes,
        }
        if ver_costos:
            costos = costos_batch.get(key, {'costo_registrado_clp': None, 'costo_estimado_clp': None})
            fila.update(_margenes_caso_from_costos(
                costos=costos,
                exigible=exigible if conocido else None,
                neto=neto_out,
            ))
        salida.append(fila)
    return salida


def _margenes_caso(taller, ancla_tipo, ancla_id, *, exigible, neto) -> dict:
    """`margen_real_clp` es caja cobrada menos costo registrado, no la obligación."""
    costos = costos_vigentes(taller, ancla_tipo, ancla_id)
    reg = costos['costo_registrado_clp']
    est = costos['costo_estimado_clp']
    faltantes = []
    if reg is None:
        faltantes.append('costo_registrado')
    if neto is None:
        faltantes.append('neto_no_confirmado')
    if exigible is None:
        faltantes.append('exigible_desconocido')
    resultado = (neto - reg) if neto is not None and reg is not None else None
    contratado = (exigible - reg) if exigible is not None and reg is not None else None
    estimado = (exigible - est) if exigible is not None and est is not None else None
    return {
        'costo_registrado_clp': reg,
        'costo_estimado_clp': est,
        'resultado_caja_clp': resultado,
        'margen_real_clp': resultado,
        'margen_contratado_clp': contratado,
        'margen_estimado_clp': estimado,
        'margen_faltantes': faltantes,
    }


def _estado_caso(neto, exigible, saldo_conocido: bool) -> str:
    if neto is None:
        return 'unknown'
    if not saldo_conocido or exigible is None:
        return 'parcial' if neto > 0 else 'unknown'
    if neto <= 0:
        return 'pendiente' if exigible > 0 else 'pagado'
    if neto < exigible:
        return 'parcial'
    return 'pagado'


def _anclas_mecanico(miembro) -> dict[str, list[str]]:
    citas = [
        str(pk) for pk in CitaAgendaPersonal.objects.filter(
            miembro_taller=miembro,
        ).values_list('pk', flat=True)
    ]
    solicitudes = [
        str(pk) for pk in SolicitudServicio.objects.filter(
            mecanico_asignado=miembro,
        ).values_list('pk', flat=True)
    ]
    ofertas = [
        str(pk) for pk in OfertaProveedor.objects.filter(
            miembro_taller_asignado=miembro,
        ).values_list('pk', flat=True)
    ]
    out = {}
    if citas:
        out[CobroTaller.ANCLA_CITA] = citas
    if solicitudes:
        out[CobroTaller.ANCLA_SOLICITUD] = solicitudes
    if ofertas:
        out[CobroTaller.ANCLA_OFERTA] = ofertas
    return out


def _contar_legacy(taller, *, miembro=None, rol=None) -> int:
    """Flags o anotaciones con evidencia incompleta o sin fila de libro. No inserta."""
    total = 0
    ofertas = OfertaProveedor.objects.filter(proveedor=taller.usuario).filter(
        models_q_pagado(),
    )
    if rol == 'mecanico' and miembro is not None:
        ofertas = ofertas.filter(miembro_taller_asignado=miembro)
    elif rol == 'mecanico':
        ofertas = ofertas.none()
    ids = [str(pk) for pk in ofertas.values_list('pk', flat=True)]
    if ids:
        con_libro = set(CobroTaller.objects.filter(
            taller=taller,
            ancla_tipo=CobroTaller.ANCLA_OFERTA,
            ancla_id__in=ids,
            estado=CobroTaller.ESTADO_CONFIRMADO,
            contabiliza_clp=True,
            monto_clp__gt=0,
        ).values_list('ancla_id', flat=True))
        total += sum(1 for pk in ids if pk not in con_libro)
    
    # Batch citas check: one query with ancla_id__in instead of exists() per cita
    citas = CitaAgendaPersonal.objects.filter(taller=taller, cobro_estado='anotado')
    if rol == 'mecanico' and miembro is not None:
        citas = citas.filter(miembro_taller=miembro)
    elif rol == 'mecanico':
        citas = citas.none()
    
    cita_ids = [str(cita.id) for cita in citas.only('id')]
    if cita_ids:
        # One query to check which citas have libro entries
        con_libro_citas = set(CobroTaller.objects.filter(
            taller=taller,
            ancla_tipo=CobroTaller.ANCLA_CITA,
            ancla_id__in=cita_ids,
            estado=CobroTaller.ESTADO_CONFIRMADO,
            contabiliza_clp=True,
            monto_clp__gt=0,
        ).values_list('ancla_id', flat=True))
        total += sum(1 for cita_id in cita_ids if cita_id not in con_libro_citas)
    
    return total


def models_q_pagado():
    from django.db.models import Q
    return Q(estado_pago_repuestos='pagado') | Q(estado_pago_servicio='pagado')


IDENTIDAD_VACIA = {
    'cliente_nombre': None,
    'vehiculo_patente': None,
    'folio': None,
}


def _texto_real(valor) -> str | None:
    texto = str(valor or '').strip()
    return texto or None


def _nombre_cliente(cliente) -> str | None:
    if cliente is None:
        return None
    partes = [
        texto for texto in (
            _texto_real(getattr(cliente, 'nombre', None)),
            _texto_real(getattr(cliente, 'apellido', None)),
        ) if texto
    ]
    return ' '.join(partes) or None


def _pks_enteros(ids: set[str]) -> list[int]:
    salida = []
    for raw in ids:
        try:
            salida.append(int(raw))
        except (TypeError, ValueError):
            continue
    return salida


def _pks_uuid(ids: set[str]) -> list[uuid.UUID]:
    salida = []
    for raw in ids:
        try:
            salida.append(uuid.UUID(str(raw)))
        except (TypeError, ValueError, AttributeError):
            continue
    return salida


def _identidad_cita(cita, taller_id) -> dict:
    from django.core.exceptions import ObjectDoesNotExist

    detalle = None
    try:
        detalle = cita.detalle
    except ObjectDoesNotExist:
        detalle = None
    cot = cita.cotizacion_canal_origen if cita.cotizacion_canal_origen_id else None
    if cot is not None and cot.taller_id != taller_id:
        cot = None
    nombre = _texto_real(getattr(detalle, 'cliente_nombre', None))
    patente = _texto_real(getattr(detalle, 'vehiculo_patente', None))
    folio = _texto_real(cita.numero_publico)
    if cot is not None:
        nombre = nombre or _texto_real(cot.cliente_nombre)
        patente = patente or _texto_real(cot.vehiculo_patente)
        folio = folio or _texto_real(cot.numero_publico)
    return {
        'cliente_nombre': nombre,
        'vehiculo_patente': patente,
        'folio': folio,
    }


def _identidad_solicitud(orden) -> dict:
    return {
        'cliente_nombre': _nombre_cliente(orden.cliente),
        'vehiculo_patente': _texto_real(getattr(orden.vehiculo, 'patente', None)),
        'folio': _texto_real(orden.numero_publico),
    }


def identidades_anclas(taller, pares) -> dict[tuple[str, str], dict]:
    """Nombre, patente y folio ya guardados. Una consulta por tipo, solo de este taller.

    No crea folios ni rellena un nombre ausente. Una ancla de otro taller queda en null.
    """
    grupos = {
        CobroTaller.ANCLA_CITA: set(),
        CobroTaller.ANCLA_SOLICITUD: set(),
        CobroTaller.ANCLA_OFERTA: set(),
    }
    for tipo, ancla_id in pares:
        if tipo in grupos and ancla_id:
            grupos[tipo].add(str(ancla_id))
    salida: dict[tuple[str, str], dict] = {}
    cita_ids = _pks_enteros(grupos[CobroTaller.ANCLA_CITA])
    if cita_ids:
        citas = CitaAgendaPersonal.objects.filter(
            taller=taller, pk__in=cita_ids,
        ).select_related('detalle', 'cotizacion_canal_origen')
        for cita in citas:
            salida[(CobroTaller.ANCLA_CITA, str(cita.pk))] = _identidad_cita(cita, taller.id)
    solicitud_ids = _pks_enteros(grupos[CobroTaller.ANCLA_SOLICITUD])
    if solicitud_ids:
        ordenes = SolicitudServicio.objects.filter(
            taller=taller, pk__in=solicitud_ids,
        ).select_related('cliente', 'vehiculo')
        for orden in ordenes:
            salida[(CobroTaller.ANCLA_SOLICITUD, str(orden.pk))] = _identidad_solicitud(orden)
    oferta_ids = _pks_uuid(grupos[CobroTaller.ANCLA_OFERTA])
    if oferta_ids:
        ofertas = OfertaProveedor.objects.filter(
            proveedor_id=taller.usuario_id, pk__in=oferta_ids,
        ).select_related('solicitud__cliente', 'solicitud__vehiculo')
        ordenes_oferta = SolicitudServicio.objects.filter(
            taller=taller, oferta_proveedor_id__in=oferta_ids,
        ).select_related('cliente', 'vehiculo').order_by('pk')
        por_oferta: dict[str, SolicitudServicio] = {}
        for orden in ordenes_oferta:
            clave = str(orden.oferta_proveedor_id)
            previa = por_oferta.get(clave)
            if previa is None or (
                not _texto_real(previa.numero_publico) and _texto_real(orden.numero_publico)
            ):
                por_oferta[clave] = orden
        for oferta in ofertas:
            orden = por_oferta.get(str(oferta.pk))
            publica = oferta.solicitud
            nombre = _nombre_cliente(orden.cliente) if orden is not None else None
            patente = (
                _texto_real(getattr(orden.vehiculo, 'patente', None))
                if orden is not None else None
            )
            folio = _texto_real(orden.numero_publico) if orden is not None else None
            if publica is not None:
                nombre = nombre or _nombre_cliente(publica.cliente)
                patente = patente or _texto_real(getattr(publica.vehiculo, 'patente', None))
            salida[(CobroTaller.ANCLA_OFERTA, str(oferta.pk))] = {
                'cliente_nombre': nombre,
                'vehiculo_patente': patente,
                'folio': folio,
            }
    return salida


def _anotar_identidad(taller, movimientos: list[dict], casos: list[dict]) -> None:
    pares = [(fila['ancla_tipo'], fila['ancla_id']) for fila in movimientos]
    pares.extend((fila['ancla_tipo'], fila['ancla_id']) for fila in casos)
    encontradas = identidades_anclas(taller, pares)
    for fila in [*movimientos, *casos]:
        ident = encontradas.get((fila['ancla_tipo'], str(fila['ancla_id'])), IDENTIDAD_VACIA)
        fila['cliente_nombre'] = ident['cliente_nombre']
        fila['vehiculo_patente'] = ident['vehiculo_patente']
        fila['folio'] = ident['folio']


def movimiento_response(mov: CobroTaller, *, creado: bool) -> dict:
    data = _movimiento_json(mov)
    data['creado'] = creado
    _anotar_identidad(mov.taller, [data], [])
    return data
