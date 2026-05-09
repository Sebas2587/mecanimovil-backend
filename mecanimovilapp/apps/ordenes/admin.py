from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.contrib import messages
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import (
    SolicitudServicio, LineaServicio, ConfiguracionPrecio, 
    CarritoAgendamiento, ItemCarritoAgendamiento, AuditAccesoCliente,
    SolicitudServicioPublica, FotoSolicitudPublica, OfertaProveedor, DetalleServicioOferta, ChatSolicitud
)

# ADMIN PARA DISPONIBILIDAD ELIMINADO - REEMPLAZADO POR HorarioProveedor EN USUARIOS APP

class LineaServicioInline(admin.TabularInline):
    """
    Inline para mostrar las líneas de servicio en la solicitud
    """
    model = LineaServicio
    extra = 0
    readonly_fields = ('precio_final',)
    fields = ('oferta_servicio', 'con_repuestos', 'cantidad', 'precio_unitario', 'descuento_porcentaje', 'precio_final')

@admin.register(SolicitudServicio)
class SolicitudServicioAdmin(admin.ModelAdmin):
    """
    Administración para las solicitudes de servicio
    """
    list_display = (
        'id', 'cliente', 'vehiculo_info', 'proveedor_info', 'fecha_servicio', 
        'hora_servicio', 'estado_badge', 'total', 'metodo_pago'
    )
    list_filter = (
        'estado', 'tipo_servicio', 'metodo_pago', 'fecha_servicio', 
        'comprobante_validado', 'fecha_hora_solicitud'
    )
    search_fields = (
        'cliente__nombre', 'cliente__email', 'vehiculo__marca', 'vehiculo__modelo',
        'taller__nombre', 'mecanico__nombre'
    )
    readonly_fields = ('fecha_hora_solicitud', 'fecha_validacion', 'fecha_cancelacion', 'fecha_devolucion')
    date_hierarchy = 'fecha_servicio'
    
    fieldsets = (
        ('Información Básica', {
            'fields': (
                'cliente', 'vehiculo', 'fecha_hora_solicitud', 'ubicacion_servicio'
            )
        }),
        ('Servicio', {
            'fields': (
                'tipo_servicio', 'taller', 'mecanico', 'fecha_servicio', 'hora_servicio'
            )
        }),
        ('Pago', {
            'fields': (
                'metodo_pago', 'total', 'comprobante_pago', 'comprobante_validado', 'fecha_validacion'
            )
        }),
        ('Estado y Gestión', {
            'fields': (
                'estado', 'notas_cliente', 'notas_admin', 'notas_proveedor'
            )
        }),
        ('Cancelación/Devolución', {
            'fields': (
                'motivo_cancelacion', 'fecha_cancelacion', 'fecha_devolucion',
                'fecha_respuesta_proveedor', 'motivo_rechazo'
            ),
            'classes': ('collapse',)
        }),
    )
    
    inlines = [LineaServicioInline]
    
    actions = ['validar_comprobantes_y_enviar_a_proveedor', 'marcar_como_pago_validado', 'enviar_a_proveedor']
    
    def validar_comprobantes_y_enviar_a_proveedor(self, request, queryset):
        """
        Valida comprobantes y envía solicitudes a proveedores para aceptación
        """
        updated = 0
        for solicitud in queryset:
            if solicitud.estado == 'pendiente' and not solicitud.comprobante_validado:
                # Validar comprobante
                solicitud.comprobante_validado = True
                solicitud.fecha_validacion = timezone.now()
                
                # Cambiar estado para que aparezca en app de proveedores
                solicitud.estado = 'pendiente_aceptacion_proveedor'
                solicitud.save()
                updated += 1
        
        if updated:
            self.message_user(
                request,
                f'{updated} comprobante(s) validado(s) y enviado(s) a proveedor(es)',
                messages.SUCCESS
            )
        else:
            self.message_user(
                request,
                'No se pudieron validar las solicitudes seleccionadas (deben estar en estado pendiente)',
                messages.WARNING
            )
    validar_comprobantes_y_enviar_a_proveedor.short_description = "✅ Validar comprobante y enviar a proveedor"
    
    def marcar_como_pago_validado(self, request, queryset):
        """
        Marca el pago como validado sin enviar a proveedor
        """
        updated = 0
        for solicitud in queryset:
            if not solicitud.comprobante_validado:
                solicitud.comprobante_validado = True
                solicitud.fecha_validacion = timezone.now()
                if solicitud.estado == 'pendiente':
                    solicitud.estado = 'pago_validado'
                solicitud.save()
                updated += 1
        
        if updated:
            self.message_user(
                request,
                f'{updated} pago(s) validado(s)',
                messages.SUCCESS
            )
        else:
            self.message_user(
                request,
                'No se pudieron validar los pagos de las solicitudes seleccionadas',
                messages.WARNING
            )
    marcar_como_pago_validado.short_description = "💰 Validar solo el pago"
    
    def enviar_a_proveedor(self, request, queryset):
        """
        Envía solicitudes con pago validado a proveedores
        """
        updated = 0
        for solicitud in queryset:
            if solicitud.estado == 'pago_validado' and solicitud.comprobante_validado:
                solicitud.estado = 'pendiente_aceptacion_proveedor'
                solicitud.save()
                updated += 1
        
        if updated:
            self.message_user(
                request,
                f'{updated} solicitud(es) enviada(s) a proveedor(es)',
                messages.SUCCESS
            )
        else:
            self.message_user(
                request,
                'No se pudieron enviar las solicitudes (deben tener pago validado)',
                messages.WARNING
            )
    enviar_a_proveedor.short_description = "📤 Enviar a proveedor"
    
    def vehiculo_info(self, obj):
        if obj.vehiculo:
            return f"{obj.vehiculo.marca} {obj.vehiculo.modelo} ({obj.vehiculo.year})"
        return "Sin vehículo"
    vehiculo_info.short_description = "Vehículo"
    
    def proveedor_info(self, obj):
        if obj.taller:
            return f"🏢 {obj.taller.nombre}"
        elif obj.mecanico:
            return f"🔧 {obj.mecanico.nombre}"
        return "Sin proveedor"
    proveedor_info.short_description = "Proveedor"
    
    def estado_badge(self, obj):
        color_map = {
            'pendiente': '#ffc107',
            'pago_validado': '#17a2b8',
            'confirmado': '#007bff',
            'en_proceso': '#fd7e14',
            'completado': '#28a745',
            'cancelado': '#dc3545',
            'solicitud_cancelacion': '#6f42c1',
            'pendiente_devolucion': '#e83e8c',
            'devuelto': '#6c757d',
        }
        color = color_map.get(obj.estado, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px;">{}</span>',
            color, obj.get_estado_display()
        )
    estado_badge.short_description = "Estado"

