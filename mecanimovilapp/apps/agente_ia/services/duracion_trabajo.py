"""Duración efectiva de un trabajo para bloquear agenda (no copy del LLM)."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from mecanimovilapp.apps.usuarios.services.disponibilidad_proveedor import (
    DURACION_DEFAULT_MINUTOS,
    duracion_rango_oferta,
)

# Familias largas primero: un "cambio de embrague" no debe caer en 60 min.
_FAMILIAS_DURACION: tuple[tuple[int, tuple[str, ...]], ...] = (
    (360, ('embrague', 'clutch')),
    (360, ('distribucion', 'correa de tiempo', 'kit distribucion', 'correa de distribucion')),
    (240, ('amortiguadores', 'cuna')),
    (120, ('pastillas', 'discos', 'frenos')),
    (90, ('aceite', 'filtro', 'bujias')),
    (60, ('diagnostico', 'scanner', 'revision')),
)


def _norm(texto: str) -> str:
    raw = unicodedata.normalize('NFKD', texto or '')
    sin = ''.join(ch for ch in raw if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', sin.lower()).strip()


def duracion_familia_desde_texto(*textos: str) -> int | None:
    blob = _norm(' '.join(t for t in textos if t))
    if not blob:
        return None
    for minutos, keywords in _FAMILIAS_DURACION:
        if any(kw in blob for kw in keywords):
            return minutos
    return None


def formatear_duracion_humana(minutos: int) -> str:
    minutos = max(0, int(minutos or 0))
    if minutos < 60:
        return f'unos {minutos} minutos'
    h, r = divmod(minutos, 60)
    if r == 0:
        return '1 hora' if h == 1 else f'unas {h} horas'
    return f'unas {h} horas y {r} minutos'


def _ofertas_desde_cotizacion(cotizacion) -> list:
    if cotizacion is None:
        return []
    meta = cotizacion.metadata if isinstance(getattr(cotizacion, 'metadata', None), dict) else {}
    ids: list[int] = []
    for linea in meta.get('servicios_lineas') or []:
        oid = linea.get('oferta_servicio_id')
        if oid:
            try:
                ids.append(int(oid))
            except (TypeError, ValueError):
                continue
    if not ids:
        return []
    from mecanimovilapp.apps.servicios.models import OfertaServicio

    return list(OfertaServicio.objects.filter(pk__in=ids).select_related('servicio'))


def _nombres_desde_cotizacion(cotizacion) -> list[str]:
    nombres: list[str] = []
    if cotizacion is None:
        return nombres
    if getattr(cotizacion, 'servicio_nombre', None):
        nombres.append(str(cotizacion.servicio_nombre))
    meta = cotizacion.metadata if isinstance(getattr(cotizacion, 'metadata', None), dict) else {}
    for linea in meta.get('servicios_lineas') or []:
        nom = (linea.get('nombre') or '').strip()
        if nom:
            nombres.append(nom)
    return nombres


def resolver_duracion_trabajo(
    cotizacion=None,
    *,
    servicio_nombre: str = '',
    lineas: list[dict[str, Any]] | None = None,
) -> int:
    """Minutos a bloquear: cotización → ofertas → familia → 60.

    Un 60 genérico no pisa una familia larga (embrague / distribución).
    """
    estimada = None
    if cotizacion is not None:
        raw = getattr(cotizacion, 'duracion_minutos_estimada', None)
        try:
            estimada = int(raw) if raw else None
        except (TypeError, ValueError):
            estimada = None
        if estimada is not None and estimada <= 0:
            estimada = None

    nombres = list(_nombres_desde_cotizacion(cotizacion))
    if servicio_nombre:
        nombres.append(servicio_nombre)
    for linea in lineas or []:
        nom = (linea.get('nombre') or '').strip() if isinstance(linea, dict) else str(linea or '')
        if nom:
            nombres.append(nom)
    familia = duracion_familia_desde_texto(*nombres)

    if estimada and estimada > 0:
        if estimada == DURACION_DEFAULT_MINUTOS and familia and familia > DURACION_DEFAULT_MINUTOS:
            return familia
        return estimada

    ofertas = _ofertas_desde_cotizacion(cotizacion)
    total_oferta = 0
    all_generic = True
    for oferta in ofertas:
        _mn, mx = duracion_rango_oferta(oferta)
        total_oferta += int(mx or 0)
        if mx != DURACION_DEFAULT_MINUTOS:
            all_generic = False

    if total_oferta > 0 and not all_generic:
        return total_oferta
    if familia:
        return familia
    if total_oferta > 0:
        return total_oferta
    return DURACION_DEFAULT_MINUTOS
