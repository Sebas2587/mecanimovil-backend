"""
URLs para la app de pagos con Mercado Pago Checkout Pro
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PreferenciaPagoViewSet,
    PagoViewSet,
    get_public_key,
    webhook_notification,
)

router = DefaultRouter()
router.register(r'preferences', PreferenciaPagoViewSet, basename='preference')
router.register(r'payments', PagoViewSet, basename='payment')

urlpatterns = [
    path('', include(router.urls)),
    path('public-key/', get_public_key, name='public-key'),
    path('create-preference/', PreferenciaPagoViewSet.as_view({'post': 'create_preference'}), name='create-preference'),
    path('webhook/', webhook_notification, name='webhook'),
]