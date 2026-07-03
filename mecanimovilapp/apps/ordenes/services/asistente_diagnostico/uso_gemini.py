"""Agregación de uso de tokens Gemini por mecánico / taller."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from django.conf import settings
from django.db.models import Count, Q, Sum
from django.utils import timezone


def _parse_date(value: str | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _filtro_fecha(fecha_desde: date, fecha_hasta: date) -> Q:
    return Q(creado_en__date__gte=fecha_desde, creado_en__date__lte=fecha_hasta)


def _agregar_tokens(qs) -> dict[str, int]:
    agg = qs.aggregate(
        consultas=Count('id'),
        tokens_entrada=Sum('tokens_entrada'),
        tokens_salida=Sum('tokens_salida'),
        tokens_total=Sum('tokens_total'),
    )
    return {
        'consultas': int(agg['consultas'] or 0),
        'tokens_entrada': int(agg['tokens_entrada'] or 0),
        'tokens_salida': int(agg['tokens_salida'] or 0),
        'tokens_total': int(agg['tokens_total'] or 0),
    }


def _qs_ordenes_taller(taller, fecha_desde: date, fecha_hasta: date, generado_por=None):
    from mecanimovilapp.apps.ordenes.models import DiagnosticoAsistidoOrden

    qs = DiagnosticoAsistidoOrden.objects.filter(
        orden__taller=taller,
        estado='completado',
    ).filter(_filtro_fecha(fecha_desde, fecha_hasta))
    if generado_por is not None:
        qs = qs.filter(generado_por=generado_por)
    return qs


def _qs_citas_taller(taller, fecha_desde: date, fecha_hasta: date, generado_por=None):
    from mecanimovilapp.apps.ordenes.models import DiagnosticoAsistidoCitaPersonal

    qs = DiagnosticoAsistidoCitaPersonal.objects.filter(
        cita__taller=taller,
        estado='completado',
    ).filter(_filtro_fecha(fecha_desde, fecha_hasta))
    if generado_por is not None:
        qs = qs.filter(generado_por=generado_por)
    return qs


def _merge_uso(ordenes: dict[str, int], citas: dict[str, int]) -> dict[str, Any]:
    consultas = ordenes['consultas'] + citas['consultas']
    tokens_entrada = ordenes['tokens_entrada'] + citas['tokens_entrada']
    tokens_salida = ordenes['tokens_salida'] + citas['tokens_salida']
    tokens_total = ordenes['tokens_total'] + citas['tokens_total']
    return {
        'usa_ia': consultas > 0,
        'consultas': consultas,
        'consultas_ordenes': ordenes['consultas'],
        'consultas_citas_personales': citas['consultas'],
        'tokens_entrada': tokens_entrada,
        'tokens_salida': tokens_salida,
        'tokens_total': tokens_total,
    }


def _alerta_mensual(tokens_mes: int) -> dict[str, Any]:
    limite = int(getattr(settings, 'GEMINI_LIMITE_TOKENS_MENSUAL', 0) or 0)
    hoy = timezone.localdate()
    if hoy.month == 12:
        renovacion = date(hoy.year + 1, 1, 1)
    else:
        renovacion = date(hoy.year, hoy.month + 1, 1)

    pct = round(tokens_mes / limite * 100, 1) if limite > 0 else None
    alerta_nivel = None
    alerta_mensaje = None
    if limite > 0:
        if tokens_mes >= limite:
            alerta_nivel = 'critical'
            alerta_mensaje = (
                f'El taller alcanzó el límite mensual de {limite:,} tokens de Gemini.'
            )
        elif pct is not None and pct >= 80:
            alerta_nivel = 'warning'
            alerta_mensaje = (
                f'Uso alto de Gemini: {pct:.0f}% del límite mensual ({limite:,} tokens).'
            )

    return {
        'tokens_mes_calendario': tokens_mes,
        'limite_mensual_tokens': limite,
        'pct_limite_mensual': pct,
        'renovacion_tokens_en': renovacion.isoformat(),
        'dias_hasta_renovacion': (renovacion - hoy).days,
        'alerta_nivel': alerta_nivel,
        'alerta_mensaje': alerta_mensaje,
        'gemini_configurado': bool((getattr(settings, 'GEMINI_API_KEY', '') or '').strip()),
        'asistente_habilitado': bool(getattr(settings, 'ASISTENTE_DIAGNOSTICO_IA_ENABLED', False)),
    }


def compute_uso_gemini_taller(taller, *, desde=None, hasta=None, dias: int = 30) -> dict[str, Any]:
    """Uso agregado del taller en el periodo (todas las consultas IA del taller)."""
    hoy = timezone.localdate()
    fecha_hasta = _parse_date(hasta) or hoy
    fecha_desde = _parse_date(desde)
    if fecha_desde is None:
        dias = max(1, min(int(dias), 365))
        fecha_desde = fecha_hasta - timedelta(days=dias - 1)

    ordenes = _agregar_tokens(_qs_ordenes_taller(taller, fecha_desde, fecha_hasta))
    citas = _agregar_tokens(_qs_citas_taller(taller, fecha_desde, fecha_hasta))
    uso = _merge_uso(ordenes, citas)

    inicio_mes = fecha_hasta.replace(day=1)
    tokens_mes = _merge_uso(
        _agregar_tokens(_qs_ordenes_taller(taller, inicio_mes, fecha_hasta)),
        _agregar_tokens(_qs_citas_taller(taller, inicio_mes, fecha_hasta)),
    )['tokens_total']

    return {**uso, **_alerta_mensual(tokens_mes)}


def compute_uso_gemini_mecanico(miembro, *, desde=None, hasta=None, dias: int = 30) -> dict[str, Any]:
    """Uso atribuido a un mecánico (generado_por) + alertas del taller."""
    taller = miembro.taller
    hoy = timezone.localdate()
    fecha_hasta = _parse_date(hasta) or hoy
    fecha_desde = _parse_date(desde)
    if fecha_desde is None:
        dias = max(1, min(int(dias), 365))
        fecha_desde = fecha_hasta - timedelta(days=dias - 1)

    ordenes = _agregar_tokens(
        _qs_ordenes_taller(taller, fecha_desde, fecha_hasta, generado_por=miembro)
    )
    citas = _agregar_tokens(
        _qs_citas_taller(taller, fecha_desde, fecha_hasta, generado_por=miembro)
    )
    uso = _merge_uso(ordenes, citas)

    alerta_taller = compute_uso_gemini_taller(taller, desde=fecha_desde, hasta=fecha_hasta)
    return {
        **uso,
        'tokens_mes_calendario': alerta_taller['tokens_mes_calendario'],
        'limite_mensual_tokens': alerta_taller['limite_mensual_tokens'],
        'pct_limite_mensual': alerta_taller['pct_limite_mensual'],
        'renovacion_tokens_en': alerta_taller['renovacion_tokens_en'],
        'dias_hasta_renovacion': alerta_taller['dias_hasta_renovacion'],
        'alerta_nivel': alerta_taller['alerta_nivel'],
        'alerta_mensaje': alerta_taller['alerta_mensaje'],
        'gemini_configurado': alerta_taller['gemini_configurado'],
        'asistente_habilitado': alerta_taller['asistente_habilitado'],
    }
