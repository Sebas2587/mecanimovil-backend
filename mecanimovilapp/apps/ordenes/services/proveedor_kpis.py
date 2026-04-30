"""
Agregación de KPIs para proveedores (solicitudes públicas / marketplace).

Usa datos ya persistidos (tiempo_respuesta_proveedor en OfertaProveedor,
SolicitudServicio + ChecklistInstance, Resena) sin alterar flujos de cliente.
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
    """100 = respuesta inmediata; baja linealmente hasta 0 a los 120 min."""
    if avg_minutes is None:
        return None
    return max(0, min(100, int(100 - min(avg_minutes, 120) * (100.0 / 120.0))))


def _score_calificacion(avg_rating: float | None) -> int | None:
    if avg_rating is None:
        return None
    # 1..5 -> 0..100
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


def compute_proveedor_kpis_resumen(user, dias: int = 30) -> dict[str, Any]:
    """
    Calcula métricas agregadas para el usuario proveedor autenticado.

    Args:
        user: Usuario Django (debe tener taller o mecanico_domicilio).
        dias: ventana hacia atrás desde ahora (1..365).

    Returns:
        dict serializable a JSON (números nativos / None).
    """
    from mecanimovilapp.apps.checklists.models import ChecklistInstance
    from mecanimovilapp.apps.ordenes.models import OfertaProveedor, SolicitudServicio
    from mecanimovilapp.apps.usuarios.models import Resena

    dias = max(1, min(int(dias), 365))
    since = timezone.now() - timedelta(days=dias)

    taller = getattr(user, 'taller', None)
    mecanico = getattr(user, 'mecanico_domicilio', None)
    if not taller and not mecanico:
        return _empty_payload(dias)

    orden_filter = Q(estado='completado', oferta_proveedor__isnull=False, fecha_hora_solicitud__gte=since)
    if taller:
        orden_filter &= Q(taller=taller)
    else:
        orden_filter &= Q(mecanico=mecanico)

    ordenes_mercado = SolicitudServicio.objects.filter(orden_filter)

    # --- Respuesta en ofertas (desde publicación hasta envío de oferta) ---
    base_ofertas = OfertaProveedor.objects.filter(
        proveedor=user,
        es_oferta_secundaria=False,
        fecha_envio__gte=since,
        tiempo_respuesta_proveedor__isnull=False,
    )

    ofertas_dirigidas = base_ofertas.filter(
        solicitud__tipo_solicitud='dirigida',
        solicitud__proveedores_dirigidos=user,
    )
    ofertas_globales = base_ofertas.filter(solicitud__tipo_solicitud='global')

    avg_dir_td = ofertas_dirigidas.aggregate(avg=Avg('tiempo_respuesta_proveedor'))['avg']
    avg_glob_td = ofertas_globales.aggregate(avg=Avg('tiempo_respuesta_proveedor'))['avg']

    avg_dir_min = _timedelta_to_minutes(avg_dir_td)
    avg_glob_min = _timedelta_to_minutes(avg_glob_td)

    # Priorizar dirigidas para el score de respuesta; si no hay, usar globales.
    if ofertas_dirigidas.exists():
        resp_min_for_score = avg_dir_min
    elif ofertas_globales.exists():
        resp_min_for_score = avg_glob_min
    else:
        resp_min_for_score = None

    score_respuesta = (
        _score_tiempo_respuesta_minutos(resp_min_for_score) if resp_min_for_score is not None else None
    )

    # --- Marketplace completado: checklist + reseñas ---
    con_instancia = ordenes_mercado.filter(checklist_instance__isnull=False).distinct()
    n_con_checklist = con_instancia.count()
    n_checklist_completado = con_instancia.filter(checklist_instance__estado='COMPLETADO').count()

    pct_checklist = None
    if n_con_checklist > 0:
        pct_checklist = 100.0 * n_checklist_completado / n_con_checklist

    avg_checklist_min = None
    if n_checklist_completado > 0:
        agg = ChecklistInstance.objects.filter(
            orden__in=ordenes_mercado,
            estado='COMPLETADO',
            tiempo_total_minutos__isnull=False,
        ).aggregate(avg=Avg('tiempo_total_minutos'))
        avg_checklist_min = agg['avg']

    resenas_qs = Resena.objects.filter(solicitud__in=ordenes_mercado)
    agg_rating = resenas_qs.aggregate(avg=Avg('calificacion'), n=Count('id'))
    avg_rating = agg_rating['avg']
    n_resenas = agg_rating['n'] or 0

    score_calificacion = _score_calificacion(float(avg_rating) if avg_rating is not None else None)
    score_checklist = _score_checklist_cumplimiento(pct_checklist)

    # Tiempo checklist vs tiempo estimado oferta (solo órdenes con ambos datos)
    ratio_promedio = None
    n_ratio = 0
    ratios: list[float] = []
    for orden in (
        ordenes_mercado.select_related('oferta_proveedor', 'checklist_instance')
        .filter(
            checklist_instance__estado='COMPLETADO',
            checklist_instance__tiempo_total_minutos__isnull=False,
        )
        .iterator(chunk_size=200)
    ):
        try:
            inst = orden.checklist_instance
            real_min = float(inst.tiempo_total_minutos or 0)
            if real_min <= 0:
                continue
            oferta = orden.oferta_proveedor
            if not oferta or not oferta.tiempo_estimado_total:
                continue
            est_min = oferta.tiempo_estimado_total.total_seconds() / 60.0
            if est_min <= 0:
                continue
            ratios.append(real_min / est_min)
            n_ratio += 1
        except Exception:
            continue

    if ratios:
        ratio_promedio = round(sum(ratios) / len(ratios), 3)

    # Score ejecución: 100 si ratio <= 1; penaliza hasta 0 si ratio >= 2
    score_ejecucion = None
    if ratio_promedio is not None:
        if ratio_promedio <= 1.0:
            score_ejecucion = 100
        elif ratio_promedio >= 2.0:
            score_ejecucion = 0
        else:
            score_ejecucion = int(round(100 * (2.0 - ratio_promedio)))

    score_rendimiento = _merge_score([score_respuesta, score_calificacion, score_checklist, score_ejecucion])

    return {
        'ventana_dias': dias,
        'desde': since.isoformat(),
        'ofertas_dirigidas_muestra': ofertas_dirigidas.count(),
        'ofertas_globales_muestra': ofertas_globales.count(),
        'tiempo_respuesta_dirigida_media_minutos': avg_dir_min,
        'tiempo_respuesta_global_media_minutos': avg_glob_min,
        'ordenes_mercado_completadas': ordenes_mercado.count(),
        'ordenes_con_checklist': n_con_checklist,
        'checklist_completados': n_checklist_completado,
        'checklist_cumplimiento_pct': round(pct_checklist, 2) if pct_checklist is not None else None,
        'checklist_tiempo_promedio_minutos': round(float(avg_checklist_min), 2) if avg_checklist_min is not None else None,
        'tiempo_ejecucion_vs_estimado_promedio': ratio_promedio,
        'tiempo_ejecucion_vs_estimado_muestra': n_ratio,
        'resenas_muestra': n_resenas,
        'calificacion_cliente_promedio': round(float(avg_rating), 2) if avg_rating is not None else None,
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
        'tiempo_respuesta_dirigida_media_minutos': None,
        'tiempo_respuesta_global_media_minutos': None,
        'ordenes_mercado_completadas': 0,
        'ordenes_con_checklist': 0,
        'checklist_completados': 0,
        'checklist_cumplimiento_pct': None,
        'checklist_tiempo_promedio_minutos': None,
        'tiempo_ejecucion_vs_estimado_promedio': None,
        'tiempo_ejecucion_vs_estimado_muestra': 0,
        'resenas_muestra': 0,
        'calificacion_cliente_promedio': None,
        'score_tiempo_respuesta': None,
        'score_calificacion_cliente': None,
        'score_checklist': None,
        'score_tiempo_ejecucion': None,
        'score_rendimiento': 50,
    }
