"""
Orquestador: calcula y persiste ValoracionVehiculo para un vehículo.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.utils import timezone

from mecanimovilapp.apps.valoracion_mercado.models import ValoracionVehiculo
from mecanimovilapp.apps.valoracion_mercado.services.demanda_timing import compute_demanda_timing
from mecanimovilapp.apps.valoracion_mercado.services.liquidez_engine import compute_liquidity
from mecanimovilapp.apps.valoracion_mercado.services.proyeccion_engine import project_values
from mecanimovilapp.apps.valoracion_mercado.services.scrape_progress import get_scrape_status
from mecanimovilapp.apps.valoracion_mercado.services.segmento_service import (
    get_comparables_for_vehicle,
    get_latest_segment_snapshot,
    segmento_tracking_weeks,
)
from mecanimovilapp.apps.valoracion_mercado.services.valor_engine import compute_valor_real

logger = logging.getLogger(__name__)

CACHE_MAX_AGE_DAYS = 14
MIN_COMPARABLES_FOR_MARKET = 3


def valoracion_needs_refresh(vehiculo) -> bool:
    try:
        val = vehiculo.valoracion_mercado
    except ValoracionVehiculo.DoesNotExist:
        return True
    age = timezone.now() - val.fecha_calculo
    return age > timedelta(days=CACHE_MAX_AGE_DAYS)


def maybe_enqueue_market_scrape(vehiculo, *, force: bool = False) -> dict[str, Any]:
    """
    Dispara scrape on-demand si faltan comparables externos (o force=True).
    No bloquea: el worker scraper actualiza progreso en cache.
    """
    from datetime import datetime

    from mecanimovilapp.apps.valoracion_mercado.services.scrape_progress import (
        clear_scrape_status,
        is_scrape_stale,
    )
    from mecanimovilapp.apps.valoracion_mercado.tasks import enqueue_scrape_vehiculo

    status = get_scrape_status(vehiculo.id)

    # Worker muerto mid-scrape deja running@25% en Redis → desbloquear y reintentar.
    if status.get('state') in ('pending', 'running'):
        if is_scrape_stale(status):
            logger.warning(
                'scrape zombie vehiculo=%s state=%s pct=%s → reencolando',
                vehiculo.id,
                status.get('state'),
                status.get('progress_pct'),
            )
            clear_scrape_status(vehiculo.id)
        else:
            return status

    comparables = get_comparables_for_vehicle(vehiculo)
    has_market = len(comparables) >= MIN_COMPARABLES_FOR_MARKET

    # Scrape previo sin comparables: cooldown antes de reintentar.
    # Anti-bot de ML necesita token/proxy → cooldown largo (no spamear al worker).
    if not force and status.get('state') in ('done', 'error'):
        if has_market:
            return status
        msg = status.get('message') or ''
        antibot = 'anti-bot' in msg.casefold() or 'MERCADOLIBRE_ACCESS_TOKEN' in msg
        cooldown_min = 360 if antibot else 15
        age_ok = True
        updated_raw = status.get('updated_at')
        if updated_raw:
            try:
                updated = datetime.fromisoformat(str(updated_raw).replace('Z', '+00:00'))
                if timezone.is_naive(updated):
                    updated = timezone.make_aware(updated, timezone.get_current_timezone())
                age_ok = (timezone.now() - updated) >= timedelta(minutes=cooldown_min)
            except (TypeError, ValueError):
                age_ok = True
        if not age_ok:
            return status

    needs = force or not has_market
    if not needs:
        return {
            'state': 'idle',
            'progress_pct': 100 if comparables else 0,
            'message': '',
            'task_id': None,
        }

    try:
        return enqueue_scrape_vehiculo(vehiculo.id, force=True)
    except Exception as exc:
        logger.warning('enqueue scrape vehiculo %s: %s', vehiculo.id, exc)
        return {
            'state': 'error',
            'progress_pct': 0,
            'message': 'No se pudo encolar la búsqueda de mercado',
            'task_id': None,
        }


def _attach_scrape_meta(payload: dict[str, Any], vehiculo, *, enqueue: bool = True) -> dict[str, Any]:
    scrape = maybe_enqueue_market_scrape(vehiculo) if enqueue else get_scrape_status(vehiculo.id)
    meta = dict(payload.get('meta') or {})
    meta['scrape'] = scrape
    payload['meta'] = meta
    return payload


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
    demanda = compute_demanda_timing(
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
        'demanda': demanda,
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
                'meta': {**meta, 'demanda': demanda},
            },
        )

    return payload


def get_or_compute_valoracion(vehiculo, force: bool = False, enqueue_scrape: bool = True) -> dict[str, Any]:
    if force or valoracion_needs_refresh(vehiculo):
        payload = build_valoracion_payload(vehiculo, persist=True)
    else:
        val = vehiculo.valoracion_mercado
        payload = {
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
            'demanda': (val.meta or {}).get('demanda') or {
                'recomendacion': 'indeterminado',
                'confianza': 'baja',
                'titulo': 'Aún midiendo la demanda',
                'detalle': 'Necesitamos historial de avisos del segmento para comparar hoy vs. próximo mes.',
                'razones': [],
            },
            'proyeccion': val.proyeccion or [],
            'histograma': val.histograma or [],
            'meta': dict(val.meta or {}),
            'fecha_calculo': val.fecha_calculo.isoformat(),
            'currency': 'CLP',
        }
    return _attach_scrape_meta(payload, vehiculo, enqueue=enqueue_scrape)
