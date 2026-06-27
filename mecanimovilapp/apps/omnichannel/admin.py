from django.contrib import admin

from .models import ExternalContact, ProviderChannelConnection


@admin.register(ProviderChannelConnection)
class ProviderChannelConnectionAdmin(admin.ModelAdmin):
    list_display = ('channel', 'usuario', 'status', 'enabled', 'display_identifier', 'updated_at')
    list_filter = ('channel', 'status', 'enabled')
    search_fields = ('usuario__email', 'display_name', 'phone_number_id', 'page_id')
    readonly_fields = ('created_at', 'updated_at', 'connected_at', 'disconnected_at')


@admin.register(ExternalContact)
class ExternalContactAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'channel', 'external_id', 'phone', 'connection')
    list_filter = ('channel',)
    search_fields = ('display_name', 'external_id', 'phone')
