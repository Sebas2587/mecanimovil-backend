"""
Motor 2: proyección de valor (hoy, +1 año, +3 años).
"""
from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Avg
from django.utils import timezone

from mecanimovilapp.apps.valoracion_mercado.models import (
    CurvaDepreciacionSegmento,
    SegmentoValorHistorial,
    TasacionHistorial,
)

logger = logging.getLogger(__name__)

DEFAULT_DEPRECIATION_PCT = Decimal('7.0')


def _get_curva_pct(tipo_vehiculo: str | None) -> Decimal:
    key = (tipo_vehiculo or 'LIVIANO').upper().strip()
    for alias, canonical in (
        ('SUV', 'SUV'),
        ('SEDAN', 'SEDAN'),
        ('CAMIONETA', 'CAMIONETA'),
        ('HATCHBACK', 'HATCHBACK'),
        ('LIVIANO', 'LIVIANO'),
    ):
        if alias in key:
            key = canonical
            break
    row = CurvaDepreciacionSegmento.objects.filter(tipo_vehiculo__iexact=key, activo=True).first()
    if row:
        return Decimal(str(row.tasa_anual_pct))
    fallback = CurvaDepreciacionSegmento.objects.filter(tipo_vehiculo__iexact='LIVIANO', activo=True).first()
    if fallback:
        return Decimal(str(fallback.tasa_anual_pct))
    return DEFAULT_DEPRECIATION_PCT


def _empirical_rate_from_segment(marca_id: int, modelo_id: int, year_bucket: int) -> Decimal | None:
    """Regresión log-lineal sobre snapshots de segmento (≥3 puntos)."""
    qs = (
        SegmentoValorHistorial.objects.filter(
            marca_id=marca_id,
            modelo_id=modelo_id,
            year_bucket=year_bucket,
            precio_mediana__gt=0,
        )
        .order_by('fecha_snapshot')
        .values_list('fecha_snapshot', 'precio_mediana')[:12]
    )
    points = list(qs)
    if len(points) < 3:
        return None
    t0 = points[0][0]
    xs = []
    ys = []
    for d, price in points:
        days = (d - t0).days or 1
        xs.append(days / 365.25)
        ys.append(math.log(max(price, 1)))
    n = len(xs)
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_xx = sum(x * x for x in xs)
    denom = n * sum_xx - sum_x * sum_x
    if abs(denom) < 1e-9:
        return None
    slope = (n * sum_xy - sum_x * sum_y) / denom
    # slope negativo => depreciación
    annual_pct = (1 - math.exp(slope)) * 100
    return Decimal(str(round(max(-30, min(30, annual_pct)), 2)))


def _empirical_rate_from_tasacion(vehiculo_id: int) -> Decimal | None:
    qs = (
        TasacionHistorial.objects.filter(vehiculo_id=vehiculo_id, precio_mercado_promedio__gt=0)
        .order_by('fecha')
        .values_list('fecha', 'precio_mercado_promedio')[:12]
    )
    points = list(qs)
    if len(points) < 3:
        return None
    t0 = points[0][0]
    xs, ys = [], []
    for d, price in points:
        days = (d - t0).days or 1
        xs.append(days / 365.25)
        ys.append(math.log(max(price, 1)))
    n = len(xs)
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_xx = sum(x * x for x in xs)
    denom = n * sum_xx - sum_x * sum_x
    if abs(denom) < 1e-9:
        return None
    slope = (n * sum_xy - sum_x * sum_y) / denom
    annual_pct = (1 - math.exp(slope)) * 100
    return Decimal(str(round(max(-30, min(30, annual_pct)), 2)))


def _health_score(vehiculo) -> float:
    if hasattr(vehiculo, 'get_health_score'):
        try:
            return float(vehiculo.get_health_score() or 70)
        except Exception:
            pass
    if hasattr(vehiculo, 'salud_general') and vehiculo.salud_general is not None:
        return float(vehiculo.salud_general)
    if hasattr(vehiculo, 'estados_salud'):
        ultimo = vehiculo.estados_salud.order_by('-fecha_calculo').first()
        if ultimo and ultimo.salud_general_porcentaje is not None:
            return float(ultimo.salud_general_porcentaje)
    return 70.0


