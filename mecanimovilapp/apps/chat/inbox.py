"""Construcción del inbox unificado para proveedores."""
from datetime import timedelta

from django.utils import timezone

from mecanimovilapp.apps.chat.models import Conversation, Message
from mecanimovilapp.apps.omnichannel.services.omnichannel_service import (
    corte_bandeja,
    mensaje_visible_en_bandeja,
)
from mecanimovilapp.apps.omnichannel.utils import channel_to_api_slug
from mecanimovilapp.apps.ordenes.models import ChatSolicitud, CotizacionCanal, OfertaProveedor

CANALES_OMNI = ('WHATSAPP', 'MESSENGER', 'INSTAGRAM')


def _cotizaciones_por_conversacion(conversation_ids: list[int]) -> dict[int, CotizacionCanal]:
    """Última cotización relevante por conversación (enviada/aceptada/borrador/rechazada)."""
    if not conversation_ids:
        return {}
    qs = (
        CotizacionCanal.objects.filter(
            conversation_id__in=conversation_ids,
            estado__in=('borrador', 'enviada', 'aceptada', 'rechazada'),
        )
        .order_by('conversation_id', '-actualizado_en', '-id')
    )
    out: dict[int, CotizacionCanal] = {}
    for cot in qs:
        cid = cot.conversation_id
        if cid not in out:
            out[cid] = cot
    return out


def _vehiculo_desde_cotizacion(cot: CotizacionCanal | None) -> dict | None:
    if cot is None:
        return None
    if not (cot.vehiculo_marca or cot.vehiculo_modelo or cot.vehiculo_patente):
        return None
    return {
        'marca': cot.vehiculo_marca or None,
        'modelo': cot.vehiculo_modelo or None,
        'year': cot.vehiculo_anio,
        'patente': cot.vehiculo_patente or None,
    }


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
            'cotizacion_estado': None,
            'cotizacion_id': None,
            'cotizacion_servicio': None,
            'cliente_sin_responder': not ultimo.es_proveedor or oferta.mensajes_no_leidos > 0,
            'lead_categoria': 'sin_calificar',
            'lead_score': 0,
            'sort_at': ultimo.fecha_envio,
        })
    return chats_list


def _ultimos_visibles(conversations: list) -> tuple[dict[int, Message], dict[int, int]]:
    """Último mensaje vigente y no leídos, sin el historial anterior al canal."""
    conv_ids = [c.id for c in conversations]
    if not conv_ids:
        return {}, {}
    cortes = {}
    for conv in conversations:
        contact = conv.external_contact
        connection = contact.connection if contact else None
        cortes[conv.id] = corte_bandeja(connection)
    desde = timezone.now() - timedelta(days=120)
    filas = Message.objects.filter(
        conversation_id__in=conv_ids,
        timestamp__gte=desde,
    ).only(
        'id',
        'conversation_id',
        'content',
        'direction',
        'timestamp',
        'is_read',
        'channel_metadata',
    )
    por_chat: dict[int, list[Message]] = {}
    for msg in filas:
        if not mensaje_visible_en_bandeja(msg, cortes.get(msg.conversation_id)):
            continue
        por_chat.setdefault(msg.conversation_id, []).append(msg)
    ultimos: dict[int, Message] = {}
    no_leidos: dict[int, int] = {}
    for conv_id, msgs in por_chat.items():
        msgs.sort(key=lambda m: (m.timestamp, m.id))
        ultimos[conv_id] = msgs[-1]
        no_leidos[conv_id] = sum(
            1 for m in msgs if m.direction == 'inbound' and not m.is_read
        )
    return ultimos, no_leidos


def build_omnichannel_chats(user):
    conversations = list(
        Conversation.objects.filter(
            participants=user,
            source_channel__in=CANALES_OMNI,
        ).select_related(
            'external_contact',
            'external_contact__connection',
            'lead_calificacion',
        ).order_by('-updated_at')
    )
    ultimos, no_leidos = _ultimos_visibles(conversations)
    conv_ids = [c.id for c in conversations]
    cot_map = _cotizaciones_por_conversacion(conv_ids)

    items = []
    for conv in conversations:
        last_msg = ultimos.get(conv.id)
        if not last_msg:
            continue
        contact = conv.external_contact
        unread = no_leidos.get(conv.id, 0)
        solicitud_id = None
        if conv.content_type and conv.object_id:
            model = conv.content_type.model_class()
            if model and 'solicitud' in model.__name__.lower():
                solicitud_id = conv.object_id

        cot = cot_map.get(conv.id)
        lead = getattr(conv, 'lead_calificacion', None)
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
            'vehiculo': _vehiculo_desde_cotizacion(cot),
            'ultimo_mensaje': {
                'id': str(last_msg.id),
                'mensaje': last_msg.content or '',
                'fecha_envio': last_msg.timestamp.isoformat(),
                'es_propio': last_msg.direction == 'outbound',
                'leido': last_msg.is_read if last_msg.direction == 'inbound' else True,
            },
            'mensajes_no_leidos': unread,
            'estado_oferta': None,
            'cotizacion_estado': cot.estado if cot else None,
            'cotizacion_id': cot.id if cot else None,
            'cotizacion_servicio': (cot.servicio_nombre or '') if cot else None,
            'cliente_sin_responder': (
                last_msg.direction == 'inbound' or unread > 0
            ),
            'lead_categoria': lead.categoria if lead else 'sin_calificar',
            'lead_score': lead.score if lead else 0,
            'contacto_rol': contact.rol if contact else 'sin_clasificar',
            'rol_sugerido': contact.rol_sugerido if contact else '',
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
