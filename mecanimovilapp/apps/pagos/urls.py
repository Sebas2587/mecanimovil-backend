"""
URLs para la app de pagos con Mercado Pago Checkout Pro
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PreferenciaPagoViewSet,
    PagoViewSet,
    CuentaMercadoPagoProveedorViewSet,
    get_public_key,
    webhook_notification,
    crear_preferencia_pago_proveedor,
    confirmar_pago_oferta,
    obtener_estado_pago_oferta,
    verificar_pago_mercadopago,
)
from .views_liquidacion import LiquidacionProveedorViewSet

router = DefaultRouter()
router.register(r'preferences', PreferenciaPagoViewSet, basename='preference')
router.register(r'payments', PagoViewSet, basename='payment')
router.register(r'cuenta-proveedor', CuentaMercadoPagoProveedorViewSet, basename='cuenta-proveedor')
router.register(r'liquidaciones-proveedor', LiquidacionProveedorViewSet, basename='liquidaciones-proveedor')

urlpatterns = [
    path('', include(router.urls)),
    path('public-key/', get_public_key, name='public-key'),
    path('create-preference/', PreferenciaPagoViewSet.as_view({'post': 'create_preference'}), name='create-preference'),
    path('webhook/', webhook_notification, name='webhook'),
    # Endpoints para pago directo al proveedor
    path('pago-proveedor/', crear_preferencia_pago_proveedor, name='pago-proveedor'),
    path('confirmar-pago-oferta/', confirmar_pago_oferta, name='confirmar-pago-oferta'),
    path('estado-pago-oferta/<uuid:oferta_id>/', obtener_estado_pago_oferta, name='estado-pago-oferta'),
    path('verificar-pago-mercadopago/', verificar_pago_mercadopago, name='verificar-pago-mercadopago'),
]
