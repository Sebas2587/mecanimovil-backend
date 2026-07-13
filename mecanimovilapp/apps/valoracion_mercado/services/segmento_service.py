"""
Agregación de segmentos y utilidades de consulta.
"""
from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Any

from django.db.models import Count, Min, Q
from django.utils import timezone

from mecanimovilapp.apps.valoracion_mercado.models import AvisoExternoVehiculo, SegmentoValorHistorial


def year_bucket_for(vehicle_year: int) -> tuple[int, int, int]:
    return vehicle_year, vehicle_year - 1, vehicle_year + 1


def get_comparables_for_vehicle(vehiculo) -> list[dict]:
    year = vehiculo.year or timezone.now().year
    y_min, y_max = year - 1, year + 1
    qs = AvisoExternoVehiculo.objects.filter(
        marca_id=vehiculo.marca_id,
        modelo_id=vehiculo.modelo_id,
        activo=True,
        precio__gt=0,
    ).filter(
        Q(year__isnull=True) | Q(year__gte=y_min, year__lte=y_max)
    ).values('precio', 'kilometraje', 'year', 'fuente', 'fecha_ultima_vista')
    return list(qs)


def segmento_tracking_weeks(marca_id: int, modelo_id: int, year_bucket: int) -> int:
    first = SegmentoValorHistorial.objects.filter(
        marca_id=marca_id,
        modelo_id=modelo_id,
        year_bucket=year_bucket,
    ).aggregate(m=Min('fecha_snapshot'))
    if not first['m']:
        first_aviso = AvisoExternoVehiculo.objects.filter(
            marca_id=marca_id,
            modelo_id=modelo_id,
        ).aggregate(m=Min('fecha_primera_vista'))
        if not first_aviso['m']:
            return 0
        delta = timezone.now().date() - first_aviso['m'].date()
    else:
        delta = timezone.now().date() - first['m']
    return max(0, delta.days // 7)


def get_latest_segment_snapshot(marca_id: int, modelo_id: int, year_bucket: int) -> dict | None:
    row = (
        SegmentoValorHistorial.objects.filter(
            marca_id=marca_id,
            modelo_id=modelo_id,
            year_bucket=year_bucket,
        )
        .order_by('-fecha_snapshot')
        .first()
    )
    if not row:
        return None
    return {
        'n_anuncios_activos': row.n_anuncios_activos,
        'precio_mediana': row.precio_mediana,
        'precio_p25': row.precio_p25,
        'precio_p75': row.precio_p75,
        'tasa_rotacion_30d_pct': float(row.tasa_rotacion_30d_pct or 0),
        'fecha_snapshot': str(row.fecha_snapshot),
        'n_semanas_tracking': segmento_tracking_weeks(marca_id, modelo_id, year_bucket),
    }


def aggregate_segment(marca_obj, modelo_obj, year_bucket: int, snapshot_date: date | None = None) -> SegmentoValorHistorial:
    """Calcula y persiste agregado semanal del segmento."""
    snapshot_date = snapshot_date or timezone.now().date()
    year_min, year_max = year_bucket - 1, year_bucket + 1
    avisos = AvisoExternoVehiculo.objects.filter(
        marca=marca_obj,
        modelo=modelo_obj,
        activo=True,
        precio__gt=0,
    ).filter(
        Q(year__isnull=True) | Q(year__gte=year_min, year__lte=year_max)
    )
    prices = sorted(a.precio for a in avisos.only('precio'))
    n = len(prices)

    def pct(p: float) -> int:
        if not prices:
            return 0
        k = int((len(prices) - 1) * p)
        return prices[k]

    cutoff_old = timezone.now() - timedelta(days=60)
    cutoff_recent = timezone.now() - timedelta(days=30)
    old_count = AvisoExternoVehiculo.objects.filter(
        marca=marca_obj,
        modelo=modelo_obj,
        year__gte=year_min,
        year__lte=year_max,
        fecha_primera_vista__lte=cutoff_old,
    ).count()
    removed = AvisoExternoVehiculo.objects.filter(
        marca=marca_obj,
        modelo=modelo_obj,
        year__gte=year_min,
        year__lte=year_max,
        activo=False,
        fecha_removido__gte=cutoff_recent,
        fecha_primera_vista__lte=cutoff_old,
    ).count()
    rot_pct = (removed / old_count * 100) if old_count >= 3 else None

    obj, _ = SegmentoValorHistorial.objects.update_or_create(
        marca=marca_obj,
        modelo=modelo_obj,
        year_bucket=year_bucket,
        fecha_snapshot=snapshot_date,
        defaults={
            'year_min': year_min,
            'year_max': year_max,
            'n_anuncios_activos': n,
            'precio_mediana': int(statistics.median(prices)) if prices else 0,
            'precio_p25': pct(0.25),
            'precio_p75': pct(0.75),
            'tasa_rotacion_30d_pct': round(rot_pct, 2) if rot_pct is not None else None,
        },
    )
    return obj


def unique_segments_from_vehicles():
    """Segmentos únicos (marca, modelo, year) de vehículos registrados."""
    from mecanimovilapp.apps.vehiculos.models import Vehiculo

    seen = set()
    segments = []
    for v in Vehiculo.objects.select_related('marca', 'modelo').only(
        'id', 'year', 'marca_id', 'modelo_id', 'marca__nombre', 'modelo__nombre'
    ):
        if not v.marca_id or not v.modelo_id:
            continue
        key = (v.marca_id, v.modelo_id, v.year or timezone.now().year)
        if key in seen:
            continue
        seen.add(key)
        segments.append({
            'marca': v.marca,
            'modelo': v.modelo,
            'marca_nombre': str(v.marca),
            'modelo_nombre': str(v.modelo),
            'year_bucket': v.year or timezone.now().year,
        })
    return segments
