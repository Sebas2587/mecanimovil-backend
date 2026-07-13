"""
Señal de timing de venta por DEMANDA (no por depreciación de tasación).

Responde: ¿es mejor vender hoy o esperar, según rotación/oferta/precios
observados en el segmento? Si no hay tracking suficiente, lo declara
explícitamente en vez de fingir certeza.
"""
from __future__ import annotations

from typing import Any

from django.utils import timezone

from mecanimovilapp.apps.valoracion_mercado.models import SegmentoValorHistorial
from mecanimovilapp.apps.valoracion_mercado.services.liquidez_engine import (
    _density_score,
    _health_score,
    _price_position_score,
    _rotation_score,
)


def _segment_trend(marca_id, modelo_id, year_bucket: int) -> dict[str, Any]:
    rows = list(
        SegmentoValorHistorial.objects.filter(
            marca_id=marca_id,
            modelo_id=modelo_id,
            year_bucket=year_bucket,
        )
        .order_by('-fecha_snapshot')
        .values(
            'fecha_snapshot',
            'n_anuncios_activos',
            'precio_mediana',
            'tasa_rotacion_30d_pct',
        )[:6]
    )
    if len(rows) < 2:
        return {
            'n_snapshots': len(rows),
            'oferta_tendencia': None,
            'precio_tendencia': None,
            'rotacion_tendencia': None,
        }

    newest, older = rows[0], rows[1]
    oferta_delta = (newest['n_anuncios_activos'] or 0) - (older['n_anuncios_activos'] or 0)
    precio_delta = (newest['precio_mediana'] or 0) - (older['precio_mediana'] or 0)
    rot_n = float(newest['tasa_rotacion_30d_pct'] or 0)
    rot_o = float(older['tasa_rotacion_30d_pct'] or 0)
    rot_delta = rot_n - rot_o

    def sign(delta, deadband=0):
        if delta > deadband:
            return 'sube'
        if delta < -deadband:
            return 'baja'
        return 'estable'

    return {
        'n_snapshots': len(rows),
        'oferta_tendencia': sign(oferta_delta, deadband=1),
        'precio_tendencia': sign(precio_delta, deadband=50_000),
        'rotacion_tendencia': sign(rot_delta, deadband=2),
        'oferta_delta': oferta_delta,
        'precio_delta': precio_delta,
        'rotacion_delta': round(rot_delta, 1),
    }


