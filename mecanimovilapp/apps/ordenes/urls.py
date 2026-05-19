from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    SolicitudServicioViewSet, LineaServicioViewSet,
    CarritoAgendamientoViewSet, AgendamientoViewSet,
    ProveedorOrdenesViewSet,
    SolicitudPublicaViewSet, OfertaProveedorViewSet, ChatSolicitudViewSet,
    validar_disponibilidad_taller, validar_disponibilidad_mecanico,
    obtener_configuracion_precio, calcular_precio_detallado
)
from .views_asistente_agendamiento import AsistenteAgendamientoViewSet

app_name = 'ordenes'

# Router para ViewSets
router = DefaultRouter()
router.register(r'solicitudes', SolicitudServicioViewSet, basename='solicitud')
router.register(r'lineas', LineaServicioViewSet, basename='linea')
router.register(r'carritos', CarritoAgendamientoViewSet, basename='carrito')
router.register(r'agendamiento', AgendamientoViewSet, basename='agendamiento')
router.register(r'proveedor-ordenes', ProveedorOrdenesViewSet, basename='proveedor-ordenes')
router.register(r'solicitudes-publicas', SolicitudPublicaViewSet, basename='solicitud-publica')
router.register(r'ofertas', OfertaProveedorViewSet, basename='oferta')
router.register(r'chat-solicitudes', ChatSolicitudViewSet, basename='chat-solicitud')
router.register(
    r'asistente-agendamiento',
    AsistenteAgendamientoViewSet,
    basename='asistente-agendamiento',
)

# RUTAS DE DISPONIBILIDAD ELIMINADAS - REEMPLAZADAS POR ENDPOINTS EN USUARIOS APP
# Los horarios ahora se manejan desde:
# - /api/usuarios/talleres/{id}/horarios_disponibles/
# - /api/usuarios/mecanicos-domicilio/{id}/horarios_disponibles/

urlpatterns = [
    # Incluir rutas del router
    path('', include(router.urls)),
    
    # Endpoints para validación de disponibilidad (DEPRECADOS, mantienen compatibilidad)
    path('validar_disponibilidad/', validar_disponibilidad_taller, name='validar_disponibilidad_taller'),
    path('validar_disponibilidad_mecanico/', validar_disponibilidad_mecanico, name='validar_disponibilidad_mecanico'),
    
    # Endpoints para configuración de precios
    path('configuracion_precio/', obtener_configuracion_precio, name='configuracion_precio'),
    path('calcular_precio/', calcular_precio_detallado, name='calcular_precio'),
] 