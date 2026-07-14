"""
Ingesta de avisos de mercado capturados desde el cliente (IP residencial).
Usado cuando Render no puede scrapear ML/Chileautos por anti-bot.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from django.utils import timezone

logger = logging.getLogger(__name__)

ALLOWED_FUENTES = {'mercadolibre', 'chileautos'}
MAX_AVISOS = 40


def ingest_client_listings(vehiculo, raw_listings: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Valida avisos del app, upsert, agrega segmento y recalcula valoración.
    """
    from mecanimovilapp.apps.valoracion_mercado.services.scrape_progress import set_scrape_status
    from mecanimovilapp.apps.valoracion_mercado.services.scraper_service import (
        ListingScraped,
        _external_id_from_url,
        _parse_km_from_title,
        _parse_year_from_title,
        mark_removed_for_segment,
        upsert_listings,
    )
    from mecanimovilapp.apps.valoracion_mercado.services.segmento_service import aggregate_segment
    from mecanimovilapp.apps.valoracion_mercado.services.valoracion_service import (
        build_valoracion_payload,
        get_or_compute_valoracion,
    )

    year_bucket = vehiculo.year or timezone.now().year
    year_min, year_max = year_bucket - 1, year_bucket + 1
    marca_nombre = getattr(vehiculo.marca, 'nombre', '') or ''
    modelo_nombre = getattr(vehiculo.modelo, 'nombre', '') or ''

    parsed: list[ListingScraped] = []
    for row in (raw_listings or [])[:MAX_AVISOS]:
        if not isinstance(row, dict):
            continue
        fuente = str(row.get('fuente') or '').strip().lower()
        if fuente not in ALLOWED_FUENTES:
            continue
        titulo = str(row.get('titulo_raw') or row.get('titulo') or '').strip()
        if len(titulo) < 6:
            continue
        try:
            precio = int(re.sub(r'[^\d]', '', str(row.get('precio') or '0')) or '0')
        except (TypeError, ValueError):
            precio = 0
        if precio < 500_000 or precio > 500_000_000:
            continue
        url = str(row.get('url') or '').strip()[:512]
        year = row.get('year')
        try:
            year = int(year) if year is not None else _parse_year_from_title(titulo)
        except (TypeError, ValueError):
            year = _parse_year_from_title(titulo)
        km = row.get('kilometraje')
        try:
            km = int(km) if km is not None else _parse_km_from_title(titulo)
        except (TypeError, ValueError):
            km = _parse_km_from_title(titulo)
        eid = str(row.get('external_id') or '').strip()
        if not eid:
            eid = _external_id_from_url(url, titulo, fuente)
        parsed.append(
            ListingScraped(
                fuente=fuente,
                external_id=eid[:128],
                url=url or f'client://{fuente}/{eid}',
                titulo_raw=titulo[:2000],
                precio=precio,
                year=year,
                kilometraje=km,
                marca_texto=marca_nombre,
                modelo_texto=modelo_nombre,
            )
        )

    if not parsed:
        set_scrape_status(
            vehiculo.id,
            state='done',
            progress_pct=100,
            message='Sin avisos desde el dispositivo',
            listings_count=0,
        )
        return get_or_compute_valoracion(vehiculo, force=False, enqueue_scrape=False)

    seen = upsert_listings(parsed, vehiculo.marca, vehiculo.modelo, year_bucket)
    mark_removed_for_segment(vehiculo.marca, vehiculo.modelo, year_min, year_max, seen)
    aggregate_segment(vehiculo.marca, vehiculo.modelo, year_bucket)
    payload = build_valoracion_payload(vehiculo, persist=True)

    set_scrape_status(
        vehiculo.id,
        state='done',
        progress_pct=100,
        message=f'Listo · {len(parsed)} avisos desde tu dispositivo',
        listings_count=len(parsed),
    )
    logger.info(
        'ingest_client_listings vehiculo=%s n=%s fuentes=%s',
        vehiculo.id,
        len(parsed),
        sorted({p.fuente for p in parsed}),
    )
    from mecanimovilapp.apps.valoracion_mercado.services.valoracion_service import (
        _attach_scrape_meta,
    )

    return _attach_scrape_meta(payload, vehiculo, enqueue=False)
