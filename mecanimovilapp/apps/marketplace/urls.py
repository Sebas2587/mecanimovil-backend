from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TransferenciaViewSet

router = DefaultRouter()
router.register(r'transferencias', TransferenciaViewSet, basename='transferencia')

urlpatterns = [
    path('', include(router.urls)),
]
