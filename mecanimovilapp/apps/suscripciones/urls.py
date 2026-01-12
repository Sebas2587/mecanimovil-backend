"""
URLs para la app de suscripciones.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PaqueteCreditosViewSet,
    CompraCreditosViewSet,
    CreditoProveedorViewSet
)

# Router para créditos (sistema Pay-per-Win)
router_creditos = DefaultRouter()
router_creditos.register(r'paquetes', PaqueteCreditosViewSet, basename='paquete-creditos')
router_creditos.register(r'compras', CompraCreditosViewSet, basename='compra-creditos')
router_creditos.register(r'mi-saldo', CreditoProveedorViewSet, basename='credito-proveedor')

urlpatterns = [
    path('creditos/', include(router_creditos.urls)),
]

