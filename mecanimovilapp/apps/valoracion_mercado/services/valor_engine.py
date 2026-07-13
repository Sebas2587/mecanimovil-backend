"""
Motor 1: valor real estimado hoy (blend GetAPI + comparables externos).
"""
from __future__ import annotations

import math
import statistics
from decimal import Decimal
from typing import Any

from mecanimovilapp.apps.marketplace.valuation_engine import calculate_suggested_price


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


def _km_adjust_factor(vehicle_km: int, comparable_km: int | None) -> float:
    if not vehicle_km or not comparable_km or comparable_km <= 0:
        return 1.0
    ratio = vehicle_km / comparable_km
    if ratio < 0.7:
        return 1.03
    if ratio > 1.3:
        return 0.97
    return 1.0


def compute_valor_getapi_ajustado(vehiculo) -> int:
    precio_mercado = vehiculo.precio_mercado_promedio or 0
    if not precio_mercado:
        return 0
    return calculate_suggested_price(
        vehiculo,
        precio_mercado,
        vehiculo.tasacion_fiscal or 0,
    )


def compute_external_median_adjusted(vehiculo, comparables: list[dict]) -> tuple[int, list[int]]:
    """Mediana de precios externos ajustada por km del vehículo."""
    prices: list[int] = []
    for c in comparables:
        p = int(c.get('precio') or 0)
        if p <= 0:
            continue
        km = c.get('kilometraje')
        factor = _km_adjust_factor(vehiculo.kilometraje or 0, km)
        prices.append(int(p * factor))
    if not prices:
        return 0, []
    prices.sort()
    return int(statistics.median(prices)), prices


def compute_valor_real(
    vehiculo,
    comparables: list[dict],
    segmento_snapshot: dict | None,
) -> dict[str, Any]:
    """
    Retorna valor_real_hoy, rango min/max, confianza, histograma buckets, meta.
    """
    valor_getapi = compute_valor_getapi_ajustado(vehiculo)
    mediana_ext, price_list = compute_external_median_adjusted(vehiculo, comparables)
    n_comp = len(price_list)
    n_anuncios = (segmento_snapshot or {}).get('n_anuncios_activos', n_comp)
    n_semanas = (segmento_snapshot or {}).get('n_semanas_tracking', 0)

    w_externo = 0.0
    if n_anuncios >= 5 and mediana_ext > 0:
        w_externo = min(0.60, 0.10 + n_comp * 0.05)
    w_getapi = max(0.40, 1.0 - w_externo)

    if valor_getapi <= 0 and mediana_ext > 0:
        valor_real = mediana_ext
    elif valor_getapi > 0 and mediana_ext > 0:
        valor_real = int(w_getapi * valor_getapi + w_externo * mediana_ext)
    else:
        valor_real = valor_getapi or mediana_ext

    banda_min_api = vehiculo.precio_mercado_min or 0
    banda_max_api = vehiculo.precio_mercado_max or 0

    if price_list:
        p25 = _percentile(price_list, 0.25)
        p75 = _percentile(price_list, 0.75)
        rango_min = min(p25, banda_min_api) if banda_min_api else p25
        rango_max = max(p75, banda_max_api) if banda_max_api else p75
    else:
        rango_min = banda_min_api or (int(valor_real * 0.9) if valor_real else 0)
        rango_max = banda_max_api or (int(valor_real * 1.1) if valor_real else 0)

    # Sanear banda invertida o desfasada respecto al valor ajustado.
    if rango_min and rango_max and rango_min > rango_max:
        rango_min, rango_max = rango_max, rango_min
    if valor_real > 0:
        if not rango_min and not rango_max:
            rango_min = int(valor_real * 0.92)
            rango_max = int(valor_real * 1.08)
        elif valor_real < rango_min or (rango_max and valor_real > rango_max):
            half = max(int(valor_real * 0.06), int(abs((rango_max or valor_real) - (rango_min or valor_real)) / 2) or 1)
            rango_min = max(0, valor_real - half)
            rango_max = valor_real + half
    if rango_max and rango_min and rango_max <= rango_min:
        rango_max = rango_min + max(1, int((valor_real or rango_min) * 0.05))

    if n_comp >= 8 and n_semanas >= 3:
        confianza = 'alta'
    elif n_comp >= 1:
        confianza = 'media'
    else:
        confianza = 'estimado'

    histograma, histograma_origen = _build_histogram(price_list, rango_min, rango_max, valor_real)

    return {
        'valor_real_hoy': max(0, valor_real),
        'valor_real_rango_min': max(0, rango_min),
        'valor_real_rango_max': max(0, rango_max),
        'confianza': confianza,
        'valor_getapi_ajustado': valor_getapi,
        'mediana_externa': mediana_ext,
        'histograma': histograma,
        'histograma_origen': histograma_origen,
        'n_comparables': n_comp,
        'w_externo': round(w_externo, 2),
        'w_getapi': round(w_getapi, 2),
    }


