"""
Tarea Celery para sincronizar el estado de las suscripciones activas con MercadoPago.
Se ejecuta diariamente via Celery Beat para mantener los estados en sync.
"""
from celery import shared_task
import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=60, name='suscripciones.verificar_suscripciones_activas')
def verificar_suscripciones_activas(self):
    """
    Sincroniza el estado de todas las suscripciones activas/pendientes con MP API.
    Tarea diaria de mantenimiento — no acredita créditos (eso lo hace el webhook).
    """
    from .models import SuscripcionProveedor
    from .suscripcion_services import sincronizar_estado_suscripcion

    try:
        suscripciones = SuscripcionProveedor.objects.filter(
            estado__in=['activa', 'pendiente', 'pausada'],
            mp_preapproval_id__isnull=False,
        ).select_related('plan')

        total = suscripciones.count()
        logger.info(f"🔄 [Celery] Sincronizando {total} suscripción(es) activa(s)")

        actualizadas = 0
        errores = 0

        for suscripcion in suscripciones:
            try:
                estado_antes = suscripcion.estado
                nuevo_estado, cobros_res = sincronizar_estado_suscripcion(suscripcion)
                if nuevo_estado != estado_antes:
                    actualizadas += 1
                if cobros_res:
                    logger.info(
                        f"[Celery] Suscripción {suscripcion.id}: "
                        f"{len(cobros_res)} cobro(s) procesado(s) durante sync"
                    )
            except Exception as e:
                logger.error(f"[Celery] Error en suscripción {suscripcion.id}: {e}")
                errores += 1
                continue

        logger.info(
            f"[Celery] Sincronización completada: {actualizadas} actualizadas, "
            f"{errores} errores de {total} total"
        )
        return {'total': total, 'actualizadas': actualizadas, 'errores': errores}

    except Exception as exc:
        logger.error(f"❌ [Celery] Error en verificar_suscripciones_activas: {exc}", exc_info=True)
        raise self.retry(exc=exc)
