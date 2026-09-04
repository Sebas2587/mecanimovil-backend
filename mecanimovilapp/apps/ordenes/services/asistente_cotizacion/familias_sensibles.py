"""Familias de pieza cuya variante define el precio (bujía, pastilla, etc.)."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


FAMILIAS_SENSIBLES: dict[str, dict[str, Any]] = {
    'bujia': {
        'categoria': 'bujias',
        'label': 'Tipo de bujía',
        'opciones': ['Cobre', 'Platino', 'Iridio'],
        'keywords': ('bujia', 'bujias', 'spark plug'),
        'excluye': ('cable', 'bobina', 'pozo', 'conector', 'llave'),
        'eje_calidad': True,
    },
    'pastilla_freno': {
        'categoria': 'frenos',
        'label': 'Tipo de pastilla',
        'opciones': ['Orgánica', 'Semi-metálica', 'Cerámica'],
        'keywords': ('pastilla', 'pastillas', 'balata', 'balatas'),
        'eje_calidad': True,
    },
    'aceite_motor': {
        'categoria': 'aceites',
        'label': 'Tipo y viscosidad',
        'opciones': ['Mineral', 'Semi-sintético', 'Sintético'],
        'requiere_viscosidad': True,
        'keywords': ('aceite', 'lubricante'),
        # Un filtro o una bomba de aceite no se piden por viscosidad.
        'excluye': ('filtro', 'bomba', 'carter', 'enfriador', 'sensor', 'tapa', 'reten'),
        'eje_calidad': True,
    },
    'amortiguador': {
        'categoria': 'suspension',
        'label': 'Tipo',
        'opciones': ['Hidráulico', 'Gas'],
        'keywords': ('amortiguador', 'amortiguadores'),
        'excluye': ('soporte', 'base', 'goma', 'tope', 'buje', 'kit de montaje'),
        'eje_calidad': True,
    },
    'bateria': {
        'categoria': 'bateria',
        'label': 'Tecnología',
        'opciones': ['Convencional', 'EFB', 'AGM'],
        'keywords': ('bateria', 'baterias', 'acumulador'),
        'excluye': ('cable', 'borne', 'porta', 'soporte', 'sensor'),
        'eje_calidad': True,
    },
    'neumatico': {
        'categoria': 'otros',
        'label': 'Índice/medida',
        'opciones': [],
        'keywords': ('neumatico', 'neumaticos', 'llanta', 'llantas'),
        'eje_calidad': False,
    },
    'disco_freno': {
        'categoria': 'frenos',
        'label': 'Tipo',
        'opciones': ['Liso', 'Ventilado', 'Perforado'],
        'keywords': ('disco de freno', 'discos de freno', 'disco freno'),
        'eje_calidad': True,
    },
}


def _norm(texto: str) -> str:
    t = unicodedata.normalize('NFD', (texto or '').strip().lower())
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    t = re.sub(r'[^a-z0-9]+', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def familia_tiene_eje_calidad(nombre: str, familia: str | None = None) -> bool:
    fam = familia or detectar_familia_sensible(nombre)
    if fam and fam in FAMILIAS_SENSIBLES:
        return bool((FAMILIAS_SENSIBLES[fam] or {}).get('eje_calidad'))
    n = _norm(nombre)
    return any(k in n for k in ('filtro', 'embrague', 'clutch'))


def detectar_familia_sensible(nombre: str) -> str | None:
    n = _norm(nombre)
    if not n:
        return None
    for clave, meta in FAMILIAS_SENSIBLES.items():
        if any(ex in n for ex in meta.get('excluye') or ()):
            continue
        for key in meta.get('keywords') or ():
            if key in n:
                return clave
    return None


def _opciones_norm(familia: str) -> list[str]:
    meta = FAMILIAS_SENSIBLES.get(familia) or {}
    return [_norm(o) for o in (meta.get('opciones') or []) if o]


def _opciones_en_spec(familia: str, spec: str) -> list[str]:
    """Opciones que menciona el texto, sin contar las contenidas en otra más específica.

    "semi sintetico 10w40" menciona semi-sintético (y no también sintético).
    """
    encontradas = [op for op in _opciones_norm(familia) if op in spec or spec in op]
    return [
        op for op in encontradas
        if not any(otra != op and op in otra for otra in encontradas)
    ]


def especificacion_valida(familia: str, texto: str) -> bool:
    """True si el texto decide UNA variante de la familia (o la familia no exige opciones)."""
    spec = _norm(texto)
    if not spec:
        return False
    opciones = _opciones_norm(familia)
    if not opciones:
        return True
    encontradas = _opciones_en_spec(familia, spec)
    # Dos variantes ("cerámica o semi-metálica") no es una decisión: el precio cambia.
    if len(encontradas) >= 2:
        return False
    if encontradas:
        return True
    meta = FAMILIAS_SENSIBLES.get(familia) or {}
    if meta.get('requiere_viscosidad') and re.search(r'\d+\s*w\s*\d+', spec):
        return True
    return False


def linea_especificacion_pendiente(rep: dict[str, Any] | None) -> bool:
    if not isinstance(rep, dict):
        return False
    if bool(rep.get('especificacion_pendiente')):
        return True
    familia = (
        str(rep.get('familia_sensible') or '').strip()
        or detectar_familia_sensible(str(rep.get('nombre') or ''))
    )
    if not familia or familia not in FAMILIAS_SENSIBLES:
        return False
    spec = str(rep.get('especificacion') or '').strip()
    return not especificacion_valida(familia, spec)


def anotar_familia_en_linea(
    rep: dict[str, Any],
    *,
    descartar_spec_invalida: bool = True,
) -> dict[str, Any]:
    """Rellena familia_sensible / especificacion_pendiente sobre una copia.

    Al reanotar una línea que el taller está editando conviene
    `descartar_spec_invalida=False`: la marca se recalcula igual, pero no se
    borra el texto que acaba de escribir.
    """
    next_rep = dict(rep)
    nombre = str(next_rep.get('nombre') or '')
    familia = str(next_rep.get('familia_sensible') or '').strip() or detectar_familia_sensible(nombre)
    if familia:
        next_rep['familia_sensible'] = familia
        spec = str(next_rep.get('especificacion') or '').strip()
        if especificacion_valida(familia, spec):
            next_rep['especificacion'] = spec
            next_rep['especificacion_pendiente'] = False
        else:
            next_rep['especificacion_pendiente'] = True
            if descartar_spec_invalida:
                next_rep.pop('especificacion', None)
    else:
        next_rep.pop('familia_sensible', None)
        if not str(next_rep.get('especificacion') or '').strip():
            next_rep.pop('especificacion_pendiente', None)
    return next_rep
