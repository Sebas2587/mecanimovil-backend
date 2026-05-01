"""
URLs para la app de suscripciones (créditos + suscripciones mensuales).

mecanimovilapp/urls.py monta esta app en: api/suscripciones/
Rutas resultantes:
  api/suscripciones/creditos/paquetes/           → créditos (existente)
  api/suscripciones/creditos/compras/            → créditos (existente)
  api/suscripciones/creditos/mi-saldo/           → créditos (existente)
  api/suscripciones/planes/                      → planes de suscripción (nuevo)
  api/suscripciones/mi-suscripcion/              → suscripción del proveedor (nuevo)
  api/suscripciones/webhook-preapproval/         → webhook MP Preapproval (nuevo)
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

# Router de créditos (sistema Pay-per-Win existente) — montado en creditos/
router_creditos = DefaultRouter()
router_creditos.register(r'paquetes', PaqueteCreditosViewSet, basename='paquete-creditos')
router_creditos.register(r'compras', CompraCreditosViewSet, basename='compra-creditos')
router_creditos.register(r'mi-saldo', CreditoProveedorViewSet, basename='credito-proveedor')

# Router de suscripciones mensuales — montado directamente en la raíz
router_suscripciones = DefaultRouter()
router_suscripciones.register(r'planes', PlanSuscripcionViewSet, basename='plan-suscripcion')
router_suscripciones.register(r'mi-suscripcion', SuscripcionProveedorViewSet, basename='suscripcion-proveedor')

urlpatterns = [
    # Tabla servicio ↔ créditos (ruta explícita): evita que el router trate
    # "tabla-servicios-creditos" como pk de GET .../mi-saldo/<pk>/ (retrieve).
    path(
        'creditos/tabla-servicios-creditos/',
        CreditoProveedorViewSet.as_view({'get': 'tabla_servicios_creditos'}),
        name='credito-tabla-servicios-creditos',
    ),
    # Créditos en api/suscripciones/creditos/...
    path('creditos/', include(router_creditos.urls)),
    # Suscripciones directamente en api/suscripciones/planes/ y mi-suscripcion/
    path('', include(router_suscripciones.urls)),
    # Webhook MercadoPago Preapproval
    path(
        'webhook-preapproval/',
        SuscripcionProveedorViewSet.as_view({'post': 'webhook_preapproval'}),
        name='webhook-preapproval',
    ),
]
