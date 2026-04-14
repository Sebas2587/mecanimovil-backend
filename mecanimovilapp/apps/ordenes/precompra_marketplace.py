"""
Helpers de inspección pre-compra marketplace.

Centraliza la validación del bypass de propiedad de vehículo
y la detección del servicio de inspección pre-compra.
"""
import re
from rest_framework.exceptions import ValidationError

_PRECOMPRA_RE = re.compile(r'inspecci[oó]n.*pre[\s\-]?compra', re.IGNORECASE)


def es_servicio_precompra(servicio):
    """Determina si un Servicio corresponde a inspección pre-compra."""
    if servicio is None:
        return False
    nombre = (servicio.nombre or '').strip()
    return bool(_PRECOMPRA_RE.search(nombre))


def validar_precompra_marketplace(cliente, vehiculo, oferta_vehiculo_id):
    """
    Valida que exista una OfertaVehiculo aceptada donde `cliente` es el
    comprador y el vehículo coincide.

    Retorna la instancia de OfertaVehiculo si es válida; lanza
    ValidationError en caso contrario.
    """
    from mecanimovilapp.apps.vehiculos.models import OfertaVehiculo

    try:
        oferta = OfertaVehiculo.objects.select_related('vehiculo', 'comprador').get(
            id=oferta_vehiculo_id,
        )
    except OfertaVehiculo.DoesNotExist:
        raise ValidationError('Oferta de compra marketplace no encontrada.')

    if oferta.estado != 'aceptada':
        raise ValidationError('La oferta de compra no está en estado aceptada.')

    if oferta.vehiculo_id != vehiculo.id:
        raise ValidationError('El vehículo no corresponde a la oferta indicada.')

    if oferta.comprador_id != cliente.usuario_id:
        raise ValidationError('El usuario no es el comprador de esta oferta.')

    return oferta
