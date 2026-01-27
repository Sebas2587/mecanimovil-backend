"""
ASGI config for mecanimovilapp project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/

Nota: En producción (Render), se usa daphne como servidor ASGI.
El comando de inicio es: daphne -b 0.0.0.0 -p $PORT mecanimovilapp.asgi:application
"""

import os
import django

# Usar settings_production si DJANGO_SETTINGS_MODULE no está configurado
# En Render, se configura explícitamente en render.yaml
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')
django.setup()

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

# Importar las rutas de WebSocket después de configurar Django
from mecanimovilapp.apps.usuarios.routing import websocket_urlpatterns
import mecanimovilapp.apps.chat.routing
from mecanimovilapp.apps.usuarios.middleware import TokenAuthMiddleware

# Aplicación ASGI con soporte para HTTP y WebSockets
application = ProtocolTypeRouter({
    # HTTP requests son manejados por Django
    "http": get_asgi_application(),
    # WebSocket connections con autenticación por token
    "websocket": AllowedHostsOriginValidator(
        TokenAuthMiddleware(
            URLRouter(
                websocket_urlpatterns + mecanimovilapp.apps.chat.routing.websocket_urlpatterns
            )
        )
    ),
})
