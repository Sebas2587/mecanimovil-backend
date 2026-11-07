#!/usr/bin/env python
import os
import django

# Force dummy cache and disable Celery before Django starts
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')

# Patch settings before import
from mecanimovilapp import settings
settings.CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
    }
}
# Use eager mode for Celery (no Redis needed)
settings.CELERY_TASK_ALWAYS_EAGER = True
settings.CELERY_TASK_EAGER_PROPAGATES = True

django.setup()

# Disconnect Celery-triggering signals
from django.db.models.signals import post_save
from mecanimovilapp.apps.agente_ia import signals as agente_signals
from mecanimovilapp.apps.servicios.models import OfertaServicio
from mecanimovilapp.apps.ordenes.models import SolicitudServicio

post_save.disconnect(agente_signals.sync_oferta_servicio_chunk, sender=OfertaServicio)
post_save.disconnect(agente_signals.sync_solicitud_historico_chunk, sender=SolicitudServicio)

from django.core.management import execute_from_command_line
execute_from_command_line(['manage.py', 'runserver', '0.0.0.0:8000'])
