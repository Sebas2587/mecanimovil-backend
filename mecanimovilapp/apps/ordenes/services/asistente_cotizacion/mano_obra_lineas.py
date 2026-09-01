"""Líneas de mano de obra: metadata.servicios_lineas expuesto como mano_obra_lineas."""
from __future__ import annotations

import uuid
from typing import Any

from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import _to_int_clp

MAX_MANO_OBRA_LINEAS = 20
NOMBRE_FALLBACK_MO = 'Mano de obra'
_MONTO_KEYS = (
    'monto_clp',
    'precio_mano_obra_clp',
    'precio_clp',
    'precio_catalogo_clp',
)


def monto_linea_mo(linea: dict[str, Any] | None) -> int:
    if not isinstance(linea, dict):
        return 0
    for key in _MONTO_KEYS:
        if key not in linea or linea.get(key) is None:
            continue
        raw = linea.get(key)
        if isinstance(raw, str) and not raw.strip():
            continue
        return _to_int_clp(raw)
    return 0


def _lineas_crudas(cotizacion) -> list[dict[str, Any]]:
    meta = getattr(cotizacion, 'metadata', None)
    if not isinstance(meta, dict):
        return []
    raw = meta.get('servicios_lineas') or []
    if not isinstance(raw, list):
        return []
    return [lin for lin in raw if isinstance(lin, dict)]


def resolver_mano_obra_lineas(cotizacion, *, backfill: bool = True) -> list[dict[str, Any]]:
    """Normaliza a [{id, nombre, monto_clp}]. Backfill si no hay líneas y hay lump."""
    out: list[dict[str, Any]] = []
    for idx, lin in enumerate(_lineas_crudas(cotizacion)):
        nombre = str(lin.get('nombre') or '').strip()[:200]
        monto = monto_linea_mo(lin)
        if not nombre and monto <= 0 and not str(lin.get('id') or '').strip():
            continue
        lid = str(lin.get('id') or '').strip() or f'mo-{idx + 1}'
        out.append({
            'id': lid,
            'nombre': nombre or NOMBRE_FALLBACK_MO,
            'monto_clp': monto,
        })
        if len(out) >= MAX_MANO_OBRA_LINEAS:
            break
    if out:
        return out
    if not backfill:
        return []
    mo = _to_int_clp(getattr(cotizacion, 'mano_obra_clp', 0))
    if mo <= 0:
        return []
    titulo = str(getattr(cotizacion, 'servicio_nombre', '') or '').strip()
    return [{
        'id': 'mo-1',
        'nombre': (titulo or NOMBRE_FALLBACK_MO)[:200],
        'monto_clp': mo,
    }]


def mano_obra_lineas_publicas(cotizacion) -> list[dict[str, Any]]:
    return [
        {'nombre': lin['nombre'], 'monto_clp': lin['monto_clp']}
        for lin in resolver_mano_obra_lineas(cotizacion)
    ]


def persistir_mano_obra_lineas(cotizacion, lineas: list[Any]) -> None:
    """Escribe servicios_lineas conservando keys del agente. Actualiza mano_obra_clp."""
    existing = _lineas_crudas(cotizacion)
    by_id = {
        str(lin.get('id') or '').strip(): lin
        for lin in existing
        if str(lin.get('id') or '').strip()
    }
    merged: list[dict[str, Any]] = []
    for idx, raw in enumerate(list(lineas or [])[:MAX_MANO_OBRA_LINEAS]):
        if not isinstance(raw, dict):
            continue
        nombre = str(raw.get('nombre') or '').strip()[:200]
        monto = monto_linea_mo(raw)
        lid = str(raw.get('id') or '').strip() or f'mo-{uuid.uuid4().hex[:10]}'
        prev = by_id.get(lid)
        if prev is None and idx < len(existing):
            prev = existing[idx]
        row = dict(prev or {})
        row['id'] = lid
        row['nombre'] = nombre
        row['monto_clp'] = monto
        merged.append(row)
    meta = dict(getattr(cotizacion, 'metadata', None) or {})
    meta['servicios_lineas'] = merged
    cotizacion.metadata = meta
    cotizacion.mano_obra_clp = sum(monto_linea_mo(lin) for lin in merged)


def aplicar_mano_obra_en_edicion(cotizacion, data: dict[str, Any]) -> None:
    """PATCH: líneas ganan; lump legacy no pisa N>1."""
    if 'mano_obra_lineas' in data and isinstance(data.get('mano_obra_lineas'), list):
        persistir_mano_obra_lineas(cotizacion, data['mano_obra_lineas'])
        return
    if 'mano_obra_clp' not in data:
        return
    lump = _to_int_clp(data.get('mano_obra_clp'))
    resolved = resolver_mano_obra_lineas(cotizacion, backfill=False)
    if len(resolved) > 1:
        cotizacion.mano_obra_clp = sum(lin['monto_clp'] for lin in resolved)
        return
    if len(resolved) == 1:
        persistir_mano_obra_lineas(
            cotizacion,
            [{**resolved[0], 'monto_clp': lump}],
        )
        return
    if lump > 0:
        titulo = str(getattr(cotizacion, 'servicio_nombre', '') or '').strip()
        persistir_mano_obra_lineas(cotizacion, [{
            'id': 'mo-1',
            'nombre': (titulo or NOMBRE_FALLBACK_MO)[:200],
            'monto_clp': lump,
        }])
        return
    cotizacion.mano_obra_clp = 0


def validar_nombres_mano_obra_para_enviar(cotizacion) -> str | None:
    """Cada línea persistida con monto > 0 debe tener nombre. None = ok."""
    for lin in _lineas_crudas(cotizacion):
        if monto_linea_mo(lin) > 0 and not str(lin.get('nombre') or '').strip():
            return 'Cada línea de mano de obra con monto debe tener nombre.'
    return None
