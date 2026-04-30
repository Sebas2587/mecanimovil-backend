"""
Agregación de KPIs para proveedores (solicitudes públicas / marketplace).

Criterios de ventana: actividad reciente (orden creada, checklist o reseña en el periodo),
no solo fecha_hora_solicitud. Reseñas: todas las del taller/mecánico, no solo las ligadas a solicitud.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import Avg, Count, Q
from django.utils import timezone


def _timedelta_to_minutes(td) -> float | None:
    if td is None:
        return None
    try:
        return round(td.total_seconds() / 60.0, 2)
    except Exception:
        return None


def _score_tiempo_respuesta_minutos(avg_minutes: float | None) -> int | None:
    if avg_minutes is None:
        return None
    return max(0, min(100, int(100 - min(avg_minutes, 120) * (100.0 / 120.0))))


def _score_calificacion(avg_rating: float | None) -> int | None:
    if avg_rating is None:
        return None
    return max(0, min(100, int(round((avg_rating - 1.0) / 4.0 * 100))))


def _score_checklist_cumplimiento(pct: float | None) -> int | None:
    if pct is None:
        return None
    return max(0, min(100, int(round(pct))))


def _merge_score(components: list[int | None]) -> int:
    vals = [c for c in components if c is not None]
    if not vals:
        return 50
    return max(0, min(100, int(round(sum(vals) / len(vals)))))


def _resenas_qs(taller, mecanico):
    from mecanimovilapp.apps.usuarios.models import Resena

    if taller:
        return Resena.objects.filter(taller=taller)
    return Resena.objects.filter(mecanico=mecanico)


def _orden_mercado_base(taller, mecanico):
    from mecanimovilapp.apps.ordenes.models import SolicitudServicio

    qs = SolicitudServicio.objects.filter(oferta_proveedor__isnull=False)
    if taller:
        return qs.filter(taller=taller)
    return qs.filter(mecanico=mecanico)


def _ordenes_en_ventana_actividad(base_qs, since):
    """Órdenes con oferta donde hubo actividad en el periodo (creación, checklist o reseña)."""
    return base_qs.filter(
        Q(fecha_hora_solicitud__gte=since)
        | Q(checklist_instance__fecha_finalizacion__gte=since)
        | Q(checklist_instance__fecha_inicio__gte=since)
        | Q(resena__fecha_hora_resena__gte=since)
    ).distinct()


def _minutos_respuesta_oferta(oferta) -> float | None:
    """Minutos desde publicación de la solicitud hasta envío de la oferta."""
    if oferta.tiempo_respuesta_proveedor:
        return oferta.tiempo_respuesta_proveedor.total_seconds() / 60.0
    sol = oferta.solicitud
    if sol and sol.fecha_publicacion and oferta.fecha_envio:
        try:
            return (oferta.fecha_envio - sol.fecha_publicacion).total_seconds() / 60.0
        except Exception:
            return None
    return None


def _avg_minutes_from_ofertas(qs):
    mins: list[float] = []
    for o in qs.select_related('solicitud').iterator(chunk_size=300):
        m = _minutos_respuesta_oferta(o)
        if m is not None and m >= 0:
            mins.append(m)
    if not mins:
        return None
    return round(sum(mins) / len(mins), 2)


def _checklist_minutes_real(inst) -> float | None:
    if inst.tiempo_total_minutos is not None:
        return float(inst.tiempo_total_minutos)
    if inst.fecha_inicio and inst.fecha_finalizacion:
        try:
            return (inst.fecha_finalizacion - inst.fecha_inicio).total_seconds() / 60.0
        except Exception:
            return None
    return None


def compute_proveedor_kpis_resumen(user, dias: int = 30) -> dict[str, Any]:
    from mecanimovilapp.apps.checklists.models import ChecklistInstance
    from mecanimovilapp.apps.ordenes.models import OfertaProveedor

    dias = max(1, min(int(dias), 365))
    since = timezone.now() - timedelta(days=dias)

    taller = getattr(user, 'taller', None)
    mecanico = getattr(user, 'mecanico_domicilio', None)
    if not taller and not mecanico:
        return _empty_payload(dias)

    # --- Reseñas del proveedor (todas las que dejó un cliente al taller/mecánico) ---
    rq_all = _resenas_qs(taller, mecanico)
    rq_periodo = rq_all.filter(fecha_hora_resena__gte=since)
    agg_all = rq_all.aggregate(avg=Avg('calificacion'), n=Count('id'))
    agg_periodo = rq_periodo.aggregate(avg=Avg('calificacion'), n=Count('id'))
    n_resenas_total = agg_all['n'] or 0
    n_resenas_periodo = agg_periodo['n'] or 0
    avg_rating_all = agg_all['avg']
    avg_rating_periodo = agg_periodo['avg']
    calificacion_para_score = (
        float(avg_rating_periodo) if n_resenas_periodo > 0 and avg_rating_periodo is not None
        else (float(avg_rating_all) if n_resenas_total > 0 and avg_rating_all is not None else None)
    )
    calificacion_muestra_ui = (
        float(avg_rating_periodo) if n_resenas_periodo > 0 and avg_rating_periodo is not None
        else (float(avg_rating_all) if avg_rating_all is not None else None)
    )

    # --- Ofertas con actividad en ventana (envío o solicitud publicada en periodo) ---
    base_ofertas = OfertaProveedor.objects.filter(
        proveedor=user,
        es_oferta_secundaria=False,
    ).filter(Q(fecha_envio__gte=since) | Q(solicitud__fecha_publicacion__gte=since))

    ofertas_dirigidas = base_ofertas.filter(
        solicitud__tipo_solicitud='dirigida',
        solicitud__proveedores_dirigidos=user,
    )
    ofertas_globales = base_ofertas.filter(solicitud__tipo_solicitud='global')

    avg_dir_min = _avg_minutes_from_ofertas(ofertas_dirigidas)
    avg_glob_min = _avg_minutes_from_ofertas(ofertas_globales)

    if ofertas_dirigidas.exists() and avg_dir_min is not None:
        resp_min_for_score = avg_dir_min
    elif ofertas_globales.exists() and avg_glob_min is not None:
        resp_min_for_score = avg_glob_min
    else:
        resp_min_for_score = _avg_minutes_from_ofertas(base_ofertas)

    score_respuesta = (
        _score_tiempo_respuesta_minutos(resp_min_for_score) if resp_min_for_score is not None else None
    )

    # --- Órdenes marketplace (con oferta) en ventana de actividad ---
    orden_base = _orden_mercado_base(taller, mecanico)
    ordenes_periodo = _ordenes_en_ventana_actividad(orden_base, since)
    ordenes_completadas_periodo = ordenes_periodo.filter(estado='completado')

    estados_checklist = [
        'aceptada_por_proveedor',
        'checklist_en_progreso',
        'checklist_completado',
        'en_proceso',
        'completado',
    ]
    ordenes_check_scope = ordenes_periodo.filter(estado__in=estados_checklist)

    con_instancia = ordenes_check_scope.filter(checklist_instance__isnull=False).distinct()
    n_con_checklist = con_instancia.count()
    n_checklist_completado = con_instancia.filter(checklist_instance__estado='COMPLETADO').count()

    pct_checklist = None
    if n_con_checklist > 0:
        pct_checklist = 100.0 * n_checklist_completado / n_con_checklist

    checklist_minutes: list[float] = []
    for inst in ChecklistInstance.objects.filter(
        orden__in=ordenes_check_scope,
        estado='COMPLETADO',
    ).select_related('orden', 'orden__oferta_proveedor'):
        m = _checklist_minutes_real(inst)
        if m is not None and m > 0:
            checklist_minutes.append(m)
    avg_checklist_min = round(sum(checklist_minutes) / len(checklist_minutes), 2) if checklist_minutes else None

    # Ratio: tiempo real checklist / tiempo estimado oferta (1.0 = en tiempo)
    ratios: list[float] = []
    for orden in (
        ordenes_check_scope.select_related('oferta_proveedor', 'checklist_instance')
        .filter(
            checklist_instance__estado='COMPLETADO',
        )
        .distinct()
        .iterator(chunk_size=200)
    ):
        try:
            inst = orden.checklist_instance
            real_min = _checklist_minutes_real(inst)
            if real_min is None or real_min <= 0:
                continue
            oferta = orden.oferta_proveedor
            if not oferta or not oferta.tiempo_estimado_total:
                continue
            est_min = oferta.tiempo_estimado_total.total_seconds() / 60.0
            if est_min <= 0:
                continue
            ratios.append(real_min / est_min)
        except Exception:
            continue

    ratio_promedio = round(sum(ratios) / len(ratios), 3) if ratios else None
    n_ratio = len(ratios)

    score_ejecucion = None
    if ratio_promedio is not None:
        if ratio_promedio <= 1.0:
            score_ejecucion = 100
        elif ratio_promedio >= 2.0:
            score_ejecucion = 0
        else:
            score_ejecucion = int(round(100 * (2.0 - ratio_promedio)))

    score_calificacion = _score_calificacion(calificacion_para_score)
    score_checklist = _score_checklist_cumplimiento(pct_checklist)
    score_rendimiento = _merge_score([score_respuesta, score_calificacion, score_checklist, score_ejecucion])

    return {
        'ventana_dias': dias,
        'desde': since.isoformat(),
        'ofertas_dirigidas_muestra': ofertas_dirigidas.count(),
        'ofertas_globales_muestra': ofertas_globales.count(),
        'ofertas_total_en_periodo': base_ofertas.count(),
        'tiempo_respuesta_dirigida_media_minutos': avg_dir_min,
        'tiempo_respuesta_global_media_minutos': avg_glob_min,
        'ordenes_mercado_en_periodo': ordenes_periodo.count(),
        'ordenes_mercado_completadas': ordenes_completadas_periodo.count(),
        'ordenes_con_checklist': n_con_checklist,
        'checklist_completados': n_checklist_completado,
        'checklist_cumplimiento_pct': round(pct_checklist, 2) if pct_checklist is not None else None,
        'checklist_tiempo_promedio_minutos': avg_checklist_min,
        'tiempo_ejecucion_vs_estimado_promedio': ratio_promedio,
        'tiempo_ejecucion_vs_estimado_muestra': n_ratio,
        'resenas_muestra': n_resenas_periodo,
        'resenas_totales_proveedor': n_resenas_total,
        'calificacion_cliente_promedio': round(calificacion_muestra_ui, 2) if calificacion_muestra_ui is not None else None,
        'calificacion_promedio_todas_resenas': round(float(avg_rating_all), 2) if avg_rating_all is not None else None,
        'score_tiempo_respuesta': score_respuesta,
        'score_calificacion_cliente': score_calificacion,
        'score_checklist': score_checklist,
        'score_tiempo_ejecucion': score_ejecucion,
        'score_rendimiento': score_rendimiento,
    }


def _empty_payload(dias: int) -> dict[str, Any]:
    since = timezone.now() - timedelta(days=dias)
    return {
        'ventana_dias': dias,
        'desde': since.isoformat(),
        'ofertas_dirigidas_muestra': 0,
        'ofertas_globales_muestra': 0,
        'ofertas_total_en_periodo': 0,
        'tiempo_respuesta_dirigida_media_minutos': None,
        'tiempo_respuesta_global_media_minutos': None,
        'ordenes_mercado_en_periodo': 0,
        'ordenes_mercado_completadas': 0,
        'ordenes_con_checklist': 0,
        'checklist_completados': 0,
        'checklist_cumplimiento_pct': None,
        'checklist_tiempo_promedio_minutos': None,
        'tiempo_ejecucion_vs_estimado_promedio': None,
        'tiempo_ejecucion_vs_estimado_muestra': 0,
        'resenas_muestra': 0,
        'resenas_totales_proveedor': 0,
        'calificacion_cliente_promedio': None,
        'calificacion_promedio_todas_resenas': None,
        'score_tiempo_respuesta': None,
        'score_calificacion_cliente': None,
        'score_checklist': None,
        'score_tiempo_ejecucion': None,
        'score_rendimiento': 50,
    }
