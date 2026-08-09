"""Dispara búsqueda web async tras crear/actualizar borrador de cotización."""
from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)


def marcar_busqueda_web_pendiente(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Devuelve metadata con busqueda_web_estado=pendiente si el feature está ON."""
    meta = dict(metadata or {})
    if not getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_ENABLED', False):
        return meta
    if not (getattr(settings, 'GEMINI_API_KEY', '') or '').strip():
        return meta
    meta['busqueda_web_estado'] = 'pendiente'
    return meta


def disparar_busqueda_web_cotizacion(cotizacion_id: int | None) -> None:
    """Encola Celery tras commit. No-op si feature OFF o id inválido."""
    if not cotizacion_id:
        return
    if not getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_ENABLED', False):
        return
    if not (getattr(settings, 'GEMINI_API_KEY', '') or '').strip():
        return

    def _enqueue() -> None:
        try:
            from mecanimovilapp.apps.ordenes.tasks import buscar_precios_web_cotizacion_task

            buscar_precios_web_cotizacion_task.delay(int(cotizacion_id))
        except Exception as exc:
            logger.warning(
                'No se pudo encolar buscar_precios_web_cotizacion_task(%s): %s',
                cotizacion_id,
                exc,
            )

    try:
        transaction.on_commit(_enqueue)
    except Exception:
        _enqueue()
