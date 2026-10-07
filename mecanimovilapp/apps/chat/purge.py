"""
Saca un hilo de la bandeja sin recorrer archivos ni borrar cotizaciones.
"""
from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from rest_framework.exceptions import PermissionDenied, NotFound

from mecanimovilapp.apps.chat.models import Conversation
from mecanimovilapp.apps.ordenes.models import ChatSolicitud, OfertaProveedor, SolicitudServicioPublica


def _user_may_access_oferta(user, oferta: OfertaProveedor) -> bool:
    if hasattr(user, 'cliente') and oferta.solicitud.cliente_id == user.cliente.id:
        return True
    if oferta.proveedor_id == user.id:
        return True
    return user.is_staff or user.is_superuser


def _desvincular_cotizaciones(conversation: Conversation) -> None:
    """El chat sale de la bandeja. La cotización, la cita y el historial de la patente quedan."""
    from mecanimovilapp.apps.ordenes.models import CotizacionCanal

    CotizacionCanal.objects.filter(conversation_id=conversation.id).update(conversation=None)


def _purge_chat_solicitud_queryset(qs) -> int:
    deleted, _ = qs.delete()
    return deleted


def _purge_conversation_instance(conversation: Conversation) -> None:
    _desvincular_cotizaciones(conversation)
    conversation.delete()


def _conversations_for_solicitud(solicitud: SolicitudServicioPublica):
    ct = ContentType.objects.get_for_model(SolicitudServicioPublica)
    return Conversation.objects.filter(content_type=ct, object_id=str(solicitud.id))


@transaction.atomic
def purge_chat_for_oferta(oferta_id, user) -> dict:
    try:
        oferta = OfertaProveedor.objects.select_related(
            'solicitud', 'solicitud__cliente', 'proveedor'
        ).get(pk=oferta_id)
    except OfertaProveedor.DoesNotExist:
        raise NotFound('Oferta no encontrada')

    if not _user_may_access_oferta(user, oferta):
        raise PermissionDenied('No tienes permiso para eliminar este chat')

    solicitud = oferta.solicitud
    chat_deleted = _purge_chat_solicitud_queryset(ChatSolicitud.objects.filter(oferta=oferta))

    conversation_deleted = 0
    remaining = ChatSolicitud.objects.filter(oferta__solicitud=solicitud).exists()
    if not remaining:
        for conv in _conversations_for_solicitud(solicitud).filter(participants=user):
            _purge_conversation_instance(conv)
            conversation_deleted += 1

    return {
        'oferta_id': str(oferta.id),
        'solicitud_id': str(solicitud.id),
        'mensajes_chat_solicitud_eliminados': chat_deleted,
        'conversaciones_eliminadas': conversation_deleted,
    }


@transaction.atomic
def purge_conversation(conversation_id, user) -> dict:
    try:
        conversation = Conversation.objects.prefetch_related('participants').get(pk=conversation_id)
    except Conversation.DoesNotExist:
        raise NotFound('Conversación no encontrada')

    if not conversation.participants.filter(id=user.id).exists() and not (user.is_staff or user.is_superuser):
        raise PermissionDenied('No tienes permiso para eliminar esta conversación')

    chat_deleted = 0
    solicitud_id = None

    ctx = conversation.context_object
    if isinstance(ctx, SolicitudServicioPublica):
        solicitud_id = str(ctx.id)
        if not _user_may_access_solicitud_chat(user, ctx):
            raise PermissionDenied('No tienes permiso para eliminar este chat')
        chat_deleted = _purge_chat_solicitud_queryset(
            ChatSolicitud.objects.filter(oferta__solicitud=ctx)
        )

    _purge_conversation_instance(conversation)

    return {
        'conversation_id': str(conversation_id),
        'solicitud_id': solicitud_id,
        'mensajes_chat_solicitud_eliminados': chat_deleted,
        'conversaciones_eliminadas': 1,
    }


def _user_may_access_solicitud_chat(user, solicitud: SolicitudServicioPublica) -> bool:
    if hasattr(user, 'cliente') and solicitud.cliente_id == user.cliente.id:
        return True
    if OfertaProveedor.objects.filter(solicitud=solicitud, proveedor=user).exists():
        return True
    return user.is_staff or user.is_superuser
