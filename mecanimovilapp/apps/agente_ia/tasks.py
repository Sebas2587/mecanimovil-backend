"""Tareas Celery del agente IA."""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='agente_ia.procesar_mensaje_entrante', queue='default')
def procesar_mensaje_entrante_task(message_id: int) -> dict:
    from mecanimovilapp.apps.agente_ia.services.orquestador import procesar_mensaje_entrante_ia

    try:
        return procesar_mensaje_entrante_ia(message_id)
    except Exception:
        logger.exception('Error procesando mensaje agente IA %s', message_id)
        return {'ok': False, 'error': 'internal'}


@shared_task(name='agente_ia.procesar_documento_conocimiento', queue='default')
def procesar_documento_conocimiento_task(documento_id: int) -> None:
    from mecanimovilapp.apps.agente_ia.services.rag import procesar_documento_conocimiento

    procesar_documento_conocimiento(documento_id)


@shared_task(name='agente_ia.sincronizar_chunk_servicio', queue='default')
def sincronizar_chunk_servicio_task(oferta_servicio_id: int) -> None:
    from mecanimovilapp.apps.agente_ia.services.rag import sincronizar_chunk_oferta_servicio

    sincronizar_chunk_oferta_servicio(oferta_servicio_id)


@shared_task(name='agente_ia.sincronizar_chunk_historico', queue='default')
def sincronizar_chunk_historico_task(solicitud_id: int) -> None:
    from mecanimovilapp.apps.agente_ia.services.rag import sincronizar_chunk_historico_solicitud

    sincronizar_chunk_historico_solicitud(solicitud_id)


@shared_task(name='agente_ia.sincronizar_instrucciones', queue='default')
def sincronizar_instrucciones_task(taller_id: int) -> None:
    from mecanimovilapp.apps.agente_ia.services.rag import sincronizar_instrucciones_taller

    sincronizar_instrucciones_taller(taller_id)


@shared_task(name='agente_ia.iniciar_agendamiento', queue='default')
def iniciar_agendamiento_task(cotizacion_id: int) -> dict:
    from mecanimovilapp.apps.agente_ia.models import AgenteConversacionSesion
    from mecanimovilapp.apps.agente_ia.services.agendamiento_conversacional import iniciar_agendamiento
    from mecanimovilapp.apps.agente_ia.services.taller_resolver import resolver_taller_desde_conversation
    from mecanimovilapp.apps.ordenes.models import CotizacionCanal

    try:
        cotizacion = (
            CotizacionCanal.objects.select_related('conversation', 'taller', 'creado_por')
            .filter(pk=cotizacion_id)
            .first()
        )
        if cotizacion is None or not cotizacion.conversation_id:
            return {'ok': False, 'reason': 'sin_conversacion'}

        cita = cotizacion.citas_generadas.order_by('-id').first()
        if cita is None:
            return {'ok': False, 'reason': 'sin_cita'}

        conversation = cotizacion.conversation
        taller, proveedor_user_id = resolver_taller_desde_conversation(conversation)
        if not taller or not proveedor_user_id:
            return {'ok': False, 'reason': 'sin_taller'}

        sesion = AgenteConversacionSesion.objects.filter(conversation=conversation).first()
        return iniciar_agendamiento(
            cita=cita,
            conversation=conversation,
            taller=taller,
            proveedor_user_id=proveedor_user_id,
            sesion=sesion,
        )
    except Exception:
        logger.exception('Error iniciando agendamiento IA cotización %s', cotizacion_id)
        return {'ok': False, 'error': 'internal'}


@shared_task(name='agente_ia.reaccionar_rechazo', queue='default')
def reaccionar_rechazo_task(cotizacion_id: int) -> dict:
    from mecanimovilapp.apps.agente_ia.models import AgenteConversacionSesion
    from mecanimovilapp.apps.agente_ia.services.agendamiento_conversacional import (
        reaccionar_rechazo_cotizacion,
    )
    from mecanimovilapp.apps.agente_ia.services.taller_resolver import resolver_taller_desde_conversation
    from mecanimovilapp.apps.ordenes.models import CotizacionCanal

    try:
        cotizacion = (
            CotizacionCanal.objects.select_related('conversation', 'taller')
            .filter(pk=cotizacion_id)
            .first()
        )
        if cotizacion is None or not cotizacion.conversation_id:
            return {'ok': False, 'reason': 'sin_conversacion'}

        conversation = cotizacion.conversation
        taller, proveedor_user_id = resolver_taller_desde_conversation(conversation)
        if not taller or not proveedor_user_id:
            return {'ok': False, 'reason': 'sin_taller'}

        sesion = AgenteConversacionSesion.objects.filter(conversation=conversation).first()
        return reaccionar_rechazo_cotizacion(
            cotizacion=cotizacion,
            conversation=conversation,
            taller=taller,
            proveedor_user_id=proveedor_user_id,
            sesion=sesion,
        )
    except Exception:
        logger.exception('Error reaccionando rechazo IA cotización %s', cotizacion_id)
        return {'ok': False, 'error': 'internal'}
