"""
Catálogo maestro Servicio ↔ vehículo (marca/modelo/tipo_motor).
"""
from django.db.models import Q

from mecanimovilapp.apps.usuarios.models import MecanicoDomicilio, Taller
from mecanimovilapp.apps.usuarios.proveedor_cobertura import TIPO_COBERTURA_MULTIMARCA

from .compatibilidad_vehiculo import queryset_servicios_catalogo_por_marca_modelo
from .models import Servicio
from .oferta_compatibilidad import normalizar_tipo_motor_oferta
from mecanimovilapp.apps.vehiculos.catalogo_resolver import normalizar_tipo_motor_vehiculo


def _q_oferta_motor(tipo_motor: str | None) -> Q:
    """Oferta universal ('' tipo_motor) o específica para el motor del vehículo."""
    if not tipo_motor:
        return Q(pk__isnull=False)
    motor = normalizar_tipo_motor_vehiculo(tipo_motor)
    return Q(ofertas__tipo_motor='') | Q(ofertas__tipo_motor=motor)


def queryset_servicios_disponibles_para_modelo_marca(modelo, marca, tipo_motor=None):
    """
    Unión de:
    - servicios compatibles con marca/modelo/motor (catálogo maestro);
    - servicios con oferta explícita para la marca y motor;
    - servicios con oferta genérica de especialistas en la marca;
    - servicios con oferta de proveedores multimarca verificados.
    """
    if not modelo or not marca:
        return Servicio.objects.none()

    servicios_por_catalogo = queryset_servicios_catalogo_por_marca_modelo(
        modelo, marca, tipo_motor=tipo_motor
    )
    q_motor = _q_oferta_motor(tipo_motor)

    servicios_con_ofertas = Servicio.objects.filter(
        q_motor,
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
        q_motor,
        Q(ofertas__marca_vehiculo_seleccionada__isnull=True)
        & Q(ofertas__disponible=True)
        & (
            Q(ofertas__taller_id__in=talleres_esp)
            | Q(ofertas__mecanico_id__in=mecanicos_esp)
        ),
    ).distinct()

    talleres_mm, mecanicos_mm = _ids_proveedores_multimarca_activos()
    q_marca_oferta_mm = Q(ofertas__marca_vehiculo_seleccionada=marca) | Q(
        ofertas__marca_vehiculo_seleccionada__isnull=True
    )
    servicios_multimarca = Servicio.objects.filter(
        q_motor,
        Q(ofertas__disponible=True)
        & q_marca_oferta_mm
        & (
            Q(ofertas__taller_id__in=talleres_mm)
            | Q(ofertas__mecanico_id__in=mecanicos_mm)
        ),
    ).distinct()

    servicios = (
        servicios_por_catalogo
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
        'marcas_compatibles',
        'modelos_compatibles',
        'modelos_compatibles__marca',
    )


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
