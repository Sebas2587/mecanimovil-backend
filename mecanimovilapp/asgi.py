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

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')
django.setup()

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter

from mecanimovilapp.apps.usuarios.routing import websocket_urlpatterns
import mecanimovilapp.apps.chat.routing
from mecanimovilapp.apps.usuarios.middleware import TokenAuthMiddleware

# AllowedHostsOriginValidator was removed intentionally:
# Mobile apps (React Native) don't send an Origin header, and the Vercel
# web frontend uses a different domain than ALLOWED_HOSTS.  WebSocket
# security is enforced by token authentication in TokenAuthMiddleware
# and each consumer's connect() method — not by browser-origin checks.

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": TokenAuthMiddleware(
        URLRouter(
            websocket_urlpatterns + mecanimovilapp.apps.chat.routing.websocket_urlpatterns
        )
    ),
})
