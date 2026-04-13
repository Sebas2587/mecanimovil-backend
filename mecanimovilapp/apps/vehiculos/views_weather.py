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
    get_prediction_for_coords,
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
    lat_param = request.query_params.get('lat')
    lng_param = request.query_params.get('lng')
    force_refresh = request.query_params.get('force_refresh', '').lower() in ('1', 'true')

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

    # Prioridad 1: coordenadas GPS enviadas desde el dispositivo
    if lat_param and lng_param:
        try:
            lat = float(lat_param)
            lng = float(lng_param)
        except ValueError:
            return Response(
                {'error': 'Parámetros lat/lng inválidos.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        prediction = get_prediction_for_coords(lat, lng, vehicle, force_refresh=force_refresh)
        return Response(prediction)

    # Prioridad 2: dirección guardada en el backend
    def _build_address_text(addr_obj):
        parts = [addr_obj.direccion or '']
        if addr_obj.detalles:
            parts.append(addr_obj.detalles)
        return ' '.join(filter(None, parts))

    def _prediction_from_addr(addr_obj):
        """Usa coords del PointField si existen (más preciso), si no hace string-match."""
        label = addr_obj.etiqueta
        addr_text = _build_address_text(addr_obj)
        addr_id = addr_obj.id

        if addr_obj.ubicacion:
            lat = addr_obj.ubicacion.y
            lng = addr_obj.ubicacion.x
            pred = get_prediction_for_coords(lat, lng, vehicle, force_refresh=force_refresh)
        else:
            pred = get_prediction_for_address(addr_text, vehicle, force_refresh=force_refresh)

        pred['address'] = {
            'id': addr_id,
            'direccion': addr_text,
            'etiqueta': label,
        }
        return pred

    if address_id:
        try:
            addr = DireccionUsuario.objects.get(id=address_id, usuario=user)
            return Response(_prediction_from_addr(addr))
        except DireccionUsuario.DoesNotExist:
            return Response(
                {'error': 'Dirección no encontrada.'},
                status=status.HTTP_404_NOT_FOUND,
            )

    # Sin address_id: usar principal o primera disponible
    addr = (
        DireccionUsuario.objects
        .filter(usuario=user, es_principal=True)
        .first()
    )
    if not addr:
        addr = DireccionUsuario.objects.filter(usuario=user).first()

    if addr:
        return Response(_prediction_from_addr(addr))

    if user.direccion:
        prediction = get_prediction_for_address(user.direccion, vehicle, force_refresh=force_refresh)
        prediction['address'] = {'id': None, 'direccion': user.direccion, 'etiqueta': 'Perfil'}
        return Response(prediction)

    return Response({
        'available': False,
        'reason': 'No tienes una dirección registrada. Agrega una dirección o activa el GPS para ver el clima.',
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def weather_stations(request):
    """Retorna la lista de estaciones meteorológicas disponibles."""
    stations = [
        {'code': code, 'city': city}
        for code, city in sorted(STATION_MAP.items(), key=lambda x: x[1])
    ]
    return Response({'stations': stations})
