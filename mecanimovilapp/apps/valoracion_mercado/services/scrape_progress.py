"""
Progreso de scrape on-demand por vehículo (cache Redis).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.core.cache import cache
from django.utils import timezone

CACHE_TTL_SEC = 60 * 30  # 30 min
# Si un worker muere mid-scrape, el estado running quedaba pegado hasta TTL.
STALE_AFTER_SEC = 150  # 2.5 min sin update → se considera zombie
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


def _parse_updated_at(raw) -> datetime | None:
    if not raw:
        return None
    try:
        updated = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
        if timezone.is_naive(updated):
            updated = timezone.make_aware(updated, timezone.get_current_timezone())
        return updated
    except (TypeError, ValueError):
        return None


def is_scrape_stale(status: dict[str, Any] | None = None, *, vehiculo_id: int | None = None) -> bool:
    data = status if status is not None else get_scrape_status(vehiculo_id or 0)
    if data.get('state') not in ('pending', 'running'):
        return False
    updated = _parse_updated_at(data.get('updated_at'))
    if updated is None:
        return True
    return (timezone.now() - updated) >= timedelta(seconds=STALE_AFTER_SEC)


def clear_scrape_status(vehiculo_id: int) -> None:
    cache.delete(_key(vehiculo_id))


def set_scrape_status(
    vehiculo_id: int,
    *,
    state: str,
    progress_pct: int = 0,
    message: str = '',
    task_id: str | None = None,
    listings_count: int | None = None,
) -> dict[str, Any]:
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
    status = get_scrape_status(vehiculo_id)
    if status.get('state') not in ('pending', 'running'):
        return False
    if is_scrape_stale(status):
        return False
    return True
