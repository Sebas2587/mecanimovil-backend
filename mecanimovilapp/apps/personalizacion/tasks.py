"""
Tareas periódicas para el sistema de personalización
"""
from django.core.management import call_command
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

def generar_recomendaciones_periodicas():
    """
    Tarea para generar recomendaciones periódicamente
    Esta función puede ser llamada por Celery o cron
    """
    try:
        logger.info("Iniciando generación periódica de recomendaciones")
        
        # Ejecutar el comando de generación
        call_command('generar_recomendaciones', verbosity=1)
        
        logger.info("Generación periódica de recomendaciones completada")
        return True
        
    except Exception as e:
        logger.error(f"Error en generación periódica: {str(e)}")
        return False

def limpiar_recomendaciones_expiradas():
    """
    Tarea para limpiar recomendaciones expiradas
    """
    try:
        from .models import RecomendacionPersonalizada
        
        # Marcar como inactivas las recomendaciones expiradas
        expiradas = RecomendacionPersonalizada.objects.filter(
            fecha_expiracion__lt=timezone.now(),
            activa=True
        )
        
        count = expiradas.count()
        expiradas.update(activa=False)
        
        logger.info(f"Marcadas como inactivas {count} recomendaciones expiradas")
        return count
        
    except Exception as e:
        logger.error(f"Error limpiando recomendaciones expiradas: {str(e)}")
        return 0

def actualizar_perfiles_vehiculos():
    """
    Tarea para actualizar perfiles de vehículos con nueva actividad
    """
    try:
        from .ml_engine import MotorRecomendaciones
        from mecanimovilapp.apps.vehiculos.models import Vehiculo
        
        motor = MotorRecomendaciones()
        
        # Actualizar perfiles de vehículos con actividad reciente
        vehiculos_activos = Vehiculo.objects.filter(
            solicitudes__fecha_servicio__gte=timezone.now() - timedelta(days=7)
        ).distinct()
        
        count = 0
        for vehiculo in vehiculos_activos:
            motor.actualizar_perfil_vehiculo(vehiculo)
            count += 1
        
        logger.info(f"Actualizados {count} perfiles de vehículos")
        return count
        
    except Exception as e:
        logger.error(f"Error actualizando perfiles: {str(e)}")
        return 0

# Configuración para Celery (cuando se implemente)
"""
from celery import shared_task

@shared_task
def generar_recomendaciones_celery():
    return generar_recomendaciones_periodicas()

@shared_task
def limpiar_recomendaciones_celery():
    return limpiar_recomendaciones_expiradas()

@shared_task
def actualizar_perfiles_celery():
    return actualizar_perfiles_vehiculos()
"""

# Configuración para cron (alternativa sin Celery)
"""
# Agregar al crontab del servidor:
# 
# # Generar recomendaciones cada día a las 2:00 AM
# 0 2 * * * cd /path/to/project && python manage.py shell -c "from mecanimovilapp.apps.personalizacion.tasks import generar_recomendaciones_periodicas; generar_recomendaciones_periodicas()"
# 
# # Limpiar recomendaciones expiradas cada día a las 3:00 AM
# 0 3 * * * cd /path/to/project && python manage.py shell -c "from mecanimovilapp.apps.personalizacion.tasks import limpiar_recomendaciones_expiradas; limpiar_recomendaciones_expiradas()"
# 
# # Actualizar perfiles cada 6 horas
# 0 */6 * * * cd /path/to/project && python manage.py shell -c "from mecanimovilapp.apps.personalizacion.tasks import actualizar_perfiles_vehiculos; actualizar_perfiles_vehiculos()"
""" 