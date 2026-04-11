"""
Vista DRF para predicción de desgaste vehicular basada en clima.
GET /api/vehiculos/weather-prediction/?address_id=<id>&vehicle_id=<id>
"""
import logging
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from mecanimovilapp.apps.usuarios.models import DireccionUsuario
from mecanimovilapp.apps.vehiculos.models import Vehiculo
from mecanimovilapp.apps.vehiculos.services.weather_prediction import (
    get_prediction_for_address,
    STATION_MAP,
)

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def weather_prediction(request):
    """
    Retorna predicción de desgaste vehicular basada en clima real.
    Query params:
      - address_id: ID de una DireccionUsuario (opcional, usa principal si no se envía)
      - vehicle_id: ID de un Vehiculo (opcional, enriquece cálculo con telemetría)
    """
    user = request.user
    address_id = request.query_params.get('address_id')
    vehicle_id = request.query_params.get('vehicle_id')

    # Resolver dirección
    address_text = None
    address_label = None
    address_obj_id = None

    if address_id:
        try:
            addr = DireccionUsuario.objects.get(id=address_id, usuario=user)
            address_text = addr.direccion
            address_label = addr.etiqueta
            address_obj_id = addr.id
        except DireccionUsuario.DoesNotExist:
            return Response(
                {'error': 'Dirección no encontrada.'},
                status=status.HTTP_404_NOT_FOUND,
            )
    else:
        addr = (
            DireccionUsuario.objects
            .filter(usuario=user, es_principal=True)
            .first()
        )
        if not addr:
            addr = DireccionUsuario.objects.filter(usuario=user).first()
        if addr:
            address_text = addr.direccion
            address_label = addr.etiqueta
            address_obj_id = addr.id
        elif user.direccion:
            address_text = user.direccion
            address_label = 'Perfil'

    if not address_text:
        return Response({
            'available': False,
            'reason': 'No tienes una dirección registrada. Agrega una dirección para ver el clima.',
        })

    # Resolver vehículo (opcional)
    vehicle = None
    if vehicle_id:
        try:
            vehicle = Vehiculo.objects.select_related('cliente').get(
                id=vehicle_id,
                cliente__usuario=user,
            )
        except Vehiculo.DoesNotExist:
            pass

    prediction = get_prediction_for_address(address_text, vehicle)
    prediction['address'] = {
        'id': address_obj_id,
        'direccion': address_text,
        'etiqueta': address_label,
    }
    return Response(prediction)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def weather_stations(request):
    """Retorna la lista de estaciones meteorológicas disponibles."""
    stations = [
        {'code': code, 'city': city}
        for code, city in sorted(STATION_MAP.items(), key=lambda x: x[1])
    ]
    return Response({'stations': stations})
