"""
Compatibilidad catálogo maestro Servicio ↔ vehículo (marca/modelo/tipo_motor).

Reglas:
- Genérico: sin marcas ni modelos → cualquier vehículo.
- Marca directa (marcas_compatibles): aplica a toda la marca salvo restricción por modelos.
- Legacy: solo modelos_compatibles → marca inferida; restricción por modelo si aplica.
- tipos_motor_compatibles vacío → todos los motores; si tiene valores, filtra por tipo_motor.
- Ofertas de proveedor (OfertaServicio.marca_vehiculo_seleccionada) se evalúan aparte en catalogo_vehiculo.
"""
from __future__ import annotations

from django.db.models import Count, Q, QuerySet

from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo, Modelo, Vehiculo

from .models import Servicio
from .tipos_motor_utils import (
    queryset_filtrar_por_tipo_motor,
    servicio_compatible_con_tipo_motor,
)


def _annotate_conteos_compatibilidad(qs: QuerySet[Servicio]) -> QuerySet[Servicio]:
    return qs.annotate(
        _n_marcas=Count('marcas_compatibles', distinct=True),
        _n_modelos=Count('modelos_compatibles', distinct=True),
    )


def queryset_servicios_genericos() -> QuerySet[Servicio]:
    """Servicios sin marcas ni modelos asignados (catálogo universal)."""
    return _annotate_conteos_compatibilidad(Servicio.objects.all()).filter(
        _n_marcas=0,
        _n_modelos=0,
    )


def queryset_servicios_catalogo_por_marca(marca_id, tipo_motor: str | None = None) -> QuerySet[Servicio]:
    """
    Servicios del catálogo maestro para una marca (onboarding / referencia proveedor).
    marca_id == 0 → genéricos.
    """
    marca_key = str(marca_id)
    if marca_key == '0':
        qs = queryset_servicios_genericos().order_by('nombre')
    else:
        qs = (
            Servicio.objects.filter(
                Q(marcas_compatibles__id=marca_id)
                | Q(modelos_compatibles__marca_id=marca_id)
            )
            .distinct()
            .order_by('nombre')
        )
    return queryset_filtrar_por_tipo_motor(qs, tipo_motor)


def _restriccion_modelo_q(marca_id: int, modelo_id: int | None) -> Q:
    """
    Si el servicio lista modelos de la marca, el vehículo debe coincidir con uno.
    Si no lista modelos de esa marca, no restringe por modelo.
    """
    if modelo_id is None:
        return Q(pk__isnull=False)

    tiene_modelos_marca = Q(modelos_compatibles__marca_id=marca_id)
    modelo_ok = Q(modelos_compatibles__marca_id=marca_id, modelos_compatibles__id=modelo_id)
    sin_modelos_marca = ~tiene_modelos_marca
    return sin_modelos_marca | modelo_ok


def queryset_servicios_catalogo_por_marca_modelo(
    modelo: Modelo | None,
    marca: MarcaVehiculo | None,
    tipo_motor: str | None = None,
) -> QuerySet[Servicio]:
    """Servicios del catálogo maestro compatibles con marca/modelo (y opcionalmente motor)."""
    if not marca:
        return Servicio.objects.none()

    base = queryset_servicios_catalogo_por_marca(marca.id, tipo_motor=tipo_motor)
    modelo_id = modelo.id if modelo else None
    return base.filter(_restriccion_modelo_q(marca.id, modelo_id)).distinct()


def queryset_servicios_compatibles_vehiculo(vehiculo: Vehiculo | None) -> QuerySet[Servicio]:
    """Queryset de servicios de catálogo compatibles con un vehículo registrado."""
    if not vehiculo or not vehiculo.marca_id:
        return Servicio.objects.none()

    marca = vehiculo.marca
    modelo = vehiculo.modelo if vehiculo.modelo_id else None
    tipo_motor = getattr(vehiculo, 'tipo_motor', None)
    return queryset_servicios_catalogo_por_marca_modelo(modelo, marca, tipo_motor=tipo_motor)


def servicio_es_generico(servicio: Servicio) -> bool:
    if hasattr(servicio, '_n_marcas') and hasattr(servicio, '_n_modelos'):
        return servicio._n_marcas == 0 and servicio._n_modelos == 0
    return (
        not servicio.marcas_compatibles.exists()
        and not servicio.modelos_compatibles.exists()
    )


def servicio_compatible_con_marca_modelo(
    servicio: Servicio,
    marca: MarcaVehiculo | None,
    modelo: Modelo | None = None,
    tipo_motor: str | None = None,
) -> bool:
    """Evalúa compatibilidad de instancia (ideal con prefetch de marcas/modelos)."""
    if not servicio_compatible_con_tipo_motor(servicio, tipo_motor):
        return False

    if servicio_es_generico(servicio):
        return True
    if not marca:
        return False

    marca_ok = servicio.marcas_compatibles.filter(pk=marca.pk).exists()
    if not marca_ok:
        if servicio.marcas_compatibles.exists():
            return False
        marca_ok = servicio.modelos_compatibles.filter(marca_id=marca.pk).exists()
    if not marca_ok:
        return False

    modelos_marca = servicio.modelos_compatibles.filter(marca_id=marca.pk)
    if not modelos_marca.exists():
        return True
    if modelo is None:
        return True
    return modelos_marca.filter(pk=modelo.pk).exists()


def servicio_compatible_con_vehiculo(servicio: Servicio, vehiculo: Vehiculo | None) -> bool:
    """Compatibilidad completa marca + modelo + tipo de motor."""
    if not vehiculo or not vehiculo.marca_id:
        return False
    modelo = vehiculo.modelo if vehiculo.modelo_id else None
    return servicio_compatible_con_marca_modelo(
        servicio,
        vehiculo.marca,
        modelo,
        tipo_motor=getattr(vehiculo, 'tipo_motor', None),
    )


def servicios_comunes_por_marcas_queryset(
    marca_ids: list[int],
    tipo_motor: str | None = None,
) -> QuerySet[Servicio]:
    """Intersección de servicios compatibles con todas las marcas indicadas."""
    ids = [int(m) for m in marca_ids if str(m) not in ('', '0')]
    if not ids:
        return Servicio.objects.none()
    if len(ids) == 1:
        return queryset_servicios_catalogo_por_marca(ids[0], tipo_motor=tipo_motor)

    conjuntos = [
        set(
            queryset_servicios_catalogo_por_marca(marca_id, tipo_motor=tipo_motor).values_list(
                'id', flat=True
            )
        )
        for marca_id in ids
    ]
    comunes = set.intersection(*conjuntos) if conjuntos else set()
    if not comunes:
        return Servicio.objects.none()
    return Servicio.objects.filter(id__in=comunes).order_by('nombre')