@admin.register(LineaServicio)
class LineaServicioAdmin(admin.ModelAdmin):
    """
    Administración para las líneas de servicio
    """
    list_display = (
        'id', 'solicitud', 'servicio_info', 'con_repuestos', 
        'cantidad', 'precio_unitario', 'precio_final'
    )
    list_filter = ('con_repuestos', 'solicitud__estado')
    search_fields = (
        'solicitud__id', 'oferta_servicio__servicio__nombre', 
        'solicitud__cliente__nombre'
    )
    readonly_fields = ('precio_final',)
    
    def servicio_info(self, obj):
        return f"{obj.oferta_servicio.servicio.nombre} ({obj.oferta_servicio.proveedor_nombre})"
    servicio_info.short_description = "Servicio"

@admin.register(ConfiguracionPrecio)
class ConfiguracionPrecioAdmin(admin.ModelAdmin):
    """
    Administración para la configuración de precios
    """
    list_display = (
        'id', 'iva_porcentaje', 'tarifa_servicio_porcentaje', 
        'activo_badge', 'fecha_creacion'
    )
    list_filter = ('activo', 'fecha_creacion')
    readonly_fields = ('fecha_creacion',)
    
    fieldsets = (
        ('Configuración de Precios', {
            'fields': (
                'iva_porcentaje', 'tarifa_servicio_porcentaje', 'activo'
            )
        }),
        ('Información del Sistema', {
            'fields': ('fecha_creacion',),
            'classes': ('collapse',)
        }),
    )
    
    def activo_badge(self, obj):
        if obj.activo:
            return format_html(
                '<span style="background-color: #28a745; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px;">✓ ACTIVO</span>'
            )
        return format_html(
            '<span style="background-color: #6c757d; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px;">INACTIVO</span>'
        )
    activo_badge.short_description = "Estado"

