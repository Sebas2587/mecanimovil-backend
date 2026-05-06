"""
Signals para integración del sistema de checklists con salud vehicular.
Actualiza automáticamente la salud del vehículo cuando se completa un checklist.

Estrategia de ejecución:
1. Actualizar odómetro del vehículo síncronamente (liviano, crítico para coherencia de datos).
2. Delegar el recálculo del HealthEngine a Celery con apply_async.
3. Fallback síncrono solo si el broker Redis no está disponible (ConnectionError).
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
    Al completar el checklist: invalidar cache, actualizar odómetro y recalcular salud.

    El odómetro se actualiza en el mismo proceso (garantía de persistencia en Render sin
    depender del worker Celery). El recálculo del HealthEngine se delega a Celery.
    """
    if instance.estado != 'COMPLETADO' or not instance.orden_id:
        return

    try:
        orden = instance.orden
        vehicle_id = orden.vehiculo_id
        if not vehicle_id:
            return

        # --- Inspección pre-compra: skip salud, certificar vehículo ---
        from mecanimovilapp.apps.ordenes.precompra_marketplace import es_servicio_precompra

        linea = orden.lineas.select_related('oferta_servicio__servicio').first()
        servicio = linea.oferta_servicio.servicio if linea and linea.oferta_servicio else None
        if es_servicio_precompra(servicio):
            def _certificar():
                from mecanimovilapp.apps.vehiculos.models import Vehiculo
                Vehiculo.objects.filter(id=vehicle_id).update(is_certified_mecanimovil=True)
                logger.info(
                    "🛡️ Vehículo %s certificado MecaniMóvil (checklist %s, inspección pre-compra)",
                    vehicle_id, instance.id,
                )
            transaction.on_commit(_certificar)
            return

        from mecanimovilapp.apps.vehiculos.utils.cache_health import invalidate_vehicle_health_cache

        invalidate_vehicle_health_cache(vehicle_id)

        checklist_id = instance.id

        def run_actualizacion():
            from mecanimovilapp.apps.vehiculos.tasks import actualizar_salud_desde_checklist

            # Intentar encolar en Celery primero (no bloquea el proceso web)
            try:
                actualizar_salud_desde_checklist.apply_async(
                    args=[checklist_id, vehicle_id],
                    countdown=0,
                )
                logger.info(
                    "✅ Post-checklist: tarea encolada en Celery para vehículo %s (checklist %s)",
                    vehicle_id,
                    checklist_id,
                )
            except Exception as celery_err:
                # Celery no disponible (Redis caído, etc.) → fallback síncrono
                logger.warning(
                    "⚠️ Celery no disponible para checklist %s vehículo %s (%s) — ejecutando síncronamente",
                    checklist_id,
                    vehicle_id,
                    celery_err,
                )
                try:
                    actualizar_salud_desde_checklist(checklist_id, vehicle_id)
                    logger.info(
                        "✅ Post-checklist: km/salud procesados síncronamente para vehículo %s (checklist %s)",
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
