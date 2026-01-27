from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import Conversation, Message
from .serializers import ConversationSerializer, MessageSerializer

class ConversationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet to list and retrieve conversations for the current user.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ConversationSerializer

    def get_queryset(self):
        # Return conversations where the user is a participant
        return Conversation.objects.filter(participants=self.request.user).distinct().order_by('-updated_at')

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

    @action(detail=True, methods=['get'])
    def messages(self, request, pk=None):
        """
        Retrieve messages for a specific conversation.
        Paginated by default from settings.
        """
        conversation = self.get_object()
        messages = conversation.messages.all().order_by('-timestamp') # Latest first for chat UI often
        
        page = self.paginate_queryset(messages)
        if page is not None:
            serializer = MessageSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
            
        serializer = MessageSerializer(messages, many=True)
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
            attachment=attachment
        )
        
        # Update conversation timestamp
        conversation.save()  # Triggers auto_now on updated_at
        
        serializer = MessageSerializer(message, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        """
        Mark all messages in this conversation as read for the current user
        """
        conversation = self.get_object()
        # Mark messages NOT sent by me as read
        unread = conversation.messages.exclude(sender=request.user).filter(is_read=False)
        count = unread.update(is_read=True)
        return Response({'marked_read': count})
