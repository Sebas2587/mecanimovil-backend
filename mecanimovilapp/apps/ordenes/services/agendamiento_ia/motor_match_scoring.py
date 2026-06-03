"""
Scoring ML de coincidencia catálogo ↔ vehículo para motor_match.

Combina todas las señales de compatibilidad en un vector de features normalizado
y un score ponderado (NumPy). Usado por motor_match y MotorRecomendaciones.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from mecanimovilapp.apps.servicios.models import OfertaServicio
from mecanimovilapp.apps.servicios.oferta_resolucion import (
    prioridad_oferta_para_marca,
    prioridad_oferta_para_motor,
)
from mecanimovilapp.apps.usuarios.proveedor_cobertura import (
    TIPO_COBERTURA_ESPECIALISTA,
    TIPO_COBERTURA_MULTIMARCA,
)
from mecanimovilapp.apps.vehiculos.models import Vehiculo

MAX_RADIO_KM = 5.0
_DISTANCIA_SIN_UBICACION_KM = 999.0

# Pesos del modelo lineal (suman 1.0). Ajustables vía ConfiguracionPersonalizacion futuro.
FEATURE_KEYS = (
    'proximidad',
    'rating',
    'marca_oferta',
    'cobertura_proveedor',
    'motor',
    'repuestos',
    'historial',
    'zona_mecanico',
    'catalogo_completo',
    'dentro_radio',
)

PESOS_COINCIDENCIA: dict[str, float] = {
    'proximidad': 0.12,
    'rating': 0.08,
    'marca_oferta': 0.10,
    'cobertura_proveedor': 0.18,
    'motor': 0.18,
    'repuestos': 0.12,
    'historial': 0.08,
    'zona_mecanico': 0.05,
    'catalogo_completo': 0.04,
    'dentro_radio': 0.05,
}

# Bonus cuando especialista + motor exacto (no lo compensa solo estar más cerca).
_BONUS_COMPAT_EXACTA = 0.06


def _safe_float(value, default: float = 0.0) -> float:
    try:
        n = float(value if value is not None else default)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(n):
        return default
    return n


def _prioridad_a_feature(prioridad: int, *, exacto: float, universal: float, neutro: float) -> float:
    if prioridad >= 2:
        return exacto
    if prioridad == 0:
        return universal
    if prioridad == 1:
        return neutro
    return 0.0


@dataclass
class CoincidenciaCatalogoContext:
    vehiculo: Vehiculo | None = None
    marca_id: int | None = None
    requiere_repuestos: bool = True
    dist_km: float | None = None
    comunas: list[str] = field(default_factory=list)
    mecanico_cubre_comuna: bool = False
    con_ubicacion_cliente: bool = False
    catalogo_completo: bool = True
    oferta_ofrece_repuestos: bool = False


@dataclass
class ResultadoScoreCoincidencia:
    score: float
    explicacion: str
    factores: dict[str, float]
    contribuciones: dict[str, float]


def _score_proximidad(dist_km: float | None, *, con_ubicacion: bool) -> float:
    if dist_km is None or dist_km >= _DISTANCIA_SIN_UBICACION_KM:
        return 0.45 if con_ubicacion else 0.55
    dist = _safe_float(dist_km, default=MAX_RADIO_KM)
    prox = max(0.0, 1.0 - min(dist, MAX_RADIO_KM) / MAX_RADIO_KM)
    if dist <= 1.0:
        return min(1.0, prox + 0.08)
    return prox


def _score_cobertura_proveedor(proveedor, marca_id: int | None) -> float:
    if not proveedor:
        return 0.5
    tipo = getattr(proveedor, 'tipo_cobertura_marca', None) or ''
    if tipo in (TIPO_COBERTURA_ESPECIALISTA, 'por_marca', 'especialista'):
        return 1.0
    if tipo == TIPO_COBERTURA_MULTIMARCA:
        return 0.62
    if marca_id and hasattr(proveedor, 'marcas_atendidas'):
        try:
            if proveedor.marcas_atendidas.filter(id=marca_id).exists():
                return 0.88
        except Exception:
            pass
    return 0.70


def _id_en_frecuentes(proveedor_id: int | None, frecuentes) -> bool:
    if proveedor_id is None or not frecuentes:
        return False
    if isinstance(frecuentes, dict):
        return proveedor_id in frecuentes or str(proveedor_id) in frecuentes
    return proveedor_id in frecuentes


def _score_historial(oferta: OfertaServicio, perfil) -> float:
    base = 0.38
    if perfil is None:
        return base
    proveedor = oferta.taller or oferta.mecanico
    if not proveedor:
        return base
    talleres = getattr(perfil, 'talleres_frecuentes', None) or {}
    mecanicos = getattr(perfil, 'mecanicos_frecuentes', None) or {}
    if oferta.tipo_proveedor == 'taller' and _id_en_frecuentes(proveedor.id, talleres):
        return 0.96
    if oferta.tipo_proveedor == 'mecanico' and _id_en_frecuentes(proveedor.id, mecanicos):
        return 0.96
    categorias = getattr(perfil, 'categorias_frecuentes', None) or {}
    servicio = getattr(oferta, 'servicio', None)
    if servicio:
        try:
            cat = servicio.categorias.first()
            if cat and str(cat.id) in categorias:
                return max(base, 0.78)
        except Exception:
            pass
    return base


def _score_repuestos(*, requiere: bool, ofrece_repuestos: bool) -> float:
    if not requiere:
        return 0.82
    return 1.0 if ofrece_repuestos else 0.32


def _score_zona_mecanico(
    oferta: OfertaServicio,
    *,
    cubre_comuna: bool,
    dist_km: float | None,
) -> float:
    if oferta.tipo_proveedor != 'mecanico':
        return 0.85
    if cubre_comuna:
        return 1.0
    if dist_km is not None and dist_km < _DISTANCIA_SIN_UBICACION_KM:
        return 0.42
    return 0.50


def extraer_features_coincidencia(
    oferta: OfertaServicio,
    ctx: CoincidenciaCatalogoContext,
    *,
    perfil=None,
) -> dict[str, float]:
    """Features normalizadas en [0, 1] para el modelo lineal."""
    proveedor = oferta.taller or oferta.mecanico
    rating = _safe_float(getattr(proveedor, 'calificacion_promedio', 0)) / 5.0
    rating = min(1.0, max(0.0, rating))

    tipo_motor = getattr(ctx.vehiculo, 'tipo_motor', None) if ctx.vehiculo else None
    prio_marca = prioridad_oferta_para_marca(oferta, ctx.marca_id)
    prio_motor = prioridad_oferta_para_motor(oferta, tipo_motor)

    dist = ctx.dist_km
    dentro_radio = (
        dist is not None
        and dist < _DISTANCIA_SIN_UBICACION_KM
        and dist <= MAX_RADIO_KM
    )

    return {
        'proximidad': _score_proximidad(dist, con_ubicacion=ctx.con_ubicacion_cliente),
        'rating': rating if rating > 0 else 0.52,
        'marca_oferta': _prioridad_a_feature(
            prio_marca, exacto=1.0, universal=0.58, neutro=0.72,
        ),
        'cobertura_proveedor': _score_cobertura_proveedor(proveedor, ctx.marca_id),
        'motor': _prioridad_a_feature(
            prio_motor, exacto=1.0, universal=0.55, neutro=0.72,
        ),
        'repuestos': _score_repuestos(
            requiere=ctx.requiere_repuestos,
            ofrece_repuestos=ctx.oferta_ofrece_repuestos,
        ),
        'historial': _score_historial(oferta, perfil),
        'zona_mecanico': _score_zona_mecanico(
            oferta, cubre_comuna=ctx.mecanico_cubre_comuna, dist_km=dist,
        ),
        'catalogo_completo': 1.0 if ctx.catalogo_completo else 0.28,
        'dentro_radio': 1.0 if dentro_radio else (0.48 if ctx.con_ubicacion_cliente else 0.72),
    }


def _construir_explicacion(
    features: dict[str, float],
    contribuciones: dict[str, float],
    *,
    dist_km: float | None,
) -> str:
    partes: list[str] = []

    if dist_km is not None and dist_km < _DISTANCIA_SIN_UBICACION_KM:
        if dist_km < 5:
            partes.append(f'Muy cerca de ti ({dist_km:.1f} km)')
        elif dist_km < 25:
            partes.append(f'A {dist_km:.1f} km de tu ubicación')
        else:
            partes.append(f'A ~{dist_km:.0f} km de tu ubicación')
    else:
        partes.append('Ofrece el servicio para tu vehículo')

    ordenadas = sorted(contribuciones.items(), key=lambda x: x[1], reverse=True)
    etiquetas = {
        'cobertura_proveedor': 'Especialista en tu marca',
        'motor': 'Precio para tu tipo de motor',
        'marca_oferta': 'Tarifa específica para tu marca',
        'repuestos': 'Incluye repuestos en catálogo',
        'historial': 'Proveedor que ya conoces',
        'proximidad': 'Cercano a tu dirección',
        'rating': 'Buena calificación',
    }
    extras: list[str] = []
    for key, contrib in ordenadas:
        if key not in etiquetas or contrib < 0.045:
            continue
        if features.get(key, 0) < 0.55:
            continue
        label = etiquetas[key]
        if key == 'repuestos' and features.get('repuestos', 0) < 0.5:
            label = 'Solo mano de obra en catálogo'
        if label not in extras:
            extras.append(label)
        if len(extras) >= 2:
            break

    if extras:
        partes.append(' · '.join(extras))
    return ' · '.join(partes)


def calcular_score_coincidencia(
    oferta: OfertaServicio,
    ctx: CoincidenciaCatalogoContext,
    *,
    perfil=None,
    pesos: dict[str, float] | None = None,
) -> ResultadoScoreCoincidencia:
    """
    Score de coincidencia exacta usando producto punto features × pesos (NumPy).
    """
    pesos = pesos or PESOS_COINCIDENCIA
    features = extraer_features_coincidencia(oferta, ctx, perfil=perfil)

    keys = [k for k in FEATURE_KEYS if k in pesos]
    vec = np.array([features.get(k, 0.0) for k in keys], dtype=np.float64)
    w = np.array([pesos[k] for k in keys], dtype=np.float64)
    w_sum = w.sum()
    if w_sum > 0:
        w = w / w_sum

    raw = float(vec @ w)
    if (
        features.get('motor', 0) >= 0.99
        and features.get('cobertura_proveedor', 0) >= 0.99
    ):
        raw += _BONUS_COMPAT_EXACTA
    score = max(0.05, min(0.99, raw))

    contribuciones = {k: round(features[k] * pesos.get(k, 0.0), 4) for k in features}
    explicacion = _construir_explicacion(features, contribuciones, dist_km=ctx.dist_km)

    return ResultadoScoreCoincidencia(
        score=round(score, 3),
        explicacion=explicacion,
        factores={k: round(v, 3) for k, v in features.items()},
        contribuciones=contribuciones,
    )


def prioridad_orden_cobertura_proveedor(candidato: dict[str, Any]) -> int:
    """Menor valor = más preferido (especialista antes que multimarca)."""
    tipo = candidato.get('tipo_cobertura_marca') or ''
    if tipo in (TIPO_COBERTURA_ESPECIALISTA, 'por_marca', 'especialista'):
        return 0
    if tipo == TIPO_COBERTURA_MULTIMARCA:
        return 2
    return 1
