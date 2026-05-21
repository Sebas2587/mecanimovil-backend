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
    Muestra mínima: prioriza servicios terminados (checklist inicio+fin) y reseñas.
    Las ofertas solas aportan poco (no implican servicio ejecutado).
    """
    terminados = _clamp_int(
        kpis.get("servicios_terminados_en_periodo", kpis.get("ordenes_mercado_completadas", 0)),
        0,
        10_000,
    )
    resenas = _clamp_int(kpis.get("resenas_muestra", 0), 0, 10_000)
    ofertas = min(_clamp_int(kpis.get("ofertas_total_en_periodo", 0), 0, 10_000), 3)
    return terminados * 2 + resenas + ofertas


def _servicios_terminados_en_periodo(kpis: dict[str, Any]) -> int:
    return _clamp_int(
        kpis.get("servicios_terminados_en_periodo", kpis.get("ordenes_mercado_completadas", 0)),
        0,
        10_000,
    )


def _badge_sin_actividad(*, score: int, window_days: int, sample_points: int, reason: str) -> KpiBadge:
    return KpiBadge(
        code="SIN_ACTIVIDAD",
        label="Sin actividad reciente",
        short_label="Sin actividad",
        bg_color="#334155",
        text_color="#F8FAFC",
        border_color="#475569",
        score=score,
        window_days=window_days,
        sample_points=sample_points,
        is_active=False,
        reason=reason,
    )


def _badge_en_progreso(*, score: int, window_days: int, sample_points: int, reason: str) -> KpiBadge:
    capped = min(score, 54)
    return KpiBadge(
        code="EN_PROGRESO",
        label="KPI En progreso",
        short_label="En progreso",
        bg_color="#0F172A",
        text_color="#E2E8F0",
        border_color="#1F2937",
        score=capped,
        window_days=window_days,
        sample_points=sample_points,
        is_active=sample_points > 0,
        reason=reason,
    )


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

    score = _clamp_int(kpis.get("score_rendimiento", 0), 0, 100)
    sample_points = _sample_points_from_kpis(kpis)
    terminados = _servicios_terminados_en_periodo(kpis)

    min_sample_points = 5 if window_days <= 30 else 8
    has_min_sample = sample_points >= min_sample_points
    has_any_activity = sample_points > 0
    # Insignia alta solo con servicios realmente terminados en la ventana.
    has_completed_in_period = terminados > 0
    is_active = bool(has_completed_in_period and has_min_sample)

    if not has_any_activity:
        reason = (
            f"Sin ofertas, servicios terminados ni reseñas en los últimos {window_days} días."
        )
        badge = _badge_sin_actividad(
            score=0,
            window_days=window_days,
            sample_points=sample_points,
            reason=reason,
        )
        return badge.to_dict()

    if not has_completed_in_period:
        reason = (
            f"Hay actividad ({sample_points} pts de muestra) pero ningún servicio terminado "
            f"(checklist inicio y fin) en los últimos {window_days} días. "
            f"El nivel visible no puede ser Pro, Máster ni Elite hasta completar servicios."
        )
        badge = _badge_en_progreso(
            score=score,
            window_days=window_days,
            sample_points=sample_points,
            reason=reason,
        )
        return badge.to_dict()

    tier = _tier_from_score(score)

    if not has_min_sample:
        reason = (
            f"Score de rendimiento {score}/100 con {terminados} servicio(s) terminado(s). "
            f"Muestra insuficiente ({sample_points} pts; se recomiendan ≥ {min_sample_points} en {window_days} días)."
        )
        badge = _badge_en_progreso(
            score=score,
            window_days=window_days,
            sample_points=sample_points,
            reason=reason,
        )
        return badge.to_dict()

    if tier.code == "ELITE":
        reason = f"Score ≥ 90 con {terminados} servicio(s) terminado(s) en {window_days} días."
    elif tier.code == "MASTER":
        reason = f"Score ≥ 75 con {terminados} servicio(s) terminado(s) en {window_days} días."
    elif tier.code == "PRO":
        reason = f"Score ≥ 55 con {terminados} servicio(s) terminado(s) en {window_days} días."
    else:
        reason = (
            f"Score < 55 con {terminados} servicio(s) terminado(s) en {window_days} días."
        )

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
    out = badge.to_dict()
    out['servicios_terminados_en_periodo'] = terminados
    return out
