"""Pool único de opciones de una línea de repuesto (taller + vitrina)."""
from __future__ import annotations

import hashlib
import logging
from typing import Any
from urllib.parse import urlparse

from .calidad_repuesto import anotar_calidad_en_linea, detectar_calidad
from .resolver_precio import (
    CERTEZA_ASUMIDO,
    CERTEZA_CONFIRMADO,
    CERTEZA_REFERENCIAL,
    _to_int_clp,
)

logger = logging.getLogger(__name__)

MAX_OPCIONES_LINEA = 3
MAX_OPCIONES_TALLER = 8

_ORDEN_FUENTE = {
    'proveedor': 0,
    'catalogo': 1,
    'historial': 2,
    'web': 3,
    'mercadolibre': 4,
}

_FUENTES_TALLER = frozenset({'proveedor', 'catalogo'})

_OPCION_PUBLICA_KEYS = (
    'id',
    'nombre',
    'marca_repuesto',
    'especificacion',
    'calidad',
    'imagen_url',
    'precio_min_clp',
    'precio_max_clp',
    'posicion_relativa',
)

_OPCION_PUBLICA_PROHIBIDOS = (
    'tienda',
    'dominio',
    'url',
    'proveedor_id',
    'es_proveedor_taller',
    'fuente',
    'certeza',
    'confianza',
    'precio_clp',
)


def _dominio_de_url(url: str) -> str:
    try:
        host = (urlparse(url).hostname or '').lower()
    except Exception:
        return ''
    return host[4:] if host.startswith('www.') else host


def _id_opcion(*, fuente: str, dominio: str, clave: str, precio: int) -> str:
    raw = f'{fuente}|{dominio}|{clave}|{precio}'.encode('utf-8')
    return hashlib.sha1(raw).hexdigest()[:16]


def _certeza_de_fuente(fuente: str, es_proveedor: bool) -> str:
    if es_proveedor or fuente in _FUENTES_TALLER:
        return CERTEZA_CONFIRMADO
    if fuente in ('historial', 'web', 'mercadolibre'):
        return CERTEZA_REFERENCIAL
    return CERTEZA_ASUMIDO


