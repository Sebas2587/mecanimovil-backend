"""
Agregación de KPIs para proveedores (solicitudes públicas / marketplace).

Criterios de ventana: actividad reciente (orden creada, checklist o reseña en el periodo),
no solo fecha_hora_solicitud.

Calificaciones mostradas al proveedor combinan modelo Resena y Review (app usuarios): si el mirror
a Resena falló, sigue contando Review. La nota por orden prefiere Resena; las líneas de servicio
usan la misma nota por orden sobre LineaServicio + OfertaServicio del proveedor.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import Avg, Count, Exists, OuterRef, Q
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
        return 0
    return max(0, min(100, int(round(sum(vals) / len(vals)))))


def _score_aspectos_resena(
    *,
    avg_puntualidad: float | None,
    avg_recepcion_a_tiempo: float | None,
    avg_limpieza_auto: float | None,
    avg_zona_limpia: float | None,
    avg_claridad: float | None,
    avg_info: float | None,
    avg_trato: float | None,
    pct_entrego_repuestos: float | None,
) -> int | None:
    """
    Convierte promedios 1–5 y booleanos a un score 0–100.
    - Promedios 1–5 → 0–100 usando la misma normalización que estrellas.
    - entrego_repuestos: porcentaje True (0–100).
    Solo promedia señales presentes.
    """
    parts: list[int] = []

    def norm_1_5(v: float | None) -> int | None:
        if v is None:
            return None
        try:
            return max(0, min(100, int(round((float(v) - 1.0) / 4.0 * 100))))
        except Exception:
            return None

    for v in [
        norm_1_5(avg_puntualidad),
        norm_1_5(avg_recepcion_a_tiempo),
        norm_1_5(avg_limpieza_auto),
        norm_1_5(avg_zona_limpia),
        norm_1_5(avg_claridad),
        norm_1_5(avg_info),
        norm_1_5(avg_trato),
    ]:
        if v is not None:
            parts.append(v)

    if pct_entrego_repuestos is not None:
        try:
            parts.append(max(0, min(100, int(round(float(pct_entrego_repuestos))))))
        except Exception:
            pass

    if not parts:
        return None
    return max(0, min(100, int(round(sum(parts) / len(parts)))))


def _resenas_qs(taller, mecanico):
    from mecanimovilapp.apps.usuarios.models import Resena

    if taller:
        return Resena.objects.filter(taller=taller)
    return Resena.objects.filter(mecanico=mecanico)


def _merged_rating_by_solicitud(taller, mecanico, solicitud_ids: list[int] | None) -> dict[int, float]:
    """
    Por orden: calificación 1–5. Prefiere Resena; si no hay, usa Review (app usuarios).
    """
    from mecanimovilapp.apps.usuarios.models import Resena, Review

    rq = Resena.objects.exclude(solicitud_id__isnull=True)
    if taller:
        rq = rq.filter(taller=taller)
    else:
        rq = rq.filter(mecanico=mecanico)
    if solicitud_ids is not None:
        if not solicitud_ids:
            return {}
        rq = rq.filter(solicitud_id__in=solicitud_ids)

    out: dict[int, float] = {}
    for r in rq.only('solicitud_id', 'calificacion').iterator(chunk_size=400):
        out[int(r.solicitud_id)] = float(r.calificacion)

    rv = Review.objects.all()
    if taller:
        rv = rv.filter(provider_type='taller', provider_id=taller.id)
    else:
        rv = rv.filter(provider_type='mecanico', provider_id=mecanico.id)
    if solicitud_ids is not None:
        rv = rv.filter(service_order_id__in=solicitud_ids)

    for row in rv.only('service_order_id', 'rating').iterator(chunk_size=400):
        oid = int(row.service_order_id)
        if oid not in out:
            out[oid] = float(row.rating)
    return out


def _merged_global_rating_samples(taller, mecanico) -> list[float]:
    """
    Muestras globales: cada Resena del proveedor + cada Review cuya orden no tiene Resena
    (evita duplicar cuando el mirror Resena sí existió).
    """
    from mecanimovilapp.apps.usuarios.models import Review, Resena

    rq = _resenas_qs(taller, mecanico)
    vals = [float(x) for x in rq.values_list('calificacion', flat=True)]

    rev_q = Review.objects.all()
    if taller:
        rev_q = rev_q.filter(provider_type='taller', provider_id=taller.id)
    else:
        rev_q = rev_q.filter(provider_type='mecanico', provider_id=mecanico.id)

    covered = Resena.objects.filter(solicitud_id=OuterRef('service_order_id'))
    orphan = rev_q.annotate(has_resena=Exists(covered)).filter(has_resena=False).values_list('rating', flat=True)
    vals.extend(float(x) for x in orphan)
    return vals


def _service_line_rating_samples(
    taller,
    mecanico,
    solicitud_ids: list[int],
    rating_by_sol: dict[int, float],
) -> list[float]:
    """Por cada línea con OfertaServicio del proveedor, una muestra = rating de la orden."""
    from mecanimovilapp.apps.ordenes.models import LineaServicio

    if not solicitud_ids or not rating_by_sol:
        return []

    qs = LineaServicio.objects.filter(
        solicitud_id__in=solicitud_ids,
        oferta_servicio__isnull=False,
    )
    if taller:
        qs = qs.filter(solicitud__taller_id=taller.id, oferta_servicio__taller_id=taller.id)
    elif mecanico:
        qs = qs.filter(
            solicitud__mecanico_id=mecanico.id,
            oferta_servicio__mecanico_id=mecanico.id,
        )
    else:
        return []

    vals: list[float] = []
    for sid in qs.values_list('solicitud_id', flat=True).iterator(chunk_size=600):
        r = rating_by_sol.get(int(sid))
        if r is not None:
            vals.append(r)
    return vals


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

    # --- Reseñas con aspectos (solo modelo Resena en ventana calendario; KPI de estrellas se calcula más abajo) ---
    rq_periodo = _resenas_qs(taller, mecanico).filter(fecha_hora_resena__gte=since)

    # --- Aspectos estructurados desde reseñas (opcional; mejora señal de calidad) ---
    agg_aspects = rq_periodo.aggregate(
        punctual=Avg('puntualidad'),
        recep=Avg('recepcion_a_tiempo'),
        clean_car=Avg('limpieza_auto'),
        clean_zone=Avg('zona_limpia'),
        clarity=Avg('claridad_explicacion'),
        info=Avg('informacion_relevante'),
        trato=Avg('trato'),
        repuestos_true=Count('id', filter=Q(entrego_repuestos=True)),
        repuestos_total=Count('id', filter=Q(entrego_repuestos__isnull=False)),
    )
    repuestos_total = agg_aspects.get('repuestos_total') or 0
    repuestos_true = agg_aspects.get('repuestos_true') or 0
    pct_repuestos = (100.0 * repuestos_true / repuestos_total) if repuestos_total > 0 else None
    score_calidad_servicio = _score_aspectos_resena(
        avg_puntualidad=agg_aspects.get('punctual'),
        avg_recepcion_a_tiempo=agg_aspects.get('recep'),
        avg_limpieza_auto=agg_aspects.get('clean_car'),
        avg_zona_limpia=agg_aspects.get('clean_zone'),
        avg_claridad=agg_aspects.get('clarity'),
        avg_info=agg_aspects.get('info'),
        avg_trato=agg_aspects.get('trato'),
        pct_entrego_repuestos=pct_repuestos,
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

    orden_ids_period = list(ordenes_periodo.values_list('id', flat=True))
    rating_map_period = _merged_rating_by_solicitud(taller, mecanico, orden_ids_period)
    rated_in_period = [rating_map_period[oid] for oid in orden_ids_period if oid in rating_map_period]

    samples_global = _merged_global_rating_samples(taller, mecanico)
    avg_global_merged = sum(samples_global) / len(samples_global) if samples_global else None

    if rated_in_period:
        calificacion_muestra_ui = sum(rated_in_period) / len(rated_in_period)
        calificacion_para_score = calificacion_muestra_ui
        n_resenas_muestra_eff = len(rated_in_period)
    elif avg_global_merged is not None:
        calificacion_muestra_ui = avg_global_merged
        calificacion_para_score = avg_global_merged
        # Sin órdenes calificadas dentro de la ventana de actividad; el promedio es histórico.
        n_resenas_muestra_eff = 0
    else:
        calificacion_muestra_ui = None
        calificacion_para_score = None
        n_resenas_muestra_eff = 0

    n_resenas_total_merged = len(samples_global)

    rating_map_all = _merged_rating_by_solicitud(taller, mecanico, None)
    srv_samples_period = _service_line_rating_samples(taller, mecanico, orden_ids_period, rating_map_period)
    srv_samples_all = _service_line_rating_samples(
        taller,
        mecanico,
        list(rating_map_all.keys()),
        rating_map_all,
    )

    if srv_samples_period:
        calificacion_servicios_muestra_ui = sum(srv_samples_period) / len(srv_samples_period)
        n_srv_periodo = len(srv_samples_period)
    elif srv_samples_all:
        calificacion_servicios_muestra_ui = sum(srv_samples_all) / len(srv_samples_all)
        n_srv_periodo = 0
    else:
        calificacion_servicios_muestra_ui = None
        n_srv_periodo = 0

    n_srv_total = len(srv_samples_all)

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
    score_rendimiento = _merge_score(
        [score_respuesta, score_calificacion, score_calidad_servicio, score_checklist, score_ejecucion]
    )

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
        'resenas_muestra': n_resenas_muestra_eff,
        'resenas_totales_proveedor': n_resenas_total_merged,
        'calificacion_cliente_promedio': round(calificacion_muestra_ui, 2) if calificacion_muestra_ui is not None else None,
        'calificacion_promedio_todas_resenas': (
            round(float(avg_global_merged), 2) if avg_global_merged is not None else None
        ),
        'calificacion_servicios_promedio': (
            round(calificacion_servicios_muestra_ui, 2) if calificacion_servicios_muestra_ui is not None else None
        ),
        'calificacion_servicios_lineas_muestra': n_srv_periodo,
        'calificacion_servicios_lineas_total': n_srv_total,
        'score_tiempo_respuesta': score_respuesta,
        'score_calificacion_cliente': score_calificacion,
        'score_calidad_servicio': score_calidad_servicio,
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
        'calificacion_servicios_promedio': None,
        'calificacion_servicios_lineas_muestra': 0,
        'calificacion_servicios_lineas_total': 0,
        'score_tiempo_respuesta': None,
        'score_calificacion_cliente': None,
        'score_calidad_servicio': None,
        'score_checklist': None,
        'score_tiempo_ejecucion': None,
        'score_rendimiento': 0,
    }


def merge_kpi_resumen_insignia_cliente_fields(usuario, dias: int, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Añade flags de suscripción / visibilidad de insignia KPI en app usuarios (misma regla que serializers usuarios).
    """
    from mecanimovilapp.apps.usuarios.kpi_badge_utils import compute_kpi_badge_for_proveedor

    sus = getattr(usuario, 'suscripcion_proveedor', None)
    suscripcion_mensual_activa = sus is not None and getattr(sus, 'estado', None) == 'activa'
    payload['suscripcion_mensual_activa'] = suscripcion_mensual_activa
    payload['insignia_visible_a_clientes'] = suscripcion_mensual_activa

    badge = compute_kpi_badge_for_proveedor(proveedor_usuario=usuario, window_days=dias)
    good_tiers = {'PRO', 'MASTER', 'ELITE'}
    sugerencia = False
    mensaje = None
    if not suscripcion_mensual_activa and isinstance(badge, dict):
        code = str(badge.get('code') or '').strip().upper()
        score = int(badge.get('score') or 0)
        if badge.get('is_active') and (code in good_tiers or score >= 55):
            sugerencia = True
            mensaje = (
                'Tu rendimiento califica para mostrar la insignia KPI a los clientes. '
                'Activa una suscripción mensual para destacar tu perfil en la app de usuarios.'
            )
    payload['sugerencia_suscripcion_para_insignia'] = sugerencia
    payload['mensaje_sugerencia_suscripcion'] = mensaje
    return payload
