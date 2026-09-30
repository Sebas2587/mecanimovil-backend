"""Si el taller pide un kit, la cotización trae la faena y las piezas de ese cambio."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


_KIT_EMBRAGUE = (
    'Kit de embrague',
    ('kit',),
    'Disco, prensa y rodamiento de empuje. Así lo venden las casas de repuestos.',
)
_ASOCIADOS_CAMBIO = (
    ('Aceite de caja de cambios', ('aceite',), 'Insumo del cambio de embrague.'),
)
_PIEZA_DEL_KIT = ('disco', 'prensa', 'plato', 'collarin', 'empuje')


def completar_pedido_con_faena(contenido: dict[str, Any] | None, servicio_nombre: str = '') -> dict[str, Any]:
    """Un kit de embrague incluye el cambio y cada pieza que se compra para hacerlo."""
    data = dict(contenido or {})
    pedido = ' '.join(
        parte for parte in (
            servicio_nombre,
            str(data.get('servicio_nombre') or ''),
            str(data.get('descripcion_problema') or ''),
        ) if parte
    )
    if not _es_embrague(pedido) and not _es_embrague(_nombres(data)):
        return data
    reps = [rep for rep in (data.get('repuestos') or []) if isinstance(rep, dict)]
    reps = [rep for rep in reps if not _es_pieza_suelta_del_kit(str(rep.get('nombre') or ''))]
    nombre_kit, claves_kit, comentario_kit = _KIT_EMBRAGUE
    if not _ya_tiene(reps, claves_kit):
        reps.insert(0, _linea(nombre_kit, comentario_kit))
    for nombre, claves, comentario in _ASOCIADOS_CAMBIO:
        if _ya_tiene(reps, claves):
            continue
        reps.append(_linea(nombre, comentario))
    data['repuestos'] = reps
    data['servicios_lineas'] = _faena(data, servicio_nombre)
    return data


def _faena(data: dict[str, Any], servicio_nombre: str) -> list[dict[str, Any]]:
    lineas = [lin for lin in (data.get('servicios_lineas') or []) if isinstance(lin, dict)]
    if any(_es_embrague(str(lin.get('nombre') or '')) for lin in lineas):
        return lineas
    titulo = (servicio_nombre or str(data.get('servicio_nombre') or '')).strip()
    if not titulo.lower().startswith('cambio'):
        titulo = 'Cambio de embrague'
    monto = 0
    if len(lineas) == 1 and _es_faena_generica(str(lineas[0].get('nombre') or '')):
        monto = int(lineas[0].get('monto_clp') or data.get('mano_obra_clp') or 0)
        lineas[0]['nombre'] = titulo[:200]
        lineas[0]['monto_clp'] = monto
        return lineas
    if not lineas:
        monto = int(data.get('mano_obra_clp') or 0)
    lineas.append({'nombre': titulo[:200], 'monto_clp': monto})
    return lineas


def _linea(nombre: str, comentario: str) -> dict[str, Any]:
    return {
        'nombre': nombre,
        'cantidad': 1,
        'precio_unitario_clp': 0,
        'precio_min_clp': 0,
        'precio_max_clp': 0,
        'especificacion': '',
        'marca_repuesto': '',
        'fuente_marketplace': '',
        'tienda_ml': '',
        'comentario': comentario,
    }


def _es_embrague(texto: str) -> bool:
    n = _norm(texto)
    return 'embrague' in n or 'clutch' in n


def _es_pieza_suelta_del_kit(nombre: str) -> bool:
    """Disco, prensa o rodamiento de empuje sueltos: el kit de las casas ya los trae."""
    n = _norm(nombre)
    if 'embrague' not in n and 'clutch' not in n and 'collarin' not in n and 'empuje' not in n:
        return False
    if 'kit' in n or 'juego' in n or 'set' in n:
        return False
    if 'piloto' in n or 'aceite' in n or 'volante' in n or 'bimasa' in n:
        return False
    return any(pieza in n for pieza in _PIEZA_DEL_KIT)


def _es_faena_generica(nombre: str) -> bool:
    n = _norm(nombre)
    return n in ('', 'mano de obra', 'servicio', 'faena')


def _ya_tiene(repuestos: list[dict[str, Any]], claves: tuple[str, ...]) -> bool:
    for rep in repuestos:
        n = _norm(str(rep.get('nombre') or ''))
        if any(clave in n for clave in claves):
            return True
    return False


def _nombres(data: dict[str, Any]) -> str:
    return ' '.join(
        str(rep.get('nombre') or '')
        for rep in (data.get('repuestos') or [])
        if isinstance(rep, dict)
    )


def _norm(texto: str) -> str:
    plano = unicodedata.normalize('NFD', texto or '')
    plano = ''.join(ch for ch in plano if unicodedata.category(ch) != 'Mn')
    plano = re.sub(r'[^a-z0-9]+', ' ', plano.lower())
    return re.sub(r'\s+', ' ', plano).strip()
