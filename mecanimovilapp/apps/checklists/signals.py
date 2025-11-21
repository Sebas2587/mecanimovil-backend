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
    """
    # Solo procesar si el checklist está completado
    if instance.estado == 'COMPLETADO' and instance.orden:
        try:
            vehicle_id = instance.orden.vehiculo_id
            
            if vehicle_id:
                # Importar aquí para evitar imports circulares
                from mecanimovilapp.apps.vehiculos.utils.cache_health import invalidate_vehicle_health_cache
                from mecanimovilapp.apps.vehiculos.tasks import actualizar_salud_desde_checklist
                
                # Invalidar cache inmediatamente
                invalidate_vehicle_health_cache(vehicle_id)
                
                # Recalcular en background (NO bloquea)
                actualizar_salud_desde_checklist.delay(instance.id, vehicle_id)
                
                logger.info(f"Cache invalidado y recálculo iniciado para vehículo {vehicle_id} desde checklist {instance.id}")
        except Exception as e:
            logger.error(f"Error en signal de checklist: {str(e)}")

