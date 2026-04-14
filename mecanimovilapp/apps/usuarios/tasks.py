from celery import shared_task
from django.core.cache import cache
import logging

logger = logging.getLogger(__name__)

THROTTLE_WINDOWS = {
    'health_alert':              3600,
    'global_health_alert':       3600 * 6,
    'viaje_registrado':          300,
    'salud_actualizada':         1800,
    'recordatorio_pago':         3600 * 4,
    'cambio_estado':             60,
    'nueva_oferta':              120,
    'new_offer':                 120,
    'chat_message':              90,
    'solicitud_adjudicada':      60,
    'suscripcion_por_vencer':    3600 * 12,  # Max 1 push cada 12 h
    'suscripcion_vencida':       3600 * 12,
    'suscripcion_pago_fallido':  3600 * 12,
    'creditos_agotados':         3600 * 12,
}

DEFAULT_THROTTLE_SECONDS = 300


def _normalize_expo_push_data(data):
    """
    Expo/FCM en Android exige valores string en el mapa data.
    """
    if not data:
        return {}
    out = {}
    for key, val in data.items():
        if val is None:
            out[key] = ''
        elif isinstance(val, bool):
            out[key] = 'true' if val else 'false'
        else:
            out[key] = str(val)
    return out


def _should_throttle(user_id, data):
    """
    Returns True if this push should be skipped (duplicate within window).
    Uses Redis/cache with a per-user per-event key.
    """
    notif_type = (data or {}).get('type', 'generic')
    vehicle_id = (data or {}).get('vehicle_id', '')
    solicitud_id = (data or {}).get('solicitud_id', '')
    conversation_id = (data or {}).get('conversation_id', '')
    unique_suffix = conversation_id or vehicle_id or solicitud_id or ''

    # Incluir oferta_id si viene (evita silenciar ofertas distintas en la misma solicitud)
    oferta_id = (data or {}).get('oferta_id', '')
    if oferta_id:
        unique_suffix = f"{unique_suffix}:{oferta_id}"

    cache_key = f"push_throttle:{user_id}:{notif_type}:{unique_suffix}"
    window = THROTTLE_WINDOWS.get(notif_type, DEFAULT_THROTTLE_SECONDS)

    if cache.get(cache_key):
        logger.debug(f"⏳ Push throttled: {cache_key} (window {window}s)")
        return True

    cache.set(cache_key, 1, timeout=window)
    return False


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def send_expo_push_notification(self, user_id, title, body, data=None):
    """
    Tarea de Celery para enviar notificaciones push usando Expo.
    Incluye throttling por tipo de evento y reintentos automáticos.
    """
    from .models import Usuario
    from exponent_server_sdk import (
        PushClient,
        PushMessage,
        PushServerError,
        PushTicketError,
    )

    if _should_throttle(user_id, data):
        return

    try:
        user = Usuario.objects.get(pk=user_id)
        token = user.expo_push_token

        if not token:
            logger.debug(f"ℹ️ [push] Usuario {user_id} sin expo_push_token")
            return

        data = _normalize_expo_push_data(data)
        notif_type = data.get('type', 'generic')
        channel_id = 'default'
        if notif_type in ('health_alert', 'global_health_alert', 'salud_actualizada'):
            channel_id = 'salud'
        elif notif_type == 'viaje_registrado':
            channel_id = 'viajes'
        elif notif_type == 'chat_message':
            channel_id = 'chat'
        elif notif_type in ('recordatorio_pago', 'cambio_estado', 'nueva_oferta', 'solicitud_adjudicada', 'new_offer'):
            channel_id = 'servicios'
        elif notif_type in ('suscripcion_por_vencer', 'suscripcion_vencida', 'suscripcion_pago_fallido', 'creditos_agotados'):
            channel_id = 'suscripciones'

        message = PushMessage(
            to=token,
            title=title,
            body=body,
            data=data,
            sound='default',
            channel_id=channel_id,
            priority='high' if notif_type in (
                'health_alert', 'global_health_alert', 'salud_actualizada', 'cambio_estado',
                'chat_message', 'new_offer', 'nueva_oferta',
            ) else 'default',
        )

        try:
            PushClient().publish(message)
            logger.info(f"✅ Push [{notif_type}] enviada a usuario {user_id}")
        except PushServerError as exc:
            logger.error(f"❌ Expo server error para usuario {user_id}: {exc}")
            raise self.retry(exc=exc)
        except (PushTicketError, ValueError) as exc:
            logger.error(f"❌ Token inválido para usuario {user_id}: {exc}")
            user.expo_push_token = None
            user.save(update_fields=['expo_push_token'])

    except Usuario.DoesNotExist:
        logger.error(f"❌ [push] Usuario {user_id} no encontrado")
    except Exception as e:
        logger.error(f"❌ Error crítico en push: {str(e)}", exc_info=True)
        raise self.retry(exc=e)