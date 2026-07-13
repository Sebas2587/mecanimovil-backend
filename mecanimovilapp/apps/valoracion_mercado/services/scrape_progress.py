"""
Progreso de scrape on-demand por vehículo (cache Redis).
"""
from __future__ import annotations

from typing import Any

from django.core.cache import cache

CACHE_TTL_SEC = 60 * 30  # 30 min
KEY_PREFIX = 'valoracion_scrape_v1'


def _key(vehiculo_id: int) -> str:
    return f'{KEY_PREFIX}:{vehiculo_id}'


def get_scrape_status(vehiculo_id: int) -> dict[str, Any]:
    data = cache.get(_key(vehiculo_id))
    if not isinstance(data, dict):
        return {
            'state': 'idle',
            'progress_pct': 0,
            'message': '',
            'task_id': None,
        }
    return data


def set_scrape_status(
    vehiculo_id: int,
    *,
    state: str,
    progress_pct: int = 0,
    message: str = '',
    task_id: str | None = None,
    listings_count: int | None = None,
) -> dict[str, Any]:
    from django.utils import timezone

    prev = get_scrape_status(vehiculo_id)
    payload = {
        'state': state,
        'progress_pct': max(0, min(100, int(progress_pct))),
        'message': message or '',
        'task_id': task_id if task_id is not None else prev.get('task_id'),
        'updated_at': timezone.now().isoformat(),
        'listings_count': (
            listings_count
            if listings_count is not None
            else prev.get('listings_count')
        ),
    }
    cache.set(_key(vehiculo_id), payload, CACHE_TTL_SEC)
    return payload


def is_scrape_active(vehiculo_id: int) -> bool:
    return get_scrape_status(vehiculo_id).get('state') in ('pending', 'running')
