from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Consumer original para compatibilidad
    re_path(r'ws/proveedor/$', consumers.ConnectionConsumer.as_asgi()),
    
    # Nuevos consumers para el sistema de estados en tiempo real
    re_path(r'ws/mechanic_status/$', consumers.MechanicStatusConsumer.as_asgi()),
    re_path(r'ws/client_status/$', consumers.ClientStatusConsumer.as_asgi()),
] 