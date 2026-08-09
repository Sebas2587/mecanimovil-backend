"""Dispara búsqueda web async/sync tras crear/actualizar borrador de cotización."""
from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)


def marcar_busqueda_web_pendiente(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Devuelve metadata con busqueda_web_estado=pendiente si el feature está ON."""
    meta = dict(metadata or {})
    if not getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_ENABLED', True):
        return meta
    if not (getattr(settings, 'GEMINI_API_KEY', '') or '').strip():
        return meta
    meta['busqueda_web_estado'] = 'pendiente'
    return meta


def _feature_listo() -> bool:
    return bool(getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_ENABLED', True)) and bool(
        (getattr(settings, 'GEMINI_API_KEY', '') or '').strip(),
    )


def _ejecutar_task(cotizacion_id: int, *, sync: bool) -> None:
    from mecanimovilapp.apps.ordenes.tasks import buscar_precios_web_cotizacion_task

    if sync:
        # Corre en el proceso actual para que el caller pueda refresh_from_db
        # y devolver marca/tienda en la misma respuesta HTTP.
        buscar_precios_web_cotizacion_task.apply(args=[int(cotizacion_id)], throw=False)
        return
    buscar_precios_web_cotizacion_task.delay(int(cotizacion_id))


def disparar_busqueda_web_cotizacion(
    cotizacion_id: int | None,
    *,
    sync: bool | None = None,
) -> bool:
    """Ejecuta búsqueda web. Devuelve True si corrió en sync (hay que refrescar).

    sync por defecto: BUSQUEDA_WEB_REPUESTOS_SYNC_ON_CREATE (True) para no depender
    solo del worker Celery (p. ej. Free tier dormido).
    """
    if not cotizacion_id or not _feature_listo():
        return False

    if sync is None:
        sync = bool(getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_SYNC_ON_CREATE', True))

    if sync:
        try:
            _ejecutar_task(int(cotizacion_id), sync=True)
            return True
        except Exception as exc:
            logger.warning(
                'Sync busqueda web cotizacion=%s falló: %s — encola async',
                cotizacion_id,
                exc,
            )
            try:
                transaction.on_commit(
                    lambda: _ejecutar_task(int(cotizacion_id), sync=False),
                )
            except Exception as exc2:
                logger.warning(
                    'No se pudo encolar buscar_precios_web_cotizacion_task(%s): %s',
                    cotizacion_id,
                    exc2,
                )
            return False

    def _enqueue() -> None:
        try:
            _ejecutar_task(int(cotizacion_id), sync=False)
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
    return False


def disparar_y_refrescar_cotizacion(cotizacion: Any) -> Any:
    """Dispara búsqueda (sync por default) y refresca la instancia desde BD.

    Si historial/plantilla/cache ya cubren el mismo modelo+servicio, omite Tavily
    (`busqueda_web_estado=omitida_*`) para no gastar créditos.
    """
    if cotizacion is None or not getattr(cotizacion, 'id', None):
        return cotizacion
    if (getattr(cotizacion, 'metadata', None) or {}).get('busqueda_web_estado') != 'pendiente':
        return cotizacion

    try:
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.aprendizaje_cotizacion import (
            marcar_omitir_busqueda_web,
            puede_omitir_busqueda_web,
        )

        if puede_omitir_busqueda_web(cotizacion):
            logger.info(
                'disparar_y_refrescar_cotizacion(%s): omitida (historial/cache/plantilla)',
                cotizacion.id,
            )
            return marcar_omitir_busqueda_web(cotizacion, motivo='historial')
    except Exception as exc:
        logger.warning(
            'No se pudo evaluar omitir busqueda web cotizacion=%s: %s',
            cotizacion.id,
            exc,
        )

    ran_sync = disparar_busqueda_web_cotizacion(cotizacion.id)
    if ran_sync:
        try:
            cotizacion.refresh_from_db()
        except Exception as exc:
            logger.warning(
                'refresh_from_db tras busqueda web cotizacion=%s: %s',
                cotizacion.id,
                exc,
            )
    return cotizacion
