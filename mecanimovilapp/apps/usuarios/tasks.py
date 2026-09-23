from celery import shared_task
from django.core.cache import cache
from django.conf import settings
import json
import logging

logger = logging.getLogger(__name__)

CHAT_CHANNEL_TYPES = frozenset({
    'chat_message',
    'nuevo_mensaje_chat',
    'nuevo_contacto_canal',
    'agente_ia_escalamiento',
})

SERVICIOS_CHANNEL_TYPES = frozenset({
    'recordatorio_pago',
    'cambio_estado',
    'nueva_oferta',
    'solicitud_adjudicada',
    'new_offer',
    'solicitud_cancelada_cliente',
    'nueva_solicitud',
    'catalog_assignment',
    'solicitud_por_vencer',
    'checklist_pendiente',
    'orden_asignada_mecanico',
    'agente_ia_cotizacion_borrador',
    'agente_ia_cotizacion_enviada',
    'agente_ia_cotizacion_aceptada',
    'agente_ia_cotizacion_rechazada',
    'agente_ia_cita_confirmada',
    'agente_ia_procesando',
    'cita_agendada',
    'pipeline_borrador_listo_sin_enviar',
    'pipeline_cotizacion_sin_respuesta_24h',
    'pipeline_cotizacion_demorada_48h',
    'pipeline_agenda_pendiente_confirmacion',
    'pipeline_cotizacion_adicional_borrador',
})

SUSCRIPCION_CHANNEL_TYPES = frozenset({
    'suscripcion_por_vencer',
    'suscripcion_vencida',
    'suscripcion_pago_fallido',
    'creditos_agotados',
})

HIGH_PRIORITY_TYPES = (
    CHAT_CHANNEL_TYPES
    | SERVICIOS_CHANNEL_TYPES
    | SUSCRIPCION_CHANNEL_TYPES
    | frozenset({
        'health_alert',
        'global_health_alert',
        'salud_actualizada',
    })
)


def _iter_native_tokens(user):
    """Todos los tokens Expo activos del usuario (iOS + Android), sin duplicar."""
    from .models import PushToken

    seen = set()
    tokens = []
    qs = PushToken.objects.filter(usuario_id=user.id, activo=True).order_by('-fecha_actualizacion')
    for pt in qs:
        token = (pt.token or '').strip()
        if token and token not in seen:
            seen.add(token)
            tokens.append(token)
    legacy = (getattr(user, 'expo_push_token', None) or '').strip()
    if legacy and legacy not in seen:
        tokens.append(legacy)
    return tokens


def _invalidate_native_token(user, token: str) -> None:
    from .models import PushToken

    token = (token or '').strip()
    if not token:
        return
    PushToken.objects.filter(usuario=user, token=token).update(activo=False)
    if getattr(user, 'expo_push_token', None) == token:
        user.expo_push_token = None
        user.save(update_fields=['expo_push_token'])
        logger.warning('🗑️ Token Expo inválido, desactivado para usuario %s', user.id)


def _push_operativo_permitido(user) -> bool:
    from django.core.exceptions import ObjectDoesNotExist

    try:
        prefs = user.preferencias_notificacion
    except ObjectDoesNotExist:
        return True
    if prefs is None:
        return True
    return bool(getattr(prefs, 'push_operativo', True))


def _channel_for_type(notif_type: str) -> str:
    if notif_type in ('health_alert', 'global_health_alert', 'salud_actualizada'):
        return 'salud'
    if notif_type == 'viaje_registrado':
        return 'viajes'
    if notif_type in CHAT_CHANNEL_TYPES or notif_type.startswith('agente_ia_escalamiento'):
        return 'chat'
    if notif_type in SERVICIOS_CHANNEL_TYPES or notif_type.startswith(('agente_ia_', 'pipeline_')):
        return 'servicios'
    if notif_type in SUSCRIPCION_CHANNEL_TYPES:
        return 'suscripciones'
    return 'default'


