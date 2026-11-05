"""Lectura de evidencia de pago. No escribe el libro ni pisa flags guardados."""
from __future__ import annotations

from mecanimovilapp.apps.ordenes.models_caja import CobroTaller
from mecanimovilapp.apps.ordenes.services.caja_taller import (
    SALIDAS,
    CajaError,
    _efecto_contable,
    _neto_movimientos,
    canonizar_ancla,
    explicar_exigible,
)

UI_SIN_INFORMACION = 'pago_sin_informacion'
UI_PAGADO_OFERTA = 'pagado_segun_oferta'
UI_PAGADO_MP = 'pagado_segun_mp'
UI_PAGADO_ANOTACION = 'pagado_segun_anotacion'
UI_PAGADO = 'pagado'
UI_PARCIAL = 'parcial'
UI_POR_COBRAR = 'por_cobrar'
UI_REEMBOLSADO = 'reembolsado'


def proyeccion_ancla(*, taller, ancla_tipo: str, ancla_id: str, legacy: dict | None = None) -> dict:
    legacy = legacy or {}
    try:
        ancla_tipo, ancla_id = canonizar_ancla(taller, ancla_tipo, str(ancla_id))
    except CajaError:
        return _vacio()['pago_provenance']
    movimientos = list(CobroTaller.objects.filter(
        taller=taller, ancla_tipo=ancla_tipo, ancla_id=ancla_id,
    ))
    contables = [m for m in movimientos if _efecto_contable(m)]
    sin_efecto = [m for m in movimientos if not _efecto_contable(m)]
    hay = bool(contables)
    _bruto, _reembolsos, neto_num = _neto_movimientos(contables) if hay else (0, 0, 0)
    neto = neto_num if hay else None
    explicacion = explicar_exigible(taller, ancla_tipo, ancla_id)
    exigible = explicacion['monto_exigible_clp']
    exigible_conocido = explicacion['exigible_conocido']
    flags = legacy.get('flags')
    mp_status = legacy.get('mp_status')
    anotacion = legacy.get('anotacion')
    flag_pagado = bool(flags) and (
        (flags or {}).get('repuestos') == 'pagado'
        or (flags or {}).get('servicio') == 'pagado'
    )
    mp_reverso = mp_status in {'refunded', 'charged_back'}
    mp_approved = mp_status == 'approved'
    anot_completa = _anotacion_completa(anotacion)
    contabilizable = bool(contables)
    hubo_reverso = any(m.tipo in SALIDAS for m in contables)
    pendientes = sum(
        int(m.monto_clp)
        for m in sin_efecto
        if m.estado == CobroTaller.ESTADO_PENDIENTE and m.contabiliza_clp
    )

    if mp_reverso:
        ui = UI_REEMBOLSADO
        dominio = 'mercadopago_reverso'
    elif hay and exigible_conocido and exigible is not None and neto is not None and neto >= exigible and neto > 0:
        ui = UI_PAGADO
        dominio = 'movimiento'
    elif hay and exigible_conocido and exigible is not None and neto is not None and 0 < neto < exigible:
        ui = UI_PARCIAL
        dominio = 'movimiento'
    elif hay and neto is not None and neto > 0 and not exigible_conocido:
        ui = UI_PARCIAL
        dominio = 'movimiento'
    elif hay and hubo_reverso and neto is not None and neto <= 0:
        ui = UI_REEMBOLSADO
        dominio = 'movimiento'
    elif hay and exigible_conocido and exigible is not None and neto is not None and neto < exigible:
        ui = UI_POR_COBRAR
        dominio = 'movimiento'
    elif mp_approved:
        ui = UI_PAGADO_MP
        dominio = 'mercadopago'
    elif flag_pagado:
        ui = UI_PAGADO_OFERTA
        dominio = 'oferta'
    elif anot_completa:
        ui = UI_PAGADO_ANOTACION
        dominio = 'anotacion'
    else:
        ui = UI_SIN_INFORMACION
        dominio = 'desconocido'

    saldo = None
    saldo_conocido = False
    evidencia_legacy_sin_libro = (not hay) and (flag_pagado or mp_approved or anot_completa or mp_reverso)
    if hay and exigible_conocido and exigible is not None and not evidencia_legacy_sin_libro:
        saldo = exigible - neto
        saldo_conocido = True

    return {
        'estado_cobro_ui': ui,
        'pago_contabilizable': contabilizable,
        'dominio': dominio,
        'monto_exigible_clp': exigible if exigible_conocido else None,
        'exigible_conocido': bool(exigible_conocido),
        'exigible_fuente': explicacion['exigible_fuente'],
        'exigible_faltantes': explicacion['exigible_faltantes'],
        'neto_acumulado_clp': neto if hay else None,
        'saldo_clp': saldo,
        'saldo_conocido': saldo_conocido,
        'filas_sin_efecto_contable': len(sin_efecto),
        'pendientes_no_sumados_clp': pendientes,
        'aviso_libro': 'sin_efecto_contable' if sin_efecto and not hay else None,
        'flags_oferta': flags,
        'anotacion': anotacion,
        'mercadopago_status': mp_status,
    }


def _anotacion_completa(anotacion) -> bool:
    if not isinstance(anotacion, dict):
        return False
    if anotacion.get('estado') != 'anotado':
        return False
    return anotacion.get('monto_clp') is not None and bool(anotacion.get('fecha'))


