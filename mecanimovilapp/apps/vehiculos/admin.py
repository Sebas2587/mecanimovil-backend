from django.contrib import admin
from django.utils.html import format_html
from .models import Marca, MarcaVehiculo, Modelo, Vehiculo
from .models_health import (
    ComponenteSalud,
    ReglaMantenimientoGenerica,
    ReglaMantenimientoEspecifica,
    EstadoSaludVehiculo,
    ComponenteSaludVehiculo,
    AlertaMantenimiento
)
from mecanimovilapp.apps.usuarios.models import Cliente

class ModeloInline(admin.TabularInline):
    """
    Inline para mostrar/editar modelos relacionados a una marca
    """
    model = Modelo
    extra = 1
    verbose_name = "Modelo"
    verbose_name_plural = "Modelos"


@admin.register(MarcaVehiculo)
class MarcaVehiculoAdmin(admin.ModelAdmin):
    """
    Administrador para el modelo MarcaVehiculo
    """
    list_display = ('nombre', 'total_modelos')
    search_fields = ('nombre',)
    inlines = [ModeloInline]
    
    def total_modelos(self, obj):
        """
        Muestra el número total de modelos para esta marca
        """
        return obj.modelos.count()
    total_modelos.short_description = 'Total de Modelos'


class VehiculoInline(admin.TabularInline):
    """
    Inline para mostrar los vehículos relacionados a un modelo
    """
    model = Vehiculo
    extra = 0
    fields = ('patente', 'year', 'cliente', 'tipo_motor', 'kilometraje')
    verbose_name = "Vehículo"
    verbose_name_plural = "Vehículos"
    

@admin.register(Modelo)
class ModeloAdmin(admin.ModelAdmin):
    """
    Administrador para el modelo Modelo
    """
    list_display = ('nombre', 'marca', 'total_vehiculos')
    list_filter = ('marca',)
    search_fields = ('nombre', 'marca__nombre')
    inlines = [VehiculoInline]
    
    def total_vehiculos(self, obj):
        """
        Muestra el número total de vehículos para este modelo
        """
        return obj.vehiculos.count()
    total_vehiculos.short_description = 'Total de Vehículos'


class VehiculoClienteInline(admin.TabularInline):
    """
    Inline para añadir a la vista de Cliente
    """
    model = Vehiculo
    extra = 0
    fields = ('patente', 'marca', 'modelo', 'year', 'tipo_motor')
    verbose_name = "Vehículo"
    verbose_name_plural = "Vehículos del Cliente"


# Extendemos el admin de Cliente para mostrar sus vehículos
class ClienteVehiculosAdmin(admin.ModelAdmin):
    inlines = [VehiculoClienteInline]
    list_display = ('__str__', 'total_vehiculos')
    search_fields = ('usuario__username', 'usuario__email', 'usuario__first_name', 'usuario__last_name')
    
    def total_vehiculos(self, obj):
        return obj.vehiculos.count()
    total_vehiculos.short_description = 'Total de Vehículos'

# Solo registramos si no está ya registrado
try:
    admin.site.unregister(Cliente)
    admin.site.register(Cliente, ClienteVehiculosAdmin)
except admin.sites.NotRegistered:
    pass