def _send_web_push_to_user(user, title, body, data=None):
    """
    Enviar Web Push (VAPID/RFC 8030) a todas las suscripciones web activas del usuario.
    Desactiva automaticamente los endpoints que devuelvan 410 Gone (suscripcion expirada).
    Siempre intenta web: el taller usa teléfono y navegador a la vez, y un token
    nativo inválido no debe silenciar Chrome/Safari.
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
    # Salud — throttles por tipo de cambio detectado
    'health_alert':              3600,       # 1 h por componente + evento
    'health_alert_critico':      3600 * 8,   # 8 h alerta critica de componente
    'global_health_alert':       3600 * 6,   # 6 h alerta global
    'componentes_criticos':      3600 * 12,  # 12 h resumen de componentes criticos
    'salud_actualizada':         3600 * 2,   # 2 h aviso informativo de recálculo
    'sugerencia_mantenimiento':  3600 * 168, # 1 semana sugerencia ML
    # Viajes y ordenes
    'viaje_registrado':          300,
    'recordatorio_pago':         3600 * 4,
    'cambio_estado':             60,
    'nueva_oferta':              120,
    'new_offer':                 120,
    'chat_message':              4,    # 4s solo para evitar dobles envíos por race condition
    'nuevo_mensaje_chat':        4,
    'nuevo_contacto_canal':      3600,
    'solicitud_adjudicada':      60,
    'solicitud_por_vencer':      3600,
    'checklist_pendiente':       300,
    'agente_ia_cotizacion_borrador': 20,
    'agente_ia_cotizacion_enviada': 30,
    'agente_ia_cotizacion_aceptada': 60,
    'agente_ia_cotizacion_rechazada': 60,
    'agente_ia_cita_confirmada': 60,
    'agente_ia_escalamiento':    20,
    'cita_agendada':             60,
    'pipeline_borrador_listo_sin_enviar': 3600 * 6,
    'pipeline_cotizacion_sin_respuesta_24h': 3600 * 10,
    'pipeline_cotizacion_demorada_48h': 3600 * 10,
    'pipeline_agenda_pendiente_confirmacion': 3600 * 10,
    'pipeline_cotizacion_adicional_borrador': 300,
    # Suscripciones
    'suscripcion_por_vencer':    3600 * 12,
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

    Para 'chat_message' se incluye el sender_id en el key para que mensajes
    de distintos remitentes en la misma conversación no se bloqueen entre sí.
    """
    payload = data or {}
    notif_type = str(payload.get('type') or 'generic')

    def _part(key):
        val = payload.get(key, '')
        return '' if val is None else str(val)

    unique_suffix = (
        _part('conversation_id')
        or _part('cotizacion_id')
        or _part('cita_id')
        or _part('vehicle_id')
        or _part('solicitud_id')
        or ''
    )

    oferta_id = _part('oferta_id')
    if oferta_id:
        unique_suffix = f"{unique_suffix}:{oferta_id}"

    if notif_type in ('chat_message', 'nuevo_mensaje_chat', 'nuevo_contacto_canal'):
        sender_id = _part('sender_id')
        message_id = _part('message_id')
        if message_id:
            unique_suffix = f"{unique_suffix}:{message_id}"
        elif sender_id:
            unique_suffix = f"{unique_suffix}:{sender_id}"

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
    Tarea de Celery para enviar notificaciones push usando Expo (iOS/Android)
    y Web Push (navegador). Entrega a *todos* los tokens nativos activos y
    a las suscripciones web; un token muerto no silencia el resto.
    """
    from .models import Usuario
    from exponent_server_sdk import (
        PushClient,
        PushMessage,
        PushServerError,
        PushTicketError,
    )

    if not getattr(self.request, 'retries', 0) and _should_throttle(user_id, data):
        return

    try:
        user = Usuario.objects.select_related('preferencias_notificacion').get(pk=user_id)
    except Usuario.DoesNotExist:
        logger.error(f"❌ [push] Usuario {user_id} no encontrado")
        return

    if not _push_operativo_permitido(user):
        logger.info('[push] Usuario %s tiene push operativo desactivado', user_id)
        return

    data = _normalize_expo_push_data(data)
    notif_type = data.get('type', 'generic')
    channel_id = _channel_for_type(notif_type)
    priority = 'high' if notif_type in HIGH_PRIORITY_TYPES or notif_type.startswith(('agente_ia_', 'pipeline_')) else 'default'
    tokens = _iter_native_tokens(user)

    native_sent = False
    should_retry_server = False
    last_server_exc = None

    if tokens:
        client = PushClient()
        for token in tokens:
            message = PushMessage(
                to=token,
                title=title,
                body=body,
                data=data,
                sound='default',
                channel_id=channel_id,
                priority=priority,
            )
            try:
                response = client.publish(message)
                try:
                    response.validate_response()
                    native_sent = True
                    logger.info(
                        f"✅ Push [{notif_type}] enviada a usuario {user_id} | token={token[:30]}…"
                    )
                except PushTicketError as ticket_err:
                    err_msg = str(ticket_err).lower()
                    logger.error(f"❌ Ticket error push usuario {user_id}: {ticket_err}")
                    if 'devicenotregistered' in err_msg or 'invalid' in err_msg:
                        _invalidate_native_token(user, token)
            except PushServerError as exc:
                logger.error(f"❌ Expo server error para usuario {user_id}: {exc}")
                should_retry_server = True
                last_server_exc = exc
            except (ValueError, Exception) as exc:
                exc_str = str(exc).lower()
                logger.error(f"❌ Error enviando push a usuario {user_id}: {exc}")
                if 'devicenotregistered' in exc_str or 'invalid' in exc_str:
                    _invalidate_native_token(user, token)
    else:
        logger.warning(
            f"⚠️ [push] Usuario {user_id} sin token Expo; intentando web push"
        )

    try:
        _send_web_push_to_user(user, title, body, data)
    except Exception as web_exc:
        logger.error(f"❌ Error en web push para usuario {user_id}: {web_exc}")

    if should_retry_server and not native_sent:
        raise self.retry(exc=last_server_exc)



@shared_task(bind=True, max_retries=1, default_retry_delay=60)
def send_smart_maintenance_push(self, vehicle_id):
    """
    Genera y envía una sugerencia de mantenimiento inteligente usando los datos
    del Health Engine y del predictor ML (cuando esté disponible).

    - Throttle: 1 semana (168 h) por vehículo.
    - Solo se envía si hay componentes en URGENTE o CRITICO.
    - El texto es amigable, claro y orientado a la acción.
    """
    try:
        from mecanimovilapp.apps.vehiculos.models_health import (
            ComponenteSaludVehiculo,
            EstadoSaludVehiculo,
        )
        from mecanimovilapp.apps.vehiculos.models import Vehiculo

        vehiculo = Vehiculo.objects.select_related(
            'cliente__usuario', 'marca', 'modelo'
        ).get(pk=vehicle_id)

        if not (vehiculo.cliente and vehiculo.cliente.usuario):
            return

        user = vehiculo.cliente.usuario
        nombre_vehiculo = (
            f"{vehiculo.marca} {vehiculo.modelo}"
            if vehiculo.marca
            else f"Vehículo {vehiculo.patente or ''}"
        )

        # Componentes que necesitan atención
        urgentes = ComponenteSaludVehiculo.objects.filter(
            vehiculo=vehiculo,
            nivel_alerta__in=('URGENTE', 'CRITICO'),
        ).select_related('componente').order_by('salud_porcentaje')

        if not urgentes.exists():
            return

        # Intentar enriquecer con predictor ML
        recomendaciones = []
        for comp in urgentes[:4]:  # max 4 para no sobrecargar el texto
            salud = comp.salud_porcentaje
            nivel = comp.nivel_alerta
            nombre = comp.componente.nombre
            km_rest = comp.km_estimados_restantes

            if salud <= 0:
                urgencia = "⛔ Requiere reemplazo inmediato"
            elif nivel == 'CRITICO':
                urgencia = f"🔴 Crítico — {salud:.0f}% vida útil restante"
            else:
                urgencia = f"🟡 Urgente — {salud:.0f}% vida útil restante"

            extra = ""
            if km_rest > 0:
                extra = f" (≈{km_rest:,} km antes de falla)"
            recomendaciones.append(f"• {nombre}: {urgencia}{extra}")

        total_criticos = urgentes.filter(nivel_alerta='CRITICO').count()
        total_urgentes = urgentes.filter(nivel_alerta='URGENTE').count()

        # Título contextual
        if total_criticos > 0:
            title = f"🔴 {nombre_vehiculo} necesita revisión urgente"
        else:
            title = f"🔧 Mantenimiento recomendado para tu {nombre_vehiculo}"

        # Cuerpo con componentes
        cuerpo_comp = "\n".join(recomendaciones)
        body = f"{cuerpo_comp}\n\nPrograma una revisión para evitar daños mayores."

        # Acortar para push (máx ~200 chars)
        if len(body) > 220:
            first = recomendaciones[0] if recomendaciones else ""
            n_mas = len(recomendaciones) - 1
            body = f"{first}"
            if n_mas > 0:
                body += f" y {n_mas} componente(s) más.\nPrograma una revisión pronto."

        data = {
            "type": "sugerencia_mantenimiento",
            "vehicle_id": str(vehicle_id),
            "total_criticos": str(total_criticos),
            "total_urgentes": str(total_urgentes),
        }

        if _should_throttle(user.id, data):
            return

        send_expo_push_notification(
            user.id, title, body, data
        )

        # In-app también
        from .models import Notificacion
        Notificacion.crear_unica(
            usuario=user,
            tipo='health_alert',
            titulo=title,
            mensaje=body,
            data={"vehicle_id": str(vehicle_id)},
            ventana_horas=168,
            dedup_key={"vehicle_id": str(vehicle_id), "tipo": "sugerencia"},
        )

        logger.info(
            f"💡 Sugerencia de mantenimiento enviada a usuario {user.id} "
            f"para vehículo {vehicle_id} "
            f"({total_criticos} críticos, {total_urgentes} urgentes)"
        )

    except Exception as exc:
        logger.error(f"❌ Error en sugerencia mantenimiento vehículo {vehicle_id}: {exc}", exc_info=True)