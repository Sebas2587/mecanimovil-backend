"""
Motor 2: proyección de valor (hoy, +1 año, +3 años).
"""
from __future__ import annotations

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


def project_values(
    valor_hoy: int,
    vehiculo,
    confianza: str,
    tipo_vehiculo: str | None = None,
) -> tuple[list[dict], Decimal, str]:
    """
    Retorna proyección [{anio_offset, valor, tendencia}], tasa usada, fuente_tasa.
    """
    if valor_hoy <= 0:
        return [], DEFAULT_DEPRECIATION_PCT, 'default'

    year_bucket = vehiculo.year or timezone.now().year
    tasa = _empirical_rate_from_segment(
        vehiculo.marca_id,
        vehiculo.modelo_id,
        year_bucket,
    )
    fuente = 'empirica_segmento'
    if tasa is None:
        tasa = _empirical_rate_from_tasacion(vehiculo.id)
        fuente = 'empirica_tasacion'
    if tasa is None:
        tasa = _get_curva_pct(tipo_vehiculo)
        fuente = 'curva_categoria'

    rate_f = float(tasa) / 100.0
    proyeccion = []
    for offset in (0, 1, 3):
        if offset == 0:
            val = valor_hoy
        else:
            val = int(valor_hoy * ((1 - rate_f) ** offset))
        tendencia = 'estable'
        if tasa > Decimal('1'):
            tendencia = 'depreciacion'
        elif tasa < Decimal('-1'):
            tendencia = 'apreciacion'
        proyeccion.append({
            'anio_offset': offset,
            'valor': max(0, val),
            'tendencia': tendencia,
            'label': 'Hoy' if offset == 0 else f'En {offset} año{"s" if offset > 1 else ""}',
        })

    if confianza == 'estimado' and fuente.startswith('empirica'):
        fuente = 'curva_categoria'

    return proyeccion, tasa, fuente
