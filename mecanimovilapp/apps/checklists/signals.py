"""
Signals para integración del sistema de checklists con salud vehicular
Actualiza automáticamente la salud del vehículo cuando se completa un checklist
"""
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import ChecklistInstance
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=ChecklistInstance)
def invalidar_cache_salud_vehiculo(sender, instance, created, **kwargs):
    """
    Al completar el checklist: invalidar cache y actualizar km + salud.

    Importante: en producción (p. ej. Render) `.delay()` de Celery suele aceptar la tarea aunque
    no haya worker; el fallback síncrono anterior nunca corría. Por eso se programa
    `actualizar_salud_desde_checklist` en `transaction.on_commit` para ejecutarlo en el mismo
    proceso web y garantizar persistencia del odómetro en Vehiculo (también tras transferencia
    de titularidad: el FK vehículo sigue siendo el mismo registro).
    """
    if instance.estado != 'COMPLETADO' or not instance.orden_id:
        return

    try:
        orden = instance.orden
        vehicle_id = orden.vehiculo_id
        if not vehicle_id:
            return

        from mecanimovilapp.apps.vehiculos.utils.cache_health import invalidate_vehicle_health_cache

        invalidate_vehicle_health_cache(vehicle_id)

        checklist_id = instance.id

        def run_actualizacion():
            from mecanimovilapp.apps.vehiculos.tasks import actualizar_salud_desde_checklist

            try:
                actualizar_salud_desde_checklist(checklist_id, vehicle_id)
                logger.info(
                    "✅ Post-checklist: km/salud procesados para vehículo %s (checklist %s)",
                    vehicle_id,
                    checklist_id,
                )
            except Exception as sync_error:
                logger.error(
                    "❌ Error actualizando km/salud tras checklist %s: %s",
                    checklist_id,
                    sync_error,
                    exc_info=True,
                )

        transaction.on_commit(run_actualizacion)
    except Exception as e:
        logger.error("❌ Error en signal de checklist: %s", e, exc_info=True)

