"""
Funciones compartidas de scoring KPI (taller y mecánico).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.utils import timezone

from mecanimovilapp.apps.ordenes.services.kpi_constants import (
    BONUS_ACEPTACION_A_TIEMPO,
    PENALIZACION_RECHAZO_K,
    PENALIZACION_RECHAZOS_MULTIPLICADOR,
    PENALIZACION_RECHAZOS_RECIENTES_UMBRAL,
    PENALIZACION_RECHAZOS_RECIENTES_VENTANA_DIAS,
    RECHAZO_DECAY_DIAS,
    SEVERIDAD_RECHAZO_ORDEN,
    SEVERIDAD_RECHAZO_SOLICITUD_PUBLICA,
    SLA_ACEPTACION_ORDEN_MINUTOS,
)


@dataclass
class RechazoEvento:
    fecha: Any
    severidad: float


def _timedelta_to_minutes(td) -> float | None:
    if td is None:
        return None
    try:
        return round(td.total_seconds() / 60.0, 2)
    except Exception:
        return None


def score_tiempo_minutos_lineal(
    avg_minutes: float | None,
    *,
    max_minutes: float,
) -> int | None:
    """0 min → 100; >= max_minutes → 0 (lineal)."""
    if avg_minutes is None:
        return None
    return max(0, min(100, int(100 - min(avg_minutes, max_minutes) * (100.0 / max_minutes))))


def score_tiempo_aceptacion_minutos(avg_minutes: float | None) -> int | None:
    return score_tiempo_minutos_lineal(
        avg_minutes,
        max_minutes=float(SLA_ACEPTACION_ORDEN_MINUTOS),
    )


def peso_temporal_rechazo(fecha_evento, ahora=None) -> float:
    ahora = ahora or timezone.now()
    try:
        dias = max(0.0, (ahora - fecha_evento).total_seconds() / 86400.0)
    except Exception:
        return 1.0
    return math.exp(-dias / float(RECHAZO_DECAY_DIAS))


def score_confiabilidad_from_eventos(
    rechazos: list[RechazoEvento],
    *,
    aceptaciones_a_tiempo: int = 0,
    ahora=None,
) -> tuple[int, float]:
    """
    Score 0–100 desde rechazos ponderados + bonus por aceptaciones a tiempo.
    Retorna (score, penalizacion_acumulada).
    """
    ahora = ahora or timezone.now()
    penalizacion = 0.0
    for ev in rechazos:
        penalizacion += (
            peso_temporal_rechazo(ev.fecha, ahora)
            * ev.severidad
            * PENALIZACION_RECHAZO_K
        )
    bonus = min(10, aceptaciones_a_tiempo * BONUS_ACEPTACION_A_TIEMPO)
    score = int(round(max(0, min(100, 100 - penalizacion + bonus))))
    return score, penalizacion


def aplicar_multiplicador_rechazos_recientes(
    score: int,
    rechazos_ultimos_7_dias: int,
) -> tuple[int, float]:
    """Aplica -15% si hay >= umbral rechazos en ventana reciente."""
    if rechazos_ultimos_7_dias >= PENALIZACION_RECHAZOS_RECIENTES_UMBRAL:
        return max(0, int(round(score * PENALIZACION_RECHAZOS_MULTIPLICADOR))), PENALIZACION_RECHAZOS_MULTIPLICADOR
    return score, 1.0


def inicio_ventana_aceptacion_orden(orden) -> Any:
    """Timestamp desde el cual corre el SLA de aceptación."""
    if getattr(orden, 'fecha_pendiente_aceptacion_proveedor', None):
        return orden.fecha_pendiente_aceptacion_proveedor
    return getattr(orden, 'fecha_hora_solicitud', None)


def minutos_aceptacion_orden(orden) -> float | None:
    inicio = inicio_ventana_aceptacion_orden(orden)
    fin = getattr(orden, 'fecha_respuesta_proveedor', None)
    if not inicio or not fin:
        return None
    try:
        delta = fin - inicio
        return _timedelta_to_minutes(delta)
    except Exception:
        return None


def compute_score_aceptacion_ordenes(ordenes_qs) -> tuple[int | None, float | None, int]:
    """
    Promedio de score por orden respondida (aceptada o rechazada).
    Rechazada = 0 pts para esa orden.
    """
    scores: list[int] = []
    mins: list[float] = []
    for orden in ordenes_qs.iterator(chunk_size=200):
        if orden.estado == 'rechazada_por_proveedor':
            scores.append(0)
            m = minutos_aceptacion_orden(orden)
            if m is not None:
                mins.append(m)
            continue
        if orden.estado in (
            'aceptada_por_proveedor',
            'checklist_en_progreso',
            'checklist_completado',
            'en_proceso',
            'pendiente_firma_cliente',
            'completado',
            'servicio_iniciado',
        ):
            m = minutos_aceptacion_orden(orden)
            if m is None:
                continue
            mins.append(m)
            s = score_tiempo_aceptacion_minutos(m)
            if s is not None:
                scores.append(s)
    if not scores:
        return None, (round(sum(mins) / len(mins), 2) if mins else None), 0
    avg_min = round(sum(mins) / len(mins), 2) if mins else None
    return max(0, min(100, int(round(sum(scores) / len(scores))))), avg_min, len(scores)


def contar_rechazos_recientes(rechazos: list[RechazoEvento], dias: int = PENALIZACION_RECHAZOS_RECIENTES_VENTANA_DIAS) -> int:
    limite = timezone.now() - timedelta(days=dias)
    n = 0
    for ev in rechazos:
        try:
            if ev.fecha >= limite:
                n += 1
        except Exception:
            continue
    return n


def rechazos_proveedor_en_ventana(user, since, taller, mecanico) -> list[RechazoEvento]:
    """Rechazos de solicitud pública + órdenes rechazadas del proveedor."""
    from mecanimovilapp.apps.ordenes.models import RechazoSolicitud, SolicitudServicio

    eventos: list[RechazoEvento] = []

    for r in RechazoSolicitud.objects.filter(
        proveedor=user,
        fecha_rechazo__gte=since,
    ).only('fecha_rechazo'):
        eventos.append(RechazoEvento(fecha=r.fecha_rechazo, severidad=SEVERIDAD_RECHAZO_SOLICITUD_PUBLICA))

    orden_qs = SolicitudServicio.objects.filter(
        oferta_proveedor__isnull=False,
        estado='rechazada_por_proveedor',
        fecha_respuesta_proveedor__gte=since,
    )
    if taller:
        orden_qs = orden_qs.filter(taller=taller)
    else:
        orden_qs = orden_qs.filter(mecanico=mecanico)

    for o in orden_qs.only('fecha_respuesta_proveedor'):
        if o.fecha_respuesta_proveedor:
            eventos.append(
                RechazoEvento(fecha=o.fecha_respuesta_proveedor, severidad=SEVERIDAD_RECHAZO_ORDEN)
            )
    return eventos


def rechazos_mecanico_en_ventana(miembro, since) -> list[RechazoEvento]:
    from mecanimovilapp.apps.ordenes.models import SolicitudServicio

    eventos: list[RechazoEvento] = []
    qs = SolicitudServicio.objects.filter(
        mecanico_asignado=miembro,
        estado='rechazada_por_proveedor',
        fecha_respuesta_proveedor__gte=since,
    ).only('fecha_respuesta_proveedor')
    for o in qs:
        if o.fecha_respuesta_proveedor:
            eventos.append(
                RechazoEvento(fecha=o.fecha_respuesta_proveedor, severidad=SEVERIDAD_RECHAZO_ORDEN)
            )
    return eventos


def aceptaciones_a_tiempo_count(ordenes_qs) -> int:
    n = 0
    for orden in ordenes_qs.iterator(chunk_size=200):
        if orden.estado == 'rechazada_por_proveedor':
            continue
        m = minutos_aceptacion_orden(orden)
        if m is not None and m <= SLA_ACEPTACION_ORDEN_MINUTOS:
            n += 1
    return n


def ordenes_respondidas_en_ventana(orden_base_qs, since):
    """Órdenes marketplace con respuesta del proveedor en el periodo."""
    return orden_base_qs.filter(
        fecha_respuesta_proveedor__gte=since,
        estado__in=[
            'aceptada_por_proveedor',
            'rechazada_por_proveedor',
            'checklist_en_progreso',
            'checklist_completado',
            'en_proceso',
            'pendiente_firma_cliente',
            'completado',
            'servicio_iniciado',
        ],
    )
