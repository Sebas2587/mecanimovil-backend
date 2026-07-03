"""Permisos asistente cotización — mandante/supervisor del taller."""
from __future__ import annotations

from mecanimovilapp.apps.chat.models import Conversation


def usuario_puede_cotizar_canal(user, *, conversation: Conversation | None = None) -> bool:
    if not user or not user.is_authenticated:
        return False
    from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller

    taller, _miembro, rol = resolver_contexto_taller(user)
    if taller is None:
        return False
    if rol == 'mecanico':
        return False
    if conversation is None:
        return rol in ('mandante', 'supervisor')
    if conversation.type != 'OMNICHANNEL':
        return False
    return conversation.participants.filter(id=user.id).exists()