class ItemCarritoInline(admin.TabularInline):
    """
    Inline para mostrar los items del carrito
    """
    model = ItemCarritoAgendamiento
    extra = 0
    readonly_fields = ('precio_estimado', 'fecha_agregado')
    fields = (
        'oferta_servicio', 'con_repuestos', 'cantidad', 
        'fecha_servicio', 'hora_servicio', 'precio_estimado', 'fecha_agregado'
    )

@admin.register(CarritoAgendamiento)
class CarritoAgendamientoAdmin(admin.ModelAdmin):
    """
    Administración para los carritos de agendamiento
    """
    list_display = (
        'id', 'cliente', 'vehiculo_info', 'cantidad_items', 
        'total', 'activo_badge', 'fecha_creacion'
    )
    list_filter = ('activo', 'fecha_creacion', 'fecha_actualizacion')
    search_fields = ('cliente__nombre', 'vehiculo__marca', 'vehiculo__modelo')
    readonly_fields = ('fecha_creacion', 'fecha_actualizacion', 'total', 'cantidad_items')
    date_hierarchy = 'fecha_creacion'
    
    fieldsets = (
        ('Información del Carrito', {
            'fields': ('cliente', 'vehiculo', 'activo')
        }),
        ('Programación', {
            'fields': ('fecha_programada', 'hora_programada', 'notas')
        }),
        ('Información del Sistema', {
            'fields': ('fecha_creacion', 'fecha_actualizacion', 'total', 'cantidad_items'),
            'classes': ('collapse',)
        }),
    )
    
    inlines = [ItemCarritoInline]
    
    def vehiculo_info(self, obj):
        if obj.vehiculo:
            return f"{obj.vehiculo.marca} {obj.vehiculo.modelo}"
        return "Sin vehículo"
    vehiculo_info.short_description = "Vehículo"
    
    def activo_badge(self, obj):
        if obj.activo:
            return format_html(
                '<span style="background-color: #28a745; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px;">✓ ACTIVO</span>'
            )
        return format_html(
            '<span style="background-color: #dc3545; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px;">INACTIVO</span>'
        )
    activo_badge.short_description = "Estado"

@admin.register(ItemCarritoAgendamiento)
class ItemCarritoAgendamientoAdmin(admin.ModelAdmin):
    """
    Administración para los items del carrito
    """
    list_display = (
        'id', 'carrito', 'servicio_info', 'con_repuestos', 
        'cantidad', 'fecha_servicio', 'hora_servicio', 'precio_estimado'
    )
    list_filter = ('con_repuestos', 'fecha_servicio', 'fecha_agregado')
    search_fields = (
        'carrito__cliente__nombre', 'oferta_servicio__servicio__nombre'
    )
    readonly_fields = ('precio_estimado', 'fecha_agregado')
    date_hierarchy = 'fecha_agregado'
    
    def servicio_info(self, obj):
        return f"{obj.oferta_servicio.servicio.nombre}"
    servicio_info.short_description = "Servicio"

