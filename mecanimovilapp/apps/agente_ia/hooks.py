"""Utilidades para enganchar el agente IA en flujos de mensajería."""
from __future__ import annotations

from mecanimovilapp.apps.agente_ia.services.orquestador import agente_ia_habilitado, pausar_sesion_por_mensaje_taller
from mecanimovilapp.apps.agente_ia.services.taller_resolver import resolver_taller_desde_conversation
from mecanimovilapp.apps.chat.models import Message


def es_mensaje_de_cliente(message: Message) -> bool:
    if message.direction == 'inbound':
        return True
    if message.conversation.source_channel != 'APP':
        return False
    _, proveedor_user_id = resolver_taller_desde_conversation(message.conversation)
    if message.sender_id is None:
        return True
    if not proveedor_user_id:
        return False
    return message.sender_id != proveedor_user_id


def es_mensaje_manual_taller(message: Message) -> bool:
    meta = message.channel_metadata or {}
    if meta.get('from_agente_ia'):
        return False
    if message.direction == 'outbound' and message.conversation.source_channel != 'APP':
        return True
    _, proveedor_user_id = resolver_taller_desde_conversation(message.conversation)
    if not proveedor_user_id or not message.sender_id:
        return False
    return message.sender_id == proveedor_user_id


def encolar_agente_para_mensaje(message: Message) -> None:
    if not agente_ia_habilitado():
        return
    if es_mensaje_manual_taller(message):
        pausar_sesion_por_mensaje_taller(message.conversation_id)
        return
    if not es_mensaje_de_cliente(message):
        return
    from mecanimovilapp.apps.agente_ia.tasks import procesar_mensaje_entrante_task

    procesar_mensaje_entrante_task.delay(message.id)
