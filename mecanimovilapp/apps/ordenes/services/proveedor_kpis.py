"""
Agregación de KPIs para proveedores (solicitudes públicas / marketplace).

Dimensiones del score_rendimiento (todas 0–100):
  1. score_tiempo_respuesta       — velocidad para enviar oferta tras publicación
  2. score_calificacion_cliente   — estrellas de reseñas (SIEMPRE incluida; 0 sin reseñas)
  3. score_calidad_servicio       — aspectos estructurados de reseñas (opcional, no penaliza)
  4. score_checklist              — % checklists completados en órdenes terminadas
  5. score_tiempo_ejecucion       — tiempo real proveedor vs estimado en oferta
  6. score_consistencia           — racha máx. de días consecutivos con ≥1 servicio terminado
  7. score_inicio_checklist       — velocidad para arrancar el checklist tras crear la instancia
  8. score_aceptacion_ordenes     — tiempo para aceptar/rechazar orden pagada (SLA 24h)
  9. score_confiabilidad          — rechazos recientes con decay temporal

  score_rendimiento puede aplicar multiplicador 0.85 si ≥3 rechazos en 7 días.

Regla central de composición (_merge_score_activity_aware):
  - Sin actividad (ni ofertas ni órdenes) → 0.
  - Con solo ofertas y sin servicios terminados → promedio de score_respuesta, cap 54.
  - Con servicios terminados:
      · score_calificacion SIEMPRE entra al promedio (0 si no hay reseñas).
        Esto evita que un proveedor sin reseñas llegue a Elite solo por completar.
      · score_consistencia SIEMPRE entra al promedio (0 si sin datos).
      · score_calidad_servicio solo si hay aspectos (no penaliza si no existen).
      · score_inicio_checklist solo si hay datos de timing (no penaliza si no existen).
  - Resultado clampado 0–100.

Calificaciones combinan Resena + Review (app usuarios); si el mirror falló sigue
contando Review. La nota por orden prefiere Resena; las líneas de servicio usan la
misma nota sobre LineaServicio + OfertaServicio del proveedor.
"""
from __future__ import annotations

from datetime import timedelta, date
from typing import Any

from django.db.models import Avg, Count, Exists, OuterRef, Q
from django.utils import timezone


# ---------------------------------------------------------------------------
# Helpers numéricos
# ---------------------------------------------------------------------------

def _timedelta_to_minutes(td) -> float | None:
    if td is None:
        return None
    try:
        return round(td.total_seconds() / 60.0, 2)
    except Exception:
        return None


def _score_tiempo_respuesta_minutos(avg_minutes: float | None) -> int | None:
    """0 min → 100, ≥120 min → 0 (lineal)."""
    if avg_minutes is None:
        return None
    return max(0, min(100, int(100 - min(avg_minutes, 120) * (100.0 / 120.0))))


def _score_calificacion(avg_rating: float | None) -> int | None:
    """1 estrella → 0, 5 estrellas → 100."""
    if avg_rating is None:
        return None
    return max(0, min(100, int(round((avg_rating - 1.0) / 4.0 * 100))))


