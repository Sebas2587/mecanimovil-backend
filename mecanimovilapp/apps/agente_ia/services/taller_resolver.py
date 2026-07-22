"""Resolución de taller y usuario proveedor desde una conversación."""
from __future__ import annotations

from mecanimovilapp.apps.chat.models import Conversation
from mecanimovilapp.apps.usuarios.models import Taller


def resolver_taller_desde_conversation(conversation: Conversation) -> tuple[Taller | None, int | None]:
    """
    Devuelve (taller, usuario_proveedor_id) para una conversación.
    """
    if conversation.type == 'OMNICHANNEL' and conversation.external_contact_id:
        contact = conversation.external_contact
        if contact and contact.connection_id:
            conn = contact.connection
            proveedor = conn.proveedor
            if isinstance(proveedor, Taller):
                return proveedor, conn.usuario_id
            from mecanimovilapp.apps.usuarios.models import MecanicoDomicilio

            if isinstance(proveedor, MecanicoDomicilio):
                return None, conn.usuario_id

    from mecanimovilapp.apps.usuarios.models import MecanicoDomicilio

    for participant in conversation.participants.all():
        taller = getattr(participant, 'taller', None)
        if taller is None:
            taller = Taller.objects.filter(usuario=participant).first()
        if taller:
            return taller, participant.id
        if MecanicoDomicilio.objects.filter(usuario=participant).exists():
            return None, participant.id

    return None, None


def canal_conversacion(conversation: Conversation) -> str:
    """Normaliza el canal de la conversación."""
    if conversation.source_channel and conversation.source_channel != 'APP':
        return conversation.source_channel
    return 'APP'
