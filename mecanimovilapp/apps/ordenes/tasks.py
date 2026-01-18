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
        solicitudes_pendientes = SolicitudServicioPublica.objects.filter(
            estado='adjudicada',
            pago_realizado=False,
            fecha_preferida__gte=ahora,
            fecha_preferida__lte=ventana_6_horas
        ).select_related('cliente__usuario')
        
        logger.info(f"🔍 Verificando pagos pendientes: {solicitudes_pendientes.count()} solicitudes encontradas")
        
        notificaciones_enviadas = 0
        
        for solicitud in solicitudes_pendientes:
            if solicitud.cliente and solicitud.cliente.usuario:
                # Calcular tiempo restante
                tiempo_restante = solicitud.fecha_preferida - ahora
                horas_restantes = int(tiempo_restante.total_seconds() / 3600)
                minutos_restantes = int((tiempo_restante.total_seconds() % 3600) / 60)
                
                # Solo enviar si faltan entre 5.5 y 6 horas (evitar duplicados)
                if 5.5 <= tiempo_restante.total_seconds() / 3600 <= 6:
                    mensaje = (
                        f"Tu solicitud #{solicitud.id} requiere pago antes de "
                        f"{solicitud.fecha_preferida.strftime('%d/%m/%Y a las %H:%M')}. "
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
def enviar_notificacion_cambio_estado(solicitud_id, user_id, estado_anterior, estado_nuevo):
    """
    Enviar push notification cuando cambia el estado de una solicitud
    
    Args:
        solicitud_id: ID de la solicitud
        user_id: ID del usuario (cliente)
        estado_anterior: Estado anterior de la solicitud
        estado_nuevo: Nuevo estado de la solicitud
    """
    try:
        # Mensajes según el cambio de estado
        mensajes_estado = {
            'adjudicada': {
                'titulo': '✅ Oferta Aceptada',
                'mensaje': 'Tu solicitud ha sido adjudicada. Procede con el pago para confirmar el servicio.'
            },
            'pagada': {
                'titulo': '💳 Pago Confirmado',
                'mensaje': 'Tu pago ha sido confirmado. El proveedor será notificado para iniciar el servicio.'
            },
            'en_ejecucion': {
                'titulo': '🔧 Servicio Iniciado',
                'mensaje': 'El proveedor ha iniciado el servicio. Puedes seguir el progreso en la app.'
            },
            'completada': {
                'titulo': '✅ Servicio Completado',
                'mensaje': 'Tu servicio ha sido completado. Puedes dejar una reseña y ver el checklist.'
            },
            'cancelada': {
                'titulo': '❌ Solicitud Cancelada',
                'mensaje': 'Tu solicitud ha sido cancelada.'
            },
            'expirada': {
                'titulo': '⏰ Solicitud Expirada',
                'mensaje': 'Tu solicitud ha expirado sin ofertas aceptadas.'
            }
        }
        
        if estado_nuevo not in mensajes_estado:
            logger.debug(f"Estado {estado_nuevo} no requiere notificación push")
            return {'enviados': 0, 'razon': 'Estado no requiere notificación'}
        
        info_mensaje = mensajes_estado[estado_nuevo]
        
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
                'title': info_mensaje['titulo'],
                'body': info_mensaje['mensaje'],
                'data': {
                    'type': 'cambio_estado',
                    'solicitud_id': str(solicitud_id),
                    'estado_anterior': estado_anterior,
                    'estado_nuevo': estado_nuevo
                },
                'priority': 'high'
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
            exitosos = [r for r in resultado.get('data', []) if r.get('status') == 'ok']
            logger.info(f"✅ Notificaciones de cambio de estado enviadas para solicitud {solicitud_id}: {len(exitosos)} exitosas")
            return {'enviados': len(exitosos)}
        else:
            logger.error(f"❌ Error enviando notificaciones de cambio de estado: {response.status_code}")
            return {'enviados': 0, 'error': f'HTTP {response.status_code}'}
            
    except Exception as e:
        logger.error(f"❌ Error en enviar_notificacion_cambio_estado: {e}", exc_info=True)
        return {'enviados': 0, 'error': str(e)}
