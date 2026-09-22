from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    ProviderChannelConnectionViewSet,
    meta_oauth_callback,
    meta_webhook_receive,
)
from .views_contacto_rol import ContactoRolView

router = DefaultRouter()
router.register(r'connections', ProviderChannelConnectionViewSet, basename='omnichannel-connection')

urlpatterns = [
    path('contacts/<uuid:contact_id>/rol/', ContactoRolView.as_view(), name='contacto-rol'),
    path('', include(router.urls)),
    path('webhooks/meta/', meta_webhook_receive, name='meta-webhook'),
    path('oauth/callback/', meta_oauth_callback, name='meta-oauth-callback'),
]
