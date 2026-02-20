"""
URLs para la app de suscripciones (créditos + suscripciones mensuales).
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PaqueteCreditosViewSet,
    CompraCreditosViewSet,
    CreditoProveedorViewSet,
    PlanSuscripcionViewSet,
    SuscripcionProveedorViewSet,
)

# Router para créditos (sistema Pay-per-Win)
router_creditos = DefaultRouter()
router_creditos.register(r'paquetes', PaqueteCreditosViewSet, basename='paquete-creditos')
router_creditos.register(r'compras', CompraCreditosViewSet, basename='compra-creditos')
router_creditos.register(r'mi-saldo', CreditoProveedorViewSet, basename='credito-proveedor')

# Router para suscripciones mensuales
router_suscripciones = DefaultRouter()
router_suscripciones.register(r'planes', PlanSuscripcionViewSet, basename='plan-suscripcion')
router_suscripciones.register(r'mi-suscripcion', SuscripcionProveedorViewSet, basename='suscripcion-proveedor')

urlpatterns = [
    path('creditos/', include(router_creditos.urls)),
    path('suscripciones/', include(router_suscripciones.urls)),
    # Webhook en raíz de suscripciones para URL limpia usada con MP
    path(
        'suscripciones/webhook-preapproval/',
        SuscripcionProveedorViewSet.as_view({'post': 'webhook_preapproval'}),
        name='webhook-preapproval',
    ),
]
