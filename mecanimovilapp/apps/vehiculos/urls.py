from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import VehiculoViewSet, MarcaViewSet, MarcaVehiculoViewSet, ModeloViewSet, OfertaVehiculoViewSet
from .views_health import VehicleHealthViewSet

# Configuración del router
router = DefaultRouter()
router.register(r'ofertas', OfertaVehiculoViewSet, basename='oferta-vehiculo')
router.register(r'marcas', MarcaViewSet)
router.register(r'marcas-vehiculos', MarcaVehiculoViewSet)
router.register(r'modelos', ModeloViewSet)
router.register(r'health', VehicleHealthViewSet, basename='vehicle-health')
router.register(r'', VehiculoViewSet)

urlpatterns = [
    path('', include(router.urls)),
] 