"""
Signals para integración del sistema de checklists con salud vehicular
Actualiza automáticamente la salud del vehículo cuando se completa un checklist
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import ChecklistInstance
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=ChecklistInstance)
def invalidar_cache_salud_vehiculo(sender, instance, created, **kwargs):
    """
    Cuando se completa un checklist, invalidar cache y recalcular salud en background
    
    Signal que se ejecuta automáticamente cuando se guarda un ChecklistInstance
    
    GARANTIZA que siempre se ejecute la actualización:
    - Intenta usar Celery si está disponible
    - Si Celery falla, ejecuta sincrónicamente como fallback
    """
    # Solo procesar si el checklist está completado
    if instance.estado == 'COMPLETADO' and instance.orden:
        try:
            vehicle_id = instance.orden.vehiculo_id
            
            if vehicle_id:
                # Importar aquí para evitar imports circulares
                from mecanimovilapp.apps.vehiculos.utils.cache_health import invalidate_vehicle_health_cache
                from mecanimovilapp.apps.vehiculos.tasks import (
                    actualizar_salud_desde_checklist,
                    CELERY_AVAILABLE
                )
                
                # Invalidar cache inmediatamente
                invalidate_vehicle_health_cache(vehicle_id)
                
                # Intentar ejecutar con Celery primero
                ejecutado = False
                if CELERY_AVAILABLE:
                    try:
                        actualizar_salud_desde_checklist.delay(instance.id, vehicle_id)
                        ejecutado = True
                        logger.info(
                            f"✅ Celery: Actualización de salud iniciada para vehículo {vehicle_id} "
                            f"desde checklist {instance.id}"
                        )
                    except Exception as celery_error:
                        logger.warning(
                            f"⚠️ Celery no disponible o falló, ejecutando sincrónicamente: {celery_error}"
                        )
                
                # Fallback: ejecutar sincrónicamente si Celery no está disponible o falló
                if not ejecutado:
                    try:
                        actualizar_salud_desde_checklist(instance.id, vehicle_id)
                        logger.info(
                            f"✅ Sincrónico: Salud actualizada para vehículo {vehicle_id} "
                            f"desde checklist {instance.id}"
                        )
                    except Exception as sync_error:
                        logger.error(
                            f"❌ Error ejecutando actualización sincrónica: {sync_error}",
                            exc_info=True
                        )
                
        except Exception as e:
            logger.error(f"❌ Error en signal de checklist: {str(e)}", exc_info=True)

