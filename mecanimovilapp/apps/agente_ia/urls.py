from django.urls import include, path
from rest_framework.routers import DefaultRouter

from mecanimovilapp.apps.agente_ia.views import AgenteIaViewSet

router = DefaultRouter()
router.register(r'', AgenteIaViewSet, basename='agente-ia')

urlpatterns = [
    path('', include(router.urls)),
]
