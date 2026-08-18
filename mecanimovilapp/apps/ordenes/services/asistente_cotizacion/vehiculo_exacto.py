"""Igualdad estricta de marca+modelo para reuso de historial/precios.

Substring ("Yaris" ⊂ "Yaris Cross") NO cuenta. Falta marca o modelo → no reusar.
Guiones y espacios se ignoran: "T-Jet" ≡ "TJET", "CX-3" ≡ "CX3".
"""
from __future__ import annotations

import re
import unicodedata


def _norm_vehiculo_campo(texto: str) -> str:
    t = unicodedata.normalize('NFD', (texto or '').strip().lower())
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9]+', '', t)


def vehiculo_historial_identico(
    marca_a: str | None,
    modelo_a: str | None,
    marca_b: str | None,
    modelo_b: str | None,
) -> bool:
    """True solo si marca y modelo coinciden en ambos lados (normalizados)."""
    ma, moa = _norm_vehiculo_campo(marca_a or ''), _norm_vehiculo_campo(modelo_a or '')
    mb, mob = _norm_vehiculo_campo(marca_b or ''), _norm_vehiculo_campo(modelo_b or '')
    if not ma or not moa or not mb or not mob:
        return False
    return ma == mb and moa == mob


def _norm_clave_veh(texto: str) -> str:
    t = unicodedata.normalize('NFD', (texto or '').strip().lower())
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    t = re.sub(r'[^a-z0-9]+', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def clave_historial_cubre_vehiculo(
    clave: str,
    marca_vehiculo: str = '',
    modelo_vehiculo: str = '',
) -> bool:
    """True si la clave PrecioRepuestoWeb (`pieza|marca modelo [año]`) es de este auto.

    Claves fuzzy sin `|` (legado) nunca cubren un vehículo concreto.
    Un sufijo que no sea año (`yaris cross`) no matchea `yaris`.
    """
    raw = (clave or '').strip()
    if '|' not in raw:
        return False
    veh_part = raw.split('|', 1)[1]
    ma = _norm_clave_veh(marca_vehiculo)
    mo = _norm_clave_veh(modelo_vehiculo)
    if not ma or not mo:
        return False
    expected = f'{ma} {mo}'.strip()
    veh_n = _norm_clave_veh(veh_part)
    if not veh_n:
        return False
    if veh_n == expected:
        return True
    prefix = expected + ' '
    if veh_n.startswith(prefix):
        resto = veh_n[len(prefix) :].strip()
        return bool(resto) and resto.replace(' ', '').isdigit()
    return False
