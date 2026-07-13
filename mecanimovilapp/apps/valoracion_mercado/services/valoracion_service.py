"""
Orquestador: calcula y persiste ValoracionVehiculo para un vehículo.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.utils import timezone

from mecanimovilapp.apps.valoracion_mercado.models import ValoracionVehiculo
from mecanimovilapp.apps.valoracion_mercado.services.liquidez_engine import compute_liquidity
from mecanimovilapp.apps.valoracion_mercado.services.proyeccion_engine import project_values
from mecanimovilapp.apps.valoracion_mercado.services.segmento_service import (
    get_comparables_for_vehicle,
    get_latest_segment_snapshot,
    segmento_tracking_weeks,
)
from mecanimovilapp.apps.valoracion_mercado.services.valor_engine import compute_valor_real

logger = logging.getLogger(__name__)

CACHE_MAX_AGE_DAYS = 14


def valoracion_needs_refresh(vehiculo) -> bool:
    try:
        val = vehiculo.valoracion_mercado
    except ValoracionVehiculo.DoesNotExist:
        return True
    age = timezone.now() - val.fecha_calculo
    return age > timedelta(days=CACHE_MAX_AGE_DAYS)


def build_valoracion_payload(vehiculo, persist: bool = True) -> dict[str, Any]:
    year_bucket = vehiculo.year or timezone.now().year
    comparables = get_comparables_for_vehicle(vehiculo)
    segmento = get_latest_segment_snapshot(
        vehiculo.marca_id,
        vehiculo.modelo_id,
        year_bucket,
    ) or {}
    segmento['n_comparables'] = len(comparables)
    segmento['n_semanas_tracking'] = segmento_tracking_weeks(
        vehiculo.marca_id,
        vehiculo.modelo_id,
        year_bucket,
    )

    valor_data = compute_valor_real(vehiculo, comparables, segmento)
    tipo_veh = (vehiculo.meta_tipo_vehiculo if hasattr(vehiculo, 'meta_tipo_vehiculo') else None) or 'LIVIANO'

    proyeccion, tasa_dep, fuente_tasa = project_values(
        valor_data['valor_real_hoy'],
        vehiculo,
        valor_data['confianza'],
        tipo_vehiculo=tipo_veh,
    )

    liquidez = compute_liquidity(
        vehiculo,
        valor_data['valor_real_hoy'],
        comparables,
        segmento,
    )

    fuentes = []
    if comparables:
        ml = sum(1 for c in comparables if c.get('fuente') == 'mercadolibre')
        ca = sum(1 for c in comparables if c.get('fuente') == 'chileautos')
        if ml:
            fuentes.append('mercadolibre')
        if ca:
            fuentes.append('chileautos')
    if vehiculo.precio_mercado_promedio:
        fuentes.append('getapi')

    meta = {
        'n_comparables': valor_data['n_comparables'],
        'n_semanas_tracking': segmento.get('n_semanas_tracking', 0),
        'fuentes': fuentes,
        'tasa_depreciacion_anual_pct': float(tasa_dep),
        'fuente_tasa': fuente_tasa,
        'w_externo': valor_data.get('w_externo'),
        'w_getapi': valor_data.get('w_getapi'),
        'valor_getapi_ajustado': valor_data.get('valor_getapi_ajustado'),
        'mediana_externa': valor_data.get('mediana_externa'),
        'precision_liquidez': liquidez.get('precision_suficiente', False),
        'histograma_origen': valor_data.get('histograma_origen', 'estimado'),
        'salud_aplicada': next(
            (p.get('salud_aplicada') for p in proyeccion if p.get('salud_aplicada') is not None),
            None,
        ),
    }

    liquidez_score = liquidez['liquidez_score']
    if liquidez['liquidez_label'] == 'calculando':
        liquidez_score = None

    payload = {
        'vehiculo_id': vehiculo.id,
        'valor_real_hoy': valor_data['valor_real_hoy'],
        'valor_real_rango_min': valor_data['valor_real_rango_min'],
        'valor_real_rango_max': valor_data['valor_real_rango_max'],
        'confianza': valor_data['confianza'],
        'liquidez': {
            'score': liquidez_score,
            'label': liquidez['liquidez_label'],
            'razones': liquidez['liquidez_razones'],
        },
        'proyeccion': proyeccion,
        'histograma': valor_data['histograma'],
        'meta': meta,
        'fecha_calculo': timezone.now().isoformat(),
        'currency': 'CLP',
    }

    if persist:
        ValoracionVehiculo.objects.update_or_create(
            vehiculo=vehiculo,
            defaults={
                'valor_real_hoy': valor_data['valor_real_hoy'],
                'valor_real_rango_min': valor_data['valor_real_rango_min'],
                'valor_real_rango_max': valor_data['valor_real_rango_max'],
                'confianza': valor_data['confianza'],
                'liquidez_score': liquidez['liquidez_score'] or 0,
                'liquidez_label': liquidez['liquidez_label'],
                'liquidez_razones': liquidez['liquidez_razones'],
                'proyeccion': proyeccion,
                'histograma': valor_data['histograma'],
                'meta': meta,
            },
        )

    return payload


def get_or_compute_valoracion(vehiculo, force: bool = False) -> dict[str, Any]:
    if force or valoracion_needs_refresh(vehiculo):
        return build_valoracion_payload(vehiculo, persist=True)
    val = vehiculo.valoracion_mercado
    return {
        'vehiculo_id': vehiculo.id,
        'valor_real_hoy': val.valor_real_hoy,
        'valor_real_rango_min': val.valor_real_rango_min,
        'valor_real_rango_max': val.valor_real_rango_max,
        'confianza': val.confianza,
        'liquidez': {
            'score': val.liquidez_score if val.liquidez_label != 'calculando' else None,
            'label': val.liquidez_label,
            'razones': val.liquidez_razones or [],
        },
        'proyeccion': val.proyeccion or [],
        'histograma': val.histograma or [],
        'meta': val.meta or {},
        'fecha_calculo': val.fecha_calculo.isoformat(),
        'currency': 'CLP',
    }