def opcion_desde_hit(hit: dict[str, Any], linea: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not isinstance(hit, dict):
        return None
    fuente = str(hit.get('fuente_marketplace') or hit.get('fuente') or '').strip().lower()
    if fuente in ('estimado',):
        return None
    precio = _to_int_clp(hit.get('precio_unitario_clp') or hit.get('precio_clp'))
    url = str(hit.get('url_producto') or hit.get('url') or '')[:500]
    dominio = str(hit.get('dominio') or _dominio_de_url(url))[:200]
    tienda = str(hit.get('proveedor_nombre') or hit.get('tienda') or hit.get('tienda_ml') or '')[:200]
    nombre = str(
        hit.get('nombre_producto') or hit.get('nombre') or (linea or {}).get('nombre') or '',
    )[:200]
    if not nombre and precio <= 0 and not tienda:
        return None
    proveedor_id = hit.get('proveedor_id')
    try:
        proveedor_id = int(proveedor_id) if proveedor_id not in (None, '') else None
    except (TypeError, ValueError):
        proveedor_id = None
    es_proveedor = bool(proveedor_id) or fuente == 'proveedor'
    calidad = str(hit.get('calidad') or '').strip().lower()
    if calidad not in ('original', 'oem', 'alternativo'):
        calidad = detectar_calidad(
            ' '.join(str(hit.get(k) or '') for k in ('nombre', 'nombre_producto', 'especificacion', 'tienda')),
        ) or str((linea or {}).get('calidad') or '')
    spec = str(hit.get('especificacion') or (linea or {}).get('especificacion') or '')[:120]
    clave = str(hit.get('clave') or nombre)
    oid = str(hit.get('id') or '') or _id_opcion(
        fuente=fuente, dominio=dominio or tienda, clave=clave, precio=precio,
    )
    return {
        'id': oid,
        'nombre': nombre or str((linea or {}).get('nombre') or 'Repuesto')[:200],
        'marca_repuesto': str(hit.get('marca_repuesto') or (linea or {}).get('marca_repuesto') or '')[:100],
        'especificacion': spec,
        'calidad': calidad if calidad in ('original', 'oem', 'alternativo') else '',
        'precio_clp': precio,
        'precio_min_clp': _to_int_clp(hit.get('precio_min_clp')) or precio,
        'precio_max_clp': _to_int_clp(hit.get('precio_max_clp')) or precio,
        'fuente': fuente,
        'tienda': tienda,
        'dominio': dominio,
        'url': url,
        'es_proveedor_taller': es_proveedor,
        'proveedor_id': proveedor_id,
        'imagen_url': str(hit.get('imagen_url') or '')[:500],
        'certeza': str(hit.get('certeza') or _certeza_de_fuente(fuente, es_proveedor)),
        'compatibilidad': str(hit.get('compatibilidad') or '')[:20],
        'confianza': float(hit.get('confianza') or 0),
    }


def _dedupe_key(op: dict[str, Any]) -> str:
    dominio = str(op.get('dominio') or '').strip().lower()
    if dominio:
        return f"dom:{dominio}"
    tienda = str(op.get('tienda') or '').strip().lower()
    fuente = str(op.get('fuente') or '')
    precio = _to_int_clp(op.get('precio_clp'))
    return f'{fuente}|{tienda}|{precio}'


def ordenar_pool(opciones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _key(op: dict[str, Any]) -> tuple:
        fuente = str(op.get('fuente') or '')
        es_prov = 0 if op.get('es_proveedor_taller') or fuente in _FUENTES_TALLER else 1
        rango = _ORDEN_FUENTE.get(fuente, 9)
        conf = -float(op.get('confianza') or 0)
        precio = _to_int_clp(op.get('precio_clp')) or 10**12
        return (es_prov, rango, conf, precio)

    return sorted([o for o in opciones if isinstance(o, dict)], key=_key)


def _dedupe(opciones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for op in ordenar_pool(opciones):
        key = _dedupe_key(op)
        if key in seen:
            continue
        seen.add(key)
        out.append(op)
    return out


def spread_pool(opciones: list[dict[str, Any]]) -> float:
    precios = [_to_int_clp(o.get('precio_clp')) for o in opciones if _to_int_clp(o.get('precio_clp')) > 0]
    if len(precios) < 2:
        return 0.0
    lo, hi = min(precios), max(precios)
    if lo <= 0:
        return 0.0
    return (hi - lo) / lo


def _posicion_relativa(opciones: list[dict[str, Any]]) -> None:
    precios = [(i, _to_int_clp(o.get('precio_clp'))) for i, o in enumerate(opciones)]
    validos = [(i, p) for i, p in precios if p > 0]
    if not validos:
        for o in opciones:
            o['posicion_relativa'] = ''
        return
    orden = sorted(validos, key=lambda x: x[1])
    n = len(orden)
    for rank, (idx, _p) in enumerate(orden):
        if n == 1:
            opciones[idx]['posicion_relativa'] = 'intermedia'
        elif rank == 0:
            opciones[idx]['posicion_relativa'] = 'economica'
        elif rank == n - 1:
            opciones[idx]['posicion_relativa'] = 'mayor_precio'
        else:
            opciones[idx]['posicion_relativa'] = 'intermedia'


def construir_opciones_linea(
    rep: dict[str, Any],
    *,
    hits: list[dict[str, Any]] | None = None,
    vehiculo: dict[str, Any] | None = None,
    taller=None,
    calidad: str | None = None,
    max_opciones: int = MAX_OPCIONES_LINEA,
) -> list[dict[str, Any]]:
    """Arma el pool. `hits` evita reconsultar; si no hay, usa lo ya guardado en la línea."""
    _ = (vehiculo, taller)
    linea = anotar_calidad_en_linea(dict(rep or {}), descartar_invalida=False)
    if calidad in ('original', 'oem', 'alternativo'):
        linea['calidad'] = calidad
    crudos: list[dict[str, Any]] = []
    for hit in hits or []:
        op = opcion_desde_hit(hit, linea)
        if op:
            crudos.append(op)
    existentes = linea.get('opciones')
    if isinstance(existentes, list):
        for raw in existentes:
            if isinstance(raw, dict):
                crudos.append(raw if raw.get('id') else (opcion_desde_hit(raw, linea) or raw))
    alts = linea.get('alternativas')
    if isinstance(alts, list):
        for alt in alts:
            if not isinstance(alt, dict):
                continue
            etiqueta = str(alt.get('etiqueta') or '')
            mapa = {'economica': 'alternativo', 'equivalente': 'oem', 'premium': 'original'}
            hit = {
                'nombre': alt.get('nombre') or linea.get('nombre'),
                'marca_repuesto': alt.get('marca_repuesto'),
                'precio_unitario_clp': alt.get('precio_clp'),
                'url_producto': alt.get('url_producto'),
                'proveedor_nombre': alt.get('proveedor_nombre'),
                'especificacion': alt.get('especificacion'),
                'calidad': mapa.get(etiqueta, ''),
                'fuente_marketplace': 'web',
            }
            op = opcion_desde_hit(hit, linea)
            if op:
                crudos.append(op)
    for f in linea.get('fuentes_detalle') or []:
        if not isinstance(f, dict):
            continue
        op = opcion_desde_hit({
            'fuente_marketplace': f.get('fuente'),
            'proveedor_nombre': f.get('tienda'),
            'dominio': f.get('dominio'),
            'precio_unitario_clp': f.get('precio_clp'),
            'url_producto': f.get('url'),
            'nombre': linea.get('nombre'),
            'marca_repuesto': linea.get('marca_repuesto'),
            'especificacion': linea.get('especificacion'),
            'calidad': linea.get('calidad'),
        }, linea)
        if op:
            crudos.append(op)

    if calidad in ('original', 'oem', 'alternativo'):
        filtradas = [o for o in crudos if not o.get('calidad') or o.get('calidad') == calidad]
        crudos = filtradas or crudos

    out = _dedupe(crudos)[: max(1, int(max_opciones or MAX_OPCIONES_LINEA))]
    _posicion_relativa(out)
    return out


def construir_opciones_lineas(
    reps: list[dict[str, Any]],
    *,
    vehiculo: dict[str, Any] | None = None,
    taller=None,
    calidad: str | None = None,
    max_opciones: int = MAX_OPCIONES_LINEA,
) -> list[dict[str, Any]]:
    return [
        {
            **r,
            'opciones': construir_opciones_linea(
                r, vehiculo=vehiculo, taller=taller, calidad=calidad, max_opciones=max_opciones,
            ),
        }
        for r in reps
        if isinstance(r, dict)
    ]


def poblar_opciones_en_linea(
    next_rep: dict[str, Any],
    hits: list[dict[str, Any]],
    *,
    max_opciones: int = MAX_OPCIONES_LINEA,
) -> None:
    next_rep['opciones'] = construir_opciones_linea(next_rep, hits=hits, max_opciones=max_opciones)


def proyectar_opciones_publicas(opciones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for op in opciones or []:
        if not isinstance(op, dict):
            continue
        pub = {k: op.get(k) for k in _OPCION_PUBLICA_KEYS if k in op and op.get(k) not in (None, '')}
        for prohibido in _OPCION_PUBLICA_PROHIBIDOS:
            pub.pop(prohibido, None)
        if 'id' not in pub:
            continue
        out.append(pub)
    return out


def encontrar_opcion(linea: dict[str, Any], opcion_id: str) -> dict[str, Any] | None:
    oid = str(opcion_id or '')
    if not oid:
        return None
    for op in linea.get('opciones') or []:
        if isinstance(op, dict) and str(op.get('id') or '') == oid:
            return op
    pool = construir_opciones_linea(linea, max_opciones=MAX_OPCIONES_TALLER)
    return next((o for o in pool if str(o.get('id') or '') == oid), None)


def aplicar_usar_opcion(
    cotizacion,
    *,
    repuesto_id: str,
    opcion_id: str,
    guardar_en_mis_precios: bool = False,
    usuario=None,
) -> dict[str, Any]:
    from django.utils import timezone

    from mecanimovilapp.apps.ordenes.services.precios_proveedor import aplicar_confirmacion_linea

    reps = list(cotizacion.repuestos or [])
    idx = next(
        (i for i, r in enumerate(reps) if isinstance(r, dict) and str(r.get('id') or '') == str(repuesto_id)),
        None,
    )
    if idx is None:
        raise ValueError('No se encontró el repuesto en la cotización.')
    linea = dict(reps[idx])
    op = encontrar_opcion(linea, opcion_id)
    if op is None:
        raise ValueError('No se encontró esa opción para el repuesto.')
    precio = _to_int_clp(op.get('precio_clp'))
    if precio <= 0:
        raise ValueError('Esa opción no tiene un precio usable.')

    es_taller = bool(op.get('es_proveedor_taller') or op.get('fuente') in _FUENTES_TALLER)
    if es_taller:
        linea = aplicar_confirmacion_linea(
            cotizacion,
            repuesto_id=repuesto_id,
            precio_clp=precio,
            proveedor_id=op.get('proveedor_id'),
            proveedor_nombre=str(op.get('tienda') or ''),
            especificacion=str(op.get('especificacion') or linea.get('especificacion') or ''),
            guardar_en_mis_precios=guardar_en_mis_precios,
            usuario=usuario,
        )
        linea['calidad'] = op.get('calidad') or linea.get('calidad') or ''
        if op.get('imagen_url'):
            linea['imagen_url'] = op['imagen_url']
        linea['marca_repuesto'] = op.get('marca_repuesto') or linea.get('marca_repuesto') or ''
        reps = list(cotizacion.repuestos or [])
        for i, r in enumerate(reps):
            if isinstance(r, dict) and str(r.get('id') or '') == str(repuesto_id):
                reps[i] = linea
                break
        cotizacion.repuestos = reps
        return linea

    linea['precio_unitario_clp'] = precio
    linea['precio_min_clp'] = _to_int_clp(op.get('precio_min_clp')) or precio
    linea['precio_max_clp'] = _to_int_clp(op.get('precio_max_clp')) or precio
    linea['certeza'] = CERTEZA_ASUMIDO
    linea['precio_estimado'] = True
    linea['fuente_marketplace'] = str(op.get('fuente') or 'web')
    linea['proveedor_nombre'] = str(op.get('tienda') or '')
    linea['url_producto'] = str(op.get('url') or '')
    linea['marca_repuesto'] = str(op.get('marca_repuesto') or linea.get('marca_repuesto') or '')
    if op.get('calidad'):
        linea['calidad'] = op['calidad']
        linea['calidad_pendiente'] = False
    if op.get('especificacion'):
        linea['especificacion'] = op['especificacion']
    if op.get('imagen_url'):
        linea['imagen_url'] = op['imagen_url']
    linea['precio_capturado_en'] = timezone.now().isoformat()
    linea.pop('motivo_sin_precio', None)
    linea['fuentes_n'] = max(1, _to_int_clp(linea.get('fuentes_n')) or 1)
    linea['fuentes_detalle'] = [{
        'fuente': str(op.get('fuente') or 'web'),
        'tienda': str(op.get('tienda') or 'Referencia web'),
        'dominio': str(op.get('dominio') or ''),
        'precio_clp': precio,
        'url': str(op.get('url') or ''),
    }]
    reps[idx] = linea
    cotizacion.repuestos = reps
    return linea
