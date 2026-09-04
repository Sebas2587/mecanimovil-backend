"""Resuelve precio, banda y certeza de una línea de repuesto."""
from __future__ import annotations

from typing import Any

from .categoria_repuesto import categoria_de_repuesto, factor_mercado_categoria
from .familias_sensibles import linea_especificacion_pendiente


CERTEZA_CONFIRMADO = 'confirmado'
CERTEZA_ASUMIDO = 'asumido'
CERTEZA_REFERENCIAL = 'referencial'
CERTEZA_SIN_PRECIO = 'sin_precio'

_FUENTES_TALLER = ('proveedor', 'catalogo')
_FUENTES_REFERENCIAL = ('historial', 'web', 'mercadolibre')
_FUENTES_MERCADO = ('web', 'mercadolibre')


def _to_int_clp(valor: Any, default: int = 0) -> int:
    if valor is None:
        return default
    if isinstance(valor, (int, float)):
        return max(0, int(round(valor)))
    texto = str(valor).strip()
    if not texto:
        return default
    digits = ''.join(ch for ch in texto if ch.isdigit())
    if not digits:
        return default
    try:
        return max(0, int(digits))
    except ValueError:
        return default


def _confianza_habilitada() -> bool:
    try:
        from django.conf import settings

        return bool(getattr(settings, 'PRECIO_CONFIANZA_ENABLED', False))
    except Exception:
        return False


def backfill_certeza(rep: dict[str, Any]) -> str:
    """Deriva certeza de fuente/monto (PRD §7.9). No pisa una certeza ya válida."""
    actual = str(rep.get('certeza') or '').strip()
    if actual in (
        CERTEZA_CONFIRMADO, CERTEZA_ASUMIDO, CERTEZA_REFERENCIAL, CERTEZA_SIN_PRECIO,
    ):
        return actual
    fuente = str(rep.get('fuente_marketplace') or rep.get('fuente_repuesto') or '').strip().lower()
    if fuente in _FUENTES_TALLER:
        return CERTEZA_CONFIRMADO
    if fuente in _FUENTES_REFERENCIAL:
        return CERTEZA_REFERENCIAL
    precio = _to_int_clp(rep.get('precio_unitario_clp'))
    if precio > 0:
        return CERTEZA_REFERENCIAL
    return CERTEZA_SIN_PRECIO


def aplicar_derivados_certeza(rep: dict[str, Any]) -> None:
    """precio_estimado / precio_referencia_mercado se derivan de certeza."""
    certeza = backfill_certeza(rep)
    rep['certeza'] = certeza
    rep['precio_estimado'] = certeza != CERTEZA_CONFIRMADO
    if certeza == CERTEZA_REFERENCIAL:
        rep['precio_referencia_mercado'] = True
    else:
        rep.pop('precio_referencia_mercado', None)