def compute_demanda_timing(
    vehiculo,
    valor_real: int,
    comparables: list[dict],
    segmento_meta: dict,
) -> dict[str, Any]:
    """
    Timing por demanda del segmento.

    - vender_ahora: rotación alta / oferta bajando / precio de mercado firme
    - esperar: oferta saturada / rotación fría / precio de mercado bajando fuerte
    - indeterminado: sin semanas de tracking suficientes
    """
    n_comp = segmento_meta.get('n_comparables', len(comparables))
    n_semanas = segmento_meta.get('n_semanas_tracking', 0)
    year = vehiculo.year or timezone.now().year
    year_min, year_max = year - 1, year + 1
    trend = _segment_trend(vehiculo.marca_id, vehiculo.modelo_id, year)

    base = {
        'recomendacion': 'indeterminado',
        'confianza': 'baja',
        'titulo': 'Aún midiendo la demanda',
        'detalle': (
            'Para saber si el próximo mes es mejor que hoy necesitamos ver cómo '
            'se mueven avisos similares en el tiempo (rotación y oferta). '
            'La depreciación de tu tasación no responde esa pregunta.'
        ),
        'razones': [],
        'n_comparables': n_comp,
        'n_semanas_tracking': n_semanas,
        'tendencia': trend,
    }

    # Sin historial de segmento no hay señal de demanda temporal.
    if n_semanas < 2 or trend['n_snapshots'] < 2:
        if n_comp >= 3:
            prices = [int(c['precio']) for c in comparables if c.get('precio')]
            pos = _price_position_score(valor_real, prices)
            health = _health_score(vehiculo)
            razones = []
            if pos >= 75:
                razones.append('Hoy tu precio estimado está competitivo vs. avisos similares.')
            elif pos <= 35:
                razones.append('Hoy tu precio estimado está alto vs. la mayoría de avisos similares.')
            if health >= 85:
                razones.append('Tu salud favorece vender cuando haya demanda.')
            base.update({
                'titulo': 'Demanda aún en calibración',
                'detalle': (
                    f'Tenemos {n_comp} avisos, pero falta historial (solo {n_semanas} sem.). '
                    'Cuando el scraper acumule 2–3 semanas podremos decir si conviene esperar.'
                ),
                'razones': razones[:2],
                'confianza': 'baja',
            })
        return base

    rot_score, rot_pct = _rotation_score(
        vehiculo.marca_id, vehiculo.modelo_id, year_min, year_max
    )
    den_score, den_reason = _density_score(
        vehiculo.marca_id,
        vehiculo.modelo_id,
        year,
        segmento_meta.get('n_anuncios_activos', n_comp),
    )
    prices = [int(c['precio']) for c in comparables if c.get('precio')]
    pos = _price_position_score(valor_real, prices)

    score = 0  # >0 vender ahora, <0 esperar
    razones: list[str] = []

    if rot_pct is not None:
        if rot_pct >= 25:
            score += 2
            razones.append(f'Rotación alta ({rot_pct:.0f}% salió del mercado en 30 días): demanda activa.')
        elif rot_pct < 10:
            score -= 2
            razones.append('Pocos autos similares se están vendiendo: demanda fría.')

    if trend.get('oferta_tendencia') == 'sube':
        score -= 2
        razones.append('La oferta de tu modelo está aumentando: más competencia la próxima semana.')
    elif trend.get('oferta_tendencia') == 'baja':
        score += 1
        razones.append('Hay menos oferta similar que hace poco: mejor ventana relativa.')

    if trend.get('precio_tendencia') == 'baja':
        score += 1
        razones.append('El precio mediano del segmento está bajando: esperar puede costarte valor.')
    elif trend.get('precio_tendencia') == 'sube':
        score -= 1
        razones.append('El precio mediano del segmento está subiendo: podrías esperar un poco.')

    if den_reason and den_score <= 30:
        score -= 1
        razones.append(den_reason)
    elif den_score >= 75:
        score += 1

    if pos >= 75:
        score += 1
        razones.append('Tu precio estimado está en un tramo competitivo.')
    elif pos <= 35:
        score -= 1
        razones.append('Tu precio estimado está alto vs. el mercado actual.')

    confianza = 'alta' if n_semanas >= 3 and n_comp >= 8 else 'media'

    if score >= 2:
        return {
            **base,
            'recomendacion': 'vender_ahora',
            'confianza': confianza,
            'titulo': 'La demanda favorece vender ahora',
            'detalle': 'Según rotación y oferta reciente del segmento, esperar no mejora tu posición.',
            'razones': razones[:3],
            'score_demanda': score,
        }
    if score <= -2:
        return {
            **base,
            'recomendacion': 'esperar',
            'confianza': confianza,
            'titulo': 'Conviene observar unas semanas',
            'detalle': 'La demanda/oferta actual no es favorable; el próximo scrape puede abrir mejor ventana.',
            'razones': razones[:3],
            'score_demanda': score,
        }

    return {
        **base,
        'recomendacion': 'neutro',
        'confianza': confianza,
        'titulo': 'Sin ventaja clara entre hoy y el próximo mes',
        'detalle': 'Demanda y oferta están equilibradas. Elige por tu rango de precio y urgencia, no por timing de mercado.',
        'razones': razones[:3] or ['Señales de demanda mixtas en tu segmento.'],
        'score_demanda': score,
    }
