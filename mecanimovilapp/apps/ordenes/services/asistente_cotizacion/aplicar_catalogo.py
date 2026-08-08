"""Fusiona la cotización IA con OfertaServicio del taller (marca/modelo).

Cuando el taller tiene tarifa publicada para ese servicio + vehículo, esa data
gana sobre la estimación de Gemini: mano de obra, repuestos, marcas y precios.
Usado por generar-ia (modal Cotizar) y alineado con el borrador del agente chat.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

ADVERTENCIA_CATALOGO = 'Precio y repuestos tomados del catálogo publicado del taller (marca/modelo)'


def _split_servicios(servicio_nombre: str) -> list[str]:
    raw = (servicio_nombre or '').strip()
    if not raw:
        return []
    parts: list[str] = []
    for chunk in raw.replace('+', '|').replace(' y ', '|').split('|'):
        c = chunk.strip()
        if c:
            parts.append(c)
    return parts or [raw]


def construir_bloque_catalogo_prompt(
    *,
    taller,
    servicio_nombre: str,
    marca: str,
    modelo: str,
    tipo_motor: str = '',
) -> str:
    """Texto corto para el prompt: tarifas del taller para este vehículo."""
    if taller is None or not (servicio_nombre or '').strip():
        return ''
    try:
        from mecanimovilapp.apps.ordenes.services.catalogo_pricing import (
            buscar_oferta_exacta,
            precio_publico_oferta,
        )
    except Exception:
        return ''

    lineas: list[str] = []
    for nombre in _split_servicios(servicio_nombre)[:5]:
        oferta = buscar_oferta_exacta(
            taller=taller,
            servicio_nombre=nombre,
            marca=marca,
            modelo=modelo,
            tipo_motor=tipo_motor,
        )
        if not oferta:
            continue
        precio_con, _ = precio_publico_oferta(oferta, con_repuestos=True)
        precio_sin, _ = precio_publico_oferta(oferta, con_repuestos=False)
        marca_of = getattr(oferta.marca_vehiculo_seleccionada, 'nombre', '') or 'todas'
        modelo_of = getattr(oferta.modelo_vehiculo_seleccionado, 'nombre', '') or 'todos'
        reps = []
        for raw in (oferta.repuestos_seleccionados or [])[:8]:
            if not isinstance(raw, dict):
                continue
            rn = (raw.get('nombre') or raw.get('repuesto') or '').strip()
            rm = (raw.get('marca_repuesto') or raw.get('marca') or '').strip()
            rp = raw.get('precio_unitario_clp') or raw.get('precio') or ''
            if rn:
                reps.append(f'{rn}' + (f' ({rm})' if rm else '') + (f' ${rp}' if rp else ''))
        lineas.append(
            f'- Servicio catálogo: {oferta.servicio.nombre} | cobertura {marca_of}/{modelo_of} | '
            f'sin repuestos ${precio_sin} | con repuestos ${precio_con}'
            + (f' | piezas: {"; ".join(reps)}' if reps else '')
        )
    if not lineas:
        return ''
    return (
        'CATÁLOGO PUBLICADO DEL TALLER PARA ESTE VEHÍCULO (fuente prioritaria; '
        'usa estos montos/piezas si coinciden con el servicio pedido; no inventes otras marcas):\n'
        + '\n'.join(lineas)
    )


def fusionar_contenido_con_catalogo_taller(
    contenido: dict[str, Any],
    *,
    taller,
    servicio_nombre: str,
    marca: str,
    modelo: str,
    tipo_motor: str = '',
) -> dict[str, Any]:
    """Si hay OfertaServicio match, reemplaza mano/repuestos por desglose del taller."""
    if not isinstance(contenido, dict) or taller is None:
        return contenido
    try:
        from mecanimovilapp.apps.agente_ia.services.cotizacion_borrador import (
            _desglose_oferta_catalogo,
        )
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
            recalcular_totales,
        )
        from mecanimovilapp.apps.ordenes.services.catalogo_pricing import buscar_oferta_exacta
    except Exception as exc:
        logger.info('fusion catalogo no disponible: %s', exc)
        return contenido

    mano_total = 0
    reps_total: list[dict[str, Any]] = []
    matched = 0
    for nombre in _split_servicios(servicio_nombre) or [
        str(contenido.get('servicio_nombre') or ''),
    ]:
        if not (nombre or '').strip():
            continue
        oferta = buscar_oferta_exacta(
            taller=taller,
            servicio_nombre=nombre,
            marca=marca,
            modelo=modelo,
            tipo_motor=tipo_motor,
        )
        if not oferta:
            continue
        mano_lin, reps_lin = _desglose_oferta_catalogo(oferta, con_repuestos=True)
        if mano_lin <= 0 and not reps_lin:
            continue
        matched += 1
        mano_total += max(0, mano_lin)
        for r in reps_lin:
            r = dict(r)
            r['fuente_marketplace'] = 'catalogo'
            r['proveedor_nombre'] = 'Catálogo del taller'
            r['precio_estimado'] = False
            if not str(r.get('marca_repuesto') or '').strip():
                r.pop('marca_repuesto', None)
            reps_total.append(r)

    if matched <= 0:
        return contenido

    out = dict(contenido)
    # Catálogo del taller gana: reemplaza estimación IA para ese servicio/vehículo.
    out['mano_obra_clp'] = mano_total
    out['repuestos'] = reps_total
    costo_rep, mo, total = recalcular_totales(reps_total, mano_total)
    out['costo_repuestos_clp'] = costo_rep
    out['mano_obra_clp'] = mo
    out['total_clp'] = total
    out['valores_estimativos'] = False
    out['precio_desde_catalogo'] = True
    adv = [a for a in (out.get('advertencias') or []) if isinstance(a, str)]
    # Quita avisos de “estimado” genéricos si ya hay catálogo completo.
    adv = [
        a for a in adv
        if 'estimad' not in a.lower() or 'catálogo' in a.lower()
    ]
    if ADVERTENCIA_CATALOGO not in adv:
        adv.insert(0, ADVERTENCIA_CATALOGO)
    out['advertencias'] = adv
    logger.info(
        'Cotización fusionada con catálogo taller: matches=%s marca=%s modelo=%s servicio=%r',
        matched,
        marca,
        modelo,
        (servicio_nombre or '')[:80],
    )
    return out
