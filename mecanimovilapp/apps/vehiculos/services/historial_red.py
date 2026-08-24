"""Historial clínico de una patente en la red Mecanimovil (talleres)."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Q, Value
from django.db.models.functions import Replace, Upper
from django.utils import timezone

LIMITE_EVENTOS = 40
LIMITE_PROMPT = 10
MESES_VENTANA_RANGO = 24
MIN_MUESTRAS_RANGO = 3
MIN_TALLERES_RANGO = 2


def normalizar_patente(raw: str) -> str:
    return ''.join(c for c in (raw or '') if c.isalnum()).upper()


def patente_consulta_valida(raw: str) -> bool:
    compact = normalizar_patente(raw)
    return 5 <= len(compact) <= 8


def _patente_compact_expr(field: str):
    expr = Upper(field)
    for ch in ('-', ' ', '.'):
        expr = Replace(expr, Value(ch), Value(''))
    return expr


def _monto_clp(val) -> int | None:
    if val is None:
        return None
    if isinstance(val, Decimal):
        return int(val)
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def _fecha_iso(val) -> str | None:
    if val is None:
        return None
    if hasattr(val, 'isoformat'):
        return val.isoformat()
    return str(val)


def _formatear_clp(valor: int) -> str:
    return f'${int(valor or 0):,}'.replace(',', '.')


def _clave_marca(raw: str) -> str:
    return (raw or '').strip().lower()


def _clave_servicio(raw: str) -> str | None:
    nombre = (raw or '').strip()
    if not nombre or ',' in nombre:
        return None
    from mecanimovilapp.apps.ordenes.services.catalogo_pricing import (
        _sin_sufijo_modalidad,
        normalizar_nombre_servicio,
    )

    clave = normalizar_nombre_servicio(_sin_sufijo_modalidad(nombre)).strip()
    return clave or None


def _percentile(sorted_vals: list[int], p: float) -> int:
    if not sorted_vals:
        return 0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return int(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f))


def _proveedor_key(taller_id: int | None, mecanico_id: int | None = None) -> str | None:
    if taller_id:
        return f't:{taller_id}'
    if mecanico_id:
        return f'm:{mecanico_id}'
    return None


def _evento(
    *,
    fecha,
    taller_nombre: str,
    taller_es_propio: bool,
    servicio_nombre: str,
    kilometraje: int | None,
    monto_clp: int | None,
    fuente: str,
    evento_id: str,
    marca: str = '',
    servicio_clave: str = '',
) -> dict[str, Any]:
    return {
        'fecha': _fecha_iso(fecha),
        'taller_nombre': (taller_nombre or '').strip() or 'Taller de la red',
        'taller_es_propio': bool(taller_es_propio),
        'servicio_nombre': (servicio_nombre or '').strip() or 'Servicio',
        'kilometraje': kilometraje,
        'monto_clp': monto_clp if taller_es_propio else None,
        'rango_mercado_clp': None,
        'fuente': fuente,
        'evento_id': evento_id,
        '_marca': (marca or '').strip(),
        '_servicio_clave': (servicio_clave or servicio_nombre or '').strip(),
    }


def _filas_ordenes(patente_norm: str, taller_id: int | None) -> list[dict[str, Any]]:
    from mecanimovilapp.apps.ordenes.models import LineaServicio, SolicitudServicio

    qs = (
        SolicitudServicio.objects.filter(estado='completado', vehiculo__isnull=False)
        .select_related('taller', 'vehiculo', 'vehiculo__marca', 'vehiculo__modelo')
        .annotate(_pat_c=_patente_compact_expr('vehiculo__patente'))
        .filter(_pat_c=patente_norm)
        .order_by('-fecha_servicio', '-fecha_hora_solicitud')[:LIMITE_EVENTOS]
    )
    eventos: list[dict[str, Any]] = []
    for orden in qs:
        propio = bool(taller_id and orden.taller_id == taller_id)
        nombres = list(
            LineaServicio.objects.filter(solicitud=orden)
            .select_related('oferta_servicio__servicio')
            .values_list('oferta_servicio__servicio__nombre', flat=True)
        )
        nombres_ok = [n for n in nombres if n]
        servicio = ', '.join(nombres_ok) or (orden.notas_cliente or 'Servicio')[:120]
        km = getattr(orden.vehiculo, 'kilometraje', None)
        marca = getattr(getattr(orden.vehiculo, 'marca', None), 'nombre', '') or ''
        eventos.append(
            _evento(
                fecha=orden.fecha_servicio or (
                    orden.fecha_hora_solicitud.date() if orden.fecha_hora_solicitud else None
                ),
                taller_nombre=getattr(orden.taller, 'nombre', '') or '',
                taller_es_propio=propio,
                servicio_nombre=servicio,
                kilometraje=int(km) if km else None,
                monto_clp=_monto_clp(orden.total),
                fuente='orden_plataforma',
                evento_id=f'orden:{orden.id}',
                marca=marca,
                servicio_clave=nombres_ok[0] if len(nombres_ok) == 1 else servicio,
            )
        )
    return eventos


def _filas_informes(patente_norm: str, taller_id: int | None) -> list[dict[str, Any]]:
    from mecanimovilapp.apps.checklists.models_informe import InformeServicioPublico

    qs = (
        InformeServicioPublico.objects.filter(estado__in=['FIRMADO', 'VEHICULO_RECLAMADO'])
        .select_related(
            'checklist_instance__cita_personal__taller',
            'checklist_instance__cita_personal__detalle',
        )
        .annotate(_pat_c=_patente_compact_expr('vehiculo_patente'))
        .filter(_pat_c=patente_norm)
        .order_by('-fecha_firma_cliente', '-generado_en')[:LIMITE_EVENTOS]
    )
    eventos: list[dict[str, Any]] = []
    for informe in qs:
        cita = getattr(getattr(informe, 'checklist_instance', None), 'cita_personal', None)
        taller = getattr(cita, 'taller', None) if cita else None
        propio = bool(taller_id and taller and taller.id == taller_id)
        det = getattr(cita, 'detalle', None) if cita else None
        servicio = (getattr(det, 'servicio_nombre', None) or '').strip()
        if not servicio:
            servicio = ((informe.resumen_ia or '').split('\n')[0] or 'Servicio')[:120]
        fecha = informe.fecha_firma_cliente or informe.generado_en
        monto = _monto_clp(getattr(det, 'precio_referencia', None)) if propio else None
        marca = (informe.vehiculo_marca or getattr(det, 'vehiculo_marca', '') or '') if det else (
            informe.vehiculo_marca or ''
        )
        eventos.append(
            _evento(
                fecha=fecha,
                taller_nombre=getattr(taller, 'nombre', '') or '',
                taller_es_propio=propio,
                servicio_nombre=servicio,
                kilometraje=informe.kilometraje_servicio,
                monto_clp=monto,
                fuente='informe',
                evento_id=f'informe:{informe.id}',
                marca=marca,
                servicio_clave=servicio,
            )
        )
    return eventos


def _filas_citas(patente_norm: str, taller_id: int | None) -> list[dict[str, Any]]:
    from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal

    qs = (
        CitaAgendaPersonal.objects.filter(estado__in=['activa', 'cerrada'])
        .filter(
            Q(checklist_instance__isnull=True)
            | Q(checklist_instance__informe_publico__isnull=True)
        )
        .select_related('detalle', 'taller')
        .annotate(_pat_c=_patente_compact_expr('detalle__vehiculo_patente'))
        .filter(_pat_c=patente_norm)
        .order_by('-fecha_servicio', '-fecha_creacion')[:LIMITE_EVENTOS]
    )
    eventos: list[dict[str, Any]] = []
    for cita in qs:
        if cita.estado == 'activa' and taller_id and cita.taller_id != taller_id:
            continue
        propio = bool(taller_id and cita.taller_id == taller_id)
        det = getattr(cita, 'detalle', None)
        if det is None:
            continue
        servicio = (det.descripcion or det.servicio_nombre or 'Servicio')[:120]
        eventos.append(
            _evento(
                fecha=cita.fecha_servicio or getattr(cita, 'fecha_creacion', None),
                taller_nombre=getattr(cita.taller, 'nombre', '') or '',
                taller_es_propio=propio,
                servicio_nombre=servicio,
                kilometraje=None,
                monto_clp=_monto_clp(det.precio_referencia),
                fuente='cita_personal',
                evento_id=f'cita:{cita.id}',
                marca=det.vehiculo_marca or '',
                servicio_clave=det.servicio_nombre or servicio,
            )
        )
    return eventos


def _agregar_muestra(
    buckets: dict[tuple[str, str], list[tuple[int, str]]],
    pares: set[tuple[str, str]],
    *,
    servicio_nombre: str,
    marca: str,
    monto: int | None,
    proveedor: str | None,
) -> None:
    if not proveedor or not monto or monto <= 0:
        return
    serv = _clave_servicio(servicio_nombre)
    marca_n = _clave_marca(marca)
    if not serv or not marca_n:
        return
    clave = (serv, marca_n)
    if clave not in pares:
        return
    buckets[clave].append((monto, proveedor))


def _calcular_rangos_pares(pares: set[tuple[str, str]]) -> dict[tuple[str, str], dict[str, int]]:
    if not pares:
        return {}

    from mecanimovilapp.apps.checklists.models_informe import InformeServicioPublico
    from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, LineaServicio

    desde = timezone.now() - timedelta(days=MESES_VENTANA_RANGO * 30)
    desde_fecha = desde.date()
    buckets: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    citas_muestreadas: set[int] = set()

    lineas = (
        LineaServicio.objects.filter(solicitud__estado='completado')
        .filter(
            Q(solicitud__fecha_hora_solicitud__gte=desde)
            | Q(solicitud__fecha_servicio__gte=desde_fecha)
        )
        .select_related(
            'solicitud',
            'solicitud__vehiculo__marca',
            'oferta_servicio__servicio',
        )
        .iterator()
    )
    for linea in lineas:
        orden = linea.solicitud
        veh = getattr(orden, 'vehiculo', None)
        marca = getattr(getattr(veh, 'marca', None), 'nombre', '') if veh else ''
        servicio = ''
        oferta = getattr(linea, 'oferta_servicio', None)
        if oferta and getattr(oferta, 'servicio', None):
            servicio = oferta.servicio.nombre or ''
        monto = _monto_clp(linea.precio_final) or _monto_clp(linea.precio_unitario)
        _agregar_muestra(
            buckets,
            pares,
            servicio_nombre=servicio,
            marca=marca or '',
            monto=monto,
            proveedor=_proveedor_key(orden.taller_id, getattr(orden, 'mecanico_id', None)),
        )

    citas = (
        CitaAgendaPersonal.objects.filter(estado='cerrada')
        .filter(Q(fecha_servicio__gte=desde_fecha) | Q(cerrada_en__gte=desde))
        .select_related('detalle', 'taller', 'mecanico')
        .iterator()
    )
    for cita in citas:
        det = getattr(cita, 'detalle', None)
        if det is None:
            continue
        citas_muestreadas.add(cita.id)
        _agregar_muestra(
            buckets,
            pares,
            servicio_nombre=det.servicio_nombre or '',
            marca=det.vehiculo_marca or '',
            monto=_monto_clp(det.precio_referencia),
            proveedor=_proveedor_key(cita.taller_id, cita.mecanico_id),
        )

    informes = (
        InformeServicioPublico.objects.filter(estado__in=['FIRMADO', 'VEHICULO_RECLAMADO'])
        .filter(Q(fecha_firma_cliente__gte=desde) | Q(generado_en__gte=desde))
        .select_related(
            'checklist_instance__cita_personal__detalle',
            'checklist_instance__cita_personal__taller',
        )
        .iterator()
    )
    for informe in informes:
        cita = getattr(getattr(informe, 'checklist_instance', None), 'cita_personal', None)
        if cita is not None and cita.id in citas_muestreadas:
            continue
        det = getattr(cita, 'detalle', None) if cita else None
        servicio = (getattr(det, 'servicio_nombre', None) or '').strip() if det else ''
        marca = informe.vehiculo_marca or (getattr(det, 'vehiculo_marca', '') if det else '')
        monto = _monto_clp(getattr(det, 'precio_referencia', None)) if det else None
        taller = getattr(cita, 'taller', None) if cita else None
        mecanico_id = getattr(cita, 'mecanico_id', None) if cita else None
        _agregar_muestra(
            buckets,
            pares,
            servicio_nombre=servicio,
            marca=marca or '',
            monto=monto,
            proveedor=_proveedor_key(getattr(taller, 'id', None), mecanico_id),
        )

    rangos: dict[tuple[str, str], dict[str, int]] = {}
    for clave, muestras in buckets.items():
        if len(muestras) < MIN_MUESTRAS_RANGO:
            continue
        talleres = {prov for _monto, prov in muestras}
        if len(talleres) < MIN_TALLERES_RANGO:
            continue
        precios = sorted(monto for monto, _prov in muestras)
        p25 = _percentile(precios, 0.25)
        p75 = _percentile(precios, 0.75)
        if p25 == p75:
            continue
        lo, hi = (p25, p75) if p25 <= p75 else (p75, p25)
        rangos[clave] = {'min': lo, 'max': hi, 'muestras': len(muestras)}
    return rangos


def _adjuntar_rangos_mercado(eventos: list[dict[str, Any]], marca_fallback: str = '') -> None:
    claves: list[tuple[str | None, str]] = []
    pares: set[tuple[str, str]] = set()
    for evento in eventos:
        marca = _clave_marca(evento.pop('_marca', None) or marca_fallback)
        servicio = _clave_servicio(
            evento.pop('_servicio_clave', None) or evento.get('servicio_nombre') or ''
        )
        claves.append((servicio, marca))
        if not evento.get('taller_es_propio') and servicio and marca:
            pares.add((servicio, marca))

    rangos = _calcular_rangos_pares(pares)
    for evento, (servicio, marca) in zip(eventos, claves):
        if evento.get('taller_es_propio') or not servicio or not marca:
            evento['rango_mercado_clp'] = None
        else:
            evento['rango_mercado_clp'] = rangos.get((servicio, marca))


def consultar_historial_red(
    *,
    patente: str,
    taller_id: int | None,
    limite: int = LIMITE_EVENTOS,
) -> dict[str, Any]:
    patente_norm = normalizar_patente(patente)
    payload: dict[str, Any] = {
        'patente': patente_norm,
        'vehiculo': None,
        'eventos': [],
    }
    if not patente_consulta_valida(patente_norm):
        payload['error'] = 'patente_invalida'
        return payload

    from mecanimovilapp.apps.vehiculos.models import Vehiculo

    veh = (
        Vehiculo.objects.select_related('marca', 'modelo')
        .annotate(_pat_c=_patente_compact_expr('patente'))
        .filter(_pat_c=patente_norm)
        .first()
    )
    if veh:
        payload['vehiculo'] = {
            'marca': getattr(veh.marca, 'nombre', '') or '',
            'modelo': getattr(veh.modelo, 'nombre', '') or '',
            'anio': veh.year,
        }

    eventos: list[dict[str, Any]] = []
    eventos.extend(_filas_ordenes(patente_norm, taller_id))
    eventos.extend(_filas_informes(patente_norm, taller_id))
    eventos.extend(_filas_citas(patente_norm, taller_id))
    eventos.sort(key=lambda e: e.get('fecha') or '', reverse=True)
    cap = max(1, min(int(limite or LIMITE_EVENTOS), LIMITE_EVENTOS))
    eventos = eventos[:cap]
    marca_fallback = ((payload.get('vehiculo') or {}) or {}).get('marca') or ''
    _adjuntar_rangos_mercado(eventos, marca_fallback=marca_fallback)
    payload['eventos'] = eventos
    return payload


def texto_historial_red_para_prompt(eventos: list[dict[str, Any]], *, limite: int = LIMITE_PROMPT) -> str:
    if not eventos:
        return ''
    lineas: list[str] = []
    for evento in eventos[:limite]:
        propio = (
            ' (tu taller)'
            if evento.get('taller_es_propio')
            else f" ({evento.get('taller_nombre') or 'otro taller'})"
        )
        km = f", {evento['kilometraje']} km" if evento.get('kilometraje') else ''
        monto = ''
        if evento.get('taller_es_propio') and evento.get('monto_clp') is not None:
            monto = f" — {_formatear_clp(int(evento['monto_clp']))}"
        elif not evento.get('taller_es_propio'):
            rango = evento.get('rango_mercado_clp') or {}
            if rango.get('min') is not None and rango.get('max') is not None:
                monto = (
                    f" — en la red {_formatear_clp(int(rango['min']))}"
                    f"–{_formatear_clp(int(rango['max']))}"
                )
        fecha = (evento.get('fecha') or '')[:10]
        lineas.append(f"- {fecha}: {evento.get('servicio_nombre') or 'Servicio'}{propio}{km}{monto}")
    return (
        'Historial de la red para esta patente (contexto clínico). '
        'NO agregues estos servicios al pedido ni a la cotización salvo que el cliente los pida ahora:\n'
        + '\n'.join(lineas)
    )
