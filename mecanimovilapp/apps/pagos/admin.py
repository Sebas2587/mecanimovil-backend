"""
Admin para la app de pagos con Mercado Pago Checkout Pro
"""
from django.contrib import admin
from .models import PreferenciaPago, Pago, WebhookNotificacion


@admin.register(PreferenciaPago)
class PreferenciaPagoAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'preference_id_mp',
        'usuario',
        'carrito',
        'total_amount',
        'currency_id',
        'procesada',
        'fecha_creacion',
    ]
    list_filter = ['procesada', 'currency_id', 'fecha_creacion']
    search_fields = ['preference_id_mp', 'usuario__username', 'usuario__email', 'carrito__id']
    readonly_fields = ['id', 'preference_id_mp', 'init_point', 'sandbox_init_point', 'fecha_creacion', 'fecha_actualizacion']
    
    fieldsets = (
        ('Información Básica', {
            'fields': ('id', 'usuario', 'carrito', 'procesada')
        }),
        ('Información de Mercado Pago', {
            'fields': (
                'preference_id_mp',
                'init_point',
                'sandbox_init_point',
                'total_amount',
                'currency_id',
            )
        }),
        ('Fechas', {
            'fields': ('fecha_creacion', 'fecha_actualizacion')
        }),
    )


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'payment_id_mp',
        'usuario',
        'carrito',
        'transaction_amount',
        'currency_id',
        'status',
        'payment_method_id',
        'fecha_creacion',
        'date_approved_mp',
    ]
    list_filter = ['status', 'payment_method_id', 'payment_type_id', 'currency_id']
    search_fields = [
        'payment_id_mp',
        'usuario__username',
        'usuario__email',
        'payer_email',
        'external_reference',
        'description',
    ]
    readonly_fields = [
        'id',
        'payment_id_mp',
        'status',
        'status_detail',
        'fecha_creacion',
        'fecha_actualizacion',
        'date_created_mp',
        'date_approved_mp',
        'date_last_updated_mp',
    ]
    
    fieldsets = (
        ('Información Básica', {
            'fields': ('id', 'usuario', 'carrito', 'preferencia', 'payment_id_mp', 'status', 'status_detail')
        }),
        ('Información del Pago', {
            'fields': (
                'transaction_amount',
                'currency_id',
                'description',
                'payment_method_id',
                'payment_type_id',
            )
        }),
        ('Información del Pagador', {
            'fields': (
                'payer_email',
                'payer_first_name',
                'payer_last_name',
                'payer_identification_type',
                'payer_identification_number',
            )
        }),
        ('Relaciones', {
            'fields': ('external_reference',)
        }),
        ('URLs y Metadata', {
            'fields': ('receipt_url', 'metadata')
        }),
        ('Fechas', {
            'fields': (
                'fecha_creacion',
                'fecha_actualizacion',
                'date_created_mp',
                'date_approved_mp',
                'date_last_updated_mp',
            )
        }),
    )


@admin.register(WebhookNotificacion)
class WebhookNotificacionAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'payment_id_mp',
        'notification_type',
        'procesado',
        'fecha_procesamiento',
        'fecha_creacion',
    ]
    list_filter = ['notification_type', 'procesado']
    search_fields = ['payment_id_mp', 'notification_type']
    readonly_fields = ['id', 'data', 'fecha_creacion']
    
    fieldsets = (
        ('Información Básica', {
            'fields': ('id', 'payment_id_mp', 'notification_type', 'procesado')
        }),
        ('Datos', {
            'fields': ('data',)
        }),
        ('Procesamiento', {
            'fields': ('fecha_procesamiento', 'error_procesamiento')
        }),
        ('Fechas', {
            'fields': ('fecha_creacion',)
        }),
    )