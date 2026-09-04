"""Clasificador determinista de categoría de repuesto (sin IA)."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


CATEGORIAS = (
    'bujias',
    'frenos',
    'filtros',
    'aceites',
    'suspension',
    'embrague',
    'distribucion',
    'bateria',
    'electrico',
    'refrigeracion',
    'otros',
)

_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('bujias', ('bujia', 'bujias', 'spark plug', 'sparkplug')),
    ('frenos', (
        'pastilla', 'pastillas', 'disco de freno', 'discos de freno',
        'freno', 'frenos', 'balata', 'balatas', 'caliper', 'mordaza',
    )),
    ('filtros', ('filtro', 'filtros')),
    ('aceites', ('aceite', 'lubricante', '5w', '10w', '15w', '0w')),
    ('suspension', (
        'amortiguador', 'amortiguadores', 'resorte', 'muelle',
        'rotula', 'terminal direccion', 'buje', 'brazo suspension',
    )),
    ('embrague', ('embrague', 'clutch', 'disco embrague', 'kit embrague', 'volante bimasa')),
    ('distribucion', (
        'correa distribucion', 'kit distribucion', 'cadena distribucion',
        'tensor distribucion', 'polea distribucion',
    )),
    ('bateria', ('bateria', 'baterias', 'acumulador')),
    ('electrico', (
        'alternador', 'motor de arranque', 'bobina', 'sensor',
        'inyector', 'modulo', 'computador', 'ecu', 'cables bujia',
    )),
    ('refrigeracion', (
        'radiador', 'termostato', 'bomba de agua', 'deposito refrigerante',
        'ventilador', 'anticongelante', 'refrigerante',
    )),
)


def _norm(texto: str) -> str:
    t = unicodedata.normalize('NFD', (texto or '').strip().lower())
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    t = re.sub(r'[^a-z0-9]+', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def clasificar_categoria(nombre: str) -> str:
    """Devuelve la categoría del nombre de pieza. Default: otros."""
    n = _norm(nombre)
    if not n:
        return 'otros'
    for categoria, keys in _KEYWORDS:
        for key in keys:
            if key in n:
                return categoria
    return 'otros'


def factor_mercado_categoria(categoria: str, *, default: float = 1.50) -> float:
    """Lee FactorMercadoCategoria; fallback al default si no hay fila."""
    cat = (categoria or 'otros').strip() or 'otros'
    try:
        from django.conf import settings
        from mecanimovilapp.apps.ordenes.models import FactorMercadoCategoria

        row = FactorMercadoCategoria.objects.filter(categoria=cat).first()
        if row is None:
            return float(default)
        factor = float(row.factor or default)
        tope = float(getattr(settings, 'FACTOR_MERCADO_MAX', 2.50) or 2.50)
        return max(1.0, min(factor, tope))
    except Exception:
        return float(default)


def categoria_de_repuesto(rep: dict[str, Any] | None) -> str:
    if not isinstance(rep, dict):
        return 'otros'
    cat = str(rep.get('categoria') or '').strip()
    if cat in CATEGORIAS:
        return cat
    return clasificar_categoria(str(rep.get('nombre') or ''))