def _score_checklist_cumplimiento(pct: float | None) -> int | None:
    if pct is None:
        return None
    return max(0, min(100, int(round(pct))))


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
    Convierte promedios 1–5 y porcentaje booleano a score 0–100.
    Solo promedia señales presentes; si no hay ninguna devuelve None.
    """
    def norm_1_5(v: float | None) -> int | None:
        if v is None:
            return None
        try:
            return max(0, min(100, int(round((float(v) - 1.0) / 4.0 * 100))))
        except Exception:
            return None

    parts: list[int] = []
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


def _score_consistencia_diaria(ordenes_terminadas_qs) -> int | None:
    """
    Consistencia de actividad diaria.

    Calcula la racha máxima de días **consecutivos** en que el proveedor
    completó ≥1 servicio (checklist inicio + fin) dentro de la ventana.

    Fórmula: min(100, max_racha × 10)
      →  1 día consecutivo  =  10 pts
      →  5 días consecutivos = 50 pts
      → 10 días consecutivos = 100 pts

    Devuelve None si no hay servicios terminados (no penaliza cuando has_orders=False).
    """
    fechas_qs = (
        ordenes_terminadas_qs
        .filter(checklist_instance__fecha_finalizacion__isnull=False)
        .values_list('checklist_instance__fecha_finalizacion', flat=True)
        .iterator(chunk_size=500)
    )

    days_set: set[date] = set()
    for f in fechas_qs:
        if f is not None:
            try:
                days_set.add(f.date())
            except Exception:
                pass

    if not days_set:
        return None

    sorted_days = sorted(days_set)
    max_streak = 1
    current_streak = 1

    for i in range(1, len(sorted_days)):
        diff = (sorted_days[i] - sorted_days[i - 1]).days
        if diff == 1:
            current_streak += 1
            if current_streak > max_streak:
                max_streak = current_streak
        else:
            current_streak = 1

    return min(100, max_streak * 10)


def _score_velocidad_inicio_checklist(ordenes_terminadas_qs) -> tuple[float | None, int | None]:
    """
    Mide cuánto tarda el proveedor en pulsar 'iniciar checklist' desde que
    se crea la instancia (i.e., desde que el servicio fue inicializado).

    Fórmula: ≤5 min → 100, ≥90 min → 0, lineal entre ambos extremos.

    Retorna (avg_minutos, score). Si no hay datos suficientes, (None, None).
    """
    from mecanimovilapp.apps.checklists.models import ChecklistInstance

    deltas: list[float] = []
    for inst in (
        ChecklistInstance.objects.filter(
            orden__in=ordenes_terminadas_qs,
            estado='COMPLETADO',
            fecha_inicio__isnull=False,
            fecha_creacion__isnull=False,
        )
        .only('fecha_creacion', 'fecha_inicio')
        .iterator(chunk_size=300)
    ):
        try:
            delta_min = (inst.fecha_inicio - inst.fecha_creacion).total_seconds() / 60.0
            if delta_min >= 0:
                deltas.append(delta_min)
        except Exception:
            pass

    if not deltas:
        return None, None

    avg = round(sum(deltas) / len(deltas), 2)
    # ≤5 min → 100; ≥90 min → 0; lineal
    score = max(0, min(100, int(round(100 - max(0.0, avg - 5.0) * (100.0 / 85.0)))))
    return avg, score


def _merge_score_activity_aware(
    *,
    score_respuesta: int | None,
    score_calificacion: int | None,
    score_calidad_servicio: int | None,
    score_checklist: int | None,
    score_ejecucion: int | None,
    score_consistencia: int | None,
    score_inicio_checklist: int | None,
    score_aceptacion_ordenes: int | None,
    score_confiabilidad: int | None,
    has_offers: bool,
    has_orders: bool,
    has_marketplace_orders: bool,
    has_marketplace_activity: bool,
    has_ratings_in_period: bool,
) -> int:
    """
    Score compuesto 0–100 robusto frente a proveedores sin historial suficiente.

    CAMBIO CLAVE respecto a la versión anterior:
    • score_calificacion SIEMPRE entra al promedio cuando has_orders=True,
      usando 0 si no hay reseñas en el periodo. Esto impide llegar a Elite
      solo por completar un servicio sin que ningún cliente haya calificado.
    • score_consistencia SIEMPRE entra al promedio cuando has_orders=True,
      usando 0 si no hay datos de racha. Penaliza la falta de actividad sostenida.
    • score_calidad_servicio es opcional (no penaliza si no hay aspectos).
    • score_inicio_checklist es opcional (no penaliza si no hay datos de timing).
    """
    if not has_offers and not has_orders and not has_marketplace_activity:
        return 0

    parts: list[int] = []

    # Respuesta: solo tiene sentido si hubo ofertas.
    if has_offers:
        parts.append(int(score_respuesta) if score_respuesta is not None else 0)

    # Confiabilidad: actividad marketplace (ofertas u órdenes).
    if has_marketplace_activity:
        parts.append(int(score_confiabilidad) if score_confiabilidad is not None else 100)

    # Aceptación de órdenes pagadas (SLA 24h).
    if has_marketplace_orders:
        parts.append(int(score_aceptacion_ordenes) if score_aceptacion_ordenes is not None else 0)

    # Sin servicios terminados: respuesta + confiabilidad (+ aceptación si aplica), cap 54.
    if has_marketplace_activity and not has_orders:
        if not parts:
            return 0
        return max(0, min(54, int(round(sum(parts) / len(parts)))))

    # --- Servicios terminados: todas las dimensiones relevantes ---

    # Checklist: % completado en órdenes terminadas.
    parts.append(int(score_checklist) if score_checklist is not None else 0)

    # Ejecución: tiempo real proveedor vs estimado.
    parts.append(int(score_ejecucion) if score_ejecucion is not None else 0)

    # Consistencia diaria: SIEMPRE penaliza si no hay actividad sostenida.
    parts.append(int(score_consistencia) if score_consistencia is not None else 0)

    # Calificación: SIEMPRE incluida (0 si sin reseñas en periodo).
    # CRÍTICO: sin este cambio, un proveedor puede llegar a Elite sin una sola reseña.
    parts.append(int(score_calificacion) if score_calificacion is not None else 0)

    # Calidad (aspectos de reseñas): opcional — si no hay aspectos no penaliza.
    if score_calidad_servicio is not None:
        parts.append(int(score_calidad_servicio))

    # Velocidad de inicio del checklist: opcional — si no hay timing no penaliza.
    if score_inicio_checklist is not None:
        parts.append(int(score_inicio_checklist))

    if not parts:
        return 0
    return max(0, min(100, int(round(sum(parts) / len(parts)))))


# ---------------------------------------------------------------------------
# Consultas de datos
# ---------------------------------------------------------------------------

def _resenas_qs(taller, mecanico):
    from mecanimovilapp.apps.usuarios.models import Resena
    if taller:
        return Resena.objects.filter(taller=taller)
    return Resena.objects.filter(mecanico=mecanico)


def _merged_rating_by_solicitud(taller, mecanico, solicitud_ids: list[int] | None) -> dict[int, float]:
    """Por orden: calificación 1–5. Prefiere Resena; si no hay, usa Review."""
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
    """Muestras globales: Resena + Review sin Resena (evita duplicados)."""
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
    """Por cada línea con OfertaServicio del proveedor, muestra = rating de la orden."""
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
    """Órdenes con oferta donde hubo actividad en el periodo."""
    return base_qs.filter(
        Q(fecha_hora_solicitud__gte=since)
        | Q(checklist_instance__fecha_finalizacion__gte=since)
        | Q(checklist_instance__fecha_inicio__gte=since)
        | Q(resena__fecha_hora_resena__gte=since)
    ).distinct()


def _ordenes_servicio_terminado(qs):
    """
    Servicio realmente ejecutado: completado con checklist cerrado (inicio + fin).
    Checklist en PENDIENTE_FIRMA_CLIENTE también cuenta — el proveedor terminó su parte.
    """
    return qs.filter(
        estado='completado',
        checklist_instance__isnull=False,
        checklist_instance__estado__in=['COMPLETADO', 'PENDIENTE_FIRMA_CLIENTE'],
        checklist_instance__fecha_inicio__isnull=False,
        checklist_instance__fecha_completado_proveedor__isnull=False,
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
    """
    Tiempo real del PROVEEDOR en el checklist.
    Prioriza la diferencia fecha_inicio → fecha_completado_proveedor para
    excluir el tiempo de espera de firma del cliente.
    """
    if inst.fecha_inicio and inst.fecha_completado_proveedor:
        try:
            secs = (inst.fecha_completado_proveedor - inst.fecha_inicio).total_seconds()
            return max(0.0, round(secs / 60.0, 2))
        except Exception:
            pass
    # Fallback: campo precalculado (puede incluir espera de firma en datos históricos)
    if inst.tiempo_total_minutos is not None:
        return float(inst.tiempo_total_minutos)
    return None


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def compute_proveedor_kpis_resumen(user, dias: int = 30) -> dict[str, Any]:
    from mecanimovilapp.apps.checklists.models import ChecklistInstance
    from mecanimovilapp.apps.ordenes.models import OfertaProveedor

    dias = max(1, min(int(dias), 365))
    since = timezone.now() - timedelta(days=dias)

    taller = getattr(user, 'taller', None)
    mecanico = getattr(user, 'mecanico_domicilio', None)
    if not taller and not mecanico:
        return _empty_payload(dias)

    # -----------------------------------------------------------------------
    # Aspectos estructurados de reseñas (ventana calendario)
    # -----------------------------------------------------------------------
    rq_periodo = _resenas_qs(taller, mecanico).filter(fecha_hora_resena__gte=since)
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

    # Aspectos detallados para el dashboard del proveedor
    aspectos_detalle = {
        'puntualidad': round(float(agg_aspects['punctual']), 2) if agg_aspects.get('punctual') else None,
        'recepcion_a_tiempo': round(float(agg_aspects['recep']), 2) if agg_aspects.get('recep') else None,
        'limpieza_auto': round(float(agg_aspects['clean_car']), 2) if agg_aspects.get('clean_car') else None,
        'zona_limpia': round(float(agg_aspects['clean_zone']), 2) if agg_aspects.get('clean_zone') else None,
        'claridad_explicacion': round(float(agg_aspects['clarity']), 2) if agg_aspects.get('clarity') else None,
        'informacion_relevante': round(float(agg_aspects['info']), 2) if agg_aspects.get('info') else None,
        'trato': round(float(agg_aspects['trato']), 2) if agg_aspects.get('trato') else None,
        'pct_entrego_repuestos': round(pct_repuestos, 1) if pct_repuestos is not None else None,
    }

    # -----------------------------------------------------------------------
    # Ofertas en ventana
    # -----------------------------------------------------------------------
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

    # -----------------------------------------------------------------------
    # Órdenes marketplace en ventana de actividad
    # -----------------------------------------------------------------------
    orden_base = _orden_mercado_base(taller, mecanico)
    ordenes_periodo = _ordenes_en_ventana_actividad(orden_base, since)
    ordenes_terminadas_periodo = _ordenes_servicio_terminado(ordenes_periodo)

    orden_ids_period = list(ordenes_terminadas_periodo.values_list('id', flat=True))
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
        # Sin órdenes calificadas en ventana; promedio histórico (no cuenta como "en periodo").
        n_resenas_muestra_eff = 0
    else:
        calificacion_muestra_ui = None
        calificacion_para_score = None
        n_resenas_muestra_eff = 0

    n_resenas_total_merged = len(samples_global)

    rating_map_all = _merged_rating_by_solicitud(taller, mecanico, None)
    srv_samples_period = _service_line_rating_samples(taller, mecanico, orden_ids_period, rating_map_period)
    srv_samples_all = _service_line_rating_samples(
        taller, mecanico, list(rating_map_all.keys()), rating_map_all,
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

    # -----------------------------------------------------------------------
    # Checklist: cumplimiento y tiempos
    # -----------------------------------------------------------------------
    ordenes_check_scope = ordenes_terminadas_periodo
    n_con_checklist = ordenes_check_scope.count()
    n_checklist_completado = n_con_checklist

    pct_checklist = None
    if n_con_checklist > 0:
        pct_checklist = 100.0 * n_checklist_completado / n_con_checklist

    checklist_minutes: list[float] = []
    for inst in ChecklistInstance.objects.filter(
        orden__in=ordenes_check_scope,
        estado__in=['COMPLETADO', 'PENDIENTE_FIRMA_CLIENTE'],
    ).select_related('orden', 'orden__oferta_proveedor'):
        m = _checklist_minutes_real(inst)
        if m is not None and m > 0:
            checklist_minutes.append(m)
    avg_checklist_min = round(sum(checklist_minutes) / len(checklist_minutes), 2) if checklist_minutes else None

    # -----------------------------------------------------------------------
    # Score ejecución: tiempo real proveedor vs tiempo estimado en oferta
    # -----------------------------------------------------------------------
    ratios: list[float] = []
    for orden in (
        ordenes_check_scope.select_related('oferta_proveedor', 'checklist_instance')
        .filter(checklist_instance__isnull=False)
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

    # -----------------------------------------------------------------------
    # Score consistencia (nuevo): racha máx. de días consecutivos
    # -----------------------------------------------------------------------
    score_consistencia = _score_consistencia_diaria(ordenes_terminadas_periodo)
    max_racha_dias = None
    if score_consistencia is not None:
        # Reconstruir el valor de días a partir del score (score = min(100, días*10))
        max_racha_dias = min(10, score_consistencia // 10) if score_consistencia > 0 else 0

    # -----------------------------------------------------------------------
    # Score inicio checklist (nuevo): velocidad para arrancar el checklist
    # -----------------------------------------------------------------------
    avg_inicio_checklist_min, score_inicio_checklist = _score_velocidad_inicio_checklist(
        ordenes_terminadas_periodo
    )

    # -----------------------------------------------------------------------
    # Aceptación de órdenes (SLA 24h) y confiabilidad (rechazos)
    # -----------------------------------------------------------------------
    from mecanimovilapp.apps.ordenes.services.kpi_scoring import (
        aceptaciones_a_tiempo_count,
        aplicar_multiplicador_rechazos_recientes,
        compute_score_aceptacion_ordenes,
        contar_rechazos_recientes,
        ordenes_respondidas_en_ventana,
        rechazos_proveedor_en_ventana,
        score_confiabilidad_from_eventos,
    )

    ordenes_respondidas = ordenes_respondidas_en_ventana(orden_base, since)
    score_aceptacion_ordenes, avg_aceptacion_min, n_aceptacion_muestra = compute_score_aceptacion_ordenes(
        ordenes_respondidas
    )

    rechazo_eventos = rechazos_proveedor_en_ventana(user, since, taller, mecanico)
    aceptaciones_tiempo = aceptaciones_a_tiempo_count(ordenes_respondidas)
    score_confiabilidad, _pen_conf = score_confiabilidad_from_eventos(
        rechazo_eventos,
        aceptaciones_a_tiempo=aceptaciones_tiempo,
    )
    rechazos_periodo = len(rechazo_eventos)
    rechazos_ultimos_7_dias = contar_rechazos_recientes(rechazo_eventos)

    has_offers = bool(base_ofertas.exists())
    has_marketplace_orders = bool(ordenes_periodo.exists()) or n_aceptacion_muestra > 0
    has_marketplace_activity = has_offers or has_marketplace_orders or rechazos_periodo > 0

    # -----------------------------------------------------------------------
    # Scores finales y composición
    # -----------------------------------------------------------------------
    score_calificacion = _score_calificacion(calificacion_para_score)
    score_checklist = _score_checklist_cumplimiento(pct_checklist)

    has_orders = bool(ordenes_terminadas_periodo.exists())
    has_ratings_in_period = n_resenas_muestra_eff > 0
    n_terminadas = ordenes_terminadas_periodo.count()

    score_rendimiento_base = _merge_score_activity_aware(
        score_respuesta=score_respuesta,
        score_calificacion=score_calificacion,
        score_calidad_servicio=score_calidad_servicio,
        score_checklist=score_checklist,
        score_ejecucion=score_ejecucion,
        score_consistencia=score_consistencia,
        score_inicio_checklist=score_inicio_checklist,
        score_aceptacion_ordenes=score_aceptacion_ordenes,
        score_confiabilidad=score_confiabilidad,
        has_offers=has_offers,
        has_orders=has_orders,
        has_marketplace_orders=has_marketplace_orders,
        has_marketplace_activity=has_marketplace_activity,
        has_ratings_in_period=has_ratings_in_period,
    )
    score_rendimiento, multiplicador_penalizacion = aplicar_multiplicador_rechazos_recientes(
        score_rendimiento_base,
        rechazos_ultimos_7_dias,
    )

    return {
        'ventana_dias': dias,
        'desde': since.isoformat(),
        # Ofertas
        'ofertas_dirigidas_muestra': ofertas_dirigidas.count(),
        'ofertas_globales_muestra': ofertas_globales.count(),
        'ofertas_total_en_periodo': base_ofertas.count(),
        'tiempo_respuesta_dirigida_media_minutos': avg_dir_min,
        'tiempo_respuesta_global_media_minutos': avg_glob_min,
        # Órdenes
        'ordenes_mercado_en_periodo': ordenes_periodo.count(),
        'ordenes_mercado_completadas': n_terminadas,
        'servicios_terminados_en_periodo': n_terminadas,
        # Checklist
        'ordenes_con_checklist': n_con_checklist,
        'checklist_completados': n_checklist_completado,
        'checklist_cumplimiento_pct': round(pct_checklist, 2) if pct_checklist is not None else None,
        'checklist_tiempo_promedio_minutos': avg_checklist_min,
        # Ejecución vs estimado
        'tiempo_ejecucion_vs_estimado_promedio': ratio_promedio,
        'tiempo_ejecucion_vs_estimado_muestra': n_ratio,
        # Consistencia (nuevo)
        'max_racha_dias_consecutivos': max_racha_dias,
        # Inicio de checklist (nuevo)
        'tiempo_inicio_checklist_promedio_minutos': avg_inicio_checklist_min,
        # Reseñas y calificaciones
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
        # Aspectos detallados
        'aspectos_resena': aspectos_detalle,
        # Sub-scores
        'score_tiempo_respuesta': score_respuesta,
        'score_calificacion_cliente': score_calificacion,
        'score_calidad_servicio': score_calidad_servicio,
        'score_checklist': score_checklist,
        'score_tiempo_ejecucion': score_ejecucion,
        'score_consistencia': score_consistencia,
        'score_inicio_checklist': score_inicio_checklist,
        'score_aceptacion_ordenes': score_aceptacion_ordenes,
        'score_confiabilidad': score_confiabilidad,
        'tiempo_aceptacion_ordenes_promedio_minutos': avg_aceptacion_min,
        'aceptacion_ordenes_muestra': n_aceptacion_muestra,
        'rechazos_periodo': rechazos_periodo,
        'rechazos_ultimos_7_dias': rechazos_ultimos_7_dias,
        'multiplicador_penalizacion': multiplicador_penalizacion,
        'score_rendimiento_base': score_rendimiento_base,
        # Score compuesto
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
        'servicios_terminados_en_periodo': 0,
        'ordenes_con_checklist': 0,
        'checklist_completados': 0,
        'checklist_cumplimiento_pct': None,
        'checklist_tiempo_promedio_minutos': None,
        'tiempo_ejecucion_vs_estimado_promedio': None,
        'tiempo_ejecucion_vs_estimado_muestra': 0,
        'max_racha_dias_consecutivos': None,
        'tiempo_inicio_checklist_promedio_minutos': None,
        'resenas_muestra': 0,
        'resenas_totales_proveedor': 0,
        'calificacion_cliente_promedio': None,
        'calificacion_promedio_todas_resenas': None,
        'calificacion_servicios_promedio': None,
        'calificacion_servicios_lineas_muestra': 0,
        'calificacion_servicios_lineas_total': 0,
        'aspectos_resena': {
            'puntualidad': None, 'recepcion_a_tiempo': None, 'limpieza_auto': None,
            'zona_limpia': None, 'claridad_explicacion': None, 'informacion_relevante': None,
            'trato': None, 'pct_entrego_repuestos': None,
        },
        'score_tiempo_respuesta': None,
        'score_calificacion_cliente': None,
        'score_calidad_servicio': None,
        'score_checklist': None,
        'score_tiempo_ejecucion': None,
        'score_consistencia': None,
        'score_inicio_checklist': None,
        'score_aceptacion_ordenes': None,
        'score_confiabilidad': None,
        'tiempo_aceptacion_ordenes_promedio_minutos': None,
        'aceptacion_ordenes_muestra': 0,
        'rechazos_periodo': 0,
        'rechazos_ultimos_7_dias': 0,
        'multiplicador_penalizacion': 1.0,
        'score_rendimiento_base': 0,
        'score_rendimiento': 0,
    }


def merge_kpi_resumen_insignia_cliente_fields(usuario, dias: int, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Añade flags de suscripción / visibilidad de insignia KPI en app usuarios.
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
