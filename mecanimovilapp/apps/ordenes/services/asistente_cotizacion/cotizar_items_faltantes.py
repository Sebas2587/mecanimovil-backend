"""Agrega ítems faltantes a un borrador y cotiza precio + fuente (catálogo/historial/web)."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
    _clave_fuzzy,
    enriquecer_repuestos_cotizacion,
    linea_necesita_busqueda_web,
    nombre_repuesto_buscable,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
    normalizar_repuesto,
    recalcular_totales,
)

logger = logging.getLogger(__name__)

MAX_ITEMS_POR_REQUEST = 12


def parsear_nombres_items(nombres: list[str] | None) -> list[str]:
    out: list[str] = []
    vistos: set[str] = set()
    for raw in nombres or []:
        nombre = ' '.join(str(raw or '').split()).strip()
        if not nombre_repuesto_buscable(nombre):
            continue
        clave = _clave_fuzzy(nombre)
        if not clave or clave in vistos:
            continue
        vistos.add(clave)
        out.append(nombre[:200])
        if len(out) >= MAX_ITEMS_POR_REQUEST:
            break
    return out


def _ya_existe(nombre: str, repuestos: list[dict[str, Any]]) -> bool:
    clave = _clave_fuzzy(nombre)
    if not clave:
        return False
    for rep in repuestos:
        if not isinstance(rep, dict):
            continue
        if _clave_fuzzy(str(rep.get('nombre') or '')) == clave:
            return True
    return False


def cotizar_items_faltantes(
    cotizacion,
    *,
    nombres: list[str] | None = None,
    repuestos_locales: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Agrega nombres nuevos, enriquece precios/fuente y dispara búsqueda web si falta.

    No pisa líneas con precio de catálogo/historial. Las líneas con monto 0
    (recién agregadas o escritas a mano) son la prioridad de la búsqueda web.
    """
    if cotizacion is None or getattr(cotizacion, 'estado', '') != 'borrador':
        raise ValueError('Solo se pueden cotizar ítems en un borrador.')

    if isinstance(repuestos_locales, list):
        base = [normalizar_repuesto(r, i) for i, r in enumerate(repuestos_locales)]
    else:
        base = list(cotizacion.repuestos or [])
        base = [normalizar_repuesto(r, i) for i, r in enumerate(base) if isinstance(r, dict)]

    nuevos_nombres = parsear_nombres_items(nombres)
    agregados: list[str] = []
    for nombre in nuevos_nombres:
        if _ya_existe(nombre, base):
            continue
        idx = len(base)
        linea = normalizar_repuesto(
            {
                'id': f'ia-item-{uuid.uuid4().hex[:10]}',
                'nombre': nombre,
                'cantidad': 1,
                'precio_unitario_clp': 0,
                'precio_estimado': True,
            },
            idx,
        )
        base.append(linea)
        agregados.append(nombre)

    pendientes_antes = [
        str(r.get('nombre') or '').strip()
        for r in base
        if linea_necesita_busqueda_web(r)
    ]
    if not agregados and not pendientes_antes:
        raise ValueError(
            'Indica al menos un ítem nuevo o deja líneas sin precio para cotizar.',
        )

    try:
        enriquecidos = enriquecer_repuestos_cotizacion(
            base,
            marca_vehiculo=cotizacion.vehiculo_marca or '',
            modelo_vehiculo=cotizacion.vehiculo_modelo or '',
            anio_vehiculo=cotizacion.vehiculo_anio or '',
            cilindraje=cotizacion.vehiculo_cilindraje or '',
            tipo_motor=cotizacion.tipo_motor or '',
            servicio_nombre=cotizacion.servicio_nombre or '',
            taller=cotizacion.taller,
            usar_ml=False,
            usar_web=True,
        )
    except Exception as exc:
        logger.warning(
            'cotizar_items_faltantes(%s): enrich falló, se guardan líneas sin precio: %s',
            getattr(cotizacion, 'id', None),
            exc,
        )
        enriquecidos = base

    costo_rep, _mo, total = recalcular_totales(
        enriquecidos,
        int(cotizacion.mano_obra_clp or 0),
    )
    cotizacion.repuestos = enriquecidos
    cotizacion.costo_repuestos_clp = costo_rep
    cotizacion.total_clp = total

    meta = dict(cotizacion.metadata or {})
    valores_estimativos = any(
        isinstance(r, dict) and r.get('precio_estimado') is not False
        for r in enriquecidos
    )
    meta['valores_estimativos'] = valores_estimativos and not bool(meta.get('precio_desde_catalogo'))

    pendientes = [r for r in enriquecidos if linea_necesita_busqueda_web(r)]
    disparo_web = False
    if pendientes:
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.disparar_busqueda_web import (
            disparar_busqueda_web_cotizacion,
            marcar_busqueda_web_pendiente,
        )

        meta = marcar_busqueda_web_pendiente(meta)
        disparo_web = meta.get('busqueda_web_estado') == 'pendiente'
        cotizacion.metadata = meta
        cotizacion.save(update_fields=[
            'repuestos',
            'costo_repuestos_clp',
            'total_clp',
            'metadata',
            'actualizado_en',
        ])
        if disparo_web:
            disparar_busqueda_web_cotizacion(cotizacion.id, sync=False)
    else:
        cotizacion.metadata = meta
        cotizacion.save(update_fields=[
            'repuestos',
            'costo_repuestos_clp',
            'total_clp',
            'metadata',
            'actualizado_en',
        ])

    return {
        'agregados': agregados,
        'busqueda_web': disparo_web,
        'cotizacion': cotizacion,
    }
