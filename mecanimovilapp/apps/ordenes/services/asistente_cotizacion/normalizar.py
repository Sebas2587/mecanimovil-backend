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
    return {
        'id': str(item.get('id') or f'rep-{idx}'),
        'nombre': nombre,
        'cantidad': cantidad,
        'precio_unitario_clp': precio,
        'precio_referencia_ia': precio,
        'comentario': str(item.get('comentario') or '')[:500],
    }


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

    servicio = str(
        data.get('servicio_nombre')
        or data.get('servicio')
        or ctx.get('servicio_nombre')
        or 'Servicio mecánico'
    ).strip()[:255]

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
