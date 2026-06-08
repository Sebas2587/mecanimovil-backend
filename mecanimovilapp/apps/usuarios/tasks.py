from celery import shared_task
from django.core.cache import cache
from django.conf import settings
import json
import logging

logger = logging.getLogger(__name__)


def _send_web_push_to_user(user, title, body, data=None):
    """
    Enviar Web Push (VAPID/RFC 8030) a todas las suscripciones web activas del usuario.
    Desactiva automaticamente los endpoints que devuelvan 410 Gone (suscripcion expirada).
    """
    from .models import WebPushSubscription

    vapid_private = getattr(settings, 'VAPID_PRIVATE_KEY', None)
    vapid_public = getattr(settings, 'VAPID_PUBLIC_KEY', None)
    vapid_email = getattr(settings, 'VAPID_EMAIL', 'mailto:admin@mecanimovil.com')

    if not vapid_private or not vapid_public:
        logger.debug('[web-push] VAPID keys no configuradas, omitiendo envio web.')
        return

    subs = WebPushSubscription.objects.filter(usuario=user, activo=True)
    if not subs.exists():
        return

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.warning('[web-push] pywebpush no instalado, omitiendo envio web.')
        return

    payload = json.dumps({
        'title': title,
        'body': body,
        'data': data or {},
    })

    vapid_claims = {'sub': vapid_email}

    for sub in subs:
        try:
            webpush(
                subscription_info={
                    'endpoint': sub.endpoint,
                    'keys': {'p256dh': sub.p256dh, 'auth': sub.auth},
                },
                data=payload,
                vapid_private_key=vapid_private,
                vapid_claims=vapid_claims,
                content_encoding='aes128gcm',
            )
            logger.info(f'✅ [web-push] Enviada a suscripcion {sub.id} del usuario {user.id}')
        except WebPushException as exc:
            status_code = exc.response.status_code if exc.response else None
            if status_code == 410:
                # Suscripcion expirada — el navegador la revoco
                sub.activo = False
                sub.save(update_fields=['activo'])
                logger.info(f'🗑️ [web-push] Suscripcion {sub.id} expirada (410), desactivada.')
            else:
                logger.error(f'❌ [web-push] Error en suscripcion {sub.id}: {exc}')
        except Exception as exc:
            logger.error(f'❌ [web-push] Error inesperado en suscripcion {sub.id}: {exc}')

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
        elif notif_type in (
            'recordatorio_pago',
            'cambio_estado',
            'nueva_oferta',
            'solicitud_adjudicada',
            'new_offer',
            'solicitud_cancelada_cliente',
            'nueva_solicitud',
            'catalog_assignment',
        ):
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
                'chat_message', 'new_offer', 'nueva_oferta', 'nueva_solicitud', 'catalog_assignment',
            ) else 'default',
        )

        try:
            response = PushClient().publish(message)
            # Verificar si el ticket reporta error (DeviceNotRegistered, etc.)
            try:
                response.validate_response()
                logger.info(f"✅ Push [{notif_type}] enviada a usuario {user_id} | token={token[:30]}…")
            except PushTicketError as ticket_err:
                err_msg = str(ticket_err).lower()
                logger.error(f"❌ Ticket error push usuario {user_id}: {ticket_err}")
                if 'devicenotregistered' in err_msg or 'invalid' in err_msg:
                    logger.warning(f"🗑️ Token inválido, limpiando para usuario {user_id}")
                    user.expo_push_token = None
                    user.save(update_fields=['expo_push_token'])
        except PushServerError as exc:
            logger.error(f"❌ Expo server error para usuario {user_id}: {exc}")
            raise self.retry(exc=exc)
        except (ValueError, Exception) as exc:
            exc_str = str(exc).lower()
            logger.error(f"❌ Error enviando push a usuario {user_id}: {exc}")
            if 'devicenotregistered' in exc_str or 'invalid' in exc_str:
                user.expo_push_token = None
                user.save(update_fields=['expo_push_token'])

        # Enviar tambien a suscripciones Web Push activas del usuario (canal web)
        try:
            _send_web_push_to_user(user, title, body, data)
        except Exception as web_exc:
            logger.error(f"❌ Error en web push para usuario {user_id}: {web_exc}")

    except Usuario.DoesNotExist:
        logger.error(f"❌ [push] Usuario {user_id} no encontrado")
    except Exception as e:
        logger.error(f"❌ Error crítico en push: {str(e)}", exc_info=True)
        raise self.retry(exc=e)