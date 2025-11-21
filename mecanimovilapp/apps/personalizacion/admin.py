from django.contrib import admin
from .models import VehiculoActivo, PerfilVehiculo, RecomendacionPersonalizada, ConfiguracionPersonalizacion


@admin.register(VehiculoActivo)
class VehiculoActivoAdmin(admin.ModelAdmin):
    list_display = ('cliente', 'vehiculo', 'fecha_seleccion')
    list_filter = ('fecha_seleccion',)
    search_fields = ('cliente__usuario__email', 'vehiculo__patente', 'vehiculo__marca_nombre')
    readonly_fields = ('fecha_seleccion',)


@admin.register(PerfilVehiculo)
class PerfilVehiculoAdmin(admin.ModelAdmin):
    list_display = ('vehiculo', 'servicios_realizados', 'gasto_promedio_mensual', 'score_mantenimiento_urgente', 'fecha_actualizacion')
    list_filter = ('fecha_actualizacion', 'fecha_calculo')
    search_fields = ('vehiculo__patente', 'vehiculo__marca_nombre', 'vehiculo__modelo_nombre')
    readonly_fields = ('fecha_actualizacion', 'fecha_calculo')
    
    fieldsets = (
        ('Información del Vehículo', {
            'fields': ('vehiculo',)
        }),
        ('Métricas de Uso', {
            'fields': ('servicios_realizados', 'gasto_promedio_mensual', 'frecuencia_mantenimiento')
        }),
        ('Preferencias', {
            'fields': ('categorias_frecuentes', 'talleres_frecuentes', 'mecanicos_frecuentes')
        }),
        ('Mantenimiento Predictivo', {
            'fields': ('km_ultimo_servicio', 'dias_ultimo_servicio', 'score_mantenimiento_urgente')
        }),
        ('Timestamps', {
            'fields': ('fecha_actualizacion', 'fecha_calculo'),
            'classes': ('collapse',)
        }),
    )


@admin.register(RecomendacionPersonalizada)
class RecomendacionPersonalizadaAdmin(admin.ModelAdmin):
    list_display = ('cliente', 'vehiculo', 'tipo', 'score_relevancia', 'activa', 'fecha_generacion', 'ctr')
    list_filter = ('tipo', 'activa', 'fecha_generacion', 'fecha_expiracion')
    search_fields = ('cliente__usuario__email', 'vehiculo__patente', 'servicio__nombre')
    readonly_fields = ('fecha_generacion', 'ctr')
    
    fieldsets = (
        ('Información Básica', {
            'fields': ('cliente', 'vehiculo', 'tipo')
        }),
        ('Contenido de la Recomendación', {
            'fields': ('servicio', 'oferta_servicio', 'score_relevancia', 'razon_recomendacion')
        }),
        ('Control de Vigencia', {
            'fields': ('fecha_generacion', 'fecha_expiracion', 'activa')
        }),
        ('Métricas de Interacción', {
            'fields': ('veces_mostrada', 'veces_clickeada', 'convertida', 'ctr'),
            'classes': ('collapse',)
        }),
    )


@admin.register(ConfiguracionPersonalizacion)
class ConfiguracionPersonalizacionAdmin(admin.ModelAdmin):
    list_display = ('clave', 'valor', 'fecha_actualizacion')
    list_filter = ('fecha_actualizacion',)
    search_fields = ('clave', 'valor', 'descripcion')
    readonly_fields = ('fecha_actualizacion',) 