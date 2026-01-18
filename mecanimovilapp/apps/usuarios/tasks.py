from celery import shared_task
from exponent_server_sdk import (
    PushClient,
    PushMessage,
    PushServerError,
    PushTicketError,
)
from .models import Usuario
import logging

logger = logging.getLogger(__name__)

@shared_task
def send_expo_push_notification(user_id, title, body, data=None):
    """
    Tarea de Celery para enviar notificaciones push usando Expo
    """
    try:
        user = Usuario.objects.get(pk=user_id)
        token = user.expo_push_token
        
        if not token:
            logger.debug(f"ℹ️ [send_expo_push_notification] Usuario {user_id} no tiene expo_push_token registrado")
            return
        
        # Preparar el mensaje
        message = PushMessage(
            to=token,
            title=title,
            body=body,
            data=data or {}
        )
        
        # Enviar usando el cliente de Expo
        try:
            # publishing devuelve un objeto de respuesta de ticket.
            # NO lo manejamos sincrónicamente para validación profunda de tickets aquí
            # ya que eso requiere un paso extra de polling, pero registramos el envío.
            PushClient().publish(message)
            logger.info(f"✅ Notificación Push enviada exitosamente a usuario {user_id} (@{user.username})")
            
        except PushServerError as exc:
            # Errores del servidor de Expo (ej. 5xx)
            logger.error(f"❌ Error del servidor de Expo para usuario {user_id}: {exc}")
            # Aquí se podría implementar reintento si se desea
        except (PushTicketError, ValueError) as exc:
            # Token inválido (DeviceNotRegistered) o errores de formato
            logger.error(f"❌ Token de Expo inválido/expirado para usuario {user_id}: {exc}")
            # Limpiar el token inválido para evitar envíos futuros fallidos
            user.expo_push_token = None
            user.save(update_fields=['expo_push_token'])
            logger.info(f"🧹 Token inválido removido del usuario {user_id}")
            
    except Usuario.DoesNotExist:
        logger.error(f"❌ [send_expo_push_notification] Usuario con ID {user_id} no encontrado")
    except Exception as e:
        logger.error(f"❌ Error crítico en send_expo_push_notification: {str(e)}", exc_info=True)