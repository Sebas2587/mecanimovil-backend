"""
Política de etiqueta KPI visible a usuarios (no acumulable, ventana móvil).

Objetivo: incentivar buen desempeño reciente y reflejarlo en relevancia/etiqueta pública.

Notas de diseño:
- Ventana recomendada para etiqueta pública: 30 días (mobile dashboard puede explorar 7/90).
- La etiqueta requiere muestra mínima para evitar "congelar" un nivel alto sin actividad.
- Si no hay actividad reciente, la etiqueta se considera inactiva.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Optional


KpiBadgeCode = Literal[
    "ELITE",
    "MASTER",
    "PRO",
    "ASCENSO",
    "EN_PROGRESO",
    "SIN_ACTIVIDAD",
]


@dataclass(frozen=True)
class KpiBadge:
    code: KpiBadgeCode
    label: str
    short_label: str
    # Colores para UI (apps). Se entregan como hex para consumo directo.
    bg_color: str
    text_color: str
    border_color: str
    score: int
    window_days: int
    sample_points: int
    # True si hay actividad suficiente y la etiqueta es "válida" para ranking/visibilidad.
    is_active: bool
    # Mensaje corto para tooltips/ayuda.
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clamp_int(v: Any, lo: int, hi: int) -> int:
    try:
        n = int(v)
    except Exception:
        n = lo
    return max(lo, min(hi, n))


def _sample_points_from_kpis(kpis: dict[str, Any]) -> int:
    """
    Muestra mínima: puntos por señales recientes.
    - Ofertas: proxy de "respuesta" y participación.
    - Órdenes con actividad: proxy de ejecución real.
    - Reseñas en ventana: proxy de satisfacción reciente.
    """
    ofertas = _clamp_int(kpis.get("ofertas_total_en_periodo", 0), 0, 10_000)
    ordenes = _clamp_int(kpis.get("ordenes_mercado_en_periodo", 0), 0, 10_000)
    resenas = _clamp_int(kpis.get("resenas_muestra", 0), 0, 10_000)
    # Suma simple (fácil de explicar al proveedor).
    return ofertas + ordenes + resenas


def compute_kpi_badge_for_proveedor(
    *,
    proveedor_usuario,
    window_days: int = 30,
) -> Optional[dict[str, Any]]:
    """
    Calcula etiqueta KPI visible para usuarios.
    Retorna dict serializable o None si no se puede computar.
    """
    try:
        from mecanimovilapp.apps.ordenes.services.proveedor_kpis import compute_proveedor_kpis_resumen
    except Exception:
        return None

    window_days = _clamp_int(window_days, 1, 365)

    try:
        kpis = compute_proveedor_kpis_resumen(proveedor_usuario, dias=window_days)
    except Exception:
        return None

    score = _clamp_int(kpis.get("score_rendimiento", 50), 0, 100)
    sample_points = _sample_points_from_kpis(kpis)

    # Caducidad: sin actividad -> etiqueta inactiva (no aporta relevancia).
    if sample_points <= 0:
        badge = KpiBadge(
            code="SIN_ACTIVIDAD",
            label="KPI sin actividad reciente",
            short_label="Sin actividad",
            bg_color="#334155",  # slate-700 aprox
            text_color="#F8FAFC",
            border_color="#475569",
            score=score,
            window_days=window_days,
            sample_points=sample_points,
            is_active=False,
            reason=f"Sin ofertas/órdenes/reseñas en los últimos {window_days} días.",
        )
        return badge.to_dict()

    # Muestra mínima recomendada para 30 días:
    # - Evita que 1 reseña o 1 oferta "pinte" una etiqueta alta.
    min_sample_points = 5 if window_days <= 30 else 8
    has_min_sample = sample_points >= min_sample_points

    if not has_min_sample:
        badge = KpiBadge(
            code="EN_PROGRESO",
            label="KPI en progreso",
            short_label="En progreso",
            bg_color="#0F172A",  # slate-900
            text_color="#E2E8F0",
            border_color="#1F2937",
            score=score,
            window_days=window_days,
            sample_points=sample_points,
            is_active=False,
            reason=f"Muestra insuficiente ({sample_points} pts). Requiere ≥ {min_sample_points} pts en {window_days} días.",
        )
        return badge.to_dict()

    # Umbrales de tier (alineados al provider app; consistentes y fáciles de entender).
    if score >= 90:
        badge = KpiBadge(
            code="ELITE",
            label="KPI Elite",
            short_label="Elite",
            bg_color="#7C3AED",  # violeta distintivo
            text_color="#FFFFFF",
            border_color="#A78BFA",
            score=score,
            window_days=window_days,
            sample_points=sample_points,
            is_active=True,
            reason=f"Score ≥ 90 con muestra suficiente en {window_days} días.",
        )
    elif score >= 75:
        badge = KpiBadge(
            code="MASTER",
            label="KPI Máster",
            short_label="Máster",
            bg_color="#2563EB",  # azul
            text_color="#FFFFFF",
            border_color="#93C5FD",
            score=score,
            window_days=window_days,
            sample_points=sample_points,
            is_active=True,
            reason=f"Score ≥ 75 con muestra suficiente en {window_days} días.",
        )
    elif score >= 55:
        badge = KpiBadge(
            code="PRO",
            label="KPI Pro",
            short_label="Pro",
            bg_color="#059669",  # verde
            text_color="#FFFFFF",
            border_color="#6EE7B7",
            score=score,
            window_days=window_days,
            sample_points=sample_points,
            is_active=True,
            reason=f"Score ≥ 55 con muestra suficiente en {window_days} días.",
        )
    else:
        badge = KpiBadge(
            code="ASCENSO",
            label="KPI En ascenso",
            short_label="En ascenso",
            bg_color="#F59E0B",  # ámbar (incentivo a mejorar)
            text_color="#111827",
            border_color="#FCD34D",
            score=score,
            window_days=window_days,
            sample_points=sample_points,
            is_active=True,
            reason=f"Score < 55 pero con muestra suficiente en {window_days} días.",
        )

    return badge.to_dict()

