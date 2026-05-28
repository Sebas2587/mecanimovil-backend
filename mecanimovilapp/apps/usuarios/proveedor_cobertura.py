"""Utilidades de cobertura por marca (especialista vs multimarca)."""
from django.db.models import Q

TIPO_COBERTURA_ESPECIALISTA = 'especialista'
TIPO_COBERTURA_MULTIMARCA = 'multimarca'

TIPO_COBERTURA_MARCA_CHOICES = [
    (TIPO_COBERTURA_ESPECIALISTA, 'Especialista en marcas'),
    (TIPO_COBERTURA_MULTIMARCA, 'Multimarca'),
]


def filtrar_queryset_por_marca_o_multimarca(queryset, marca):
    """
    Proveedores que atienden la marca del vehículo O están marcados como multimarca.
    `marca` puede ser instancia MarcaVehiculo o id numérico.
    """
    if marca is None:
        return queryset
    marca_id = getattr(marca, 'id', marca)
    return queryset.filter(
        Q(marcas_atendidas__id=marca_id) | Q(tipo_cobertura_marca=TIPO_COBERTURA_MULTIMARCA)
    ).distinct()
