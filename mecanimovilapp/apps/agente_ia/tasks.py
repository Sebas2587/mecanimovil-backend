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
