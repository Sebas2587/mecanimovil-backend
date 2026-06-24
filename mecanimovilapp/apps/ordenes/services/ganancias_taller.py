"""
Ganancias del taller / mecánico a domicilio para el dashboard proveedor.

Incluye órdenes Mecanimovil completadas (cualquier método de pago) y citas de
agenda personal cerradas con precio de referencia.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import Sum

from mecanimovilapp.apps.ordenes.services.mecanico_kpis import (
    _rango_mes,
    _ventana_periodo_q,
)


def _delta_pct(actual: float, anterior: float) -> float | None:
    if anterior == 0:
        return 100.0 if actual > 0 else 0.0
    return round((actual - anterior) / anterior * 100.0, 1)


def _ganancias_en_rango(user, fecha_desde: date, fecha_hasta: date) -> dict[str, int]:
    from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, SolicitudServicio

    taller = getattr(user, 'taller', None)
    mecanico = getattr(user, 'mecanico_domicilio', None)
    if not taller and not mecanico:
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
    if taller:
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
    if taller:
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
