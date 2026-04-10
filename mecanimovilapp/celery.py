"""
Configuración de Celery para tareas asíncronas
Optimizado para prevenir sobrecarga de memoria mediante:
- Colas separadas para tareas pesadas
- Límites de workers y memoria
- Prefetch limit para evitar acumulación de tareas
- Timeouts para evitar tareas infinitas
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

# ============================================
# CONFIGURACIÓN DE COLAS SEPARADAS
# ============================================
# Separar tareas pesadas de tareas ligeras para mejor gestión de recursos
app.conf.task_routes = {
    # Tareas pesadas van a la cola 'heavy'
    'mecanimovilapp.apps.vehiculos.tasks.procesar_checklists_historicos_batch': {'queue': 'heavy'},
    'mecanimovilapp.apps.vehiculos.tasks.procesar_checklists_historicos_vehiculo': {'queue': 'heavy'},
    'mecanimovilapp.apps.vehiculos.tasks.recalcular_salud_vehiculos_batch': {'queue': 'heavy'},
    'mecanimovilapp.apps.vehiculos.tasks.recalcular_salud_vehiculos_diario': {'queue': 'heavy'},
    # Tareas ligeras van a la cola 'default' (o se puede omitir)
    'mecanimovilapp.apps.vehiculos.tasks.calcular_salud_vehiculo_async': {'queue': 'default'},
    'mecanimovilapp.apps.vehiculos.tasks.actualizar_salud_desde_checklist': {'queue': 'default'},
}

# ============================================
# OPTIMIZACIONES DE MEMORIA Y RENDIMIENTO
# ============================================
# Prefetch limit: reduce el número de tareas pre-fetchadas por worker
# Esto previene que los workers carguen muchas tareas en memoria
# Valor recomendado: 1-4 para tareas pesadas, 4-8 para tareas ligeras
app.conf.worker_prefetch_multiplier = 4  # Cada worker pre-fetcha máximo 4 tareas

# Worker max tasks per child: reinicia workers después de N tareas
# Esto previene memory leaks acumulativos
# Valor recomendado: 50-100 tareas antes de reiniciar el worker
app.conf.worker_max_tasks_per_child = 50  # Alineado con render.yaml --max-tasks-per-child=50

# Worker max memory per child: reinicia worker si excede memoria (en KB)
# Previene workers que consumen demasiada memoria
# Valor recomendado: 512MB = 512000 KB (ajustar según tu servidor)
app.conf.worker_max_memory_per_child = 512000  # 512 MB

# Task time limits: previene tareas infinitas
app.conf.task_soft_time_limit = 300  # 5 minutos - lanza SoftTimeLimitExceeded
app.conf.task_time_limit = 600  # 10 minutos - mata el worker si excede

# Result expiration: limpia resultados antiguos automáticamente
app.conf.result_expires = 3600  # 1 hora

# Task acknowledge late: solo confirma tarea cuando termina (no cuando la recibe)
# Previene pérdida de tareas si worker muere
app.conf.task_acks_late = True

# Task reject on worker lost: reintenta tareas si el worker muere
app.conf.task_reject_on_worker_lost = True

# Autodescubrir tareas en todas las apps instaladas
app.autodiscover_tasks()

# Configuración de tareas periódicas (Celery Beat)
from celery.schedules import crontab

app.conf.beat_schedule = {
    'recalcular-salud-vehiculos': {
        'task': 'mecanimovilapp.apps.vehiculos.tasks.recalcular_salud_vehiculos_batch',
        'schedule': crontab(hour='*/6', minute=0),  # Cada 6 horas (ligero)
        'options': {'queue': 'heavy'},
    },
    # Diario: fuerza recálculo + invalida cache; usuario desconectado ve datos al día al abrir
    'recalcular-salud-vehiculos-diario': {
        'task': 'mecanimovilapp.apps.vehiculos.tasks.recalcular_salud_vehiculos_diario',
        'schedule': crontab(hour=5, minute=15),  # 05:15 UTC (baja carga)
        'options': {'queue': 'heavy'},
    },
    'verificar-pagos-pendientes': {
        'task': 'mecanimovilapp.apps.ordenes.tasks.verificar_pagos_pendientes',
        'schedule': crontab(minute='*/30'),  # Cada 30 minutos
        'options': {'queue': 'default'},
    },
    'enviar-alertas-pago-proximo': {
        'task': 'mecanimovilapp.apps.ordenes.tasks.enviar_alertas_pago_proximo_task',
        'schedule': crontab(minute=0),  # Cada hora, en punto
        'options': {'queue': 'default'},
    },
    'verificar-suscripciones-activas': {
        'task': 'suscripciones.verificar_suscripciones_activas',
        'schedule': crontab(hour=4, minute=0),  # Diariamente a las 04:00 AM
        'options': {'queue': 'default'},
    },
    'verificar-salud-suscripciones': {
        'task': 'suscripciones.verificar_salud_suscripciones',
        'schedule': crontab(hour='*/6', minute=30),  # Cada 6 horas (00:30, 06:30, 12:30, 18:30)
        'options': {'queue': 'default'},
    },
}

@app.task(bind=True)
def debug_task(self):
    """
    Tarea de debug para verificar que Celery está funcionando
    """
    print(f'Request: {self.request!r}')

