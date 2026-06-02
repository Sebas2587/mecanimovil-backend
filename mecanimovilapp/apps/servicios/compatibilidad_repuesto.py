"""
Compatibilidad catálogo Repuesto ↔ vehículo (marca/modelo/tipo_motor).

Mismas reglas que servicios/compatibilidad_vehiculo.py.
"""
from __future__ import annotations

from django.db.models import Count, Q, QuerySet

from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo, Modelo, Vehiculo

from .models import Repuesto
from .tipos_motor_utils import (
    queryset_filtrar_por_tipo_motor,
    servicio_compatible_con_tipo_motor,
)


def _annotate_conteos(qs: QuerySet[Repuesto]) -> QuerySet[Repuesto]:
    return qs.annotate(
        _n_marcas=Count('marcas_compatibles', distinct=True),
        _n_modelos=Count('modelos_compatibles', distinct=True),
    )


def queryset_repuestos_genericos() -> QuerySet[Repuesto]:
    return _annotate_conteos(Repuesto.objects.filter(activo=True)).filter(
        _n_marcas=0,
        _n_modelos=0,
    )


def queryset_repuestos_por_marca(marca_id, tipo_motor: str | None = None) -> QuerySet[Repuesto]:
    marca_key = str(marca_id)
    if marca_key == '0':
        qs = queryset_repuestos_genericos().order_by('categoria_repuesto', 'nombre')
    else:
        qs = (
            Repuesto.objects.filter(activo=True)
            .filter(
                Q(marcas_compatibles__id=marca_id)
                | Q(modelos_compatibles__marca_id=marca_id)
            )
            .distinct()
            .order_by('categoria_repuesto', 'nombre')
        )
    return queryset_filtrar_por_tipo_motor(qs, tipo_motor)


def _restriccion_modelo_q(marca_id: int, modelo_id: int | None) -> Q:
    if modelo_id is None:
        return Q(pk__isnull=False)

    tiene_modelos_marca = Q(modelos_compatibles__marca_id=marca_id)
    modelo_ok = Q(modelos_compatibles__marca_id=marca_id, modelos_compatibles__id=modelo_id)
    return ~tiene_modelos_marca | modelo_ok


def queryset_repuestos_por_marca_modelo(
    modelo: Modelo | None,
    marca: MarcaVehiculo | None,
    tipo_motor: str | None = None,
) -> QuerySet[Repuesto]:
    if not marca:
        return Repuesto.objects.none()

    base = queryset_repuestos_por_marca(marca.id, tipo_motor=tipo_motor)
    modelo_id = modelo.id if modelo else None
    return base.filter(_restriccion_modelo_q(marca.id, modelo_id)).distinct()


def queryset_repuestos_compatibles_vehiculo(vehiculo: Vehiculo | None) -> QuerySet[Repuesto]:
    if not vehiculo or not vehiculo.marca_id:
        return Repuesto.objects.none()

    marca = vehiculo.marca
    modelo = vehiculo.modelo if vehiculo.modelo_id else None
    tipo_motor = getattr(vehiculo, 'tipo_motor', None)
    return queryset_repuestos_por_marca_modelo(modelo, marca, tipo_motor=tipo_motor)


def repuesto_es_generico(repuesto: Repuesto) -> bool:
    if hasattr(repuesto, '_n_marcas') and hasattr(repuesto, '_n_modelos'):
        return repuesto._n_marcas == 0 and repuesto._n_modelos == 0
    return (
        not repuesto.marcas_compatibles.exists()
        and not repuesto.modelos_compatibles.exists()
    )


def repuesto_compatible_con_marca_modelo(
    repuesto: Repuesto,
    marca: MarcaVehiculo | None,
    modelo: Modelo | None = None,
    tipo_motor: str | None = None,
) -> bool:
    if not servicio_compatible_con_tipo_motor(repuesto, tipo_motor):
        return False

    if repuesto_es_generico(repuesto):
        return True
    if not marca:
        return False

    marca_ok = repuesto.marcas_compatibles.filter(pk=marca.pk).exists()
    if not marca_ok:
        if repuesto.marcas_compatibles.exists():
            return False
        marca_ok = repuesto.modelos_compatibles.filter(marca_id=marca.pk).exists()
    if not marca_ok:
        return False

    modelos_marca = repuesto.modelos_compatibles.filter(marca_id=marca.pk)
    if not modelos_marca.exists():
        return True
    if modelo is None:
        return True
    return modelos_marca.filter(pk=modelo.pk).exists()


def repuesto_compatible_con_vehiculo(repuesto: Repuesto, vehiculo: Vehiculo | None) -> bool:
    if not vehiculo or not vehiculo.marca_id:
        return False
    modelo = vehiculo.modelo if vehiculo.modelo_id else None
    return repuesto_compatible_con_marca_modelo(
        repuesto,
        vehiculo.marca,
        modelo,
        tipo_motor=getattr(vehiculo, 'tipo_motor', None),
    )
