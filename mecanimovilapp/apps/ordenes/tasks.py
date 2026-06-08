"""
Tareas asíncronas de Celery para el sistema de órdenes y solicitudes
Incluye envío de push notifications para recordatorios de pago
"""
try:
    from celery import shared_task
    CELERY_AVAILABLE = True
except ImportError:
    # Celery no está disponible, crear decorador dummy
    def shared_task(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    CELERY_AVAILABLE = False

import requests
import logging
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from django.core.management import call_command
from mecanimovilapp.apps.usuarios.models import PushToken

logger = logging.getLogger(__name__)


@shared_task
def enviar_push_notificacion_pago_pendiente(solicitud_id, user_id, mensaje, titulo=None):
    """
    Enviar push notification de recordatorio de pago a un usuario
    
    Args:
        solicitud_id: ID de la solicitud
        user_id: ID del usuario (cliente)
        mensaje: Mensaje de la notificación
        titulo: Título de la notificación (opcional)
    """
    try:
        # Obtener tokens activos del usuario
        tokens = PushToken.objects.filter(
            usuario_id=user_id,
            activo=True
        ).values_list('token', flat=True)
        
        if not tokens:
            logger.warning(f"⚠️ No hay tokens push activos para usuario {user_id}")
            return {'enviados': 0, 'error': 'No hay tokens activos'}
        
        # Preparar mensajes para Expo
        mensajes = [
            {
                'to': token,
                'sound': 'default',
                'title': titulo or '💳 Recordatorio de Pago',
                'body': mensaje,
                'data': {
                    'type': 'recordatorio_pago',
                    'solicitud_id': str(solicitud_id)
                },
                'priority': 'high',
                'badge': 1
            }
            for token in tokens
        ]
        
        # Enviar a Expo Push Notification Service
        response = requests.post(
            'https://exp.host/--/api/v2/push/send',
            json=mensajes,
            headers={
                'Accept': 'application/json',
                'Accept-Encoding': 'gzip, deflate',
                'Content-Type': 'application/json',
            },
            timeout=10
        )
        
        if response.status_code == 200:
            resultado = response.json()
            # Verificar si hay errores en la respuesta
            errores = [r for r in resultado.get('data', []) if r.get('status') == 'error']
            exitosos = [r for r in resultado.get('data', []) if r.get('status') == 'ok']
            
            # Desactivar tokens que dieron error
            if errores:
                for error in errores:
                    token_error = error.get('details', {}).get('expoPushToken')
                    if token_error:
                        PushToken.objects.filter(token=token_error).update(activo=False)
                        logger.warning(f"⚠️ Token inválido desactivado: {token_error[:20]}...")
            
            # Actualizar fecha de última notificación para tokens exitosos
            if exitosos:
                tokens_exitosos = [e.get('details', {}).get('expoPushToken') for e in exitosos if e.get('details', {}).get('expoPushToken')]
                PushToken.objects.filter(token__in=tokens_exitosos).update(
                    ultima_notificacion_enviada=timezone.now()
                )
            
            logger.info(f"✅ Push notifications enviadas para solicitud {solicitud_id}: {len(exitosos)} exitosas, {len(errores)} errores")
            return {
                'enviados': len(exitosos),
                'errores': len(errores),
                'total_tokens': len(tokens)
            }
        else:
            logger.error(f"❌ Error enviando push notifications: {response.status_code} - {response.text}")
            return {
                'enviados': 0,
                'error': f'HTTP {response.status_code}: {response.text[:200]}'
            }
            
    except requests.exceptions.Timeout:
        logger.error(f"❌ Timeout enviando push notifications para solicitud {solicitud_id}")
        return {'enviados': 0, 'error': 'Timeout'}
    except Exception as e:
        logger.error(f"❌ Error en tarea push notification: {e}", exc_info=True)
        return {'enviados': 0, 'error': str(e)}


@shared_task
def verificar_pagos_pendientes():
    """
    Tarea periódica que verifica solicitudes con pagos pendientes
    y envía recordatorios push
    """
    try:
        from .models import SolicitudServicioPublica
        
        ahora = timezone.now()
        ventana_6_horas = ahora + timedelta(hours=6)
        
        # Buscar solicitudes adjudicadas sin pago que venzan en las próximas 6 horas
        # NOTA: SolicitudServicioPublica NO tiene campo 'pago_realizado'
        # El estado del pago se refleja en el campo 'estado':
        # - 'adjudicada' = sin pago
        # - 'pendiente_pago' = procesando pago
        # - 'pagada' = pago completado
        solicitudes_pendientes = SolicitudServicioPublica.objects.filter(
            estado__in=['adjudicada', 'pendiente_pago'],  # Estados sin pago completado
            fecha_limite_pago__gte=ahora,  # Usar fecha_limite_pago en lugar de fecha_preferida
            fecha_limite_pago__lte=ventana_6_horas
        ).select_related('cliente__usuario')
        
        logger.info(f"🔍 Verificando pagos pendientes: {solicitudes_pendientes.count()} solicitudes encontradas")
        
        notificaciones_enviadas = 0
        
        for solicitud in solicitudes_pendientes:
            if solicitud.cliente and solicitud.cliente.usuario:
                # Usar fecha_limite_pago si existe, sino usar fecha_preferida como fallback
                fecha_limite = solicitud.fecha_limite_pago or solicitud.fecha_preferida
                if not fecha_limite:
                    continue  # Saltar si no hay fecha límite
                
                # Calcular tiempo restante
                tiempo_restante = fecha_limite - ahora
                if tiempo_restante.total_seconds() < 0:
                    continue  # Ya expiró
                    
                horas_restantes = int(tiempo_restante.total_seconds() / 3600)
                minutos_restantes = int((tiempo_restante.total_seconds() % 3600) / 60)
                
                # Solo enviar si faltan entre 5.5 y 6 horas (evitar duplicados)
                if 5.5 <= tiempo_restante.total_seconds() / 3600 <= 6:
                    mensaje = (
                        f"Tu solicitud #{solicitud.id} requiere pago antes de "
                        f"{fecha_limite.strftime('%d/%m/%Y a las %H:%M')}. "
                        f"Quedan {horas_restantes}h {minutos_restantes}m"
                    )
                    
                    enviar_push_notificacion_pago_pendiente.delay(
                        solicitud.id,
                        solicitud.cliente.usuario.id,
                        mensaje,
                        titulo='💳 Recordatorio de Pago'
                    )
                    notificaciones_enviadas += 1
        
        logger.info(f"✅ Verificación de pagos completada: {notificaciones_enviadas} notificaciones programadas")
        return {
            'solicitudes_revisadas': solicitudes_pendientes.count(),
            'notificaciones_enviadas': notificaciones_enviadas
        }
        
    except Exception as e:
        logger.error(f"❌ Error en verificar_pagos_pendientes: {e}", exc_info=True)
        return {'error': str(e)}


@shared_task
def enviar_alertas_pago_proximo_task():
    """
    Tarea Celery que ejecuta el comando de management para enviar alertas de pago próximo
    Incluye notificaciones push y WebSocket
    """
    try:
        logger.info("🔄 Ejecutando comando enviar_alertas_pago_proximo...")
        call_command('enviar_alertas_pago_proximo' )
        logger.info("✅ Comando enviar_alertas_pago_proximo ejecutado exitosamente")
        return {'status': 'success'}
    except Exception as e:
        logger.error(f"❌ Error ejecutando enviar_alertas_pago_proximo: {e}", exc_info=True)
        return {'status': 'error', 'error': str(e)}


@shared_task
def enviar_notificacion_cambio_estado(solicitud_id, user_id, estado_anterior, estado_nuevo):
    """
    Push + notificación in-app cuando cambia el estado de una SolicitudServicioPublica.

    Usa send_expo_push_notification (cola 'default', throttle, receipt checking).
    Los mensajes incluyen contexto del proveedor, vehículo y tipo de servicio.
    """
    try:
        from mecanimovilapp.apps.usuarios.models import Notificacion, Usuario
        from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification

        ESTADOS_CON_PUSH = {
            'adjudicada', 'pendiente_pago', 'pagada',
            'en_ejecucion', 'completada', 'cancelada', 'expirada',
        }
        if estado_nuevo not in ESTADOS_CON_PUSH:
            logger.debug(f"[cambio_estado] Estado {estado_nuevo} no requiere push")
            return {'enviados': 0, 'razon': 'estado_no_notificable'}

        # Obtener contexto rico de la solicitud
        try:
            from mecanimovilapp.apps.ordenes.models import SolicitudServicioPublica
            solicitud = SolicitudServicioPublica.objects.select_related(
                'vehiculo__marca', 'vehiculo__modelo',
                'oferta_seleccionada__proveedor',
            ).get(pk=solicitud_id)

            nombre_vehiculo = ""
            if solicitud.vehiculo:
                v = solicitud.vehiculo
                marca = getattr(v.marca, 'nombre', '') if v.marca else ''
                modelo = getattr(v.modelo, 'nombre', '') if v.modelo else ''
                nombre_vehiculo = f"{marca} {modelo}".strip() or f"Vehículo {v.patente or ''}"

            nombre_proveedor = ""
            try:
                oferta = solicitud.oferta_seleccionada
                if oferta and oferta.proveedor:
                    prov_user = oferta.proveedor
                    # Intentar nombre del taller si existe
                    taller = getattr(prov_user, 'taller', None)
                    if taller and getattr(taller, 'nombre_taller', ''):
                        nombre_proveedor = taller.nombre_taller
                    else:
                        nombre_proveedor = f"{prov_user.first_name} {prov_user.last_name}".strip()
            except Exception:
                pass

        except Exception:
            nombre_vehiculo = ""
            nombre_proveedor = ""

        # Plantillas enriquecidas con contexto
        def _t(titulo, cuerpo):
            return titulo, cuerpo

        ctx_vehiculo = f" para tu {nombre_vehiculo}" if nombre_vehiculo else ""
        ctx_proveedor = f" por {nombre_proveedor}" if nombre_proveedor else ""

        MENSAJES = {
            'adjudicada': _t(
                "✅ ¡Tu solicitud fue aceptada!",
                f"El proveedor{ctx_proveedor} aceptó tu solicitud{ctx_vehiculo}. "
                "Completa el pago para confirmar el servicio.",
            ),
            'pendiente_pago': _t(
                "💳 Pago pendiente",
                f"Tienes un pago pendiente{ctx_vehiculo}. "
                "Completa el pago para agendar el servicio.",
            ),
            'pagada': _t(
                "💳 Pago confirmado",
                f"Tu pago{ctx_vehiculo} fue confirmado. "
                f"El proveedor{ctx_proveedor} recibirá la notificación y coordinará el servicio.",
            ),
            'en_ejecucion': _t(
                "🔧 Servicio en progreso",
                f"El proveedor{ctx_proveedor} comenzó el servicio{ctx_vehiculo}. "
                "Puedes seguir el progreso en la app.",
            ),
            'completada': _t(
                "🎉 ¡Servicio completado!",
                f"El servicio{ctx_vehiculo} fue completado{ctx_proveedor}. "
                "¿Cómo fue tu experiencia? Deja tu reseña en la app.",
            ),
            'cancelada': _t(
                "❌ Solicitud cancelada",
                f"Tu solicitud{ctx_vehiculo} fue cancelada. "
                "Puedes crear una nueva solicitud cuando lo necesites.",
            ),
            'expirada': _t(
                "⏰ Solicitud expirada",
                f"Tu solicitud{ctx_vehiculo} expiró sin recibir ofertas. "
                "Intenta publicarla nuevamente con más detalles.",
            ),
        }

        titulo, cuerpo = MENSAJES[estado_nuevo]

        # In-app notification
        try:
            usuario_obj = Usuario.objects.get(pk=user_id)
            Notificacion.crear_unica(
                usuario=usuario_obj,
                tipo='order_update',
                titulo=titulo,
                mensaje=cuerpo,
                data={
                    'solicitud_id': str(solicitud_id),
                    'estado_anterior': estado_anterior,
                    'estado_nuevo': estado_nuevo,
                },
                ventana_horas=12,
                dedup_key={'solicitud_id': str(solicitud_id), 'estado': estado_nuevo},
            )
        except Exception as e:
            logger.error(f"[cambio_estado] Error in-app notif: {e}")

        # Push Expo via cola 'default' (con throttle y receipt checking)
        send_expo_push_notification.delay(
            user_id, titulo, cuerpo,
            {
                'type': 'cambio_estado',
                'solicitud_id': str(solicitud_id),
                'estado_anterior': estado_anterior,
                'estado_nuevo': estado_nuevo,
            },
        )

        logger.info(
            f"✅ [cambio_estado] Push encolada para solicitud {solicitud_id} "
            f"(usuario {user_id}): {estado_anterior} → {estado_nuevo}"
        )
        return {'enviados': 1}

    except Exception as e:
        logger.error(f"❌ Error en enviar_notificacion_cambio_estado: {e}", exc_info=True)
        return {'enviados': 0, 'error': str(e)}
