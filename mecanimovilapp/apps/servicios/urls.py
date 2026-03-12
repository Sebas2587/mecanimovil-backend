from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CategoriaServicioViewSet, ServicioViewSet, servicios_buscar_alias,
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

# Alias: muchos clientes llaman GET /api/servicios/<pk>/ pero el router expone
# /api/servicios/servicios/<pk>/ — este path evita 404 en producción.
urlpatterns = [
    path(
        '<int:pk>/',
        ServicioViewSet.as_view({'get': 'retrieve'}),
        name='servicio-detail-alias',
    ),
    # Cliente llama GET /api/servicios/buscar/?q= — la acción del ViewSet queda en .../servicios/servicios/buscar/
    path('buscar/', servicios_buscar_alias, name='servicios-buscar-alias'),
    path('', include(router.urls)),
    # Endpoints públicos sin autenticación
    path('vehiculo-servicios/', servicios_por_vehiculo, name='servicios_por_vehiculo'),
] 