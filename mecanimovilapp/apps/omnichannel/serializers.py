from rest_framework import serializers

from mecanimovilapp.apps.omnichannel.models import ExternalContact, ProviderChannelConnection


class ProviderChannelConnectionSerializer(serializers.ModelSerializer):
    channel_display = serializers.CharField(source='get_channel_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    channel_slug = serializers.SerializerMethodField()

    class Meta:
        model = ProviderChannelConnection
        fields = (
            'id',
            'channel',
            'channel_display',
            'channel_slug',
            'enabled',
            'status',
            'status_display',
            'display_name',
            'display_identifier',
            'mensaje_estado',
            'connected_at',
            'updated_at',
        )
        read_only_fields = fields

    def get_channel_slug(self, obj):
        return obj.channel.lower()


class ProviderChannelConnectionToggleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProviderChannelConnection
        fields = ('enabled',)


class ExternalContactMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalContact
        fields = ('id', 'display_name', 'phone', 'channel', 'external_id')