@admin.register(AuditAccesoCliente)
class AuditAccesoClienteAdmin(admin.ModelAdmin):
    """
    Admin para auditoría de accesos a información de clientes
    """
    list_display = [
        'fecha_acceso', 'usuario_proveedor', 'solicitud_servicio', 
        'tipo_acceso', 'nivel_informacion', 'acceso_autorizado',
        'requiere_revision', 'estado_orden_acceso'
    ]
    list_filter = [
        'tipo_acceso', 'nivel_informacion', 'acceso_autorizado', 
        'requiere_revision', 'estado_orden_acceso', 'fecha_acceso'
    ]
    search_fields = [
        'usuario_proveedor__username', 'usuario_proveedor__email',
        'solicitud_servicio__id', 'ip_address', 'justificacion'
    ]
    readonly_fields = [
        'fecha_acceso', 'ip_address', 'user_agent', 'datos_accedidos_json',
        'justificacion', 'link_solicitud', 'link_usuario'
    ]
    ordering = ['-fecha_acceso']
    date_hierarchy = 'fecha_acceso'
    
    fieldsets = (
        ('Información del Acceso', {
            'fields': (
                'fecha_acceso', 'tipo_acceso', 'nivel_informacion',
                'link_solicitud', 'link_usuario'
            )
        }),
        ('Contexto Técnico', {
            'fields': (
                'ip_address', 'user_agent', 'estado_orden_acceso'
            ),
            'classes': ['collapse']
        }),
        ('Datos y Justificación', {
            'fields': (
                'datos_accedidos_json', 'justificacion'
            ),
            'classes': ['collapse']
        }),
        ('Flags de Seguridad', {
            'fields': (
                'acceso_autorizado', 'requiere_revision'
            ),
            'classes': ['wide']
        }),
    )
    
    def datos_accedidos_json(self, obj):
        """Muestra los datos accedidos en formato JSON legible"""
        import json
        if obj.datos_accedidos:
            try:
                formatted = json.dumps(obj.datos_accedidos, indent=2, ensure_ascii=False)
                return format_html('<pre style="max-width: 400px; overflow: auto;">{}</pre>', formatted)
            except:
                return str(obj.datos_accedidos)
        return '-'
    datos_accedidos_json.short_description = 'Datos Accedidos'
    
    def link_solicitud(self, obj):
        """Link a la solicitud de servicio"""
        if obj.solicitud_servicio:
            url = reverse('admin:ordenes_solicitudservicio_change', args=[obj.solicitud_servicio.id])
            return format_html('<a href="{}" target="_blank">Orden #{}</a>', url, obj.solicitud_servicio.id)
        return '-'
    link_solicitud.short_description = 'Solicitud'
    
    def link_usuario(self, obj):
        """Link al usuario proveedor"""
        if obj.usuario_proveedor:
            url = reverse('admin:usuarios_usuario_change', args=[obj.usuario_proveedor.id])
            return format_html('<a href="{}" target="_blank">{}</a>', url, obj.usuario_proveedor.username)
        return '-'
    link_usuario.short_description = 'Usuario'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'solicitud_servicio', 'usuario_proveedor'
        )
    
    # Configurar colores para diferentes niveles de acceso
    def nivel_informacion(self, obj):
        colors = {
            'completo': '#28a745',
            'parcial': '#ffc107', 
            'restringido': '#dc3545'
        }
        color = colors.get(obj.nivel_informacion, '#6c757d')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_nivel_informacion_display()
        )
    nivel_informacion.short_description = 'Nivel Información'
    
    def acceso_autorizado(self, obj):
        if obj.acceso_autorizado:
            return format_html('<span style="color: #28a745;">✓ Autorizado</span>')
        else:
            return format_html('<span style="color: #dc3545;">✗ No Autorizado</span>')
    acceso_autorizado.short_description = 'Autorizado'
    
    def requiere_revision(self, obj):
        if obj.requiere_revision:
            return format_html('<span style="color: #dc3545; font-weight: bold;">⚠ Requiere Revisión</span>')
        else:
            return format_html('<span style="color: #28a745;">✓ Normal</span>')
    requiere_revision.short_description = 'Revisión'
    
    # Acciones del admin
    actions = ['marcar_como_revisado', 'marcar_como_sospechoso']
    
    def marcar_como_revisado(self, request, queryset):
        """Marcar accesos como revisados"""
        count = queryset.update(requiere_revision=False)
        self.message_user(request, f'{count} accesos marcados como revisados.')
    marcar_como_revisado.short_description = 'Marcar como revisados'
    
    def marcar_como_sospechoso(self, request, queryset):
        """Marcar accesos como sospechosos"""
        count = queryset.update(requiere_revision=True, acceso_autorizado=False)
        self.message_user(request, f'{count} accesos marcados como sospechosos.')
    marcar_como_sospechoso.short_description = 'Marcar como sospechosos'


# ============================================================================
# ADMIN PARA SISTEMA DE POSTULACIONES
# ============================================================================

class DetalleServicioOfertaInline(admin.TabularInline):
    """Inline para mostrar detalles de servicios en ofertas"""
    model = DetalleServicioOferta
    extra = 0
    fields = ('servicio', 'precio_servicio', 'tiempo_estimado', 'notas')

