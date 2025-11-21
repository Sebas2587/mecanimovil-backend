from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'vehiculo-activo', views.VehiculoActivoViewSet, basename='vehiculo-activo')
router.register(r'recomendaciones', views.RecomendacionesViewSet, basename='recomendaciones')
router.register(r'busqueda', views.BusquedaPersonalizadaViewSet, basename='busqueda-personalizada')

urlpatterns = [
    path('', include(router.urls)),
] 