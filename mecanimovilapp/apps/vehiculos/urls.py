from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import VehiculoViewSet, MarcaViewSet, MarcaVehiculoViewSet, ModeloViewSet, OfertaVehiculoViewSet
from .views_health import VehicleHealthViewSet
from .views_weather import weather_prediction, weather_stations
from .views_reclamar_informe import ReclamarInformeView

# Configuración del router
router = DefaultRouter()
router.register(r'ofertas', OfertaVehiculoViewSet, basename='oferta-vehiculo')
router.register(r'marcas', MarcaViewSet)
router.register(r'marcas-vehiculos', MarcaVehiculoViewSet)
router.register(r'modelos', ModeloViewSet)
router.register(r'health', VehicleHealthViewSet, basename='vehicle-health')
router.register(r'', VehiculoViewSet)

urlpatterns = [
    path('weather-prediction/', weather_prediction, name='weather-prediction'),
    path('weather-stations/', weather_stations, name='weather-stations'),
    path(
        'reclamar-informe/<str:token>/',
        ReclamarInformeView.as_view(),
        name='reclamar-informe',
    ),
    path('', include(router.urls)),
] 