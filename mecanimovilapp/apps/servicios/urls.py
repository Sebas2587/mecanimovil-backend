from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CategoriaServicioViewSet, ServicioViewSet,
    DetalleServicioViewSet, OfertaServicioViewSet,
    ProveedorOfertaServicioViewSet, RepuestoViewSet,
    FotoServicioViewSet, servicios_por_vehiculo
)

# Configuración del router
router = DefaultRouter()
router.register(r'categorias', CategoriaServicioViewSet)
router.register(r'servicios', ServicioViewSet)
router.register(r'detalles-servicios', DetalleServicioViewSet)
router.register(r'ofertas', OfertaServicioViewSet)

# Nuevas rutas específicas para PROVEEDORES
router.register(r'proveedor/mis-servicios', ProveedorOfertaServicioViewSet, basename='proveedor-servicios')
router.register(r'repuestos', RepuestoViewSet)
router.register(r'fotos-servicios', FotoServicioViewSet, basename='fotos-servicios')

urlpatterns = [
    path('', include(router.urls)),
    # Endpoints públicos sin autenticación
    path('vehiculo-servicios/', servicios_por_vehiculo, name='servicios_por_vehiculo'),
] 