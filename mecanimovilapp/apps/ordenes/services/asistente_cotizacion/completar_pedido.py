"""Si el taller pide un embrague, la cotización trae el trabajo completo.

Un cambio de embrague no es una sola línea. La casa vende el kit (disco,
prensa y rodamiento de empuje). Al bajar la caja se cambian el rodamiento
de volante y el aceite, y conviene el retén que queda a la vista. La piola,
si el taller la pidió, es un repuesto: no se queda solo en la mano de obra.
La faena es una: el monto cubre todas esas piezas.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any


_KIT_EMBRAGUE = (
    'Kit de embrague',
    ('kit',),
    'Disco, prensa y rodamiento de empuje. Así lo venden las casas de repuestos.',
)
_RODAMIENTO_VOLANTE = (
    'Rodamiento de volante',
    ('rodamiento de volante', 'rodamiento volante', 'rodamiento piloto', 'rodamiento de piloto', 'ruleman'),
    'Rodamiento piloto. No viene dentro del kit y no es el volante del motor.',
)
_ACEITE_CAJA = (
    'Aceite de caja de cambios',
    ('aceite de caja', 'aceite caja', 'valvulina', 'aceite de transmision'),
    'Insumo del cambio de embrague. Es el llenado de la caja, no la caja ni un tambor.',
)
_RETEN = (
    'Retén trasero de cigüeñal',
    ('reten', 'ciguenal'),
    'Queda a la vista al bajar la caja. Conviene cambiarlo en el mismo trabajo.',
)
_PIOLA = (
    'Piola de embrague',
    ('piola', 'guaya', 'cable de embrague', 'cable embrague'),
    'Cable de accionamiento. El taller lo pidió: es repuesto, no mano de obra.',
)
_PIEZA_DEL_KIT = ('disco', 'prensa', 'plato', 'collarin', 'empuje')
_FAENA = 'Cambio de embrague'


def completar_pedido_con_faena(contenido: dict[str, Any] | None, servicio_nombre: str = '') -> dict[str, Any]:
    """Un cambio de embrague incluye la faena única y cada pieza de ese trabajo."""
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
    reps = [rep for rep in reps if not _es_embrague_vago(str(rep.get('nombre') or ''))]
    for nombre, claves, comentario in _piezas_del_trabajo(pedido):
        if _ya_tiene(reps, claves):
            continue
        reps.append(_linea(nombre, comentario))
    data['repuestos'] = reps
    data['servicios_lineas'] = _faena_unica(data)
    data['mano_obra_clp'] = sum(
        int(lin.get('monto_clp') or 0) for lin in data['servicios_lineas']
    )
    return data


def _piezas_del_trabajo(pedido: str) -> tuple[tuple[str, tuple[str, ...], str], ...]:
    piezas = [_KIT_EMBRAGUE, _RODAMIENTO_VOLANTE, _ACEITE_CAJA, _RETEN]
    if _menciona_piola(pedido):
        piezas.append(_PIOLA)
    return tuple(piezas)


def _faena_unica(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Una sola faena de embrague. El monto suma lo que se había partido por pieza."""
    lineas = [lin for lin in (data.get('servicios_lineas') or []) if isinstance(lin, dict)]
    del_trabajo: list[dict[str, Any]] = []
    otras: list[dict[str, Any]] = []
    for lin in lineas:
        nombre = str(lin.get('nombre') or '')
        if _es_faena_generica(nombre) or _es_faena_de_este_trabajo(nombre):
            del_trabajo.append(lin)
        else:
            otras.append(lin)
    monto = sum(int(lin.get('monto_clp') or 0) for lin in del_trabajo)
    if monto <= 0 and not otras:
        monto = int(data.get('mano_obra_clp') or 0)
    faena = {'nombre': _FAENA, 'monto_clp': monto}
    if del_trabajo and str(del_trabajo[0].get('id') or '').strip():
        faena['id'] = del_trabajo[0]['id']
    return otras + [faena]


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


def _menciona_piola(texto: str) -> bool:
    n = _norm(texto)
    return 'piola' in n or 'guaya' in n or ('cable' in n and ('embrague' in n or 'clutch' in n))


def _es_faena_de_este_trabajo(nombre: str) -> bool:
    n = _norm(nombre)
    if 'embrague' in n or 'clutch' in n or 'piola' in n or 'guaya' in n:
        return True
    if 'volante' in n or 'piloto' in n:
        return True
    if 'aceite' in n and 'caja' in n:
        return True
    if 'reten' in n or 'ciguenal' in n:
        return True
    return False


def _es_embrague_vago(nombre: str) -> bool:
    """'Embrague completo' no es una ficha: el repuesto es el kit."""
    n = _norm(nombre)
    if 'embrague' not in n and 'clutch' not in n:
        return False
    if any(clave in n for clave in (
        'piola', 'cable', 'guaya', 'volante', 'piloto', 'aceite', 'reten',
        'sello', 'bombin', 'hidraulico', 'bimasa', 'kit', 'juego', 'set',
        'disco', 'prensa', 'plato', 'collarin', 'empuje',
    )):
        return False
    return True


def _es_pieza_suelta_del_kit(nombre: str) -> bool:
    """Disco, prensa o rodamiento de empuje sueltos: el kit de las casas ya los trae."""
    n = _norm(nombre)
    if 'embrague' not in n and 'clutch' not in n and 'collarin' not in n and 'empuje' not in n:
        return False
    if 'kit' in n or 'juego' in n or 'set' in n:
        return False
    if 'piloto' in n or 'aceite' in n or 'volante' in n or 'bimasa' in n:
        return False
    if 'piola' in n or 'cable' in n or 'guaya' in n:
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