def _hits_con_precio(hits: list[dict[str, Any]], fuentes: tuple[str, ...]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for hit in hits:
        if str(hit.get('fuente_marketplace') or '') not in fuentes:
            continue
        if _to_int_clp(hit.get('precio_unitario_clp')) > 0:
            out.append(hit)
    return out


def _aplicar_precio_legacy(next_rep: dict[str, Any], hits: list[dict[str, Any]]) -> None:
    """Comportamiento actual: catalogo → historial → web; ML solo si IA no tiene precio."""
    precio_ia = _to_int_clp(next_rep.get('precio_unitario_clp'))
    for fuente in ('catalogo', 'historial', 'web'):
        for hit in hits:
            if str(hit.get('fuente_marketplace') or '') != fuente:
                continue
            precio_hit = _to_int_clp(hit.get('precio_unitario_clp'))
            if precio_hit > 0:
                next_rep['precio_unitario_clp'] = precio_hit
                if fuente == 'web':
                    next_rep['precio_referencia_mercado'] = True
                return
    if precio_ia <= 0:
        for hit in hits:
            if str(hit.get('fuente_marketplace') or '') != 'mercadolibre':
                continue
            precio_hit = _to_int_clp(hit.get('precio_unitario_clp'))
            if precio_hit > 0:
                next_rep['precio_unitario_clp'] = precio_hit
                return


def resolver_precio_linea(
    next_rep: dict[str, Any],
    hits: list[dict[str, Any]],
    *,
    confianza_enabled: bool | None = None,
) -> None:
    """Asigna precio, banda y certeza. Mutación in-place.

    Con el flag apagado conserva el monto del pipeline actual y solo anota
    certeza/banda. Con el flag encendido: jerarquía nueva, factor de mostrador
    y la IA no escribe monto.
    """
    enabled = _confianza_habilitada() if confianza_enabled is None else confianza_enabled
    categoria = categoria_de_repuesto(next_rep)
    next_rep['categoria'] = categoria

    if linea_especificacion_pendiente(next_rep) and enabled:
        next_rep['especificacion_pendiente'] = True
        next_rep['compatibilidad'] = next_rep.get('compatibilidad') or 'no_verificada'
        next_rep['certeza'] = CERTEZA_SIN_PRECIO
        next_rep['precio_unitario_clp'] = 0
        next_rep['precio_estimado'] = True
        next_rep.pop('precio_referencia_mercado', None)
        return

    if not enabled:
        _aplicar_precio_legacy(next_rep, hits)
        precio = _to_int_clp(next_rep.get('precio_unitario_clp'))
        if precio > 0:
            next_rep.setdefault('precio_min_clp', precio)
            next_rep.setdefault('precio_max_clp', precio)
        aplicar_derivados_certeza(next_rep)
        return

    # Flag encendido: jerarquía proveedor → catalogo → historial → web/ML × factor → nada.
    for fuente, certeza in (
        ('proveedor', CERTEZA_CONFIRMADO),
        ('catalogo', CERTEZA_CONFIRMADO),
    ):
        taller_hits = _hits_con_precio(hits, (fuente,))
        if taller_hits:
            precio = _to_int_clp(taller_hits[0].get('precio_unitario_clp'))
            next_rep['precio_unitario_clp'] = precio
            next_rep['precio_min_clp'] = precio
            next_rep['precio_max_clp'] = precio
            next_rep['fuentes_n'] = 1
            next_rep['certeza'] = certeza
            next_rep['factor_mercado'] = 1.0
            aplicar_derivados_certeza(next_rep)
            return

    hist_hits = _hits_con_precio(hits, ('historial',))
    mercado_hits = _hits_con_precio(hits, _FUENTES_MERCADO)
    reales = hist_hits + mercado_hits
    if not reales:
        next_rep['precio_unitario_clp'] = 0
        next_rep['certeza'] = CERTEZA_SIN_PRECIO
        min_ia = _to_int_clp(next_rep.get('precio_min_clp'))
        max_ia = _to_int_clp(next_rep.get('precio_max_clp'))
        if min_ia > 0 and max_ia > 0:
            if min_ia > max_ia:
                min_ia, max_ia = max_ia, min_ia
            next_rep['precio_min_clp'] = min_ia
            next_rep['precio_max_clp'] = max_ia
        aplicar_derivados_certeza(next_rep)
        return

    precios_crudos = [_to_int_clp(h.get('precio_unitario_clp')) for h in reales]
    precios_ajustados: list[int] = []
    factor = 1.0
    crudo_ml = 0
    for hit, crudo in zip(reales, precios_crudos):
        fuente = str(hit.get('fuente_marketplace') or '')
        if fuente in _FUENTES_MERCADO:
            factor = factor_mercado_categoria(categoria)
            try:
                from django.conf import settings

                tope = float(getattr(settings, 'FACTOR_MERCADO_MAX', 2.50) or 2.50)
            except Exception:
                tope = 2.50
            factor = max(1.0, min(float(factor), tope))
            ajustado = int(round(crudo * factor))
            precios_ajustados.append(ajustado)
            if not crudo_ml:
                crudo_ml = crudo
        else:
            precios_ajustados.append(crudo)

    precio_min = min(precios_ajustados)
    precio_max = max(precios_ajustados)
    if len(mercado_hits) == 1 and not hist_hits:
        # 1 hit web: min = crudo, max = crudo × factor
        precio_min = crudo_ml or precios_crudos[0]
        precio_max = precios_ajustados[0]
    next_rep['precio_min_clp'] = precio_min
    next_rep['precio_max_clp'] = precio_max
    next_rep['precio_unitario_clp'] = precio_max
    next_rep['fuentes_n'] = len(reales)
    next_rep['certeza'] = CERTEZA_REFERENCIAL
    if crudo_ml:
        next_rep['precio_marketplace_clp'] = crudo_ml
        next_rep['factor_mercado'] = factor
    else:
        next_rep['factor_mercado'] = 1.0
    aplicar_derivados_certeza(next_rep)
