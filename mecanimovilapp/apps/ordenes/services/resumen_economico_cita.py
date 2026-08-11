"""Resumen económico de cita personal para el taller (desglose + IVA)."""
from __future__ import annotations

from typing import Any


def _desglose_iva_desde_total(total_clp: int) -> dict[str, int]:
    total = max(0, int(total_clp or 0))
    if total <= 0:
        return {'neto_clp': 0, 'iva_clp': 0, 'total_clp': 0}
    neto = round(total / 1.19)
    iva = total - neto
    return {'neto_clp': neto, 'iva_clp': iva, 'total_clp': total}


def _repuestos_desde_cotizacion(cot) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(cot.repuestos or []):
        if not isinstance(raw, dict):
            continue
        cantidad = max(1, int(raw.get('cantidad') or 1))
        unit = max(0, int(raw.get('precio_unitario_clp') or 0))
        out.append(
            {
                'nombre': str(raw.get('nombre') or f'Repuesto {i + 1}').strip(),
                'cantidad': cantidad,
                'precio_unitario_clp': unit,
                'subtotal_clp': cantidad * unit,
                'marca_repuesto': str(raw.get('marca_repuesto') or '').strip(),
                'proveedor_nombre': str(
                    raw.get('proveedor_nombre') or raw.get('tienda_ml') or ''
                ).strip(),
            }
        )
    return out


def _repuestos_desde_oferta(oferta) -> list[dict[str, Any]]:
    from mecanimovilapp.apps.agente_ia.services.cotizacion_borrador import (
        _desglose_oferta_catalogo,
    )

    _, reps = _desglose_oferta_catalogo(oferta, con_repuestos=True)
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(reps or []):
        if not isinstance(raw, dict):
            continue
        cantidad = max(1, int(raw.get('cantidad') or 1))
        unit = max(0, int(raw.get('precio_unitario_clp') or 0))
        out.append(
            {
                'nombre': str(raw.get('nombre') or f'Repuesto {i + 1}').strip(),
                'cantidad': cantidad,
                'precio_unitario_clp': unit,
                'subtotal_clp': cantidad * unit,
                'marca_repuesto': str(raw.get('marca_repuesto') or '').strip(),
                'proveedor_nombre': str(raw.get('proveedor_nombre') or '').strip(),
            }
        )
    return out


def construir_resumen_economico_cita(cita) -> dict[str, Any] | None:
    """Arma desglose completo desde cotización origen, oferta o precio referencia."""
    det = getattr(cita, 'detalle', None)
    if det is None:
        return None

    servicio_nombre = (det.servicio_nombre or '').strip()
    if not servicio_nombre and det.oferta_servicio_id and det.oferta_servicio:
        serv = getattr(det.oferta_servicio, 'servicio', None)
        servicio_nombre = (getattr(serv, 'nombre', '') or '').strip()

    cot = getattr(cita, 'cotizacion_canal_origen', None)
    if cot is not None:
        repuestos = _repuestos_desde_cotizacion(cot)
        mano_obra = max(0, int(cot.mano_obra_clp or 0))
        costo_rep = max(0, int(cot.costo_repuestos_clp or 0)) or sum(
            r['subtotal_clp'] for r in repuestos
        )
        total = max(0, int(cot.total_clp or 0)) or (mano_obra + costo_rep)
        iva = _desglose_iva_desde_total(total)
        meta = cot.metadata if isinstance(cot.metadata, dict) else {}
        lineas_raw = meta.get('servicios_lineas') or []
        servicios_lineas = []
        for lin in lineas_raw:
            if not isinstance(lin, dict):
                continue
            nombre = str(lin.get('nombre') or '').strip()
            monto = int(lin.get('monto_clp') or lin.get('precio_catalogo_clp') or 0)
            if nombre:
                servicios_lineas.append({'nombre': nombre, 'monto_clp': max(0, monto)})

        return {
            'fuente': 'cotizacion',
            'cotizacion_id': cot.id,
            'servicio_nombre': cot.servicio_nombre or servicio_nombre,
            'descripcion_problema': (cot.descripcion_problema or det.descripcion or '').strip(),
            'mano_obra_clp': mano_obra,
            'costo_repuestos_clp': costo_rep,
            'total_clp': total,
            'neto_clp': iva['neto_clp'],
            'iva_clp': iva['iva_clp'],
            'precios_iva_incluido': True,
            'repuestos': repuestos,
            'servicios_lineas': servicios_lineas,
            'notas_internas': (cot.notas_internas or '').strip(),
        }

    oferta = getattr(det, 'oferta_servicio', None)
    if oferta is not None:
        mo_sin = max(0, int(oferta.costo_mano_de_obra_sin_iva or 0))
        rep_sin = max(0, int(oferta.costo_repuestos_sin_iva or 0))
        total = max(0, int(oferta.precio_con_repuestos or oferta.precio_publicado_cliente or 0))
        if not total and mo_sin + rep_sin > 0:
            total = round((mo_sin + rep_sin) * 1.19)
        iva = _desglose_iva_desde_total(total)
        repuestos = _repuestos_desde_oferta(oferta)
        costo_rep = sum(r['subtotal_clp'] for r in repuestos) or round(rep_sin * 1.19)
        mano_pub = max(0, int(oferta.precio_sin_repuestos or 0)) or round(mo_sin * 1.19)

        return {
            'fuente': 'oferta',
            'oferta_servicio_id': oferta.id,
            'servicio_nombre': servicio_nombre,
            'descripcion_problema': (det.descripcion or '').strip(),
            'mano_obra_clp': mano_pub,
            'mano_obra_sin_iva_clp': mo_sin,
            'costo_repuestos_clp': costo_rep,
            'costo_repuestos_sin_iva_clp': rep_sin,
            'total_clp': total,
            'neto_clp': iva['neto_clp'],
            'iva_clp': iva['iva_clp'],
            'precios_iva_incluido': True,
            'repuestos': repuestos,
            'servicios_lineas': [],
            'notas_internas': '',
        }

    precio_ref = det.precio_referencia
    if precio_ref is not None and float(precio_ref) > 0:
        total = max(0, int(round(float(precio_ref))))
        iva = _desglose_iva_desde_total(total)
        return {
            'fuente': 'referencia',
            'servicio_nombre': servicio_nombre,
            'descripcion_problema': (det.descripcion or '').strip(),
            'mano_obra_clp': 0,
            'costo_repuestos_clp': 0,
            'total_clp': total,
            'neto_clp': iva['neto_clp'],
            'iva_clp': iva['iva_clp'],
            'precios_iva_incluido': True,
            'repuestos': [],
            'servicios_lineas': [],
            'notas_internas': '',
        }

    if servicio_nombre or (det.descripcion or '').strip():
        return {
            'fuente': 'manual',
            'servicio_nombre': servicio_nombre,
            'descripcion_problema': (det.descripcion or '').strip(),
            'mano_obra_clp': 0,
            'costo_repuestos_clp': 0,
            'total_clp': 0,
            'neto_clp': 0,
            'iva_clp': 0,
            'precios_iva_incluido': True,
            'repuestos': [],
            'servicios_lineas': [],
            'notas_internas': '',
        }

    return None
