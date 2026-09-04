"""Normalización de respuesta IA de cotización."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def _to_int_clp(valor: Any, default: int = 0) -> int:
    if valor is None:
        return default
    if isinstance(valor, (int, float)):
        return max(0, int(round(valor)))
    texto = str(valor).strip()
    if not texto:
        return default
    digits = ''.join(ch for ch in texto if ch.isdigit())
    if not digits:
        return default
    try:
        return max(0, int(digits))
    except ValueError:
        return default


def _parse_rango_clp(texto: str) -> int:
    """Toma el promedio de un rango tipo '$40.000 - $80.000 CLP'."""
    partes = [p.strip() for p in str(texto).replace('–', '-').split('-') if p.strip()]
    valores = [_to_int_clp(p) for p in partes if _to_int_clp(p) > 0]
    if not valores:
        return _to_int_clp(texto)
    return int(sum(valores) / len(valores))


def normalizar_repuesto(item: Any, idx: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {
            'id': f'rep-{idx}',
            'nombre': str(item)[:200],
            'cantidad': 1,
            'precio_unitario_clp': 0,
            'precio_referencia_ia': 0,
            'comentario': '',
            'certeza': 'sin_precio',
            'precio_estimado': True,
        }
    nombre = str(item.get('nombre') or item.get('repuesto') or f'Repuesto {idx + 1}').strip()[:200]
    cantidad = max(1, _to_int_clp(item.get('cantidad'), 1))
    precio_raw = item.get('precio_unitario_clp')
    if precio_raw is None:
        precio_raw = item.get('precio_estimado_clp')
    if isinstance(precio_raw, str) and '-' in precio_raw:
        precio = _parse_rango_clp(precio_raw)
    else:
        precio = _to_int_clp(precio_raw)
    fuente_marketplace = str(
        item.get('fuente_marketplace') or item.get('fuente_repuesto') or '',
    ).strip()[:50]
    marca_repuesto = str(item.get('marca_repuesto') or '').strip()[:100]
    tienda_ml = str(item.get('tienda_ml') or '').strip()[:200]
    proveedor_nombre = str(item.get('proveedor_nombre') or '').strip()[:200]
    url_producto = str(item.get('url_producto') or '').strip()[:500]
    out: dict[str, Any] = {
        'id': str(item.get('id') or f'rep-{idx}'),
        'nombre': nombre,
        'cantidad': cantidad,
        # Precio final al cliente (IVA 19% incluido).
        'precio_unitario_clp': precio,
        'precio_referencia_ia': _to_int_clp(item.get('precio_referencia_ia'), precio),
        'precio_iva_incluido': True,
        'comentario': str(item.get('comentario') or '')[:500],
    }
    if fuente_marketplace:
        out['fuente_marketplace'] = fuente_marketplace
    if marca_repuesto:
        out['marca_repuesto'] = marca_repuesto
    if tienda_ml:
        out['tienda_ml'] = tienda_ml
    if proveedor_nombre:
        out['proveedor_nombre'] = proveedor_nombre
    if url_producto:
        out['url_producto'] = url_producto

    for key, caster in (
        ('certeza', lambda v: str(v or '').strip()[:20]),
        ('precio_min_clp', _to_int_clp),
        ('precio_max_clp', _to_int_clp),
        ('fuentes_n', _to_int_clp),
        ('precio_capturado_en', lambda v: str(v or '').strip()[:40]),
        ('proveedor_id', lambda v: int(v) if v not in (None, '') else None),
        ('precio_marketplace_clp', _to_int_clp),
        ('factor_mercado', lambda v: float(v) if v not in (None, '') else None),
        ('categoria', lambda v: str(v or '').strip()[:40]),
        ('especificacion', lambda v: str(v or '').strip()[:120]),
        ('familia_sensible', lambda v: str(v or '').strip()[:40]),
        ('codigo_parte', lambda v: str(v or '').strip()[:60]),
        ('compatibilidad', lambda v: str(v or '').strip()[:20]),
        ('motivo_sin_precio', lambda v: str(v or '').strip()[:40]),
        ('calidad', lambda v: str(v or '').strip()[:16]),
        ('imagen_url', lambda v: str(v or '').strip()[:500]),
        ('seleccion_cliente_en', lambda v: str(v or '').strip()[:40]),
    ):
        if key not in item or item.get(key) in (None, ''):
            continue
        try:
            val = caster(item.get(key))
        except (TypeError, ValueError):
            continue
        if val in (None, '', 0) and key not in ('proveedor_id', 'factor_mercado'):
            continue
        out[key] = val
    if item.get('especificacion_pendiente') is True:
        out['especificacion_pendiente'] = True
    if item.get('calidad_pendiente') is True:
        out['calidad_pendiente'] = True
    if item.get('seleccion_cliente') is True:
        out['seleccion_cliente'] = True
    alts = item.get('alternativas')
    if isinstance(alts, list) and alts:
        out['alternativas'] = alts[:6]
    fuentes = item.get('fuentes_detalle')
    if isinstance(fuentes, list) and fuentes:
        out['fuentes_detalle'] = [f for f in fuentes[:3] if isinstance(f, dict)]
    opciones = item.get('opciones')
    if isinstance(opciones, list) and opciones:
        out['opciones'] = [o for o in opciones[:8] if isinstance(o, dict)]

    from .calidad_repuesto import anotar_calidad_en_linea
    from .familias_sensibles import anotar_familia_en_linea
    from .resolver_precio import aplicar_derivados_certeza

    out = anotar_familia_en_linea(out)
    out = anotar_calidad_en_linea(out, descartar_invalida=False)
    aplicar_derivados_certeza(out)
    precio_out = _to_int_clp(out.get('precio_unitario_clp'))
    if precio_out > 0:
        out.setdefault('precio_min_clp', precio_out)
        out.setdefault('precio_max_clp', precio_out)
    return out


def recalcular_totales(
    repuestos: list[dict[str, Any]],
    mano_obra_clp: int,
) -> tuple[int, int, int]:
    costo_rep = 0
    for rep in repuestos:
        cant = max(1, int(rep.get('cantidad') or 1))
        precio = _to_int_clp(rep.get('precio_unitario_clp'))
        costo_rep += cant * precio
    mo = max(0, int(mano_obra_clp or 0))
    return costo_rep, mo, costo_rep + mo


DESCUENTO_TIPO_MONTO = 'monto'
DESCUENTO_TIPO_PORCENTAJE = 'porcentaje'
DESCUENTO_ALCANCE_MANO_OBRA = 'mano_obra'
DESCUENTO_ALCANCE_TOTAL = 'total'


def calcular_descuento_aplicado(
    *,
    costo_repuestos_clp: int,
    mano_obra_clp: int,
    descuento_tipo: str = '',
    descuento_alcance: str = DESCUENTO_ALCANCE_MANO_OBRA,
    descuento_valor=0,
) -> tuple[int, int]:
    """Descuento sobre bruto IVA-incl. Retorna (descuento_clp, total_clp)."""
    costo_rep = max(0, int(costo_repuestos_clp or 0))
    mo = max(0, int(mano_obra_clp or 0))
    bruto = costo_rep + mo
    tipo = (descuento_tipo or '').strip()
    if tipo not in (DESCUENTO_TIPO_MONTO, DESCUENTO_TIPO_PORCENTAJE):
        return 0, bruto
    alcance = (
        descuento_alcance
        if descuento_alcance in (DESCUENTO_ALCANCE_MANO_OBRA, DESCUENTO_ALCANCE_TOTAL)
        else DESCUENTO_ALCANCE_MANO_OBRA
    )
    base = mo if alcance == DESCUENTO_ALCANCE_MANO_OBRA else bruto
    if tipo == DESCUENTO_TIPO_PORCENTAJE:
        try:
            pct = float(descuento_valor or 0)
        except (TypeError, ValueError):
            pct = 0.0
        pct = min(100.0, max(0.0, pct))
        desc = int(round(base * pct / 100.0))
    else:
        desc = _to_int_clp(descuento_valor)
    desc = max(0, min(desc, base))
    return desc, max(0, bruto - desc)


def etiqueta_descuento(
    *,
    descuento_tipo: str = '',
    descuento_alcance: str = DESCUENTO_ALCANCE_MANO_OBRA,
    descuento_valor=0,
    descuento_clp: int = 0,
) -> str:
    if int(descuento_clp or 0) <= 0:
        return ''
    alcance_txt = (
        'mano de obra'
        if descuento_alcance != DESCUENTO_ALCANCE_TOTAL
        else 'total'
    )
    if (descuento_tipo or '').strip() == DESCUENTO_TIPO_PORCENTAJE:
        try:
            pct = float(descuento_valor or 0)
        except (TypeError, ValueError):
            pct = 0.0
        pct_txt = str(int(pct)) if pct == int(pct) else f'{pct:g}'
        return f'Descuento {pct_txt}% sobre {alcance_txt}'
    n = int(descuento_clp or 0)
    monto_txt = f'Descuento ${n:,}'.replace(',', '.')
    if (descuento_tipo or '').strip() == DESCUENTO_TIPO_MONTO:
        return f'{monto_txt} sobre {alcance_txt}'
    return monto_txt


def descuento_visible_clp(
    *,
    costo_repuestos_clp=0,
    mano_obra_clp=0,
    total_clp=0,
    descuento_clp=0,
) -> int:
    """Monto a mostrar: persistido o diferencia bruto − total a pagar."""
    stored = max(0, int(descuento_clp or 0))
    if stored > 0:
        return stored
    bruto = max(0, int(costo_repuestos_clp or 0)) + max(0, int(mano_obra_clp or 0))
    total = max(0, int(total_clp or 0))
    return max(0, bruto - total)


def aplicar_totales_cotizacion(cotizacion) -> None:
    """Recalcula repuestos, mano de obra bruta, descuento_clp y total a pagar."""
    costo_rep, mo, _bruto = recalcular_totales(
        list(cotizacion.repuestos or []),
        int(cotizacion.mano_obra_clp or 0),
    )
    desc, total = calcular_descuento_aplicado(
        costo_repuestos_clp=costo_rep,
        mano_obra_clp=mo,
        descuento_tipo=getattr(cotizacion, 'descuento_tipo', '') or '',
        descuento_alcance=getattr(cotizacion, 'descuento_alcance', '') or DESCUENTO_ALCANCE_MANO_OBRA,
        descuento_valor=getattr(cotizacion, 'descuento_valor', 0) or 0,
    )
    cotizacion.costo_repuestos_clp = costo_rep
    cotizacion.mano_obra_clp = mo
    cotizacion.descuento_clp = desc
    cotizacion.total_clp = total


def normalizar_cotizacion_ia(data: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    repuestos_raw = data.get('repuestos') or []
    if not isinstance(repuestos_raw, list):
        repuestos_raw = []
    repuestos = [normalizar_repuesto(r, i) for i, r in enumerate(repuestos_raw[:12])]

    mano_obra = _to_int_clp(data.get('mano_obra_clp'))
    if mano_obra == 0:
        mano_obra = _to_int_clp(data.get('costo_mano_obra_clp'))

    costo_rep, mo, total = recalcular_totales(repuestos, mano_obra)

    advertencias = data.get('advertencias') or []
    if not isinstance(advertencias, list):
        advertencias = [str(advertencias)]
    advertencias = [str(a).strip() for a in advertencias if str(a).strip()][:8]

    pedido = str(ctx.get('servicio_nombre') or '').strip()
    servicio = (
        pedido
        or str(data.get('servicio_nombre') or data.get('servicio') or 'Servicio mecánico').strip()
    )[:255]

    descripcion = str(
        data.get('descripcion_resumen')
        or data.get('descripcion_problema')
        or ctx.get('descripcion_problema')
        or ''
    ).strip()

    tipo_motor = str(data.get('tipo_motor_efectivo') or ctx.get('tipo_motor_efectivo') or '').strip()
    tipo_motor_label = str(
        data.get('tipo_motor_label')
        or ctx.get('tipo_motor_efectivo_label')
        or ''
    ).strip()
    aviso_motor = str(data.get('aviso_motor') or ctx.get('tipo_motor_conflicto_detalle') or '').strip()

    duracion = data.get('duracion_minutos_estimada')
    try:
        duracion_int = int(duracion) if duracion else None
        if duracion_int is not None and duracion_int <= 0:
            duracion_int = None
    except (TypeError, ValueError):
        duracion_int = None

    return {
        'servicio_nombre': servicio,
        'descripcion_problema': descripcion,
        'tipo_motor': tipo_motor,
        'tipo_motor_label': tipo_motor_label,
        'aviso_motor': aviso_motor,
        'duracion_minutos_estimada': duracion_int,
        'repuestos': repuestos,
        'mano_obra_clp': mo,
        'costo_repuestos_clp': costo_rep,
        'total_clp': total,
        'advertencias': advertencias,
    }