class ChatSolicitudInline(admin.TabularInline):
    """Inline para mostrar mensajes de chat en ofertas"""
    model = ChatSolicitud
    extra = 0
    readonly_fields = ('fecha_envio', 'leido', 'fecha_lectura')
    fields = ('enviado_por', 'mensaje', 'es_proveedor', 'fecha_envio', 'leido', 'fecha_lectura')


class FotoSolicitudPublicaInline(admin.TabularInline):
    """Fotos de la necesidad (cliente) en solicitud pública"""
    model = FotoSolicitudPublica
    extra = 0
    fields = ('orden', 'imagen', 'fecha_subida')
    readonly_fields = ('fecha_subida',)


@admin.register(SolicitudServicioPublica)
class SolicitudServicioPublicaAdmin(admin.ModelAdmin):
    """Administración para solicitudes públicas de servicios"""
    list_display = (
        'id', 'cliente', 'vehiculo_info', 'tipo_solicitud', 
        'estado_badge', 'total_ofertas', 'fecha_creacion', 'fecha_expiracion'
    )
    list_filter = (
        'estado', 'tipo_solicitud', 'urgencia', 'fecha_creacion', 
        'fecha_expiracion', 'fecha_publicacion'
    )
    search_fields = (
        'id', 'cliente__nombre', 'cliente__email', 
        'vehiculo__marca', 'vehiculo__modelo', 'descripcion_problema',
        'direccion_servicio_texto'
    )
    readonly_fields = (
        'fecha_creacion', 'fecha_publicacion', 'fecha_actualizacion',
        'total_ofertas', 'total_visualizaciones', 'tiempo_restante'
    )
    date_hierarchy = 'fecha_creacion'
    filter_horizontal = ('servicios_solicitados', 'proveedores_dirigidos')
    inlines = (FotoSolicitudPublicaInline,)

    fieldsets = (
        ('Información Básica', {
            'fields': (
                'cliente', 'vehiculo', 'descripcion_problema', 'urgencia'
            )
        }),
        ('Tipo de Solicitud', {
            'fields': (
                'tipo_solicitud', 'proveedores_dirigidos'
            )
        }),
        ('Servicios', {
            'fields': ('servicios_solicitados',)
        }),
        ('Ubicación', {
            'fields': (
                'direccion_usuario', 'direccion_servicio_texto', 
                'detalles_ubicacion', 'ubicacion_servicio'
            )
        }),
        ('Fechas', {
            'fields': (
                'fecha_preferida', 'hora_preferida', 'fecha_expiracion'
            )
        }),
        ('Estado y Métricas', {
            'fields': (
                'estado', 'fecha_creacion', 'fecha_publicacion',
                'total_ofertas', 'total_visualizaciones', 'tiempo_restante',
                'oferta_seleccionada'
            )
        }),
    )
    
    def vehiculo_info(self, obj):
        if obj.vehiculo:
            return f"{obj.vehiculo.marca} {obj.vehiculo.modelo} ({obj.vehiculo.year})"
        return "Sin vehículo"
    vehiculo_info.short_description = "Vehículo"
    
    def estado_badge(self, obj):
        color_map = {
            'creada': '#6c757d',
            'seleccionando_servicios': '#17a2b8',
            'publicada': '#007bff',
            'con_ofertas': '#ffc107',
            'adjudicada': '#28a745',
            'expirada': '#dc3545',
            'cancelada': '#dc3545',
        }
        color = color_map.get(obj.estado, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px;">{}</span>',
            color, obj.get_estado_display()
        )
    estado_badge.short_description = "Estado"
    
    def tiempo_restante(self, obj):
        return obj.tiempo_restante
    tiempo_restante.short_description = "Tiempo Restante"

