"""
Política de etiqueta KPI visible a usuarios (no acumulable, ventana móvil).

Objetivo: la pill pública (Elite / Máster / Pro / En ascenso) refleja el mismo
`score_rendimiento` que ve el proveedor en su app. La muestra mínima y la
actividad reciente solo afectan `is_active` (relevancia / orden en listados),
no el texto ni los colores del nivel.
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
    # True si hay actividad y muestra suficiente (relevancia / ranking en listados).
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


def _tier_from_score(score: int) -> KpiBadge:
    """
    Nivel visible siempre según score (umbrales alineados con la app proveedor).
    """
    if score >= 90:
        return KpiBadge(
            code="ELITE",
            label="KPI Elite",
            short_label="Elite",
            bg_color="#7C3AED",
            text_color="#FFFFFF",
            border_color="#A78BFA",
            score=score,
            window_days=0,
            sample_points=0,
            is_active=True,
            reason="",
        )
    if score >= 75:
        return KpiBadge(
            code="MASTER",
            label="KPI Máster",
            short_label="Máster",
            bg_color="#2563EB",
            text_color="#FFFFFF",
            border_color="#93C5FD",
            score=score,
            window_days=0,
            sample_points=0,
            is_active=True,
            reason="",
        )
    if score >= 55:
        return KpiBadge(
            code="PRO",
            label="KPI Pro",
            short_label="Pro",
            bg_color="#059669",
            text_color="#FFFFFF",
            border_color="#6EE7B7",
            score=score,
            window_days=0,
            sample_points=0,
            is_active=True,
            reason="",
        )
    return KpiBadge(
        code="ASCENSO",
        label="KPI En ascenso",
        short_label="En ascenso",
        bg_color="#F59E0B",
        text_color="#111827",
        border_color="#FCD34D",
        score=score,
        window_days=0,
        sample_points=0,
        is_active=True,
        reason="",
    )


def compute_kpi_badge_for_proveedor(
    *,
    proveedor_usuario,
    window_days: int = 30,
) -> Optional[dict[str, Any]]:
    """
    Calcula etiqueta KPI visible para usuarios.
    Retorna dict serializable o None si no se puede computar.

    La etiqueta (code / short_label / colores) sigue siempre al score de
    rendimiento. `is_active` indica si hay muestra suficiente en la ventana
    para tratar el KPI como “confiable” en ranking.
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

    min_sample_points = 5 if window_days <= 30 else 8
    has_min_sample = sample_points >= min_sample_points
    has_any_activity = sample_points > 0
    is_active = bool(has_any_activity and has_min_sample)

    tier = _tier_from_score(score)

    if not has_any_activity:
        reason = (
            f"Nivel por score de rendimiento ({score}/100). "
            f"Sin ofertas, órdenes de mercado ni reseñas en los últimos {window_days} días."
        )
    elif not has_min_sample:
        reason = (
            f"Nivel por score de rendimiento ({score}/100). "
            f"Muestra insuficiente ({sample_points} pts; se recomiendan ≥ {min_sample_points} en {window_days} días)."
        )
    elif tier.code == "ELITE":
        reason = f"Score ≥ 90 con muestra suficiente en {window_days} días."
    elif tier.code == "MASTER":
        reason = f"Score ≥ 75 con muestra suficiente en {window_days} días."
    elif tier.code == "PRO":
        reason = f"Score ≥ 55 con muestra suficiente en {window_days} días."
    else:
        reason = f"Score < 55 con muestra suficiente en {window_days} días."

    badge = KpiBadge(
        code=tier.code,
        label=tier.label,
        short_label=tier.short_label,
        bg_color=tier.bg_color,
        text_color=tier.text_color,
        border_color=tier.border_color,
        score=score,
        window_days=window_days,
        sample_points=sample_points,
        is_active=is_active,
        reason=reason,
    )
    return badge.to_dict()