def legacy_de_oferta(oferta) -> dict:
    if oferta is None:
        return {}
    from mecanimovilapp.apps.pagos.models import Pago

    pagos = list(Pago.objects.filter(
        external_reference__startswith=f'oferta_{oferta.id}_',
    ).order_by('-fecha_creacion'))
    mp_status = None
    for pago in pagos:
        if pago.status in {'refunded', 'charged_back'}:
            mp_status = pago.status
            break
    if mp_status is None and pagos:
        mp_status = pagos[0].status
    return {
        'flags': {
            'repuestos': oferta.estado_pago_repuestos,
            'servicio': oferta.estado_pago_servicio,
        },
        'mp_status': mp_status,
    }


def legacy_de_anotacion(obj) -> dict:
    monto = getattr(obj, 'cobro_monto_clp', None)
    fecha = getattr(obj, 'cobro_anotado_en', None)
    return {
        'anotacion': {
            'estado': getattr(obj, 'cobro_estado', None),
            'monto_clp': int(monto) if monto is not None else None,
            'fecha': fecha.isoformat() if fecha else None,
            'medio': getattr(obj, 'cobro_medio', '') or '',
        },
    }


def campos_pago_solicitud(solicitud) -> dict:
    """Campos aditivos. Omite flags que la orden no tiene, no los manda en null."""
    taller = getattr(solicitud, 'taller', None)
    if taller is None:
        return _vacio()
    oferta = getattr(solicitud, 'oferta_proveedor', None)
    legacy = {}
    legacy.update(legacy_de_anotacion(solicitud))
    if oferta is not None:
        legacy.update(legacy_de_oferta(oferta))
        ancla_tipo = CobroTaller.ANCLA_OFERTA
        ancla_id = str(oferta.id)
    else:
        ancla_tipo = CobroTaller.ANCLA_SOLICITUD
        ancla_id = str(solicitud.id)
    proy = proyeccion_ancla(
        taller=taller, ancla_tipo=ancla_tipo, ancla_id=ancla_id, legacy=legacy,
    )
    data = {
        'pago_provenance': proy,
        'estado_cobro_ui': proy['estado_cobro_ui'],
        'pago_contabilizable': proy['pago_contabilizable'],
    }
    if oferta is not None:
        data['estado_pago_repuestos'] = oferta.estado_pago_repuestos
        data['estado_pago_servicio'] = oferta.estado_pago_servicio
    return data


def _vacio() -> dict:
    return {
        'pago_provenance': {
            'estado_cobro_ui': UI_SIN_INFORMACION,
            'pago_contabilizable': False,
            'dominio': 'desconocido',
            'neto_acumulado_clp': None,
            'saldo_clp': None,
            'saldo_conocido': False,
        },
        'estado_cobro_ui': UI_SIN_INFORMACION,
        'pago_contabilizable': False,
    }


def anotar_filas_pago(filas: list[dict], taller) -> None:
    if taller is None or not filas:
        return
    for fila in filas:
        ancla = _ancla_de_fila(fila)
        if ancla is None:
            fila['estado_cobro_ui'] = UI_SIN_INFORMACION
            fila['pago_contabilizable'] = False
            fila['pago_provenance'] = {
                'estado_cobro_ui': UI_SIN_INFORMACION,
                'dominio': 'desconocido',
                'neto_acumulado_clp': None,
                'saldo_clp': None,
                'saldo_conocido': False,
                'pago_contabilizable': False,
            }
            continue
        tipo, ancla_id, legacy = ancla
        proy = proyeccion_ancla(
            taller=taller, ancla_tipo=tipo, ancla_id=ancla_id, legacy=legacy,
        )
        fila['pago_provenance'] = proy
        fila['estado_cobro_ui'] = proy['estado_cobro_ui']
        fila['pago_contabilizable'] = proy['pago_contabilizable']
        flags = legacy.get('flags') or {}
        if flags.get('repuestos'):
            fila['estado_pago_repuestos'] = flags['repuestos']
        if flags.get('servicio'):
            fila['estado_pago_servicio'] = flags['servicio']


def _ancla_de_fila(fila: dict):
    oferta_id = fila.get('oferta_id')
    if oferta_id:
        from mecanimovilapp.apps.ordenes.models import OfertaProveedor
        oferta = OfertaProveedor.objects.filter(pk=oferta_id).first()
        legacy = legacy_de_oferta(oferta) if oferta is not None else {}
        return CobroTaller.ANCLA_OFERTA, str(oferta_id), legacy
    orden_id = fila.get('orden_id')
    if orden_id:
        from mecanimovilapp.apps.ordenes.models import SolicitudServicio
        solicitud = SolicitudServicio.objects.filter(pk=orden_id).select_related('oferta_proveedor').first()
        if solicitud is None:
            return None
        legacy = legacy_de_anotacion(solicitud)
        if solicitud.oferta_proveedor_id:
            legacy.update(legacy_de_oferta(solicitud.oferta_proveedor))
            return CobroTaller.ANCLA_OFERTA, str(solicitud.oferta_proveedor_id), legacy
        return CobroTaller.ANCLA_SOLICITUD, str(orden_id), legacy
    cita_id = fila.get('cita_id')
    if cita_id:
        from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal
        cita = CitaAgendaPersonal.objects.filter(pk=cita_id).first()
        legacy = legacy_de_anotacion(cita) if cita is not None else {}
        return CobroTaller.ANCLA_CITA, str(cita_id), legacy
    return None