@admin.register(Vehiculo)
class VehiculoAdmin(admin.ModelAdmin):
    """
    Administrador para el modelo Vehiculo
    """
    list_display = ('patente', 'marca', 'modelo', 'year', 'cliente_nombre', 'tipo_motor', 'mostrar_foto')
    list_filter = ('marca', 'modelo', 'tipo_motor', 'year')
    search_fields = ('patente', 'marca__nombre', 'modelo__nombre', 'cliente__usuario__email', 'cliente__usuario__username')
    readonly_fields = ('fecha_creacion', 'fecha_actualizacion', 'mostrar_foto_detalle')
    autocomplete_fields = ['marca', 'modelo', 'cliente']
    
    fieldsets = (
        ('Información Básica', {
            'fields': ('cliente', 'patente', 'marca', 'modelo')
        }),
        ('Detalles Técnicos', {
            'fields': ('year', 'cilindraje', 'tipo_motor', 'kilometraje')
        }),
        ('Multimedia', {
            'fields': ('foto', 'mostrar_foto_detalle')
        }),
        ('Metadatos', {
            'fields': ('fecha_creacion', 'fecha_actualizacion'),
            'classes': ('collapse',)
        }),
    )
    
    def cliente_nombre(self, obj):
        """
        Muestra el nombre del cliente
        """
        if not obj.cliente:
            return "Sin cliente"
            
        if hasattr(obj.cliente, 'usuario') and obj.cliente.usuario:
            nombre = obj.cliente.usuario.get_full_name() or obj.cliente.usuario.username
            return nombre
        return "Cliente sin nombre"
    cliente_nombre.short_description = 'Cliente'
    
    def mostrar_foto(self, obj):
        """
        Muestra una miniatura de la foto del vehículo en la lista
        """
        if obj.foto:
            return format_html('<img src="{}" width="50" height="auto" />', obj.foto.url)
        return "Sin foto"
    mostrar_foto.short_description = 'Foto'
    
    def mostrar_foto_detalle(self, obj):
        """
        Muestra una imagen más grande en la vista de detalle
        """
        if obj.foto:
            return format_html('<img src="{}" width="300" height="auto" />', obj.foto.url)
        return "Sin foto"
    mostrar_foto_detalle.short_description = 'Vista previa'


@admin.register(ComponenteSalud)
class ComponenteSaludAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'slug', 'es_critico', 'icono', 'orden_visualizacion']
    search_fields = ['nombre', 'slug']
    ordering = ['orden_visualizacion']
    filter_horizontal = ['servicios_asociados']
    fieldsets = (
        (None, {
            'fields': ('nombre', 'slug', 'descripcion', 'es_critico', 'icono', 'orden_visualizacion'),
        }),
        ('Servicios en app (modal salud)', {
            'fields': ('servicios_asociados',),
            'description': 'Al tocar este componente en salud del vehículo, se muestran estos servicios para agendar directo.',
        }),
    )

@admin.register(ReglaMantenimientoGenerica)
class ReglaMantenimientoGenericaAdmin(admin.ModelAdmin):
    list_display = ['componente', 'tipo_motor', 'vida_util_km', 'intervalo_meses', 'beta']
    list_filter = ['tipo_motor']
    search_fields = ['componente__nombre']

@admin.register(ReglaMantenimientoEspecifica)
class ReglaMantenimientoEspecificaAdmin(admin.ModelAdmin):
    list_display = ['componente', 'marca', 'modelo', 'vida_util_km', 'intervalo_meses', 'beta']
    list_filter = ['marca']
    search_fields = ['componente__nombre', 'marca__nombre', 'modelo__nombre']


@admin.register(EstadoSaludVehiculo)
class EstadoSaludVehiculoAdmin(admin.ModelAdmin):
    """
    Administrador para EstadoSaludVehiculo
    """
    list_display = ['vehiculo', 'salud_general_porcentaje', 'kilometraje_snapshot', 'tiene_alertas_activas', 'fecha_calculo']
    list_filter = ['tiene_alertas_activas', 'fecha_calculo']
    search_fields = ['vehiculo__patente', 'vehiculo__marca__nombre']
    readonly_fields = ['fecha_calculo']
    date_hierarchy = 'fecha_calculo'


@admin.register(ComponenteSaludVehiculo)
class ComponenteSaludVehiculoAdmin(admin.ModelAdmin):
    """
    Administrador para ComponenteSaludVehiculo
    """
    list_display = ['vehiculo', 'componente', 'salud_porcentaje', 'nivel_alerta', 'requiere_servicio_inmediato']
    list_filter = ['nivel_alerta', 'requiere_servicio_inmediato']
    search_fields = ['vehiculo__patente', 'componente__nombre']
    
    # actions = ['recalcular_salud']
    # def recalcular_salud(self, request, queryset):
    #     pass


@admin.register(AlertaMantenimiento)
class AlertaMantenimientoAdmin(admin.ModelAdmin):
    """
    Administrador para AlertaMantenimiento
    """
    list_display = ['vehiculo', 'titulo', 'tipo_alerta', 'prioridad', 'activa', 'fecha_creacion']
    list_filter = ['tipo_alerta', 'prioridad', 'activa']
    search_fields = ['vehiculo__patente', 'titulo']
    filter_horizontal = ['servicios_recomendados'] 