def _build_histogram(
    prices: list[int],
    rango_min: int,
    rango_max: int,
    valor_usuario: int,
    buckets: int = 28,
) -> tuple[list[dict], str]:
    if prices:
        lo = min(prices)
        hi = max(prices)
        if hi <= lo:
            hi = lo + 1
        step = max(1, (hi - lo) // buckets)
        counts = [0] * buckets
        edges = [lo + i * step for i in range(buckets)] + [hi + step]
        for p in prices:
            idx = min(buckets - 1, (p - lo) // step)
            counts[idx] += 1
        max_count = max(counts) or 1
        out = []
        for i, c in enumerate(counts):
            edge_lo = edges[i]
            edge_hi = edges[i + 1]
            in_range = edge_hi >= rango_min and edge_lo <= rango_max
            out.append({
                'bucket_start': edge_lo,
                'bucket_end': edge_hi,
                'count': c,
                'normalized': round(c / max_count, 3),
                'in_range': in_range,
                'is_user_bucket': edge_lo <= valor_usuario < edge_hi if valor_usuario else False,
            })
        return out, 'mercado'

    synthetic = _build_synthetic_histogram(rango_min, rango_max, valor_usuario, buckets)
    return synthetic, 'estimado'


def _build_synthetic_histogram(
    rango_min: int,
    rango_max: int,
    valor_usuario: int,
    buckets: int = 28,
) -> list[dict]:
    """Curva tipo Airbnb cuando aún no hay comparables externos."""
    if valor_usuario <= 0:
        return []
    lo = rango_min or int(valor_usuario * 0.88)
    hi = rango_max or int(valor_usuario * 1.12)
    if lo > hi:
        lo, hi = hi, lo
    if valor_usuario and (valor_usuario < lo or valor_usuario > hi):
        half = max(int(valor_usuario * 0.06), int((hi - lo) / 2) or 1)
        lo = max(0, valor_usuario - half)
        hi = valor_usuario + half
    if hi <= lo:
        hi = lo + max(1, int(valor_usuario * 0.05))
    # Eje un poco más ancho para barras grises fuera del selection (Airbnb).
    pad = max(int((hi - lo) * 0.35), int(valor_usuario * 0.04) if valor_usuario else 1)
    axis_lo = max(0, lo - pad)
    axis_hi = hi + pad
    step = max(1, (axis_hi - axis_lo) // buckets)
    center = float(valor_usuario)
    sigma = max((axis_hi - axis_lo) / 5.0, step * 2)
    raw: list[tuple[int, int, float]] = []
    for i in range(buckets):
        edge_lo = axis_lo + i * step
        edge_hi = axis_hi if i == buckets - 1 else edge_lo + step
        mid = (edge_lo + edge_hi) / 2.0
        gaussian = math.exp(-0.5 * ((mid - center) / sigma) ** 2)
        raw.append((edge_lo, edge_hi, gaussian))
    max_g = max((g for _, _, g in raw), default=0.01)
    out = []
    for edge_lo, edge_hi, gaussian in raw:
        out.append({
            'bucket_start': edge_lo,
            'bucket_end': edge_hi,
            'count': int(round(gaussian * 100)),
            'normalized': round(gaussian / max_g, 3),
            'in_range': edge_hi >= lo and edge_lo <= hi,
            'is_user_bucket': edge_lo <= valor_usuario < edge_hi,
            'sintetico': True,
        })
    return out
