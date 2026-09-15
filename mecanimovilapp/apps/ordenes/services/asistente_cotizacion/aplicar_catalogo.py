"""Fusiona la cotización IA con OfertaServicio del taller (marca/modelo).

Cuando el taller tiene tarifa publicada para ese servicio + vehículo, esa data
gana sobre la estimación de Gemini: mano de obra, repuestos, marcas y precios.
Usado por generar-ia (modal Cotizar) y alineado con el borrador del agente chat.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

ADVERTENCIA_CATALOGO = 'Precio y repuestos tomados del catálogo publicado del taller (marca/modelo)'
ADVERTENCIA_CATALOGO_PARCIAL = (
    'Parte de los precios salió del catálogo del taller; el resto se mantiene de la IA. Revisa el desglose.'
)
_PREFIJO_SERVICIO_SPLIT_RE = re.compile(
    r'^(?:servicio\s+(?:para|de)\s+|servicios?\s+:?\s*)',
    re.IGNORECASE,
)
_SPLIT_LISTA_RE = re.compile(r'\s*[+|]\s*|,(?!\d)|;(?!\d)')


def _split_servicios(servicio_nombre: str) -> list[str]:
    raw = (servicio_nombre or '').strip()
    if not raw:
        return []
    raw = _PREFIJO_SERVICIO_SPLIT_RE.sub('', raw).strip() or raw

    def _es_pack_aceite(texto: str) -> bool:
        return bool(
            re.search(r'aceite\s+y\s+filtro\b', texto, re.IGNORECASE)
            and not re.search(
                r'filtro\s+de\s+(?:aire|polen|habit[aá]culo|cabina)',
                texto,
                re.IGNORECASE,
            )
        )

    out: list[str] = []
    for chunk in _SPLIT_LISTA_RE.split(raw):
        c = chunk.strip()
        if not c:
            continue
        if _es_pack_aceite(c):
            out.append(c)
            continue
        for sub in c.replace(' y ', '|').split('|'):
            s = sub.strip()
            if s:
                out.append(s)
    return out or [raw]


def _marcar_reps_catalogo(reps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in reps:
        item = dict(r)
        item['fuente_marketplace'] = 'catalogo'
        item['proveedor_nombre'] = 'Catálogo del taller'
        item['precio_estimado'] = False
        if not str(item.get('marca_repuesto') or '').strip():
            item.pop('marca_repuesto', None)
        out.append(item)
    return out


def _tokens_linea(texto: str) -> set[str]:
    from mecanimovilapp.apps.ordenes.services.catalogo_pricing import (
        _GENERIC_TOKENS,
        _tokens_servicio,
        texto_servicio_canonico,
    )

    return _tokens_servicio(texto_servicio_canonico(texto)) - _GENERIC_TOKENS


def _repuesto_ia_cubierto_por_catalogo(
    ia_rep: dict[str, Any],
    catalog_reps: list[dict[str, Any]],
    nombres_serv: list[str],
) -> bool:
    ia_tok = _tokens_linea(str(ia_rep.get('nombre') or ''))
    if not ia_tok:
        return False
    for cat in catalog_reps:
        cat_tok = _tokens_linea(str(cat.get('nombre') or ''))
        if ia_tok & cat_tok:
            return True
    for nombre in nombres_serv:
        if ia_tok & _tokens_linea(nombre):
            return True
    return False


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
            oferta_nombre_compatible_con_pedido,
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
        cat_nombre = getattr(getattr(oferta, 'servicio', None), 'nombre', '') or nombre
        if not oferta_nombre_compatible_con_pedido(nombre, cat_nombre):
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
    """Si hay OfertaServicio match, fusiona con la cotización IA.

    Solo reemplaza por completo cuando el catálogo cubre todas las familias del
    pedido (embrague, piola, etc.). Si matchea aceite y el taller pidió kit de
    embrague, se conserva la IA.
    """
    if not isinstance(contenido, dict) or taller is None:
        return contenido
    try:
        from mecanimovilapp.apps.agente_ia.services.cotizacion_borrador import (
            _desglose_oferta_catalogo,
        )
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
            recalcular_totales,
        )
        from mecanimovilapp.apps.ordenes.services.catalogo_pricing import (
            buscar_oferta_exacta,
            oferta_nombre_compatible_con_pedido,
            pedido_familias_cubiertas_por_catalogos,
        )
    except Exception as exc:
        logger.info('fusion catalogo no disponible: %s', exc)
        return contenido

    chunks = _split_servicios(servicio_nombre) or [
        str(contenido.get('servicio_nombre') or ''),
    ]
    mano_total = 0
    reps_total: list[dict[str, Any]] = []
    nombres_catalogo: list[str] = []
    matched = 0
    for nombre in chunks:
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
        cat_nombre = getattr(getattr(oferta, 'servicio', None), 'nombre', '') or nombre
        if not oferta_nombre_compatible_con_pedido(nombre, cat_nombre):
            continue
        mano_lin, reps_lin = _desglose_oferta_catalogo(oferta, con_repuestos=True)
        if mano_lin <= 0 and not reps_lin:
            continue
        matched += 1
        mano_total += max(0, mano_lin)
        nombres_catalogo.append(cat_nombre)
        reps_total.extend(_marcar_reps_catalogo(reps_lin))

    if matched <= 0:
        return contenido

    cubre_pedido = pedido_familias_cubiertas_por_catalogos(
        servicio_nombre or str(contenido.get('servicio_nombre') or ''),
        nombres_catalogo,
    )
    n_chunks = len([c for c in chunks if (c or '').strip()])
    if not cubre_pedido and n_chunks <= 1:
        logger.info(
            'Catálogo no cubre el pedido; se conserva IA. catalogo=%s servicio=%r',
            nombres_catalogo,
            (servicio_nombre or '')[:80],
        )
        return contenido

    out = dict(contenido)
    ia_reps = [
        dict(r) for r in (contenido.get('repuestos') or []) if isinstance(r, dict)
    ]
    ia_mano = int(contenido.get('mano_obra_clp') or 0)
    if cubre_pedido:
        out['repuestos'] = reps_total
        out['mano_obra_clp'] = mano_total
        out['valores_estimativos'] = False
        out['precio_desde_catalogo'] = True
        out['precio_parcial_catalogo'] = False
        aviso = ADVERTENCIA_CATALOGO
    else:
        kept_ia = [
            r
            for r in ia_reps
            if not _repuesto_ia_cubierto_por_catalogo(r, reps_total, nombres_catalogo)
        ]
        merged_reps = reps_total + kept_ia
        # Gemini ya cotizó la mano de obra del pedido completo; no la borres
        # ni la sumes al catálogo (doble cobro del ítem matcheado).
        merged_mano = ia_mano if ia_mano > 0 else mano_total
        out['repuestos'] = merged_reps
        out['mano_obra_clp'] = merged_mano
        out['precio_desde_catalogo'] = False
        out['precio_parcial_catalogo'] = True
        out['valores_estimativos'] = any(
            bool(r.get('precio_estimado', True)) for r in kept_ia
        ) if kept_ia else False
        aviso = ADVERTENCIA_CATALOGO_PARCIAL
        logger.info(
            'Cotización fusión parcial catálogo: matches=%s/%s catalogo=%s servicio=%r',
            matched,
            n_chunks,
            nombres_catalogo,
            (servicio_nombre or '')[:80],
        )

    costo_rep, mo, total = recalcular_totales(
        out.get('repuestos') or [],
        int(out.get('mano_obra_clp') or 0),
    )
    out['costo_repuestos_clp'] = costo_rep
    out['mano_obra_clp'] = mo
    out['total_clp'] = total
    adv = [a for a in (out.get('advertencias') or []) if isinstance(a, str)]
    if cubre_pedido:
        adv = [
            a for a in adv
            if 'estimad' not in a.lower() or 'catálogo' in a.lower()
        ]
    if aviso not in adv:
        adv.insert(0, aviso)
    out['advertencias'] = adv
    if cubre_pedido:
        logger.info(
            'Cotización fusionada con catálogo taller: matches=%s marca=%s modelo=%s servicio=%r',
            matched,
            marca,
            modelo,
            (servicio_nombre or '')[:80],
        )
    return out
