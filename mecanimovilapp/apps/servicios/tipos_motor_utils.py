"""
Utilidades compartidas para compatibilidad por tipo de motor (catálogo maestro).
"""
from __future__ import annotations

from django.db.models import Q, QuerySet

from mecanimovilapp.apps.vehiculos.catalogo_resolver import normalizar_tipo_motor_vehiculo

from .models import TIPOS_MOTOR_COMPATIBLES_VALIDOS


def normalizar_lista_tipos_motor(tipos: list | None) -> list[str]:
    """Normaliza y deduplica tipos de motor válidos."""
    if not tipos:
        return []
    vistos: set[str] = set()
    resultado: list[str] = []
    for raw in tipos:
        norm = normalizar_tipo_motor_vehiculo(raw)
        if norm in TIPOS_MOTOR_COMPATIBLES_VALIDOS and norm not in vistos:
            vistos.add(norm)
            resultado.append(norm)
    return resultado


def tipos_motor_universal(tipos: list | None) -> bool:
    """Lista vacía = aplica a todos los tipos de motor."""
    return not tipos


def servicio_compatible_con_tipo_motor(obj, tipo_motor_raw: str | None) -> bool:
    """
    Evalúa compatibilidad de Servicio o Repuesto con un tipo de motor.
    obj debe tener atributo tipos_motor_compatibles.
    """
    tipos = getattr(obj, 'tipos_motor_compatibles', None) or []
    if tipos_motor_universal(tipos):
        return True
    motor = normalizar_tipo_motor_vehiculo(tipo_motor_raw)
    return motor in normalizar_lista_tipos_motor(tipos)


def queryset_filtrar_por_tipo_motor(qs: QuerySet, tipo_motor_raw: str | None) -> QuerySet:
    """
    Filtra queryset de Servicio/Repuesto por tipo de motor (DB).
    Sin tipo_motor no filtra.
    """
    if not tipo_motor_raw:
        return qs
    motor = normalizar_tipo_motor_vehiculo(tipo_motor_raw)
    return qs.filter(
        Q(tipos_motor_compatibles=[])
        | Q(tipos_motor_compatibles__contains=[motor])
    ).distinct()