def _apply_health_protection(tasa: Decimal, health: float) -> Decimal:
    """
    Salud alta frena la depreciación (protege valor).
    Salud baja la acelera. Factor ~0.55x (salud 100) a ~1.6x (salud 0).
    """
    h = max(0.0, min(100.0, health))
    factor = Decimal(str(round(1.6 - (h / 100.0) * 1.05, 4)))
    return Decimal(str(round(float(tasa) * float(factor), 2)))


def _health_score_at_horizon(vehiculo, meses_futuro: float) -> tuple[float, str]:
    """
    Salud proyectada a `meses_futuro` meses, simulando hacia adelante el
    historial real de servicios del vehículo (ver `salud_trayectoria.py`).

    Si no hay componentes de salud registrados o algo falla, cae a la salud
    ESTÁTICA de hoy (comportamiento previo) — nunca rompe el cálculo de valor.
    """
    try:
        from mecanimovilapp.apps.vehiculos.services.salud_trayectoria import (
            proyectar_salud_general,
        )
        salud, fuente = proyectar_salud_general(vehiculo, meses_futuro)
        if salud is not None:
            return float(salud), fuente
    except Exception:
        logger.exception('proyeccion_engine: fallo proyectando salud a futuro, uso salud estática')
    return _health_score(vehiculo), 'salud_actual_estatica'


def project_values(
    valor_hoy: int,
    vehiculo,
    confianza: str,
    tipo_vehiculo: str | None = None,
) -> tuple[list[dict], Decimal, str]:
    """
    Retorna proyección de valor en el tiempo + tasa de hoy + fuente_tasa.

    Horizontes: Hoy, +1, +2, +3 años. Cada año se compone con la tasa
    protegida por la salud PROYECTADA a ese horizonte (historial real de
    servicios vía `salud_trayectoria`, sklearn cuando hay modelo). Así un
    auto con mantenciones al día no deprecia igual que uno abandonado —
    aunque ambos partan con la misma salud hoy.

    Fórmula por año t (compuesta, no un único rate a 3 años):
        V(t) = V(t-1) * (1 - rate(salud_en_t))
    """
    if valor_hoy <= 0:
        return [], DEFAULT_DEPRECIATION_PCT, 'default'

    year_bucket = vehiculo.year or timezone.now().year
    tasa_base = _empirical_rate_from_segment(
        vehiculo.marca_id,
        vehiculo.modelo_id,
        year_bucket,
    )
    fuente_base = 'empirica_segmento'
    if tasa_base is None:
        tasa_base = _empirical_rate_from_tasacion(vehiculo.id)
        fuente_base = 'empirica_tasacion'
    if tasa_base is None:
        tasa_base = _get_curva_pct(tipo_vehiculo)
        fuente_base = 'curva_categoria'

    health_now = _health_score(vehiculo)
    tasa_now = _apply_health_protection(tasa_base, health_now)
    fuente = f'{fuente_base}+salud'
    if confianza == 'estimado' and fuente_base.startswith('empirica'):
        fuente = 'curva_categoria+salud'

    proyeccion = []
    valor_corrido = valor_hoy
    for offset in (0, 1, 2, 3):
        if offset == 0:
            health_offset = health_now
            fuente_salud_offset = 'actual'
            tasa_offset = tasa_now
            val = valor_hoy
        else:
            health_offset, fuente_salud_offset = _health_score_at_horizon(
                vehiculo, offset * 12
            )
            tasa_offset = _apply_health_protection(tasa_base, health_offset)
            rate_f = float(tasa_offset) / 100.0
            # Compuesto año a año: el deterioro (o protección) de este año
            # parte del valor ya proyectado del año anterior.
            valor_corrido = int(valor_corrido * (1 - rate_f))
            val = valor_corrido

        tendencia = 'estable'
        if tasa_offset > Decimal('1'):
            tendencia = 'depreciacion'
        elif tasa_offset < Decimal('-1'):
            tendencia = 'apreciacion'

        if offset == 0:
            label = 'Hoy'
        elif offset == 1:
            label = 'En 1 año'
        else:
            label = f'En {offset} años'

        proyeccion.append({
            'anio_offset': offset,
            'valor': max(0, val),
            'tendencia': tendencia,
            'label': label,
            'salud_aplicada': health_offset,
            'salud_fuente': fuente_salud_offset,
            'tasa_aplicada_pct': float(tasa_offset),
            'delta_vs_hoy_pct': (
                0.0
                if offset == 0 or valor_hoy <= 0
                else round(((val - valor_hoy) / valor_hoy) * 100, 1)
            ),
        })

    return proyeccion, tasa_now, fuente
