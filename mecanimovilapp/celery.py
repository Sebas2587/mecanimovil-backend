"""
Configuración de Celery para tareas asíncronas
"""
import os
from celery import Celery
from django.conf import settings

# Establecer el módulo de configuración de Django por defecto
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')

# Crear instancia de Celery
app = Celery('mecanimovilapp')

# Cargar configuración desde settings de Django
app.config_from_object('django.conf:settings', namespace='CELERY')

# Autodescubrir tareas en todas las apps instaladas
app.autodiscover_tasks()

# Configuración de tareas periódicas (Celery Beat)
from celery.schedules import crontab

app.conf.beat_schedule = {
    'recalcular-salud-vehiculos': {
        'task': 'mecanimovilapp.apps.vehiculos.tasks.recalcular_salud_vehiculos_batch',
        'schedule': crontab(hour='*/6', minute=0),  # Cada 6 horas
    },
}

@app.task(bind=True)
def debug_task(self):
    """
    Tarea de debug para verificar que Celery está funcionando
    """
    print(f'Request: {self.request!r}')

