"""Borrador usable si Gemini no responde (503, timeout, formato).

El cotizador no puede quedar inútil por un corte de Google: catálogo del taller,
plantilla del mismo vehículo y un esqueleto del pedido alcanzan para abrir el editor
y seguir buscando precios de piezas.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

ADVERTENCIA_RESPALDO = (
    'Armamos el borrador con el catálogo y el historial del taller. '
    'Revisa montos y espera las fichas de piezas antes de enviar.'
)


def contenido_respaldo_sin_gemini(
    *,
    ctx: dict[str, Any],
    servicio_nombre: str,
    descripcion_problema: str = '',
    taller=None,
) -> dict[str, Any]:
    """Siempre devuelve un contenido normalizado listo para guardar como borrador."""
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.aplicar_catalogo import (
        _split_servicios,
        fusionar_contenido_con_catalogo_taller,
    )
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
        normalizar_cotizacion_ia,
        recalcular_totales,
    )

    pedido = (servicio_nombre or str(ctx.get('servicio_nombre') or '')).strip() or 'Servicio mecánico'
    descripcion = (descripcion_problema or str(ctx.get('descripcion_problema') or '')).strip()
    chunks = _split_servicios(pedido) or [pedido]
    origen = 'esqueleto'

    contenido = _desde_plantilla_compatible(
        taller=taller,
        ctx=ctx,
        pedido=pedido,
        descripcion=descripcion,
    )
    if contenido is None:
        contenido = _esqueleto(ctx, pedido, descripcion, chunks)
    else:
        origen = 'plantilla'

    if taller is not None:
        try:
            contenido = fusionar_contenido_con_catalogo_taller(
                contenido,
                taller=taller,
                servicio_nombre=pedido,
                marca=str(ctx.get('marca') or ''),
                modelo=str(ctx.get('modelo') or ''),
                tipo_motor=str(ctx.get('tipo_motor_efectivo') or ''),
            )
        except Exception as exc:
            logger.info('respaldo: fusión catálogo omitida: %s', exc)

        try:
            from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
                enriquecer_repuestos_cotizacion,
            )

            reps = enriquecer_repuestos_cotizacion(
                list(contenido.get('repuestos') or []),
                marca_vehiculo=str(ctx.get('marca') or ''),
                modelo_vehiculo=str(ctx.get('modelo') or ''),
                anio_vehiculo=ctx.get('anio') or '',
                cilindraje=str(ctx.get('cilindraje') or ''),
                tipo_motor=str(ctx.get('tipo_motor_efectivo') or ''),
                servicio_nombre=pedido,
                taller=taller,
                usar_ml=False,
                usar_web=False,
            )
            costo_rep, mo, total = recalcular_totales(
                reps, int(contenido.get('mano_obra_clp') or 0),
            )
            contenido['repuestos'] = reps
            contenido['costo_repuestos_clp'] = costo_rep
            contenido['mano_obra_clp'] = mo
            contenido['total_clp'] = total
        except Exception as exc:
            logger.info('respaldo: enrich historial/catálogo omitido: %s', exc)

    contenido = normalizar_cotizacion_ia(contenido, ctx)
    contenido['servicio_nombre'] = pedido[:255]
    contenido['respaldo_sin_gemini'] = True
    contenido['origen_respaldo'] = origen
    contenido['valores_estimativos'] = not bool(contenido.get('precio_desde_catalogo'))
    contenido['servicios_lineas'] = _lineas_mano_obra(chunks, int(contenido.get('mano_obra_clp') or 0))
    adv = [a for a in (contenido.get('advertencias') or []) if isinstance(a, str)]
    if ADVERTENCIA_RESPALDO not in adv:
        adv.insert(0, ADVERTENCIA_RESPALDO)
    contenido['advertencias'] = adv[:8]
    logger.info(
        'Cotización respaldo sin Gemini origen=%s marca=%s modelo=%s servicio=%r',
        origen,
        ctx.get('marca'),
        ctx.get('modelo'),
        pedido[:80],
    )
    return contenido


def _esqueleto(
    ctx: dict[str, Any],
    pedido: str,
    descripcion: str,
    chunks: list[str],
) -> dict[str, Any]:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
        normalizar_cotizacion_ia,
    )

    reps = [
        {
            'id': f'respaldo-{i}',
            'nombre': nombre,
            'cantidad': 1,
            'precio_unitario_clp': 0,
            'precio_estimado': True,
        }
        for i, nombre in enumerate(chunks)
    ]
    return normalizar_cotizacion_ia(
        {
            'servicio_nombre': pedido,
            'descripcion_problema': descripcion,
            'mano_obra_clp': 0,
            'repuestos': reps,
            'advertencias': [ADVERTENCIA_RESPALDO],
        },
        ctx,
    )


def _desde_plantilla_compatible(
    *,
    taller,
    ctx: dict[str, Any],
    pedido: str,
    descripcion: str,
) -> dict[str, Any] | None:
    if taller is None:
        return None
    try:
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.aprendizaje_cotizacion import (
            buscar_plantilla_reutilizable,
        )
        from mecanimovilapp.apps.ordenes.services.catalogo_pricing import (
            oferta_nombre_compatible_con_pedido,
            pedido_familias_cubiertas_por_catalogos,
        )
    except Exception:
        return None

    plantilla = buscar_plantilla_reutilizable(
        taller=taller,
        marca=str(ctx.get('marca') or ''),
        modelo=str(ctx.get('modelo') or ''),
        servicio_nombre=pedido,
        cilindraje=str(ctx.get('cilindraje') or ''),
    )
    if plantilla is None:
        return None
    snap = plantilla.snapshot if isinstance(plantilla.snapshot, dict) else {}
    serv_p = str(snap.get('servicio_nombre') or plantilla.titulo or '').strip()
    if serv_p and not oferta_nombre_compatible_con_pedido(pedido, serv_p):
        if not pedido_familias_cubiertas_por_catalogos(pedido, [serv_p]):
            return None
    reps = snap.get('repuestos') or []
    if not isinstance(reps, list) or not reps:
        return None
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
        normalizar_cotizacion_ia,
    )

    return normalizar_cotizacion_ia(
        {
            'servicio_nombre': pedido,
            'descripcion_problema': descripcion or snap.get('descripcion_problema') or '',
            'mano_obra_clp': snap.get('mano_obra_clp') or 0,
            'repuestos': reps,
            'duracion_minutos_estimada': snap.get('duracion_minutos_estimada'),
            'advertencias': [ADVERTENCIA_RESPALDO],
        },
        ctx,
    )


def _lineas_mano_obra(chunks: list[str], mano_total: int) -> list[dict[str, Any]]:
    nombres = [c.strip() for c in chunks if (c or '').strip()] or ['Mano de obra']
    if len(nombres) == 1:
        return [{'nombre': nombres[0], 'monto_clp': max(0, mano_total)}]
    return [{'nombre': n, 'monto_clp': 0} for n in nombres]
