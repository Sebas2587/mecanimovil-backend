from rest_framework import serializers
from .models import Conversation, Message
from django.contrib.auth import get_user_model
from mecanimovilapp.storage.utils import get_cpanel_file_url

from mecanimovilapp.apps.omnichannel.serializers import ExternalContactMiniSerializer
from mecanimovilapp.apps.omnichannel.utils import channel_to_api_slug

User = get_user_model()

class UserMiniSerializer(serializers.ModelSerializer):
    """
    Minimal user info for chat headers
    """
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'first_name', 'last_name', 'email', 'username', 'foto_perfil', 'full_name')

    def get_full_name(self, obj):
        # Try Taller
        if hasattr(obj, 'taller') and obj.taller:
            return obj.taller.nombre
        # Try Mecanico
        if hasattr(obj, 'mecanico_domicilio') and obj.mecanico_domicilio:
            return obj.mecanico_domicilio.nombre
        # Try Cliente
        if hasattr(obj, 'cliente') and obj.cliente:
            return f"{obj.cliente.nombre} {obj.cliente.apellido}".strip()
        
        # Fallback to User
        full_name = f"{obj.first_name} {obj.last_name}".strip()
        return full_name if full_name else obj.username

class MessageSerializer(serializers.ModelSerializer):
    sender_id = serializers.SerializerMethodField()
    sender_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Message
        fields = (
            'id', 'conversation', 'sender_id', 'sender_name', 'content', 'attachment',
            'timestamp', 'is_read', 'direction', 'external_message_id',
        )
        read_only_fields = ('conversation', 'timestamp', 'is_read')

    def get_sender_id(self, obj):
        return obj.sender_id

    def get_sender_name(self, obj):
        if obj.sender:
            return f"{obj.sender.first_name} {obj.sender.last_name}".strip() or obj.sender.username
        if obj.direction == 'inbound' and obj.conversation.external_contact:
            return obj.conversation.external_contact.display_name
        return 'Contacto'

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        if instance.attachment:
            url = get_cpanel_file_url(instance.attachment, request)
            data['attachment'] = url
            data['archivo_adjunto'] = url
        else:
            data['archivo_adjunto'] = None
        data['es_propio'] = False
        req_user = getattr(request, 'user', None) if request else None
        if req_user and req_user.is_authenticated and instance.sender_id == req_user.id:
            data['es_propio'] = True
        elif instance.direction == 'outbound' and req_user and instance.sender_id == req_user.id:
            data['es_propio'] = True
        return data

class ConversationSerializer(serializers.ModelSerializer):
    last_message = serializers.SerializerMethodField()
    other_participant = serializers.SerializerMethodField()
    external_contact = ExternalContactMiniSerializer(read_only=True)
    context_info = serializers.SerializerMethodField()
    context_id = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    channel = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = (
            'id', 'type', 'source_channel', 'channel', 'last_message', 'other_participant',
            'external_contact', 'context_info', 'context_id', 'updated_at', 'unread_count',
        )

    def get_channel(self, obj):
        return channel_to_api_slug(obj.source_channel)

    def get_context_id(self, obj):
        """Return the ID of the context object (Oferta, Solicitud, etc.)"""
        if obj.context_object:
            return str(obj.context_object.id)
        return None

    def get_last_message(self, obj):
        last_msg = obj.messages.order_by('-timestamp').first()
        if last_msg:
            return MessageSerializer(last_msg).data
        return None

    def get_other_participant(self, obj):
        request = self.context.get('request')
        if not request or not request.user:
            return None
            
        other_user = obj.participants.exclude(id=request.user.id).first()
        if other_user:
            return UserMiniSerializer(other_user).data
        return None

    def get_context_info(self, obj):
        """
        Returns details about the linked Service or Vehicle
        """
        if not obj.context_object:
            return None
        
        context = obj.context_object
        
        # Determine based on model class name
        model_name = context._meta.model_name
        
        info = {
            'id': str(context.id),
            'type': model_name,
            'title': 'Desconocido',
            'subtitle': ''
        }
        
        if 'solicitud' in model_name.lower():
            try:
                # Extract vehicle info directly from FK
                if hasattr(context, 'vehiculo') and context.vehiculo:
                    vehiculo = context.vehiculo
                    marca = vehiculo.marca.nombre if hasattr(vehiculo.marca, 'nombre') else vehiculo.marca
                    info['title'] = f"{marca} {vehiculo.modelo} • {vehiculo.patente}".strip()
                elif hasattr(context, 'vehiculo_info') and context.vehiculo_info:
                     # Fallback to vehiculo_info JSON/property if exists (some models might use it)
                     v = context.vehiculo_info
                     info['title'] = f"{v.get('marca', '')} {v.get('modelo', '')}".strip()
                else:
                    info['title'] = f"Solicitud #{context.id}"
                
                # Extract services info
                # Extract services info
                # SolicitudServicioPublica uses 'servicios_solicitados' (ManyToMany)
                servicios_names = []
                if hasattr(context, 'servicios_solicitados') and context.servicios_solicitados.exists():
                     servicios_names = [s.nombre for s in context.servicios_solicitados.all()]
                
                if servicios_names:
                    info['subtitle'] = ', '.join(servicios_names)
                else:
                    info['subtitle'] = 'Sin servicios especificados'
                    
            except Exception as e:
                print(f"Error getting context info: {e}")
                info['title'] = f"Solicitud #{context.id}"
        
        elif model_name == 'vehiculo':
            try:
                info['title'] = f"{context.marca_nombre} {context.modelo_nombre}"
                info['subtitle'] = f"Año {context.year}"
            except:
                pass
                
        elif 'ofertavehiculo' in model_name.lower():
            try:
                # Extract Info from Offer -> Vehicle
                vehiculo = context.vehiculo
                info['id'] = str(vehiculo.id) # Override ID to be Vehicle ID for navigation
                info['type'] = 'vehiculo' # Frontend expects 'vehiculo' to nav to Marketplace Detail
                
                marca = vehiculo.marca_nombre or vehiculo.marca
                modelo = vehiculo.modelo_nombre or vehiculo.modelo
                info['title'] = f"{marca} {modelo} • {vehiculo.year}"
                
                # Show offer amount as subtitle
                info['subtitle'] = f"Oferta: ${context.monto:,.0f}".replace(",", ".")
            except Exception as e:
                print(f"Error getting offer context info: {e}")
                info['title'] = "Oferta de Vehículo"
                
        return info

    def get_unread_count(self, obj):
        request = self.context.get('request')
        if not request or not request.user:
            return 0
        
        if obj.source_channel != 'APP':
            return obj.messages.filter(direction='inbound', is_read=False).count()
        return obj.messages.exclude(sender=request.user).filter(is_read=False).count()
