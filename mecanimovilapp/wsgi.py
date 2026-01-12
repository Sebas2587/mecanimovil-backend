"""
WSGI config for mecanimovilapp project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

# Usar settings_production si DJANGO_SETTINGS_MODULE no está configurado
# En Render, se configura explícitamente en render.yaml
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')

application = get_wsgi_application()
