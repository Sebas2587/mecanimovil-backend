"""
Servicios disponibles para agendar según modelo/marca del vehículo.
Incluye ofertas de especialistas en la marca y de proveedores multimarca.
"""
from django.db.models import Q

from mecanimovilapp.apps.usuarios.models import MecanicoDomicilio, Taller
from mecanimovilapp.apps.usuarios.proveedor_cobertura import TIPO_COBERTURA_MULTIMARCA

from .models import Servicio


def _ids_proveedores_multimarca_activos():
    talleres_mm = Taller.objects.filter(
        tipo_cobertura_marca=TIPO_COBERTURA_MULTIMARCA,
        verificado=True,
        activo=True,
    ).values_list('id', flat=True)
    mecanicos_mm = MecanicoDomicilio.objects.filter(
        tipo_cobertura_marca=TIPO_COBERTURA_MULTIMARCA,
        verificado=True,
        activo=True,
    ).values_list('id', flat=True)
    return talleres_mm, mecanicos_mm


def queryset_servicios_disponibles_para_modelo_marca(modelo, marca):
    """
    Unión de:
    - servicios compatibles con el modelo;
    - servicios con oferta explícita para la marca;
    - servicios con oferta genérica de especialistas en la marca;
    - servicios con oferta de proveedores multimarca verificados.
    """
    if not modelo or not marca:
        return Servicio.objects.none()

    servicios_por_modelo = Servicio.objects.filter(modelos_compatibles=modelo).distinct()

    servicios_con_ofertas = Servicio.objects.filter(
        ofertas__marca_vehiculo_seleccionada=marca,
        ofertas__disponible=True,
    ).distinct()

    talleres_esp = Taller.objects.filter(
        marcas_atendidas=marca,
        verificado=True,
        activo=True,
    ).values_list('id', flat=True)
    mecanicos_esp = MecanicoDomicilio.objects.filter(
        marcas_atendidas=marca,
        verificado=True,
        activo=True,
    ).values_list('id', flat=True)

    servicios_con_ofertas_genericas = Servicio.objects.filter(
        Q(ofertas__marca_vehiculo_seleccionada__isnull=True)
        & Q(ofertas__disponible=True)
        & (
            Q(ofertas__taller_id__in=talleres_esp)
            | Q(ofertas__mecanico_id__in=mecanicos_esp)
        )
    ).distinct()

    talleres_mm, mecanicos_mm = _ids_proveedores_multimarca_activos()
    servicios_multimarca = Servicio.objects.filter(
        Q(ofertas__disponible=True)
        & (
            Q(ofertas__taller_id__in=talleres_mm)
            | Q(ofertas__mecanico_id__in=mecanicos_mm)
        )
    ).distinct()

    servicios = (
        servicios_por_modelo
        | servicios_con_ofertas
        | servicios_con_ofertas_genericas
        | servicios_multimarca
    ).distinct()

    servicios_ids = list(servicios.values_list('id', flat=True))
    return Servicio.objects.filter(id__in=servicios_ids).prefetch_related(
        'ofertas',
        'ofertas__taller',
        'ofertas__mecanico',
        'ofertas__mecanico__usuario',
        'categorias',
    )
