"""
Tareas Celery para el sistema de suscripciones.

1. verificar_suscripciones_activas  — sync diario de estados con MP.
2. verificar_salud_suscripciones   — cada 6h: detecta vencimientos,
   pagos fallidos, créditos agotados y envía push + in-app alerts.
"""
from celery import shared_task
from django.utils import timezone
from datetime import timedelta
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


# ---------------------------------------------------------------------------
# Constantes para alertas de suscripción
# ---------------------------------------------------------------------------
DIAS_AVISO_PREVIO = 3        # Avisar N días antes del vencimiento
UMBRAL_CREDITOS_BAJOS = 5    # Alertar si los créditos bajan de este umbral


def _crear_notificacion_suscripcion(proveedor, tipo, titulo, mensaje, data_extra=None):
    """
    Crea notificación in-app (dedup 24 h) + push vía Celery.
    """
    from mecanimovilapp.apps.usuarios.models import Notificacion
    from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification

    data = {'type': tipo, **(data_extra or {})}

    Notificacion.crear_unica(
        usuario=proveedor,
        tipo=tipo,
        titulo=titulo,
        mensaje=mensaje,
        data=data,
        ventana_horas=24,
    )

    send_expo_push_notification.delay(
        user_id=proveedor.id,
        title=titulo,
        body=mensaje,
        data=data,
    )
    logger.info(f"[SaludSusc] Alerta '{tipo}' enviada a proveedor {proveedor.id}")


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=120,
    name='suscripciones.verificar_salud_suscripciones',
)
def verificar_salud_suscripciones(self):
    """
    Tarea periódica (cada 6 h) que revisa TODAS las suscripciones y genera
    alertas proactivas al proveedor.

    Escenarios cubiertos:
      A) Suscripción activa cuyo fecha_proximo_cobro es en <=3 días
         → Notifica "Tu suscripción se renueva pronto".
      B) Suscripción cuyo estado cambió a 'pausada' (MP no pudo cobrar)
         → Notifica "Pago fallido — revisa tu método de pago".
      C) Suscripción cancelada/expirada recientemente
         → Notifica "Tu suscripción ha vencido".
      D) Proveedor con créditos <= UMBRAL_CREDITOS_BAJOS y sin suscripción activa
         → Notifica "Créditos agotándose".
    """
    from .models import SuscripcionProveedor, CreditoProveedor
    from .suscripcion_services import sincronizar_estado_suscripcion

    ahora = timezone.now()
    stats = {
        'total': 0,
        'por_vencer': 0,
        'pago_fallido': 0,
        'vencidas': 0,
        'creditos_bajos': 0,
        'errores': 0,
    }

    try:
        # ── A, B, C: Suscripciones no-terminales ──────────────────────
        suscripciones = SuscripcionProveedor.objects.filter(
            mp_preapproval_id__isnull=False,
        ).select_related('plan', 'proveedor')

        stats['total'] = suscripciones.count()
        logger.info(f"[SaludSusc] Revisando {stats['total']} suscripción(es)...")

        for sus in suscripciones:
            try:
                estado_previo = sus.estado

                if sus.estado in ('activa', 'pendiente', 'pausada'):
                    nuevo_estado, _ = sincronizar_estado_suscripcion(sus)
                    sus.refresh_from_db()
                else:
                    nuevo_estado = sus.estado

                # --- A) Próxima a renovarse ---
                if (
                    sus.estado == 'activa'
                    and sus.fecha_proximo_cobro
                    and sus.fecha_proximo_cobro <= ahora + timedelta(days=DIAS_AVISO_PREVIO)
                    and sus.fecha_proximo_cobro > ahora
                ):
                    fecha_fmt = sus.fecha_proximo_cobro.strftime('%d/%m/%Y')
                    _crear_notificacion_suscripcion(
                        proveedor=sus.proveedor,
                        tipo='suscripcion_por_vencer',
                        titulo='Tu suscripción se renueva pronto',
                        mensaje=(
                            f'Tu plan {sus.plan.nombre} se renovará el {fecha_fmt}. '
                            f'Asegúrate de tener saldo disponible en tu método de pago.'
                        ),
                        data_extra={
                            'suscripcion_id': sus.id,
                            'fecha_proximo_cobro': fecha_fmt,
                        },
                    )
                    stats['por_vencer'] += 1

                # --- B) Pago fallido (pausada por MP) ---
                if sus.estado == 'pausada' and estado_previo != 'pausada':
                    _crear_notificacion_suscripcion(
                        proveedor=sus.proveedor,
                        tipo='suscripcion_pago_fallido',
                        titulo='No se pudo cobrar tu suscripción',
                        mensaje=(
                            f'MercadoPago no pudo procesar el cobro de tu plan {sus.plan.nombre}. '
                            f'Revisa tu método de pago para evitar la suspensión del servicio.'
                        ),
                        data_extra={'suscripcion_id': sus.id},
                    )
                    stats['pago_fallido'] += 1

                # Enviar alerta también si ya estaba pausada (recordatorio)
                elif sus.estado == 'pausada' and estado_previo == 'pausada':
                    _crear_notificacion_suscripcion(
                        proveedor=sus.proveedor,
                        tipo='suscripcion_pago_fallido',
                        titulo='Tu suscripción sigue pausada',
                        mensaje=(
                            f'Tu plan {sus.plan.nombre} está pausado por falta de pago. '
                            f'Actualiza tu método de pago en MercadoPago para reactivarla.'
                        ),
                        data_extra={'suscripcion_id': sus.id},
                    )
                    stats['pago_fallido'] += 1

                # --- C) Vencida / cancelada (transición detectada) ---
                if nuevo_estado in ('cancelada', 'expirada') and estado_previo not in ('cancelada', 'expirada'):
                    _crear_notificacion_suscripcion(
                        proveedor=sus.proveedor,
                        tipo='suscripcion_vencida',
                        titulo='Tu suscripción ha vencido',
                        mensaje=(
                            f'Tu plan {sus.plan.nombre} fue cancelado o expiró. '
                            f'No recibirás más créditos mensuales. '
                            f'Renueva tu suscripción para seguir ofertando.'
                        ),
                        data_extra={'suscripcion_id': sus.id},
                    )
                    stats['vencidas'] += 1

            except Exception as e:
                logger.error(f"[SaludSusc] Error procesando suscripción {sus.id}: {e}")
                stats['errores'] += 1

        # ── D: Proveedores sin suscripción activa y créditos bajos ────
        proveedores_sin_sus = CreditoProveedor.objects.filter(
            saldo_creditos__lte=UMBRAL_CREDITOS_BAJOS,
        ).select_related('proveedor')

        for cp in proveedores_sin_sus:
            try:
                tiene_sus_activa = SuscripcionProveedor.objects.filter(
                    proveedor=cp.proveedor,
                    estado='activa',
                ).exists()
                if not tiene_sus_activa:
                    _crear_notificacion_suscripcion(
                        proveedor=cp.proveedor,
                        tipo='creditos_agotados',
                        titulo='Tus créditos se están agotando',
                        mensaje=(
                            f'Solo te quedan {cp.saldo_creditos} créditos y no tienes una suscripción activa. '
                            f'Compra créditos o activa un plan mensual para seguir ofertando.'
                        ),
                        data_extra={'saldo_creditos': cp.saldo_creditos},
                    )
                    stats['creditos_bajos'] += 1
            except Exception as e:
                logger.error(f"[SaludSusc] Error chequeando créditos proveedor {cp.proveedor_id}: {e}")
                stats['errores'] += 1

        logger.info(
            f"[SaludSusc] Completado — por_vencer={stats['por_vencer']}, "
            f"pago_fallido={stats['pago_fallido']}, vencidas={stats['vencidas']}, "
            f"creditos_bajos={stats['creditos_bajos']}, errores={stats['errores']}"
        )
        return stats

    except Exception as exc:
        logger.error(f"❌ [SaludSusc] Error crítico: {exc}", exc_info=True)
        raise self.retry(exc=exc)
