"""Coincidencia de plantillas de cotización con vehículo."""
from __future__ import annotations

import re
from typing import Any


def _norm_texto(valor: Any) -> str:
    return ' '.join(str(valor or '').upper().split())


def _norm_cilindraje(valor: Any) -> str:
    digits = re.sub(r'\D', '', str(valor or ''))
    if not digits:
        return ''
    return digits.lstrip('0') or digits


def plantilla_coincide_vehiculo(
    snapshot: dict[str, Any] | None,
    *,
    marca: str,
    modelo: str,
    cilindraje: str = '',
) -> bool:
    snap = snapshot or {}
    snap_marca = _norm_texto(snap.get('vehiculo_marca'))
    snap_modelo = _norm_texto(snap.get('vehiculo_modelo'))
    if not snap_marca or not snap_modelo:
        return False

    if _norm_texto(marca) != snap_marca:
        return False

    modelo_norm = _norm_texto(modelo)
    if modelo_norm != snap_modelo and modelo_norm not in snap_modelo and snap_modelo not in modelo_norm:
        return False

    snap_cil = _norm_cilindraje(snap.get('vehiculo_cilindraje'))
    cil_norm = _norm_cilindraje(cilindraje)
    if snap_cil and cil_norm and snap_cil != cil_norm:
        return False

    return True


def filtrar_plantillas_por_vehiculo(
    plantillas,
    *,
    marca: str,
    modelo: str,
    cilindraje: str = '',
):
    if not (marca or '').strip() or not (modelo or '').strip():
        return []
    return [
        p
        for p in plantillas
        if plantilla_coincide_vehiculo(
            getattr(p, 'snapshot', None) or {},
            marca=marca,
            modelo=modelo,
            cilindraje=cilindraje,
        )
    ]
