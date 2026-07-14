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


@shared_task(
    bind=True,
    max_retries=1,
    default_retry_delay=180,
    soft_time_limit=90,
    time_limit=110,
)
def task_scrape_vehiculo(self, vehiculo_id: int):
    """
    Scrape on-demand del segmento de un vehículo (ML + Chileautos),
    con progreso en cache para la UI.
    """
    from mecanimovilapp.apps.vehiculos.models import Vehiculo
    from mecanimovilapp.apps.valoracion_mercado.services.scrape_progress import set_scrape_status
    from mecanimovilapp.apps.valoracion_mercado.services.scraper_service import (
        mark_removed_for_segment,
        scrape_segmento,
        upsert_listings,
    )
    from mecanimovilapp.apps.valoracion_mercado.services.segmento_service import aggregate_segment
    from mecanimovilapp.apps.valoracion_mercado.services.valoracion_service import (
        build_valoracion_payload,
    )

    try:
        vehiculo = Vehiculo.objects.select_related('marca', 'modelo').get(pk=vehiculo_id)
    except Vehiculo.DoesNotExist:
        set_scrape_status(vehiculo_id, state='error', progress_pct=0, message='Vehículo no encontrado')
        return 0

    if not vehiculo.marca_id or not vehiculo.modelo_id:
        set_scrape_status(
            vehiculo_id,
            state='error',
            progress_pct=0,
            message='Falta marca/modelo para buscar comparables',
        )
        return 0

    year_bucket = vehiculo.year or timezone.now().year
    year_min, year_max = year_bucket - 1, year_bucket + 1
    marca_nombre = getattr(vehiculo.marca, 'nombre', '') or ''
    modelo_nombre = getattr(vehiculo.modelo, 'nombre', '') or ''

    set_scrape_status(
        vehiculo_id,
        state='running',
        progress_pct=8,
        message='Buscando autos similares en el mercado…',
        task_id=getattr(self.request, 'id', None),
    )

    def on_progress(pct: int, message: str) -> None:
        set_scrape_status(
            vehiculo_id,
            state='running',
            progress_pct=pct,
            message=message,
            task_id=getattr(self.request, 'id', None),
        )

    try:
        set_scrape_status(
            vehiculo_id,
            state='running',
            progress_pct=18,
            message='Consultando MercadoLibre…',
        )
        result = scrape_segmento(
            marca_nombre,
            modelo_nombre,
            year_bucket=year_bucket,
            on_progress=on_progress,
        )

        n = len(result.listings)
        blocked = (result.blocked_reason or '').startswith('mercadolibre')

        if blocked and n == 0:
            # Terminar limpio: sin token OAuth / proxy, ML bloquea IPs de Render.
            build_valoracion_payload(vehiculo, persist=True)
            set_scrape_status(
                vehiculo_id,
                state='done',
                progress_pct=100,
                message=(
                    'MercadoLibre bloqueó el acceso (anti-bot). '
                    'Configura MERCADOLIBRE_ACCESS_TOKEN o PLAYWRIGHT_PROXY.'
                ),
                listings_count=0,
            )
            return 0

        set_scrape_status(
            vehiculo_id,
            state='running',
            progress_pct=65,
            message=f'Guardando {n} avisos encontrados…',
        )
        seen = upsert_listings(result.listings, vehiculo.marca, vehiculo.modelo, year_bucket)
        mark_removed_for_segment(vehiculo.marca, vehiculo.modelo, year_min, year_max, seen)

        set_scrape_status(
            vehiculo_id,
            state='running',
            progress_pct=82,
            message='Agregando segmento de mercado…',
        )
        aggregate_segment(vehiculo.marca, vehiculo.modelo, year_bucket)

        set_scrape_status(
            vehiculo_id,
            state='running',
            progress_pct=92,
            message='Recalculando valor de tu auto…',
        )
        build_valoracion_payload(vehiculo, persist=True)

        set_scrape_status(
            vehiculo_id,
            state='done',
            progress_pct=100,
            message=f'Listo · {n} avisos de mercado',
            listings_count=n,
        )
        return n
    except Exception as exc:
        # SoftTimeLimitExceeded / worker kill: no dejar la UI en 25% forever.
        from celery.exceptions import SoftTimeLimitExceeded

        msg = 'Búsqueda de mercado agotó el tiempo' if isinstance(exc, SoftTimeLimitExceeded) else (
            'No pudimos completar la búsqueda de mercado'
        )
        logger.exception('task_scrape_vehiculo %s: %s', vehiculo_id, exc)
        set_scrape_status(
            vehiculo_id,
            state='error',
            progress_pct=0,
            message=msg,
            listings_count=0,
        )
        if isinstance(exc, SoftTimeLimitExceeded):
            return 0
        raise


def enqueue_scrape_vehiculo(vehiculo_id: int, *, force: bool = False) -> dict:
    """Encola scrape si no hay uno activo. Retorna scrape_status."""
    from mecanimovilapp.apps.valoracion_mercado.services.scrape_progress import (
        clear_scrape_status,
        get_scrape_status,
        is_scrape_active,
        is_scrape_stale,
        set_scrape_status,
    )

    if force or is_scrape_stale(vehiculo_id=vehiculo_id):
        clear_scrape_status(vehiculo_id)
    elif is_scrape_active(vehiculo_id):
        return get_scrape_status(vehiculo_id)

    status = set_scrape_status(
        vehiculo_id,
        state='pending',
        progress_pct=2,
        message='En cola para buscar datos del mercado…',
    )
    async_result = task_scrape_vehiculo.delay(vehiculo_id)
    return set_scrape_status(
        vehiculo_id,
        state='pending',
        progress_pct=2,
        message=status['message'],
        task_id=async_result.id,
    )


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
