"""Dispara búsqueda web async/sync tras crear/actualizar borrador de cotización."""
from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)


def construir_progreso_busqueda(
    *,
    paso: str,
    detalle: str,
    fuentes: list[str] | None = None,
    lineas: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Snapshot que el taller ve en el riel mientras corre la búsqueda."""
    return {
        'paso': str(paso or '')[:40],
        'detalle': str(detalle or '')[:240],
        'fuentes': [str(f).strip()[:80] for f in (fuentes or []) if str(f).strip()][:8],
        'lineas': list(lineas or [])[:20],
    }


def lineas_progreso_desde_repuestos(
    repuestos: list | None,
    *,
    resultados: dict | None = None,
    buscando: str = '',
    terminado: bool = False,
) -> list[dict[str, Any]]:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
        _clave_fuzzy,
        _to_int_clp,
    )

    hits = resultados or {}
    buscando_clave = _clave_fuzzy(buscando)
    out: list[dict[str, Any]] = []
    for raw in repuestos or []:
        if not isinstance(raw, dict):
            continue
        nombre = str(raw.get('nombre') or '').strip()
        if not nombre:
            continue
        clave = _clave_fuzzy(nombre)
        hit = hits.get(clave) if clave else None
        if not isinstance(hit, dict):
            hit = None
        precio_hit = _to_int_clp((hit or {}).get('precio_clp'))
        precio_linea = _to_int_clp(raw.get('precio_unitario_clp'))
        fuente_linea = str(
            raw.get('proveedor_nombre') or raw.get('fuente_marketplace') or '',
        ).strip()
        if precio_hit > 0:
            estado = 'ok'
            fuente = str((hit or {}).get('tienda') or fuente_linea)[:80]
            precio = precio_hit
        elif precio_linea > 0 and str(raw.get('fuente_marketplace') or '') in (
            'catalogo', 'historial', 'proveedor', 'web', 'mercadolibre',
        ):
            estado = 'ok'
            fuente = fuente_linea[:80]
            precio = precio_linea
        elif buscando_clave and clave == buscando_clave:
            estado = 'buscando'
            fuente = ''
            precio = 0
        elif terminado:
            estado = 'sin_precio'
            fuente = ''
            precio = 0
        else:
            estado = 'buscando'
            fuente = ''
            precio = 0
        out.append({
            'nombre': nombre[:80],
            'estado': estado,
            'fuente': fuente,
            'precio_clp': precio or None,
        })
    return out


def marcar_busqueda_web_pendiente(
    metadata: dict[str, Any] | None,
    *,
    repuestos: list | None = None,
) -> dict[str, Any]:
    """Devuelve metadata con busqueda_web_estado=pendiente si el feature está ON."""
    meta = dict(metadata or {})
    if not getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_ENABLED', True):
        return meta
    if not (getattr(settings, 'GEMINI_API_KEY', '') or '').strip():
        return meta
    from django.utils import timezone

    meta['busqueda_web_estado'] = 'pendiente'
    meta['busqueda_web_en'] = timezone.now().isoformat()
    meta['busqueda_web_progreso'] = construir_progreso_busqueda(
        paso='casas',
        detalle='En cola: catálogo del taller, historial y tiendas de Chile',
        fuentes=['Catálogo del taller', 'Historial del taller', 'Tiendas .cl'],
        lineas=lineas_progreso_desde_repuestos(repuestos),
    )
    return meta


def busqueda_web_en_curso(metadata: dict[str, Any] | None, *, gracia_s: int = 90) -> bool:
    """True si el worker todavía está en la ventana de gracia (no re-disparar)."""
    meta = dict(metadata or {})
    if str(meta.get('busqueda_web_estado') or '') != 'pendiente':
        return False
    raw = str(meta.get('busqueda_web_en') or '').strip()
    if not raw:
        return False
    try:
        from django.utils import timezone
        from django.utils.dateparse import parse_datetime

        dt = parse_datetime(raw)
        if dt is None:
            return False
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return (timezone.now() - dt).total_seconds() < max(15, int(gracia_s))
    except Exception:
        return False


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

    sync por defecto: BUSQUEDA_WEB_REPUESTOS_SYNC_ON_CREATE (False). El editor
    hace poll; correr Tavily/Gemini en el HTTP de generar-ia supera el timeout
    del cliente y dispara reintentos que gastan tokens.
    """
    if not cotizacion_id or not _feature_listo():
        return False

    if sync is None:
        sync = bool(getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_SYNC_ON_CREATE', False))

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
