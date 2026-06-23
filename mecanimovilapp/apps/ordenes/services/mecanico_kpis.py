"""
KPIs granulares por mecánico del taller (MiembroTaller).

Métricas:
  1. Servicios completados (estado completado) y con checklist cerrado
  2. Órdenes rechazadas por el proveedor
  3. Cumplimiento de tiempos vs duracion_maxima_minutos de OfertaServicio
  4. Comparativo mes actual vs mes anterior
  5. Scores 0–100 por dimensión + score global (basados en checklist)
  6. Facturación (SolicitudServicio.total en órdenes completadas + citas personales)
  7. Órdenes vía Mecanimovil vs citas personales (CitaAgendaPersonal)
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Sum
from django.utils import timezone

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
    from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, SolicitudServicio

    dias_periodo = max(1, (fecha_hasta - fecha_desde).days + 1)

    base_qs = SolicitudServicio.objects.filter(
        mecanico_asignado=miembro,
        fecha_servicio__gte=fecha_desde,
        fecha_servicio__lte=fecha_hasta,
    )

    total_asignados = base_qs.count()
    servicios_en_proceso = base_qs.filter(
        estado__in=[
            'en_proceso',
            'aceptada_por_proveedor',
            'confirmado',
            'checklist_en_progreso',
            'checklist_completado',
            'pendiente_firma_cliente',
        ]
    ).count()

    completadas_qs = base_qs.filter(estado='completado')
    terminadas_qs = _ordenes_servicio_terminado(completadas_qs)

    servicios_completados_totales = completadas_qs.count()
    servicios_completados_con_checklist = terminadas_qs.count()
    servicios_rechazados = base_qs.filter(estado='rechazada_por_proveedor').count()

    # Checklist cumplimiento: % de completadas totales que cerraron checklist
    pct_checklist = (
        100.0 * servicios_completados_con_checklist / servicios_completados_totales
        if servicios_completados_totales
        else None
    )

    # Tiempos reales vs estimados (solo órdenes con checklist cerrado)
    ratios: list[float] = []
    tiempos_reales: list[float] = []
    dentro_tiempo = 0
    n_tiempo = 0

    for orden in (
        terminadas_qs.select_related('checklist_instance', 'oferta_proveedor')
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

    ordenes_demoradas = n_tiempo - dentro_tiempo
    ordenes_dentro_tiempo = dentro_tiempo

    ratio_promedio = round(sum(ratios) / len(ratios), 3) if ratios else None
    tiempo_promedio = round(sum(tiempos_reales) / len(tiempos_reales), 2) if tiempos_reales else None
    pct_dentro_tiempo = round(100.0 * dentro_tiempo / n_tiempo, 1) if n_tiempo > 0 else None

    # Facturación: todas las órdenes completadas + precio referencia citas personales
    fact_agg = completadas_qs.aggregate(s=Sum('total'))
    facturacion_mkt = float(fact_agg['s'] or Decimal('0'))
    personal_qs = CitaAgendaPersonal.objects.filter(
        miembro_taller=miembro,
        estado='cerrada',
        fecha_servicio__gte=fecha_desde,
        fecha_servicio__lte=fecha_hasta,
    )
    personal_fact_agg = personal_qs.aggregate(s=Sum('detalle__precio_referencia'))
    facturacion = facturacion_mkt + float(personal_fact_agg['s'] or Decimal('0'))

    # Órdenes por canal (periodo)
    ordenes_mecanimovil = servicios_completados_totales
    ordenes_personales = personal_qs.count()

    # Scores de calidad: solo órdenes con checklist cerrado
    _, score_inicio = _score_velocidad_inicio_checklist(terminadas_qs)
    score_checklist = _score_checklist_cumplimiento(pct_checklist)
    score_tiempo = _score_tiempo_ejecucion(ratio_promedio)
    score_productividad = _score_productividad(servicios_completados_con_checklist, dias_periodo)
    score_global = _merge_score_global([
        score_productividad,
        score_tiempo,
        score_checklist,
        score_inicio,
    ])

    return {
        'servicios_completados': servicios_completados_totales,
        'servicios_completados_totales': servicios_completados_totales,
        'servicios_completados_con_checklist': servicios_completados_con_checklist,
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
    mes_anterior_ini, mes_anterior_fin = _rango_mes(1)

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

    return {
        **_mecanico_base_info(miembro, request),
        **periodo,
        'facturacion_mes_actual': mes_actual['facturacion_periodo'],
        'facturacion_mes_anterior': mes_anterior['facturacion_periodo'],
        'facturacion_delta_pct': comparativo['delta_facturacion_pct'],
        'comparativo': comparativo,
        'ventana_desde': fecha_desde.isoformat(),
        'ventana_hasta': fecha_hasta.isoformat(),
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
    from mecanimovilapp.apps.usuarios.models import MiembroTaller

    qs = (
        MiembroTaller.objects.filter(taller=taller, rol='mecanico')
        .prefetch_related('especialidades')
    )
    if mecanico_id is not None:
        qs = qs.filter(id=mecanico_id)

    return [
        compute_mecanico_kpis(
            m,
            desde=desde,
            hasta=hasta,
            dias=dias,
            request=request,
        )
        for m in qs
    ]
