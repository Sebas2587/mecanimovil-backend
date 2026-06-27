"""Construcción del inbox unificado para proveedores."""
from django.contrib.contenttypes.models import ContentType

from mecanimovilapp.apps.chat.models import Conversation, Message
from mecanimovilapp.apps.omnichannel.utils import channel_to_api_slug
from mecanimovilapp.apps.ordenes.models import ChatSolicitud, OfertaProveedor


def build_legacy_provider_chats(user, request=None):
    """Replica formato de lista-chats para ofertas con ChatSolicitud."""
    from django.db.models import OuterRef, Subquery, Count
    from django.db.models.functions import Coalesce

    last_msg_qs = ChatSolicitud.objects.filter(
        oferta=OuterRef('pk')
    ).order_by('-fecha_envio').values('fecha_envio')[:1]

    unread_provider_qs = ChatSolicitud.objects.filter(
        oferta=OuterRef('pk'),
        leido=False,
        es_proveedor=False,
    ).values('oferta').annotate(count=Count('id')).values('count')

    ofertas = OfertaProveedor.objects.filter(
        proveedor=user,
        mensajes_chat__isnull=False,
    ).distinct().select_related(
        'solicitud', 'solicitud__cliente', 'solicitud__cliente__usuario',
        'solicitud__vehiculo', 'solicitud__vehiculo__marca',
        'solicitud__vehiculo__modelo',
    ).prefetch_related('mensajes_chat').annotate(
        ultimo_mensaje_fecha=Subquery(last_msg_qs),
        mensajes_no_leidos=Coalesce(Subquery(unread_provider_qs), 0),
    ).order_by('-ultimo_mensaje_fecha')

    chats_list = []
    for oferta in ofertas:
        ultimo = oferta.mensajes_chat.order_by('-fecha_envio').first()
        if not ultimo:
            continue
        cliente = oferta.solicitud.cliente
        nombre_cliente = 'Cliente'
        foto_url = None
        if cliente and cliente.usuario:
            nombre_cliente = cliente.usuario.get_full_name() or cliente.usuario.username
            if cliente.usuario.foto_perfil and request:
                foto_url = request.build_absolute_uri(cliente.usuario.foto_perfil.url)

        vehiculo_info = None
        vehiculo = getattr(oferta.solicitud, 'vehiculo', None)
        if vehiculo:
            vehiculo_info = {
                'marca': vehiculo.marca.nombre if vehiculo.marca else None,
                'modelo': vehiculo.modelo.nombre if vehiculo.modelo else None,
                'year': vehiculo.year,
                'patente': vehiculo.patente,
            }

        chats_list.append({
            'kind': 'oferta',
            'channel': 'app',
            'conversation_id': None,
            'oferta_id': str(oferta.id),
            'solicitud_id': str(oferta.solicitud.id),
            'otra_persona': {
                'id': cliente.id if cliente else None,
                'nombre': nombre_cliente,
                'foto': foto_url,
            },
            'vehiculo': vehiculo_info,
            'ultimo_mensaje': {
                'id': str(ultimo.id),
                'mensaje': ultimo.mensaje,
                'fecha_envio': ultimo.fecha_envio.isoformat(),
                'es_propio': ultimo.es_proveedor,
                'leido': ultimo.leido,
            },
            'mensajes_no_leidos': oferta.mensajes_no_leidos,
            'estado_oferta': oferta.estado,
            'sort_at': ultimo.fecha_envio,
        })
    return chats_list


def build_omnichannel_chats(user):
    conversations = Conversation.objects.filter(
        participants=user,
        source_channel__in=['WHATSAPP', 'MESSENGER', 'INSTAGRAM'],
    ).select_related('external_contact').prefetch_related('messages').order_by('-updated_at')

    items = []
    for conv in conversations:
        last_msg = conv.messages.order_by('-timestamp').last()
        if not last_msg:
            continue
        contact = conv.external_contact
        unread = conv.messages.filter(direction='inbound', is_read=False).count()
        solicitud_id = None
        if conv.content_type and conv.object_id:
            model = conv.content_type.model_class()
            if model and 'solicitud' in model.__name__.lower():
                solicitud_id = conv.object_id

        items.append({
            'kind': 'omnichannel',
            'channel': channel_to_api_slug(conv.source_channel),
            'conversation_id': str(conv.id),
            'oferta_id': None,
            'solicitud_id': solicitud_id,
            'otra_persona': {
                'id': str(contact.id) if contact else None,
                'nombre': contact.display_name if contact else 'Contacto',
                'foto': contact.profile_picture_url if contact else None,
                'telefono': contact.phone if contact else None,
            },
            'vehiculo': None,
            'ultimo_mensaje': {
                'id': str(last_msg.id),
                'mensaje': last_msg.content or '',
                'fecha_envio': last_msg.timestamp.isoformat(),
                'es_propio': last_msg.direction == 'outbound',
                'leido': last_msg.is_read if last_msg.direction == 'inbound' else True,
            },
            'mensajes_no_leidos': unread,
            'estado_oferta': None,
            'sort_at': last_msg.timestamp,
        })
    return items


def build_unified_inbox(user, request=None):
    legacy = build_legacy_provider_chats(user, request)
    omni = build_omnichannel_chats(user)
    merged = legacy + omni
    merged.sort(key=lambda x: x['sort_at'], reverse=True)
    for item in merged:
        item.pop('sort_at', None)
    return merged
