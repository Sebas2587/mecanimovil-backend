"""Utilidades para enganchar el agente IA en flujos de mensajería."""
from __future__ import annotations

from django.conf import settings

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


def segundos_pensamiento(message: Message) -> int:
    """
    Pausa antes de responder: agrupa mensajes rápidos y da tiempo a bajar media
    + pensar con más contexto según complejidad del turno.
    """
    base = int(getattr(settings, 'AGENTE_IA_THINK_DELAY_SECONDS', 6) or 6)
    base = max(2, min(base, 30))
    meta = message.channel_metadata or {}
    text = (message.content or '').strip()
    low = text.lower()

    if meta.get('media') or message.attachment:
        return min(base + 8, 25)

    saludos = ('hola', 'buenas', 'buenos días', 'buenas tardes', 'qué tal', 'como vas', 'cómo vas')
    if len(text) <= 28 and any(s in low for s in saludos):
        return max(2, base // 2)

    tecnicos = (
        'ruido', 'falla', 'luz', 'tablero', 'aceite', 'freno', 'motor', 'humo',
        'vibr', 'golpe', 'patente', 'cotiz', 'presupuesto', 'diagnóst', 'diagnost',
    )
    if len(text) > 90 or '?' in text or any(t in low for t in tecnicos):
        return min(base + 5, 20)

    return base


def encolar_agente_para_mensaje(message: Message) -> None:
    if not agente_ia_habilitado():
        return
    if es_mensaje_manual_taller(message):
        pausar_sesion_por_mensaje_taller(message.conversation_id)
        return
    if not es_mensaje_de_cliente(message):
        return
    from mecanimovilapp.apps.agente_ia.tasks import procesar_mensaje_entrante_task

    delay = segundos_pensamiento(message)
    procesar_mensaje_entrante_task.apply_async(args=[message.id], countdown=delay)
