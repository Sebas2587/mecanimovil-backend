"""
Tareas Celery para valoración de mercado.
"""
from __future__ import annotations

import logging
import time

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

GETAPI_THROTTLE_SEC = 6  # ~10 req/min plan Starter


@shared_task(bind=True, max_retries=2, default_retry_delay=120)
def task_snapshot_tasacion_mensual(self):
    """Snapshot mensual de tasación GetAPI por vehículo activo."""
    from datetime import date

    from mecanimovilapp.apps.vehiculos.getapi_client import fetch_appraisal_for_plate
    from mecanimovilapp.apps.vehiculos.models import Vehiculo
    from mecanimovilapp.apps.valoracion_mercado.models import TasacionHistorial

    today = date.today()
    count = 0
    for vehiculo in Vehiculo.objects.exclude(patente='').iterator(chunk_size=50):
        if not vehiculo.patente:
            continue
        try:
            data = fetch_appraisal_for_plate(vehiculo.patente)
            TasacionHistorial.objects.update_or_create(
                vehiculo=vehiculo,
                fecha=today,
                defaults={
                    'precio_mercado_promedio': int(data.get('precio_mercado_promedio') or 0),
                    'banda_min': int(data.get('precio_mercado_min') or 0),
                    'banda_max': int(data.get('precio_mercado_max') or 0),
                    'tasacion_fiscal': int(data.get('tasacion_fiscal') or 0),
                    'mileage': data.get('mileage'),
                },
            )
            count += 1
            time.sleep(GETAPI_THROTTLE_SEC)
        except Exception as exc:
            logger.warning('tasacion snapshot falló %s: %s', vehiculo.patente, exc)
    logger.info('task_snapshot_tasacion_mensual: %s vehículos', count)
    return count


@shared_task(bind=True, max_retries=1, default_retry_delay=300)
def task_scrape_segmentos_activos(self):
    """Scrapea segmentos con vehículos registrados (ML + Chileautos)."""
    from mecanimovilapp.apps.valoracion_mercado.services.scraper_service import (
        mark_removed_for_segment,
        scrape_segmento,
        upsert_listings,
    )
    from mecanimovilapp.apps.valoracion_mercado.services.segmento_service import (
        unique_segments_from_vehicles,
    )

    segments = unique_segments_from_vehicles()
    total_listings = 0
    for seg in segments:
        marca_obj = seg['marca']
        modelo_obj = seg['modelo']
        year_bucket = seg['year_bucket']
        year_min, year_max = year_bucket - 1, year_bucket + 1
        try:
            result = scrape_segmento(
                seg['marca_nombre'],
                seg['modelo_nombre'],
                year_bucket=year_bucket,
            )
            seen = upsert_listings(
                result.listings,
                marca_obj,
                modelo_obj,
                year_bucket,
            )
            mark_removed_for_segment(marca_obj, modelo_obj, year_min, year_max, seen)
            total_listings += len(result.listings)
            time.sleep(3)
        except Exception as exc:
            logger.warning(
                'scrape segmento %s %s: %s',
                seg['marca_nombre'],
                seg['modelo_nombre'],
                exc,
            )
    logger.info('task_scrape_segmentos_activos: %s listings', total_listings)
    task_agregar_segmentos.delay()
    return total_listings


@shared_task(bind=True)
def task_agregar_segmentos(self):
    """Agrega snapshots semanales por segmento."""
    from mecanimovilapp.apps.valoracion_mercado.services.segmento_service import (
        aggregate_segment,
        unique_segments_from_vehicles,
    )

    n = 0
    for seg in unique_segments_from_vehicles():
        aggregate_segment(seg['marca'], seg['modelo'], seg['year_bucket'])
        n += 1
    logger.info('task_agregar_segmentos: %s segmentos', n)
    return n


@shared_task(bind=True)
def task_recalcular_valoracion_vehiculos(self, vehiculo_id=None):
    """Recalcula ValoracionVehiculo para todos o uno."""
    from mecanimovilapp.apps.vehiculos.models import Vehiculo
    from mecanimovilapp.apps.valoracion_mercado.services.valoracion_service import (
        build_valoracion_payload,
    )

    qs = Vehiculo.objects.select_related('marca', 'modelo')
    if vehiculo_id:
        qs = qs.filter(pk=vehiculo_id)
    count = 0
    for vehiculo in qs.iterator(chunk_size=30):
        try:
            build_valoracion_payload(vehiculo, persist=True)
            count += 1
        except Exception as exc:
            logger.warning('valoracion vehiculo %s: %s', vehiculo.id, exc)
    logger.info('task_recalcular_valoracion_vehiculos: %s', count)
    return count
