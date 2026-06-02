"""
Compatibilidad OfertaServicio ↔ vehículo (tipo de motor).
"""
from __future__ import annotations

from django.core.exceptions import ValidationError

from mecanimovilapp.apps.vehiculos.models import Vehiculo

from .models import OfertaServicio, Servicio, TIPOS_MOTOR_COMPATIBLES_VALIDOS
from .tipos_motor_utils import (
    normalizar_lista_tipos_motor,
    servicio_compatible_con_tipo_motor,
    tipos_motor_universal,
)
from mecanimovilapp.apps.vehiculos.catalogo_resolver import normalizar_tipo_motor_vehiculo


def normalizar_tipo_motor_oferta(valor: str | None) -> str:
    """Vacío = oferta para todos los motores del catálogo del servicio."""
    if not valor or not str(valor).strip():
        return ''
    return normalizar_tipo_motor_vehiculo(valor)


def motores_catalogo_servicio(servicio: Servicio | None) -> list[str]:
    """Motores aplicables según catálogo maestro ([] = todos)."""
    if not servicio:
        return []
    return normalizar_lista_tipos_motor(getattr(servicio, 'tipos_motor_compatibles', None) or [])


def motores_opciones_para_proveedor(servicio: Servicio | None) -> list[str]:
    """
    Opciones que el proveedor puede elegir al publicar.
    Si el catálogo es universal, devuelve los cuatro tipos estándar.
    """
    catalogo = motores_catalogo_servicio(servicio)
    if tipos_motor_universal(catalogo):
        return list(TIPOS_MOTOR_COMPATIBLES_VALIDOS)
    return catalogo


def validar_tipo_motor_oferta(servicio: Servicio | None, tipo_motor_raw: str | None) -> str:
    """
    Valida y normaliza tipo_motor de la oferta (subconjunto del catálogo).
    Retorna '' = todos los motores aplicables del servicio.
    """
    normalizado = normalizar_tipo_motor_oferta(tipo_motor_raw)
    if not servicio or not normalizado:
        return normalizado

    catalogo = motores_catalogo_servicio(servicio)
    if tipos_motor_universal(catalogo):
        if normalizado not in TIPOS_MOTOR_COMPATIBLES_VALIDOS:
            raise ValidationError(f'Tipo de motor inválido: {tipo_motor_raw}')
        return normalizado

    if normalizado not in catalogo:
        raise ValidationError(
            f'El servicio «{servicio.nombre}» no aplica a motor {normalizado}. '
            f'Motores permitidos: {", ".join(catalogo)}.'
        )
    return normalizado


def oferta_compatible_con_tipo_motor(oferta: OfertaServicio, tipo_motor_vehiculo: str | None) -> bool:
    """¿La oferta aplica al tipo de motor del vehículo?"""
    servicio = getattr(oferta, 'servicio', None)
    if servicio and not servicio_compatible_con_tipo_motor(servicio, tipo_motor_vehiculo):
        return False

    tipo_oferta = normalizar_tipo_motor_oferta(getattr(oferta, 'tipo_motor', None))
    if not tipo_oferta:
        return True

    motor_v = normalizar_tipo_motor_vehiculo(tipo_motor_vehiculo)
    return motor_v == tipo_oferta


def oferta_compatible_con_vehiculo(oferta: OfertaServicio, vehiculo: Vehiculo | None) -> bool:
    if not vehiculo:
        return True
    return oferta_compatible_con_tipo_motor(oferta, getattr(vehiculo, 'tipo_motor', None))