@admin.register(OfertaProveedor)
class OfertaProveedorAdmin(admin.ModelAdmin):
    """Administración para ofertas de proveedores"""
    list_display = (
        'id', 'solicitud', 'proveedor', 'tipo_proveedor',
        'precio_total_ofrecido', 'estado_badge', 'fecha_envio'
    )
    list_filter = (
        'estado', 'tipo_proveedor', 'incluye_repuestos', 
        'fecha_envio', 'fecha_disponible'
    )
    search_fields = (
        'id', 'solicitud__id', 'proveedor__username', 
        'proveedor__email', 'descripcion_oferta'
    )
    readonly_fields = (
        'fecha_envio', 'fecha_visualizacion_cliente', 
        'fecha_respuesta_cliente', 'tiempo_respuesta_proveedor'
    )
    date_hierarchy = 'fecha_envio'
    
    fieldsets = (
        ('Información Básica', {
            'fields': (
                'solicitud', 'proveedor', 'tipo_proveedor'
            )
        }),
        ('Oferta', {
            'fields': (
                'precio_total_ofrecido', 'incluye_repuestos',
                'tiempo_estimado_total', 'descripcion_oferta', 'garantia_ofrecida'
            )
        }),
        ('Disponibilidad', {
            'fields': (
                'fecha_disponible', 'hora_disponible',
                'es_fecha_alternativa', 'motivo_fecha_alternativa'
            )
        }),
        ('Estado y Timestamps', {
            'fields': (
                'estado', 'fecha_envio', 'fecha_visualizacion_cliente',
                'fecha_respuesta_cliente', 'tiempo_respuesta_proveedor'
            )
        }),
    )
    
    inlines = [DetalleServicioOfertaInline, ChatSolicitudInline]
    
    def estado_badge(self, obj):
        color_map = {
            'enviada': '#17a2b8',
            'vista': '#007bff',
            'en_chat': '#ffc107',
            'aceptada': '#28a745',
            'rechazada': '#dc3545',
            'retirada': '#6c757d',
            'expirada': '#dc3545',
        }
        color = color_map.get(obj.estado, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px;">{}</span>',
            color, obj.get_estado_display()
        )
    estado_badge.short_description = "Estado"

@admin.register(DetalleServicioOferta)
class DetalleServicioOfertaAdmin(admin.ModelAdmin):
    """Administración para detalles de servicios en ofertas"""
    list_display = (
        'id', 'oferta', 'servicio', 'precio_servicio', 
        'tiempo_estimado'
    )
    list_filter = ('oferta__estado', 'oferta__tipo_proveedor')
    search_fields = (
        'oferta__id', 'servicio__nombre', 'oferta__proveedor__username'
    )

@admin.register(ChatSolicitud)
class ChatSolicitudAdmin(admin.ModelAdmin):
    """Administración para mensajes de chat"""
    list_display = (
        'id', 'oferta', 'enviado_por', 'es_proveedor_badge',
        'mensaje_preview', 'leido_badge', 'fecha_envio'
    )
    list_filter = (
        'es_proveedor', 'leido', 'fecha_envio', 'oferta__estado'
    )
    search_fields = (
        'id', 'oferta__id', 'enviado_por__username',
        'mensaje', 'oferta__solicitud__id'
    )
    readonly_fields = ('fecha_envio', 'fecha_lectura', 'es_proveedor')
    date_hierarchy = 'fecha_envio'
    
    fieldsets = (
        ('Información Básica', {
            'fields': (
                'oferta', 'enviado_por', 'es_proveedor'
            )
        }),
        ('Mensaje', {
            'fields': (
                'mensaje', 'archivo_adjunto'
            )
        }),
        ('Estado', {
            'fields': (
                'leido', 'fecha_envio', 'fecha_lectura'
            )
        }),
    )
    
    def es_proveedor_badge(self, obj):
        if obj.es_proveedor:
            return format_html(
                '<span style="background-color: #007bff; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px;">PROVEEDOR</span>'
            )
        return format_html(
            '<span style="background-color: #28a745; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px;">CLIENTE</span>'
        )
    es_proveedor_badge.short_description = "Tipo"
    
    def mensaje_preview(self, obj):
        preview = obj.mensaje[:50] + '...' if len(obj.mensaje) > 50 else obj.mensaje
        return preview
    mensaje_preview.short_description = "Mensaje"
    
    def leido_badge(self, obj):
        if obj.leido:
            return format_html(
                '<span style="background-color: #28a745; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px;">✓ LEÍDO</span>'
            )
        return format_html(
            '<span style="background-color: #ffc107; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px;">NO LEÍDO</span>'
        )
    leido_badge.short_description = "Leído" 