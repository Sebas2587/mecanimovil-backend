"""
Ganancias del taller / mecánico a domicilio para el dashboard proveedor.

Incluye órdenes Mecanimovil completadas (cualquier método de pago) y citas de
agenda personal cerradas con precio de referencia.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Sum
from django.utils import timezone

from mecanimovilapp.apps.ordenes.services.mecanico_kpis import (
    _rango_mes,
    _ventana_periodo_q,
)


def _delta_pct(actual: float, anterior: float) -> float | None:
    if anterior == 0:
        return 100.0 if actual > 0 else 0.0
    return round((actual - anterior) / anterior * 100.0, 1)


def _resolve_proveedor_scope(user, mecanico_id: int | None = None):
    """Devuelve (taller, mecanico_domicilio, miembro_taller_opcional)."""
    from django.core.exceptions import ObjectDoesNotExist

    from mecanimovilapp.apps.usuarios.models import MecanicoDomicilio, MiembroTaller
    from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller

    taller, _, _ = resolver_contexto_taller(user)
    mecanico = None
    if taller is None:
        try:
            mecanico = MecanicoDomicilio.objects.get(usuario=user)
        except MecanicoDomicilio.DoesNotExist:
            mecanico = None
        except ObjectDoesNotExist:
            mecanico = None

    miembro = None
    if mecanico_id is not None and taller:
        miembro = MiembroTaller.objects.filter(
            id=mecanico_id,
            taller=taller,
            rol='mecanico',
        ).first()
    return taller, mecanico, miembro


def _precio_cita_personal(cita) -> float:
    from django.core.exceptions import ObjectDoesNotExist

    try:
        detalle = cita.detalle
    except ObjectDoesNotExist:
        return 0.0
    return float(detalle.precio_referencia or Decimal('0'))


def _fecha_bucket_orden(orden, fecha_desde: date, fecha_hasta: date) -> date | None:
    """
    Día del bucket alineado con _ventana_periodo_q: prioriza fecha_servicio
    dentro del rango; si no, fecha de solicitud dentro del rango.
    """
    if orden.fecha_servicio and fecha_desde <= orden.fecha_servicio <= fecha_hasta:
        return orden.fecha_servicio
    if orden.fecha_hora_solicitud:
        d = timezone.localtime(orden.fecha_hora_solicitud).date()
        if fecha_desde <= d <= fecha_hasta:
            return d
    return None


def _acumular_actividad_diaria(
    user,
    fecha_desde: date,
    fecha_hasta: date,
    *,
    mecanico_id: int | None = None,
) -> tuple[dict[date, int], dict[date, int], dict[date, int], dict[date, int]]:
    """
    Mapas día → CLP y conteo de cierres por canal (Mecanimovil / agenda personal).
    Returns: (mkt_clp, agenda_clp, mkt_ordenes, agenda_ordenes)
    """
    from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, SolicitudServicio

    taller, mecanico, miembro = _resolve_proveedor_scope(user, mecanico_id)
    mkt_clp: dict[date, int] = defaultdict(int)
    agenda_clp: dict[date, int] = defaultdict(int)
    mkt_n: dict[date, int] = defaultdict(int)
    agenda_n: dict[date, int] = defaultdict(int)

    empty = (mkt_clp, agenda_clp, mkt_n, agenda_n)
    if not taller and not mecanico:
        return empty
    if mecanico_id is not None and taller and miembro is None:
        return empty

    orden_qs = SolicitudServicio.objects.filter(estado='completado').filter(
        _ventana_periodo_q(fecha_desde, fecha_hasta)
    )
    if miembro:
        orden_qs = orden_qs.filter(mecanico_asignado=miembro)
    elif taller:
        orden_qs = orden_qs.filter(taller=taller)
    else:
        orden_qs = orden_qs.filter(mecanico=mecanico)

    for orden in orden_qs.only('fecha_servicio', 'fecha_hora_solicitud', 'total').iterator(
        chunk_size=500
    ):
        bucket = _fecha_bucket_orden(orden, fecha_desde, fecha_hasta)
        if bucket is None:
            continue
        mkt_clp[bucket] += int(round(float(orden.total or Decimal('0'))))
        mkt_n[bucket] += 1

    personal_qs = CitaAgendaPersonal.objects.filter(
        estado='cerrada',
        fecha_servicio__gte=fecha_desde,
        fecha_servicio__lte=fecha_hasta,
    )
    if miembro:
        personal_qs = personal_qs.filter(miembro_taller=miembro)
    elif taller:
        personal_qs = personal_qs.filter(taller=taller)
    else:
        personal_qs = personal_qs.filter(mecanico=mecanico)

    for cita in personal_qs.select_related('detalle').iterator(chunk_size=500):
        bucket = cita.fecha_servicio
        if not bucket:
            continue
        agenda_clp[bucket] += int(round(_precio_cita_personal(cita)))
        agenda_n[bucket] += 1

    return mkt_clp, agenda_clp, mkt_n, agenda_n


def _acumular_ganancias_diarias(
    user,
    fecha_desde: date,
    fecha_hasta: date,
    *,
    mecanico_id: int | None = None,
) -> tuple[dict[date, int], dict[date, int]]:
    """Compat: solo CLP por canal."""
    mkt_clp, agenda_clp, _, _ = _acumular_actividad_diaria(
        user, fecha_desde, fecha_hasta, mecanico_id=mecanico_id
    )
    return mkt_clp, agenda_clp


def _rango_serie(
    granularidad: str,
    *,
    dias: int | None = None,
) -> tuple[date, date]:
    hoy = timezone.localdate()
    g = (granularidad or 'dia').lower()
    if dias is not None:
        d = max(1, min(int(dias), 365))
        return hoy - timedelta(days=d - 1), hoy
    if g == 'mes':
        year = hoy.year
        month = hoy.month - 5
        while month <= 0:
            month += 12
            year -= 1
        return date(year, month, 1), hoy
    if g == 'semana':
        return hoy - timedelta(days=7 * 11 + 6), hoy
    mes_ini, _ = _rango_mes(0)
    return mes_ini, hoy


def _etiqueta_dia(d: date, idx: int, total: int) -> str:
    if total <= 10 or d.day == 1 or d.day % 5 == 0 or idx == total - 1:
        return str(d.day)
    return ''


def _etiqueta_semana(inicio: date, fin: date) -> str:
    if inicio.month == fin.month:
        return f'{inicio.day}-{fin.day}'
    return f'{inicio.day}/{inicio.month}'


def _etiqueta_mes(d: date) -> str:
    raw = d.strftime('%b')
    return raw[:1].upper() + raw[1:].lower()


def _punto_extremo(puntos: list[dict[str, Any]], clave: str) -> dict[str, Any] | None:
    if not puntos:
        return None
    return max(puntos, key=lambda p: p[clave])


def _punto_minimo(puntos: list[dict[str, Any]], clave: str) -> dict[str, Any] | None:
    if not puntos:
        return None
    return min(puntos, key=lambda p: p[clave])


def compute_ganancias_taller_serie(
    user,
    *,
    granularidad: str = 'dia',
    mecanico_id: int | None = None,
    metrica: str = 'ingresos',
    dias: int | None = None,
) -> dict[str, Any]:
    """
    Serie temporal Mecanimovil vs agenda personal.

    granularidad: dia | semana | mes (ventana por defecto, o `dias` si se indica).
    metrica: ingresos (CLP) | ordenes (cierres completados/cerradas).
    """
    g = (granularidad or 'dia').lower()
    if g not in ('dia', 'semana', 'mes'):
        g = 'dia'
    m = (metrica or 'ingresos').lower()
    if m not in ('ingresos', 'ordenes'):
        m = 'ingresos'

    fecha_desde, fecha_hasta = _rango_serie(g, dias=dias)
    mkt_clp, agenda_clp, mkt_n, agenda_n = _acumular_actividad_diaria(
        user,
        fecha_desde,
        fecha_hasta,
        mecanico_id=mecanico_id,
    )
    mkt_map = mkt_n if m == 'ordenes' else mkt_clp
    agenda_map = agenda_n if m == 'ordenes' else agenda_clp

    puntos: list[dict[str, Any]] = []

    if g == 'dia':
        cursor = fecha_desde
        idx = 0
        total_days = (fecha_hasta - fecha_desde).days + 1
        while cursor <= fecha_hasta:
            mv = mkt_map.get(cursor, 0)
            av = agenda_map.get(cursor, 0)
            puntos.append(
                {
                    'clave': cursor.isoformat(),
                    'etiqueta': _etiqueta_dia(cursor, idx, total_days),
                    'mecanimovil': mv,
                    'agenda_personal': av,
                    'total': mv + av,
                }
            )
            cursor += timedelta(days=1)
            idx += 1
    elif g == 'semana':
        cursor = fecha_desde
        while cursor <= fecha_hasta:
            fin_sem = min(cursor + timedelta(days=6), fecha_hasta)
            span = (fin_sem - cursor).days + 1
            mv = sum(mkt_map.get(cursor + timedelta(days=i), 0) for i in range(span))
            av = sum(agenda_map.get(cursor + timedelta(days=i), 0) for i in range(span))
            puntos.append(
                {
                    'clave': cursor.isoformat(),
                    'etiqueta': _etiqueta_semana(cursor, fin_sem),
                    'mecanimovil': mv,
                    'agenda_personal': av,
                    'total': mv + av,
                }
            )
            cursor = fin_sem + timedelta(days=1)
    else:
        cursor = date(fecha_desde.year, fecha_desde.month, 1)
        while cursor <= fecha_hasta:
            if cursor.month == 12:
                next_month = date(cursor.year + 1, 1, 1)
            else:
                next_month = date(cursor.year, cursor.month + 1, 1)
            fin_mes = min(next_month - timedelta(days=1), fecha_hasta)
            mv = sum(v for d, v in mkt_map.items() if cursor <= d <= fin_mes)
            av = sum(v for d, v in agenda_map.items() if cursor <= d <= fin_mes)
            puntos.append(
                {
                    'clave': cursor.isoformat(),
                    'etiqueta': _etiqueta_mes(cursor),
                    'mecanimovil': mv,
                    'agenda_personal': av,
                    'total': mv + av,
                }
            )
            cursor = next_month

    totales = _ganancias_en_rango(
        user,
        fecha_desde,
        fecha_hasta,
        mecanico_id=mecanico_id,
    )
    mayor = _punto_extremo(puntos, 'total')
    menor = _punto_minimo(puntos, 'total')

    return {
        'granularidad': g,
        'metrica': m,
        'desde': fecha_desde.isoformat(),
        'hasta': fecha_hasta.isoformat(),
        'mecanico_id': mecanico_id,
        'puntos': puntos,
        'totales_periodo': totales,
        'pico_mayor': mayor,
        'pico_menor': menor,
    }


def _ganancias_en_rango(
    user,
    fecha_desde: date,
    fecha_hasta: date,
    *,
    mecanico_id: int | None = None,
) -> dict[str, int]:
    from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, SolicitudServicio

    taller, mecanico, miembro = _resolve_proveedor_scope(user, mecanico_id)
    if not taller and not mecanico:
        return {
            'ganancias_mecanimovil': 0,
            'ganancias_agenda_personal': 0,
            'ganancias_total': 0,
            'ordenes_mecanimovil': 0,
            'ordenes_agenda_personal': 0,
        }

    if mecanico_id is not None and taller and miembro is None:
        return {
            'ganancias_mecanimovil': 0,
            'ganancias_agenda_personal': 0,
            'ganancias_total': 0,
            'ordenes_mecanimovil': 0,
            'ordenes_agenda_personal': 0,
        }

    orden_qs = SolicitudServicio.objects.filter(estado='completado').filter(
        _ventana_periodo_q(fecha_desde, fecha_hasta)
    )
    if miembro:
        orden_qs = orden_qs.filter(mecanico_asignado=miembro)
    elif taller:
        orden_qs = orden_qs.filter(taller=taller)
    else:
        orden_qs = orden_qs.filter(mecanico=mecanico)

    mecanimovil = float(orden_qs.aggregate(s=Sum('total'))['s'] or Decimal('0'))
    n_mkt = orden_qs.count()

    personal_qs = CitaAgendaPersonal.objects.filter(
        estado='cerrada',
        fecha_servicio__gte=fecha_desde,
        fecha_servicio__lte=fecha_hasta,
    )
    if miembro:
        personal_qs = personal_qs.filter(miembro_taller=miembro)
    elif taller:
        personal_qs = personal_qs.filter(taller=taller)
    else:
        personal_qs = personal_qs.filter(mecanico=mecanico)

    agenda = float(
        personal_qs.aggregate(s=Sum('detalle__precio_referencia'))['s'] or Decimal('0')
    )
    n_personal = personal_qs.count()

    total = mecanimovil + agenda
    return {
        'ganancias_mecanimovil': int(round(mecanimovil)),
        'ganancias_agenda_personal': int(round(agenda)),
        'ganancias_total': int(round(total)),
        'ordenes_mecanimovil': n_mkt,
        'ordenes_agenda_personal': n_personal,
    }


def compute_ganancias_taller_resumen(user) -> dict[str, Any]:
    """Ganancias mes actual vs mes anterior (calendario local)."""
    mes_act_ini, mes_act_fin = _rango_mes(0)
    mes_ant_ini, mes_ant_fin = _rango_mes(1)

    actual = _ganancias_en_rango(user, mes_act_ini, mes_act_fin)
    anterior = _ganancias_en_rango(user, mes_ant_ini, mes_ant_fin)

    total_actual = actual['ganancias_total']
    total_anterior = anterior['ganancias_total']

    return {
        **actual,
        'ganancias_mes_anterior': total_anterior,
        'ganancias_mecanimovil_mes_anterior': anterior['ganancias_mecanimovil'],
        'ganancias_agenda_personal_mes_anterior': anterior['ganancias_agenda_personal'],
        'delta_pct_mes': _delta_pct(float(total_actual), float(total_anterior)),
        'mes_desde': mes_act_ini.isoformat(),
        'mes_hasta': mes_act_fin.isoformat(),
    }
