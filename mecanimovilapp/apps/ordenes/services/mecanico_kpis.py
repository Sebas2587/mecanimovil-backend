"""
KPIs granulares por mecánico del taller (MiembroTaller).

Métricas (flujo completo del taller = Mecanimovil + agenda personal):
  1. Servicios completados: órdenes marketplace completadas + citas personales cerradas
  2. Checklist cerrado en ambos canales (ChecklistInstance COMPLETADO)
  3. Órdenes rechazadas por el proveedor (solo marketplace)
  4. Cumplimiento de tiempos: oferta marketplace o duracion_minutos de la cita
  5. Comparativo mes actual vs mes anterior
  6. Scores 0–100 por dimensión + score global
  7. Facturación (SolicitudServicio.total + precio_referencia citas)
  8. Desglose por canal (ordenes_mecanimovil / ordenes_personales)
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Q, Sum
from django.utils import timezone

_ESTADOS_EN_PROCESO = [
    'pendiente_aceptacion_proveedor',
    'aceptada_por_proveedor',
    'confirmado',
    'checklist_en_progreso',
    'checklist_completado',
    'servicio_iniciado',
    'en_proceso',
    'pendiente_firma_cliente',
]

_ESTADOS_CHECKLIST_OPERATIVO = (
    'COMPLETADO',
    'PENDIENTE_FIRMA_CLIENTE',
    'PENDIENTE_FIRMA_SUPERVISOR',
)

from mecanimovilapp.apps.ordenes.services.proveedor_kpis import (
    _checklist_minutes_real,
    _ordenes_servicio_terminado,
    _score_checklist_cumplimiento,
    _score_velocidad_inicio_checklist,
)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _ventana_periodo_q(fecha_desde: date, fecha_hasta: date) -> Q:
    """
    Órdenes con fecha de servicio O fecha de solicitud dentro del rango.
    Evita contadores en 0 cuando la cita es futura pero la orden ya está activa.
    """
    inicio_dt = timezone.make_aware(datetime.combine(fecha_desde, datetime.min.time()))
    fin_dt = timezone.make_aware(
        datetime.combine(fecha_hasta, datetime.max.time().replace(microsecond=0))
    )
    return (
        Q(fecha_servicio__gte=fecha_desde, fecha_servicio__lte=fecha_hasta)
        | Q(fecha_hora_solicitud__gte=inicio_dt, fecha_hora_solicitud__lte=fin_dt)
    )


def _ventana_cita_personal_q(fecha_desde: date, fecha_hasta: date) -> Q:
    """Citas cerradas contadas por fecha de servicio o por fecha de cierre."""
    inicio_dt = timezone.make_aware(datetime.combine(fecha_desde, datetime.min.time()))
    fin_dt = timezone.make_aware(
        datetime.combine(fecha_hasta, datetime.max.time().replace(microsecond=0))
    )
    return (
        Q(fecha_servicio__gte=fecha_desde, fecha_servicio__lte=fecha_hasta)
        | Q(cerrada_en__gte=inicio_dt, cerrada_en__lte=fin_dt)
    )


def _precio_oferta_servicio(oferta) -> float:
    if oferta is None:
        return 0.0
    for attr in ('precio_publicado_cliente', 'precio_sin_repuestos', 'precio_con_repuestos'):
        val = getattr(oferta, attr, None)
        if val is None:
            continue
        try:
            n = float(val)
        except (TypeError, ValueError):
            continue
        if n > 0:
            return n
    return 0.0


def _precio_cita_personal(cita) -> float:
    """Precio referencia explícito o fallback al catálogo (OfertaServicio)."""
    from django.core.exceptions import ObjectDoesNotExist

    try:
        detalle = cita.detalle
    except ObjectDoesNotExist:
        return 0.0
    if detalle.precio_referencia is not None:
        try:
            ref = float(detalle.precio_referencia)
            if ref > 0:
                return ref
        except (TypeError, ValueError):
            pass
    return _precio_oferta_servicio(getattr(detalle, 'oferta_servicio', None))


def _sumar_facturacion_citas_personales(qs) -> float:
    total = 0.0
    for cita in qs.select_related('detalle__oferta_servicio').iterator(chunk_size=500):
        total += _precio_cita_personal(cita)
    return total


def _fecha_bucket_cita_personal(cita, fecha_desde: date, fecha_hasta: date) -> date | None:
    """Día de la cita cerrada: fecha_servicio o fecha de cierre dentro del rango."""
    if cita.fecha_servicio and fecha_desde <= cita.fecha_servicio <= fecha_hasta:
        return cita.fecha_servicio
    if cita.cerrada_en:
        d = timezone.localtime(cita.cerrada_en).date()
        if fecha_desde <= d <= fecha_hasta:
            return d
    return None


def _ordenes_mecanico_periodo(miembro, fecha_desde: date, fecha_hasta: date):
    from mecanimovilapp.apps.ordenes.models import SolicitudServicio

    return SolicitudServicio.objects.filter(
        mecanico_asignado=miembro,
    ).filter(_ventana_periodo_q(fecha_desde, fecha_hasta))


def _delta_pct(actual: float | int | None, anterior: float | int | None) -> float | None:
    if actual is None or anterior is None:
        return None
    try:
        a = float(actual)
        b = float(anterior)
    except (TypeError, ValueError):
        return None
    if b == 0:
        return 100.0 if a > 0 else 0.0
    return round((a - b) / b * 100.0, 1)


def _score_tiempo_ejecucion(ratio_promedio: float | None) -> int | None:
    """ratio <= 1.0 → 100; ratio >= 2.0 → 0 (lineal)."""
    if ratio_promedio is None:
        return None
    if ratio_promedio <= 1.0:
        return 100
    if ratio_promedio >= 2.0:
        return 0
    return int(round(100 * (2.0 - ratio_promedio)))


def _score_productividad(completados: int, dias_periodo: int) -> int | None:
    """Órdenes completadas por día laboral del periodo, normalizado a 0–100."""
    if dias_periodo <= 0:
        return None
    # 1 orden/día ≈ 100 pts; cap en 100.
    rate = completados / dias_periodo
    return max(0, min(100, int(round(rate * 100))))


def _merge_score_global(parts: list[int | None]) -> int | None:
    vals = [int(p) for p in parts if p is not None]
    if not vals:
        return None
    return max(0, min(100, int(round(sum(vals) / len(vals)))))


def _est_minutos_oferta_orden(orden) -> float | None:
    """
    Minutos estimados para la orden: suma duracion_maxima_minutos de las líneas,
    o fallback a OfertaProveedor.tiempo_estimado_total.
    """
    total_min = 0.0
    tiene_linea = False
    for linea in orden.lineas.select_related('oferta_servicio').all():
        oferta = linea.oferta_servicio
        if not oferta:
            continue
        tiene_linea = True
        if oferta.duracion_maxima_minutos:
            total_min += float(oferta.duracion_maxima_minutos) * max(1, linea.cantidad)
        elif oferta.duracion_minima_minutos:
            total_min += float(oferta.duracion_minima_minutos) * max(1, linea.cantidad)
        elif oferta.duracion_estimada:
            try:
                total_min += (
                    oferta.duracion_estimada.hour * 60 + oferta.duracion_estimada.minute
                ) * max(1, linea.cantidad)
            except Exception:
                pass
    if tiene_linea and total_min > 0:
        return total_min

    oferta_prov = getattr(orden, 'oferta_proveedor', None)
    if oferta_prov and oferta_prov.tiempo_estimado_total:
        try:
            return oferta_prov.tiempo_estimado_total.total_seconds() / 60.0
        except Exception:
            pass
    return None


def _metricas_periodo(
    miembro,
    fecha_desde: date,
    fecha_hasta: date,
) -> dict[str, Any]:
    from mecanimovilapp.apps.checklists.models import ChecklistInstance
    from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, SolicitudServicio

    dias_periodo = max(1, (fecha_hasta - fecha_desde).days + 1)

    base_qs = _ordenes_mecanico_periodo(miembro, fecha_desde, fecha_hasta)

    completadas_qs = base_qs.filter(estado='completado')
    terminadas_mkt_qs = _ordenes_servicio_terminado(completadas_qs)

    personal_base = CitaAgendaPersonal.objects.filter(
        miembro_taller=miembro,
    ).filter(_ventana_cita_personal_q(fecha_desde, fecha_hasta))
    personal_cerradas_qs = personal_base.filter(estado='cerrada')
    personal_activas_qs = personal_base.filter(estado='activa')

    ordenes_mecanimovil = completadas_qs.count()
    ordenes_personales = personal_cerradas_qs.count()
    # Completadas del flujo del taller = ambos canales
    servicios_completados_totales = ordenes_mecanimovil + ordenes_personales

    personal_con_checklist_ids = set(
        ChecklistInstance.objects.filter(
            cita_personal__in=personal_cerradas_qs,
            estado__in=_ESTADOS_CHECKLIST_OPERATIVO,
            fecha_inicio__isnull=False,
            fecha_completado_proveedor__isnull=False,
        ).values_list('cita_personal_id', flat=True)
    )
    servicios_completados_con_checklist = (
        terminadas_mkt_qs.count() + len(personal_con_checklist_ids)
    )

    from mecanimovilapp.apps.checklists.services import resolver_servicio_desde_cita_personal

    mkt_elegibles_ids = set(
        completadas_qs.filter(checklist_instance__isnull=False).values_list('id', flat=True)
    ) | set(terminadas_mkt_qs.values_list('id', flat=True))
    personal_elegibles_ids = set(
        ChecklistInstance.objects.filter(
            cita_personal__in=personal_cerradas_qs,
        ).values_list('cita_personal_id', flat=True)
    )
    for cita in personal_cerradas_qs.select_related(
        'detalle__oferta_servicio__servicio',
    ).iterator(chunk_size=200):
        if cita.id in personal_elegibles_ids:
            continue
        if resolver_servicio_desde_cita_personal(cita) is not None:
            personal_elegibles_ids.add(cita.id)
    servicios_elegibles_checklist = len(mkt_elegibles_ids) + len(personal_elegibles_ids)
    servicios_rechazados = base_qs.filter(estado='rechazada_por_proveedor').count()

    total_asignados = (
        base_qs.count() + personal_activas_qs.count() + personal_cerradas_qs.count()
    )
    servicios_en_proceso = (
        base_qs.filter(estado__in=_ESTADOS_EN_PROCESO).count() + personal_activas_qs.count()
    )

    # Checklist cumplimiento: % sobre servicios elegibles (no penaliza cierres sin checklist)
    pct_checklist = (
        100.0 * servicios_completados_con_checklist / servicios_elegibles_checklist
        if servicios_elegibles_checklist > 0
        else None
    )

    # Tiempos reales vs estimados (marketplace + citas personales con checklist)
    ratios: list[float] = []
    tiempos_reales: list[float] = []
    dentro_tiempo = 0
    n_tiempo = 0

    for orden in (
        terminadas_mkt_qs.select_related('checklist_instance', 'oferta_proveedor')
        .prefetch_related('lineas__oferta_servicio')
        .iterator(chunk_size=200)
    ):
        inst = getattr(orden, 'checklist_instance', None)
        if not inst:
            continue
        real_min = _checklist_minutes_real(inst)
        if real_min is None or real_min <= 0:
            continue
        tiempos_reales.append(real_min)
        est_min = _est_minutos_oferta_orden(orden)
        if est_min and est_min > 0:
            ratio = real_min / est_min
            ratios.append(ratio)
            n_tiempo += 1
            if real_min <= est_min:
                dentro_tiempo += 1

    personal_checklist_operativo = ChecklistInstance.objects.filter(
        cita_personal__in=personal_cerradas_qs,
        estado__in=_ESTADOS_CHECKLIST_OPERATIVO,
        fecha_inicio__isnull=False,
        fecha_completado_proveedor__isnull=False,
    ).select_related('cita_personal')

    for inst in personal_checklist_operativo.iterator(chunk_size=200):
        cita = inst.cita_personal
        if cita is None:
            continue
        real_min = _checklist_minutes_real(inst)
        if real_min is None or real_min <= 0:
            continue
        tiempos_reales.append(real_min)
        est_min = float(cita.duracion_minutos or 0)
        if est_min > 0:
            ratio = real_min / est_min
            ratios.append(ratio)
            n_tiempo += 1
            if real_min <= est_min:
                dentro_tiempo += 1

    ordenes_demoradas = n_tiempo - dentro_tiempo
    ordenes_dentro_tiempo = dentro_tiempo

    ratio_promedio = round(sum(ratios) / len(ratios), 3) if ratios else None
    tiempo_promedio = round(sum(tiempos_reales) / len(tiempos_reales), 2) if tiempos_reales else None
    pct_dentro_tiempo = round(100.0 * dentro_tiempo / n_tiempo, 1) if n_tiempo > 0 else None

    # Facturación: órdenes completadas + precio citas personales (referencia o catálogo)
    fact_agg = completadas_qs.aggregate(s=Sum('total'))
    facturacion_mkt = float(fact_agg['s'] or Decimal('0'))
    facturacion = facturacion_mkt + _sumar_facturacion_citas_personales(personal_cerradas_qs)

    # Scores: productividad por volumen total; checklist/tiempo sobre cierres con checklist
    _, score_inicio = _score_velocidad_inicio_checklist(terminadas_mkt_qs)
    score_checklist = _score_checklist_cumplimiento(pct_checklist)
    score_tiempo = _score_tiempo_ejecucion(ratio_promedio)
    score_productividad = _score_productividad(servicios_completados_totales, dias_periodo)

    # Aceptación 24h, confiabilidad y calificación por órdenes asignadas
    from mecanimovilapp.apps.ordenes.services.kpi_scoring import (
        aceptaciones_a_tiempo_count,
        compute_score_aceptacion_ordenes,
        ordenes_respondidas_en_ventana,
        rechazos_mecanico_en_ventana,
        score_confiabilidad_from_eventos,
    )
    from mecanimovilapp.apps.ordenes.services.proveedor_kpis import _score_calificacion

    since_dt = timezone.make_aware(datetime.combine(fecha_desde, datetime.min.time()))
    ordenes_mkt_asignadas = base_qs.filter(oferta_proveedor__isnull=False)
    ordenes_respondidas = ordenes_respondidas_en_ventana(ordenes_mkt_asignadas, since_dt)
    score_aceptacion, avg_aceptacion_min, n_aceptacion = compute_score_aceptacion_ordenes(ordenes_respondidas)

    rechazo_eventos = rechazos_mecanico_en_ventana(miembro, since_dt)
    aceptaciones_tiempo = aceptaciones_a_tiempo_count(ordenes_respondidas)
    score_confiabilidad, _ = score_confiabilidad_from_eventos(
        rechazo_eventos,
        aceptaciones_a_tiempo=aceptaciones_tiempo,
    )

    from mecanimovilapp.apps.usuarios.models import Resena

    resenas_qs = Resena.objects.filter(
        solicitud__mecanico_asignado=miembro,
        fecha_hora_resena__gte=since_dt,
        fecha_hora_resena__lte=timezone.make_aware(
            datetime.combine(fecha_hasta, datetime.max.time().replace(microsecond=0))
        ),
    )
    califs = [float(r.calificacion) for r in resenas_qs.only('calificacion')]
    calificacion_promedio = round(sum(califs) / len(califs), 2) if califs else None
    score_calificacion = _score_calificacion(calificacion_promedio)

    score_parts: list[int | None] = [
        score_productividad,
        score_tiempo,
        score_checklist,
        score_inicio,
    ]
    if ordenes_mkt_asignadas.exists() or n_aceptacion > 0:
        score_parts.append(score_aceptacion)
    if rechazo_eventos or ordenes_mkt_asignadas.exists():
        score_parts.append(score_confiabilidad)
    if score_calificacion is not None:
        score_parts.append(score_calificacion)

    score_global = _merge_score_global(score_parts)

    return {
        'servicios_completados': servicios_completados_totales,
        'servicios_completados_totales': servicios_completados_totales,
        'servicios_completados_con_checklist': servicios_completados_con_checklist,
        'servicios_elegibles_checklist': servicios_elegibles_checklist,
        'servicios_rechazados': servicios_rechazados,
        'ordenes_demoradas': ordenes_demoradas,
        'ordenes_dentro_tiempo': ordenes_dentro_tiempo,
        'servicios_en_proceso': servicios_en_proceso,
        'total_asignados': total_asignados,
        'pct_dentro_tiempo': pct_dentro_tiempo,
        'ratio_tiempo_promedio': ratio_promedio,
        'tiempo_promedio_minutos': tiempo_promedio,
        'facturacion_periodo': int(round(facturacion)),
        'ordenes_mecanimovil': ordenes_mecanimovil,
        'ordenes_personales': ordenes_personales,
        'score_productividad': score_productividad,
        'score_tiempo_ejecucion': score_tiempo,
        'score_checklist': score_checklist,
        'score_puntualidad_inicio': score_inicio,
        'score_confiabilidad': score_confiabilidad if (rechazo_eventos or ordenes_mkt_asignadas.exists()) else None,
        'score_aceptacion': score_aceptacion if (ordenes_mkt_asignadas.exists() or n_aceptacion > 0) else None,
        'score_calificacion_cliente': score_calificacion,
        'calificacion_cliente_promedio': calificacion_promedio,
        'tiempo_aceptacion_promedio_minutos': avg_aceptacion_min,
        'rechazos_periodo': len(rechazo_eventos),
        'score_rendimiento_global': score_global,
    }


def _rango_mes(offset: int = 0) -> tuple[date, date]:
    """offset=0 mes actual hasta hoy; offset=1 mes anterior completo."""
    hoy = timezone.localdate()
    year = hoy.year
    month = hoy.month - offset
    while month <= 0:
        month += 12
        year -= 1
    ultimo_dia = monthrange(year, month)[1]
    inicio = date(year, month, 1)
    if offset == 0:
        fin = hoy
    else:
        fin = date(year, month, ultimo_dia)
    return inicio, fin


def _rango_mes_anterior_proporcional() -> tuple[date, date]:
    """Mismos N días calendario que el mes en curso (1 → hoy), en el mes anterior."""
    hoy = timezone.localdate()
    mes_actual_ini, _ = _rango_mes(0)
    dias_transcurridos = (hoy - mes_actual_ini).days + 1
    mes_anterior_ini, mes_anterior_fin_completo = _rango_mes(1)
    fin = min(
        mes_anterior_ini + timedelta(days=dias_transcurridos - 1),
        mes_anterior_fin_completo,
    )
    return mes_anterior_ini, fin


def _mecanico_base_info(miembro, request=None) -> dict[str, Any]:
    from mecanimovilapp.storage.utils import get_image_url

    return {
        'mecanico_id': miembro.id,
        'nombre': miembro.nombre,
        'foto_url': get_image_url(miembro.foto, request) if miembro.foto else None,
        'especialidades': [
            {'id': c.id, 'nombre': c.nombre}
            for c in miembro.especialidades.all()
        ],
        'activo': miembro.activo,
    }


def compute_mecanico_kpis(
    miembro,
    *,
    desde: str | date | None = None,
    hasta: str | date | None = None,
    dias: int = 30,
    request=None,
) -> dict[str, Any]:
    """
    Calcula KPIs completos para un MiembroTaller (rol mecánico).
    """
    hoy = timezone.localdate()

    fecha_hasta = _parse_date(hasta) if isinstance(hasta, str) else hasta
    fecha_desde = _parse_date(desde) if isinstance(desde, str) else desde

    if fecha_hasta is None:
        fecha_hasta = hoy
    if fecha_desde is None:
        dias = max(1, min(int(dias), 365))
        fecha_desde = fecha_hasta - timedelta(days=dias - 1)

    periodo = _metricas_periodo(miembro, fecha_desde, fecha_hasta)

    mes_actual_ini, mes_actual_fin = _rango_mes(0)
    mes_anterior_ini, mes_anterior_fin = _rango_mes_anterior_proporcional()

    mes_actual = _metricas_periodo(miembro, mes_actual_ini, mes_actual_fin)
    mes_anterior = _metricas_periodo(miembro, mes_anterior_ini, mes_anterior_fin)

    comparativo = {
        'mes_actual': {
            'completados': mes_actual['servicios_completados_totales'],
            'tiempo_prom': mes_actual['tiempo_promedio_minutos'],
            'facturacion': mes_actual['facturacion_periodo'],
        },
        'mes_anterior': {
            'completados': mes_anterior['servicios_completados_totales'],
            'tiempo_prom': mes_anterior['tiempo_promedio_minutos'],
            'facturacion': mes_anterior['facturacion_periodo'],
        },
        'ventana_mes_actual': {
            'desde': mes_actual_ini.isoformat(),
            'hasta': mes_actual_fin.isoformat(),
        },
        'ventana_mes_anterior': {
            'desde': mes_anterior_ini.isoformat(),
            'hasta': mes_anterior_fin.isoformat(),
        },
        'delta_completados_pct': _delta_pct(
            mes_actual['servicios_completados_totales'],
            mes_anterior['servicios_completados_totales'],
        ),
        'delta_tiempo_pct': _delta_pct(
            mes_actual['tiempo_promedio_minutos'],
            mes_anterior['tiempo_promedio_minutos'],
        ),
        'delta_facturacion_pct': _delta_pct(
            mes_actual['facturacion_periodo'],
            mes_anterior['facturacion_periodo'],
        ),
    }

    from mecanimovilapp.apps.ordenes.services.asistente_diagnostico.uso_gemini import (
        compute_uso_gemini_mecanico,
    )

    return {
        **_mecanico_base_info(miembro, request),
        **periodo,
        'facturacion_mes_actual': mes_actual['facturacion_periodo'],
        'facturacion_mes_anterior': mes_anterior['facturacion_periodo'],
        'facturacion_delta_pct': comparativo['delta_facturacion_pct'],
        'comparativo': comparativo,
        'ventana_desde': fecha_desde.isoformat(),
        'ventana_hasta': fecha_hasta.isoformat(),
        'uso_ia_gemini': compute_uso_gemini_mecanico(
            miembro,
            desde=fecha_desde,
            hasta=fecha_hasta,
        ),
    }


def compute_rendimiento_taller(
    taller,
    *,
    desde: str | None = None,
    hasta: str | None = None,
    dias: int = 30,
    mecanico_id: int | None = None,
    request=None,
) -> list[dict[str, Any]]:
    """KPIs detallados para todos los mecánicos del taller (o uno solo)."""
    from mecanimovilapp.apps.ordenes.services.asistente_diagnostico.uso_gemini import (
        compute_uso_gemini_taller,
    )
    from mecanimovilapp.apps.usuarios.models import MiembroTaller

    hoy = timezone.localdate()
    fecha_hasta = _parse_date(hasta) or hoy
    fecha_desde = _parse_date(desde)
    if fecha_desde is None:
        dias = max(1, min(int(dias), 365))
        fecha_desde = fecha_hasta - timedelta(days=dias - 1)

    qs = (
        MiembroTaller.objects.filter(taller=taller, rol='mecanico')
        .prefetch_related('especialidades')
    )
    if mecanico_id is not None:
        qs = qs.filter(id=mecanico_id)

    mecanicos = list(qs)
    if not mecanicos:
        uso = compute_uso_gemini_taller(
            taller,
            desde=fecha_desde,
            hasta=fecha_hasta,
        )
        return [{
            'mecanico_id': None,
            'nombre': 'Taller',
            'foto_url': None,
            'especialidades': [],
            'activo': True,
            'servicios_completados': 0,
            'servicios_completados_totales': 0,
            'servicios_completados_con_checklist': 0,
            'servicios_rechazados': 0,
            'servicios_en_proceso': 0,
            'ordenes_demoradas': 0,
            'ordenes_dentro_tiempo': 0,
            'pct_dentro_tiempo': None,
            'tiempo_promedio_minutos': None,
            'facturacion_periodo': 0,
            'facturacion_mes_actual': 0,
            'facturacion_mes_anterior': 0,
            'facturacion_delta_pct': None,
            'comparativo': {
                'mes_actual': {'completados': 0, 'tiempo_prom': None, 'facturacion': 0},
                'mes_anterior': {'completados': 0, 'tiempo_prom': None, 'facturacion': 0},
                'ventana_mes_actual': {'desde': fecha_desde.isoformat(), 'hasta': fecha_hasta.isoformat()},
                'ventana_mes_anterior': {'desde': fecha_desde.isoformat(), 'hasta': fecha_hasta.isoformat()},
                'delta_completados_pct': None,
                'delta_tiempo_pct': None,
                'delta_facturacion_pct': None,
            },
            'ordenes_mecanimovil': 0,
            'ordenes_personales': 0,
            'score_productividad': None,
            'score_tiempo_ejecucion': None,
            'score_checklist': None,
            'score_puntualidad_inicio': None,
            'score_rendimiento_global': None,
            'ventana_desde': fecha_desde.isoformat(),
            'ventana_hasta': fecha_hasta.isoformat(),
            'uso_ia_gemini': uso,
            'solo_uso_ia': True,
        }]

    return [
        compute_mecanico_kpis(
            m,
            desde=desde,
            hasta=hasta,
            dias=dias,
            request=request,
        )
        for m in mecanicos
    ]
