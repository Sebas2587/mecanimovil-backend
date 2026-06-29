import logging
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.mixins import DestroyModelMixin
from django.shortcuts import get_object_or_404
from django.contrib.contenttypes.models import ContentType
from .models import Conversation, Message
from .serializers import ConversationSerializer, MessageSerializer
from .purge import purge_conversation
from .inbox import build_unified_inbox
from mecanimovilapp.storage.utils import get_cpanel_file_url
from mecanimovilapp.apps.omnichannel.utils import channel_to_api_slug

logger = logging.getLogger(__name__)

class ConversationViewSet(DestroyModelMixin, viewsets.ReadOnlyModelViewSet):
    """
    ViewSet to list and retrieve conversations for the current user.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ConversationSerializer

    def get_queryset(self):
        # Return conversations where the user is a participant
        return Conversation.objects.filter(participants=self.request.user).distinct().order_by('-updated_at')

    def destroy(self, request, *args, **kwargs):
        conversation = self.get_object()
        result = purge_conversation(conversation.id, request.user)
        return Response(result, status=status.HTTP_200_OK)

    def filter_queryset(self, queryset):
        # Allow filtering by type (SERVICE vs MARKETPLACE)
        chat_type = self.request.query_params.get('type')
        if chat_type:
            # Map frontend types (service, marketplace) to DB choices (SERVICE, MARKETPLACE)
            type_map = {
                'service': 'SERVICE',
                'marketplace': 'MARKETPLACE'
            }
            db_type = type_map.get(chat_type.lower())
            if db_type:
                queryset = queryset.filter(type=db_type)
        return queryset

    @action(detail=False, methods=['get'])
    def inbox(self, request):
        """Inbox unificado: chats de oferta (app) + conversaciones omnicanal."""
        if hasattr(request.user, 'cliente'):
            from mecanimovilapp.apps.ordenes.models import ChatSolicitud, OfertaProveedor
            viewset = __import__(
                'mecanimovilapp.apps.ordenes.views',
                fromlist=['ChatSolicitudViewSet'],
            ).ChatSolicitudViewSet()
            viewset.request = request
            viewset.format_kwarg = None
            return viewset.lista_chats(request)
        data = build_unified_inbox(request.user, request)
        return Response(data)

    @action(detail=True, methods=['post'], url_path='vincular-solicitud')
    def vincular_solicitud(self, request, pk=None):
        from mecanimovilapp.apps.ordenes.models import SolicitudServicioPublica

        conversation = self.get_object()
        solicitud_id = request.data.get('solicitud_id')
        if not solicitud_id:
            return Response({'error': 'solicitud_id requerido'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            solicitud = SolicitudServicioPublica.objects.get(id=solicitud_id)
        except SolicitudServicioPublica.DoesNotExist:
            return Response({'error': 'Solicitud no encontrada'}, status=status.HTTP_404_NOT_FOUND)

        ct = ContentType.objects.get_for_model(SolicitudServicioPublica)
        conversation.content_type = ct
        conversation.object_id = str(solicitud.id)
        conversation.save(update_fields=['content_type', 'object_id', 'updated_at'])
        serializer = ConversationSerializer(conversation, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def messages(self, request, pk=None):
        """
        Retrieve messages for a specific conversation.
        Paginated by default from settings.
        """
        conversation = self.get_object()
        messages = conversation.messages.all().order_by('timestamp')

        page_size = request.query_params.get('page_size')
        if page_size:
            page = self.paginate_queryset(messages)
            if page is not None:
                serializer = MessageSerializer(page, many=True, context={'request': request})
                return self.get_paginated_response(serializer.data)

        serializer = MessageSerializer(messages, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def get_or_create(self, request):
        """
        Get or create a conversation from an offer.
        Expects: oferta_id, solicitud_id, type (optional, defaults to 'service')
        """
        from mecanimovilapp.apps.ordenes.models import OfertaProveedor, SolicitudServicioPublica
        from django.contrib.contenttypes.models import ContentType
        
        oferta_id = request.data.get('oferta_id')
        solicitud_id = request.data.get('solicitud_id')
        chat_type = request.data.get('type', 'service')
        
        if not oferta_id or not solicitud_id:
            return Response(
                {'error': 'oferta_id and solicitud_id are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get the offer
        try:
            oferta = OfertaProveedor.objects.get(id=oferta_id)
        except OfertaProveedor.DoesNotExist:
            return Response(
                {'error': 'Offer not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get the solicitud
        try:
            solicitud = SolicitudServicioPublica.objects.get(id=solicitud_id)
        except SolicitudServicioPublica.DoesNotExist:
            return Response(
                {'error': 'Solicitud not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get the provider user directly from the oferta
        provider_user = oferta.proveedor
        
        if not provider_user:
            return Response(
                {'error': 'Provider user not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        
        # Get ContentType for the solicitud
        solicitud_ct = ContentType.objects.get_for_model(SolicitudServicioPublica)
        
        # Get or create conversation linked to the solicitud
        # Convert UUID to string for object_id field
        conversation, created = Conversation.objects.get_or_create(
            content_type=solicitud_ct,
            object_id=str(solicitud.id),
            type='SERVICE' if chat_type == 'service' else 'MARKETPLACE'
        )

        
        # Ensure both users are participants
        if not conversation.participants.filter(id=request.user.id).exists():
            conversation.participants.add(request.user)
        if not conversation.participants.filter(id=provider_user.id).exists():
            conversation.participants.add(provider_user)
        
        serializer = ConversationSerializer(conversation, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK if not created else status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def send_message(self, request, pk=None):
        """
        HTTP endpoint to send a message (fallback when WebSocket unavailable)
        """
        conversation = self.get_object()
        content = request.data.get('content')
        attachment = request.data.get('attachment')
        
        if not content and not attachment:
            return Response(
                {'error': 'content or attachment is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create message
        message = Message.objects.create(
            conversation=conversation,
            sender=request.user,
            content=content if content else '',
            attachment=attachment,
            direction='outbound',
        )
        
        is_omnichannel = conversation.source_channel != 'APP'
        if is_omnichannel:
            from mecanimovilapp.apps.omnichannel.tasks import send_meta_message
            send_meta_message.delay(message.id)
        
        # 🔄 BACKWARDS COMPATIBILITY: Also save to ChatSolicitud table
        # This ensures apps using the old API can see messages sent via new API
        try:
            from mecanimovilapp.apps.ordenes.models import ChatSolicitud, OfertaProveedor
            
            # Determine if this conversation has an associated Oferta
            oferta = None
            if conversation.context_object and not is_omnichannel:
                context_model = conversation.content_type.model_class().__name__
                
                if context_model == 'OfertaProveedor':
                    oferta = conversation.context_object
                elif 'Solicitud' in context_model:
                    # Find related oferta
                    oferta = OfertaProveedor.objects.filter(
                        solicitud=conversation.context_object
                    ).first()
            
            if oferta:
                # Determine if sender is provider
                es_proveedor = hasattr(request.user, 'mecanicodomicilio') or hasattr(request.user, 'taller')
                
                # Create corresponding ChatSolicitud
                ChatSolicitud.objects.create(
                    oferta=oferta,
                    mensaje=content if content else '',
                    enviado_por=request.user,
                    es_proveedor=es_proveedor,
                    archivo_adjunto=attachment
                )
                print(f"✅ [CHAT BACKEND] Message also saved to ChatSolicitud for backwards compatibility")
            else:
                print(f"⚠️ [CHAT BACKEND] No oferta found, skipping ChatSolicitud creation")
                
        except Exception as e:
            # If backwards compat fails, log but don't break the main flow
            print(f"⚠️ [CHAT BACKEND] Failed to save to ChatSolicitud: {e}")
        
        # Update conversation timestamp
        conversation.save()  # Triggers auto_now on updated_at
        
        # Broadcast to WebSocket groups (Global Consumers)
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        
        print(f"🔵 [CHAT BACKEND] Iniciando broadcast para mensaje: {message.id}")
        
        channel_layer = get_channel_layer()
        
        # Determine context IDs
        oferta_id = None
        solicitud_id = None
        
        # Try to resolve context
        try:
            if conversation.context_object:
                context_model = conversation.content_type.model_class().__name__
                print(f"🔵 [CHAT BACKEND] Context model: {context_model}")
                
                if context_model == 'OfertaProveedor':
                    # Direct Oferta context
                    oferta_id = conversation.context_object.id
                    solicitud_id = conversation.context_object.solicitud.id if hasattr(conversation.context_object, 'solicitud') else None
                elif 'Solicitud' in context_model:
                    # SolicitudServicioPublica or similar
                    solicitud_id = conversation.context_object.id

                    from mecanimovilapp.apps.ordenes.models import OfertaProveedor
                    try:
                        # Prefer oferta del proveedor participante (varias ofertas por solicitud)
                        provider_user = None
                        for participant in conversation.participants.all():
                            if participant.id == request.user.id:
                                continue
                            if hasattr(participant, 'mecanicodomicilio') or hasattr(participant, 'taller'):
                                provider_user = participant
                                break
                        if provider_user:
                            oferta = OfertaProveedor.objects.filter(
                                solicitud=conversation.context_object,
                                proveedor=provider_user,
                            ).first()
                        else:
                            oferta = OfertaProveedor.objects.filter(
                                solicitud=conversation.context_object,
                            ).first()
                        if oferta:
                            oferta_id = oferta.id
                            print(f"🔵 [CHAT BACKEND] Found related Oferta: {oferta_id}")
                    except Exception as e:
                        print(f"⚠️ [CHAT BACKEND] Could not query related Oferta: {e}")
                
                print(f"🔵 [CHAT BACKEND] Context resolved - Oferta: {oferta_id}, Solicitud: {solicitud_id}")
        except Exception as e:
            print(f"❌ [CHAT BACKEND] Error resolving context: {e}")

        # Determine if sender is provider
        es_proveedor = False
        try:
            if hasattr(message.sender, 'mecanicodomicilio') or hasattr(message.sender, 'taller'):
                es_proveedor = True
        except:
            pass
        
        print(f"🔵 [CHAT BACKEND] Sender is provider: {es_proveedor}")

        external_contact = conversation.external_contact
        channel_slug = channel_to_api_slug(conversation.source_channel)

        # Prepare payload for Global Consumers (nuevo_mensaje_chat)
        payload = {
            'type': 'nuevo_mensaje_chat',
            'conversation_id': str(conversation.id),
            'id': str(message.id),
            'mensaje_id': str(message.id),
            'message': message.content,
            'oferta_id': str(oferta_id) if oferta_id else None,
            'solicitud_id': str(solicitud_id) if solicitud_id else None,
            'enviado_por': f"{message.sender.first_name} {message.sender.last_name}",
            'mensaje': message.content,
            'content': message.content, # Fallback
            'es_proveedor': es_proveedor,
            'sender_id': message.sender.id,
            'timestamp': message.timestamp.isoformat(),
            'channel': channel_slug,
            'external_contact_name': external_contact.display_name if external_contact else None,
            'external_contact_phone': external_contact.phone if external_contact else None,
            'archivo_adjunto': (
                get_cpanel_file_url(message.attachment, request) if message.attachment else None
            ),
            'attachment': (
                get_cpanel_file_url(message.attachment, request) if message.attachment else None
            ),
        }
        
        print(f"🔵 [CHAT BACKEND] Payload prepared: {payload}")

        # Garantizar que el remitente sea siempre participante
        if not conversation.participants.filter(id=request.user.id).exists():
            conversation.participants.add(request.user)
            logger.info(f"[chat] Remitente {request.user.id} añadido a conversación {conversation.id}")

        # Si la conversación tiene contexto (solicitud/oferta), sincronizar el proveedor
        # para cubrir casos donde fue creada sin ambos participantes
        try:
            if conversation.content_type and conversation.object_id:
                from mecanimovilapp.apps.ordenes.models import SolicitudServicioPublica
                ctx_model = conversation.content_type.model_class()
                if ctx_model == SolicitudServicioPublica:
                    sol = SolicitudServicioPublica.objects.select_related(
                        'oferta_seleccionada__proveedor', 'cliente__usuario'
                    ).get(pk=conversation.object_id)
                    # Añadir cliente si falta
                    if sol.cliente and sol.cliente.usuario:
                        if not conversation.participants.filter(
                            id=sol.cliente.usuario.id
                        ).exists():
                            conversation.participants.add(sol.cliente.usuario)
                    # Añadir proveedor si falta
                    if sol.oferta_seleccionada and sol.oferta_seleccionada.proveedor:
                        prov_user = sol.oferta_seleccionada.proveedor
                        if not conversation.participants.filter(id=prov_user.id).exists():
                            conversation.participants.add(prov_user)
                            logger.info(
                                f"[chat] Proveedor {prov_user.id} sincronizado "
                                f"a conversación {conversation.id}"
                            )
        except Exception as _sync_exc:
            logger.debug(f"[chat] sync participantes: {_sync_exc}")

        # Broadcast to all participants' user groups
        participants = list(conversation.participants.all())
        print(f"🔵 [CHAT BACKEND] Broadcasting to {len(participants)} participants")
        
        for participant in participants:
            # Skip sender to avoid duplicates (they have optimistic update)
            if participant.id == request.user.id:
                print(f"🔵 [CHAT BACKEND] Skipping sender (ID: {participant.id}) to avoid duplicates")
                continue
            
            print(f"🔵 [CHAT BACKEND] Broadcasting to cliente_{participant.id} and proveedor_{participant.id}")
            # Send to Client Consumer Group
            async_to_sync(channel_layer.group_send)(
                f"cliente_{participant.id}",
                payload
            )
            # Send to Provider Consumer Group
            async_to_sync(channel_layer.group_send)(
                f"proveedor_{participant.id}",
                payload
            )
            
        print(f"🔵 [CHAT BACKEND] Broadcast completado")

        # Push al destinatario (app en segundo plano / sin WebSocket)
        try:
            from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification

            for participant in participants:
                if participant.id == request.user.id:
                    continue
                sender_name = (
                    f"{message.sender.first_name} {message.sender.last_name}".strip()
                    or message.sender.email
                    or 'Chat'
                )
                preview = (message.content or '')[:120] or 'Nuevo mensaje'
                from mecanimovilapp.apps.omnichannel.services.broadcast import CHANNEL_LABELS
                label = CHANNEL_LABELS.get(conversation.source_channel, 'Chat')
                title = (
                    f'{label} · {sender_name}'
                    if conversation.source_channel != 'APP'
                    else f'💬 {sender_name}'
                )
                send_expo_push_notification.delay(
                    participant.id,
                    title,
                    preview,
                    {
                        'type': 'chat_message',
                        'channel': channel_slug,
                        'conversation_id': str(conversation.id),
                        'solicitud_id': str(solicitud_id) if solicitud_id else '',
                        'oferta_id': str(oferta_id) if oferta_id else '',
                        'sender_id': str(message.sender.id),
                    },
                )
        except Exception as exc:
            logger.error('Error enviando push chat (ConversationViewSet): %s', exc, exc_info=True)

        # Legacy broadcast to chat_{conversation.id} — ChatConsumer handles 'chat_message'.
        # IMPORTANT: spread payload first, then override 'type' so it is not
        # overwritten by payload's own 'type': 'nuevo_mensaje_chat'.
        async_to_sync(channel_layer.group_send)(
            f'chat_{conversation.id}',
            {
                **payload,
                'type': 'chat_message',  # Must come AFTER **payload to override
            }
        )
        
        serializer = MessageSerializer(message, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        """
        Mark all messages in this conversation as read for the current user
        """
        conversation = self.get_object()
        
        # 1. Mark new system Messages as read
        if conversation.source_channel != 'APP':
            count = conversation.messages.filter(direction='inbound', is_read=False).update(is_read=True)
        else:
            unread = conversation.messages.exclude(sender=request.user).filter(is_read=False)
            count = unread.update(is_read=True)
        
        # 2. 🔄 BACKWARDS COMPATIBILITY: Mark legacy ChatSolicitud as read
        try:
            from mecanimovilapp.apps.ordenes.models import ChatSolicitud, OfertaProveedor
            
            # Determine if this conversation has an associated Oferta
            oferta = None
            if conversation.context_object:
                context_model = conversation.content_type.model_class().__name__
                
                if context_model == 'OfertaProveedor':
                    oferta = conversation.context_object
                elif 'Solicitud' in context_model:
                    # Find related oferta linked to this solicitud
                    oferta = OfertaProveedor.objects.filter(
                        solicitud=conversation.context_object
                    ).first()
            
            if oferta:
                # Update ChatSolicitud records
                # Logic: If I am the provider, I read messages from USER (es_proveedor=False)
                # If I am the user, I read messages from PROVIDER (es_proveedor=True)
                
                # Check directly if user is provider to be safe, though the logic is usually inverse of message sender
                es_proveedor_usuario = hasattr(request.user, 'mecanicodomicilio') or hasattr(request.user, 'taller')
                
                # We want to mark messages SENT BY the OTHER party as read
                # If I am provider (es_proveedor_usuario=True), I read messages where es_proveedor=False
                # If I am user (es_proveedor_usuario=False), I read messages where es_proveedor=True
                
                target_es_proveedor = not es_proveedor_usuario
                
                legacy_updated = ChatSolicitud.objects.filter(
                    oferta=oferta,
                    leido=False,
                    es_proveedor=target_es_proveedor
                ).update(leido=True)
                
                print(f"✅ [CHAT BACKEND] Synced read status to {legacy_updated} ChatSolicitud records")
            else:
                print(f"⚠️ [CHAT BACKEND] No oferta found for read sync")
                
        except Exception as e:
            print(f"⚠️ [CHAT BACKEND] Failed to sync read status to ChatSolicitud: {e}")

        return Response({'marked_read': count})
