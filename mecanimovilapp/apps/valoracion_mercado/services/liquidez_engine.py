"""
Motor 3: facilidad de venta (liquidity score 0-100).
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Avg, Count, Q
from django.utils import timezone

from mecanimovilapp.apps.valoracion_mercado.models import AvisoExternoVehiculo, SegmentoValorHistorial


def _health_score(vehiculo) -> float:
    if hasattr(vehiculo, 'estados_salud'):
        ultimo = vehiculo.estados_salud.order_by('-fecha_calculo').first()
        if ultimo:
            return float(ultimo.salud_general_porcentaje or 0)
    return 70.0


def _price_position_score(valor_real: int, prices: list[int]) -> float:
    if not prices or valor_real <= 0:
        return 50.0
    sorted_p = sorted(prices)
    below = sum(1 for p in sorted_p if p <= valor_real)
    pct = below / len(sorted_p)
    # Tercio bajo del mercado vende más rápido
    if pct <= 0.33:
        return 85.0
    if pct <= 0.66:
        return 55.0
    return 25.0


def _rotation_score(marca_id, modelo_id, year_min, year_max) -> tuple[float, float | None]:
    cutoff_old = timezone.now() - timedelta(days=60)
    cutoff_recent = timezone.now() - timedelta(days=30)
    base_qs = AvisoExternoVehiculo.objects.filter(
        marca_id=marca_id,
        modelo_id=modelo_id,
        year__gte=year_min,
        year__lte=year_max,
    )
    old_active = base_qs.filter(
        fecha_primera_vista__lte=cutoff_old,
        fecha_ultima_vista__gte=cutoff_old,
    ).count()
    if old_active < 3:
        return 50.0, None
    removed = base_qs.filter(
        activo=False,
        fecha_removido__gte=cutoff_recent,
        fecha_primera_vista__lte=cutoff_old,
    ).count()
    rate = (removed / old_active) * 100
    # Alta rotación = mercado activo = más fácil vender
    if rate >= 40:
        score = 90.0
    elif rate >= 20:
        score = 70.0
    elif rate >= 10:
        score = 50.0
    else:
        score = 30.0
    return score, round(rate, 1)


def _density_score(marca_id, modelo_id, year_bucket, n_actuales: int) -> tuple[float, str | None]:
    hist = (
        SegmentoValorHistorial.objects.filter(
            marca_id=marca_id,
            modelo_id=modelo_id,
            year_bucket=year_bucket,
        )
        .aggregate(avg=Avg('n_anuncios_activos'))
    )
    avg_hist = hist.get('avg') or 0
    if avg_hist <= 0:
        if n_actuales <= 5:
            return 70.0, None
        if n_actuales <= 15:
            return 50.0, None
        return 30.0, f'Hay {n_actuales} autos similares publicados'
    ratio = n_actuales / float(avg_hist)
    if ratio <= 0.7:
        return 80.0, 'Hay menos oferta que el promedio reciente'
    if ratio <= 1.3:
        return 55.0, 'La oferta está en línea con el mercado'
    return 25.0, f'Hay {ratio:.1f}x más autos similares que el promedio'


def _getapi_signals_score(vehiculo) -> float:
    score = 50.0
    # RT vigente si mes_revision_tecnica presente (proxy sin campo rtResult persistido)
    if vehiculo.mes_revision_tecnica:
        score += 25
    if vehiculo.vin:
        score += 10
    return min(100.0, score)


def compute_liquidity(
    vehiculo,
    valor_real: int,
    comparables: list[dict],
    segmento_meta: dict,
) -> dict[str, Any]:
    n_comp = segmento_meta.get('n_comparables', len(comparables))
    n_semanas = segmento_meta.get('n_semanas_tracking', 0)
    year = vehiculo.year or timezone.now().year
    year_min, year_max = year - 1, year + 1

    if n_comp < 5:
        sin_mercado_externo = True
        try:
            from mecanimovilapp.apps.valoracion_mercado.services.ml_auth import has_valid_oauth

            sin_mercado_externo = not has_valid_oauth()
        except Exception:
            pass
        razones = ['Estimado con tasación GetAPI y salud del vehículo.']
        if sin_mercado_externo:
            razones.append('Mercado externo (MercadoLibre/Chileautos) aún no conectado.')
        else:
            razones.append('Recopilando avisos del mercado para tu modelo; vuelve en unos minutos.')
        return {
            'liquidez_score': None,
            'liquidez_label': 'calculando',
            'liquidez_razones': razones,
            'precision_suficiente': False,
        }

    # Con ≥5 avisos ya damos señal usable (aunque falte historial de rotación).
    weights = {
        'rotacion': 35 if n_semanas >= 3 else 0,
        'densidad': 25 if n_semanas >= 3 else 35,
        'salud': 20 if n_semanas >= 3 else 30,
        'precio': 15 if n_semanas >= 3 else 25,
        'getapi': 5 if n_semanas >= 3 else 10,
    }
    prices = [int(c['precio']) for c in comparables if c.get('precio')]
    rot_score, rot_pct = _rotation_score(
        vehiculo.marca_id, vehiculo.modelo_id, year_min, year_max
    )
    den_score, den_reason = _density_score(
        vehiculo.marca_id,
        vehiculo.modelo_id,
        year,
        segmento_meta.get('n_anuncios_activos', n_comp),
    )
    health = _health_score(vehiculo)
    health_score = min(100, health)
    pos_score = _price_position_score(valor_real, prices)
    api_score = _getapi_signals_score(vehiculo)

    total_w = sum(weights.values()) or 1
    composite = (
        weights['rotacion'] * rot_score
        + weights['densidad'] * den_score
        + weights['salud'] * health_score
        + weights['precio'] * pos_score
        + weights['getapi'] * api_score
    ) / total_w
    score = int(round(composite))

    if score >= 70:
        label = 'facil'
    elif score >= 40:
        label = 'moderado'
    else:
        label = 'dificil'

    razones = []
    if n_semanas < 3:
        razones.append(f'Estimación con {n_comp} avisos actuales (rotación aún midiendo).')
    if den_reason:
        razones.append(den_reason)
    if rot_pct is not None and n_semanas >= 3:
        if rot_pct >= 25:
            razones.append(f'El {rot_pct:.0f}% de autos similares salió del mercado en el último mes')
        else:
            razones.append('Pocos autos similares se han vendido recientemente')
    if health >= 85:
        razones.append('Buena salud del vehículo favorece la venta')
    elif health < 50:
        razones.append('La salud del vehículo puede dificultar la venta')
    if pos_score >= 75:
        razones.append('Tu precio estimado está en un rango competitivo')
    elif pos_score <= 35:
        razones.append('Tu precio estimado está por encima de la mayoría de ofertas')

    return {
        'liquidez_score': score,
        'liquidez_label': label,
        'liquidez_razones': razones[:2],
        'precision_suficiente': n_comp >= 8 and n_semanas >= 3,
        'tasa_rotacion_pct': rot_pct,
    }
