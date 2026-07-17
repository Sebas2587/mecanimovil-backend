from django.contrib import admin
from django import forms
from django.shortcuts import render, redirect
from django.contrib import messages
from django.urls import path, reverse
from django.utils.html import format_html
from django.http import HttpResponseRedirect
from .models import (
    CategoriaServicio, Servicio, DetalleServicio, OfertaServicio,
    Repuesto, ServicioRepuesto, SolicitudRepuesto,
    TIPOS_MOTOR_COMPATIBLES_VALIDOS,
)

TIPOS_MOTOR_CHOICES = [(t, t.title()) for t in TIPOS_MOTOR_COMPATIBLES_VALIDOS]


class TiposMotorCompatiblesFormMixin:
    """Reemplaza el JSON tipos_motor_compatibles por checkboxes en admin."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        initial = []
        if getattr(self, 'instance', None) and self.instance.pk:
            initial = self.instance.tipos_motor_compatibles or []
        self.fields['tipos_motor_compatibles'] = forms.MultipleChoiceField(
            choices=TIPOS_MOTOR_CHOICES,
            required=False,
            widget=forms.CheckboxSelectMultiple,
            label='Tipos de motor compatibles',
            help_text='Vacío = aplica a todos los tipos de motor (Gasolina, Diésel, etc.).',
            initial=initial,
        )

    def clean_tipos_motor_compatibles(self):
        raw = self.cleaned_data.get('tipos_motor_compatibles')
        return list(raw) if raw else []


class ServicioAdminForm(TiposMotorCompatiblesFormMixin, forms.ModelForm):
    class Meta:
        model = Servicio
        fields = '__all__'


class RepuestoAdminForm(TiposMotorCompatiblesFormMixin, forms.ModelForm):
    class Meta:
        model = Repuesto
        fields = '__all__'

# Inline para modelos relacionados
class DetalleServicioInline(admin.TabularInline):
    model = DetalleServicio
    extra = 1

class OfertaServicioInline(admin.TabularInline):
    model = OfertaServicio
    extra = 1
    fields = (
        'tipo_proveedor', 'taller', 'mecanico', 'tipo_motor',
        'disponible', 'precio_con_repuestos', 'precio_sin_repuestos',
    )

class ServicioRepuestoInline(admin.TabularInline):
    model = ServicioRepuesto
    extra = 3  # Aumentar número de líneas vacías por defecto
    fields = ('repuesto', 'cantidad_estimada', 'es_opcional', 'notas')
    autocomplete_fields = ['repuesto']  # Autocompletado para buscar repuestos más fácil
    
    # Nota: Se removieron referencias a archivos CSS/JS que no existen
    # para evitar errores en producción con ManifestStaticFilesStorage
    # class Media:
    #     css = {
    #         'all': ('admin/css/servicio_repuesto_inline.css',)
    #     }
    #     js = ('admin/js/servicio_repuesto_inline.js',)

@admin.register(CategoriaServicio)
class CategoriaServicioAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'categoria_padre', 'icono', 'tiene_imagen', 'orden')
    list_filter = ('categoria_padre',)
    search_fields = ('nombre', 'descripcion', 'icono')
    list_editable = ('orden',)
    fieldsets = (
        (None, {
            'fields': ('nombre', 'descripcion', 'categoria_padre', 'orden'),
        }),
        ('Iconografía', {
            'fields': ('imagen', 'icono'),
            'description': (
                'Sube un PNG/WebP cuadrado con fondo transparente. '
                'El dibujo debe ocupar casi todo el lienzo (poco padding); '
                'si queda muy centrado y chico, se verá pequeño en el home. '
                'El campo icono es fallback Lucide si no hay imagen.'
            ),
        }),
    )

    @admin.display(boolean=True, description='Imagen')
    def tiene_imagen(self, obj):
        return bool(obj.imagen)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # list/principales usan cache_page 24h — invalidar para ver imagen al instante
        try:
            from django.core.cache import cache
            cache.clear()
        except Exception:
            pass

@admin.register(Servicio)
class ServicioAdmin(admin.ModelAdmin):
    form = ServicioAdminForm
    list_display = ('id', 'nombre', 'duracion_estimada_base', 'calificacion_promedio', 'precio_referencia', 'cantidad_repuestos', 'tipos_motor_resumen')
    list_filter = ('categorias', 'requiere_repuestos')
    search_fields = ('nombre', 'descripcion')
    filter_horizontal = ('categorias', 'marcas_compatibles', 'modelos_compatibles', 'servicios_relacionados')
    inlines = [
        DetalleServicioInline,
        OfertaServicioInline,
        ServicioRepuestoInline,
    ]
    fieldsets = (
        ('Información Básica', {
            'fields': ('nombre', 'descripcion', 'duracion_estimada_base', 'foto')
        }),
        ('Precios', {
            'fields': ('requiere_repuestos', 'precio_referencia', 'calificacion_promedio')
        }),
        ('Relaciones', {
            'fields': ('categorias', 'marcas_compatibles', 'modelos_compatibles', 'tipos_motor_compatibles', 'servicios_relacionados'),
            'description': (
                'Asocie marcas compatibles. Use modelos solo para restringir a variantes concretas '
                'dentro de una marca (opcional). Tipos de motor vacíos = universal.'
            ),
        }),
    )
    
    def tipos_motor_resumen(self, obj):
        tipos = obj.tipos_motor_compatibles or []
        return 'Todos' if not tipos else ', '.join(tipos)
    tipos_motor_resumen.short_description = 'Motores'
    
    actions = ['agregar_repuestos_bulk']
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<int:servicio_id>/agregar-repuestos-bulk/', 
                 self.admin_site.admin_view(self.agregar_repuestos_bulk_view), 
                 name='servicios_servicio_agregar_repuestos_bulk'),
        ]
        return custom_urls + urls
    
    def cantidad_repuestos(self, obj):
        """Muestra la cantidad de repuestos asociados"""
        count = obj.repuestos_necesarios.count()
        if count > 0:
            url = reverse('admin:servicios_servicio_agregar_repuestos_bulk', args=[obj.id])
            return format_html(
                '<a href="{}" title="Gestionar repuestos">{} repuesto{}</a>',
                url, count, 's' if count != 1 else ''
            )
        else:
            url = reverse('admin:servicios_servicio_agregar_repuestos_bulk', args=[obj.id])
            return format_html(
                '<a href="{}" style="color: orange;" title="Agregar repuestos">Sin repuestos</a>',
                url
            )
    cantidad_repuestos.short_description = 'Repuestos'
    
    def agregar_repuestos_bulk_view(self, request, servicio_id):
        """Vista personalizada para agregar múltiples repuestos a un servicio"""
        try:
            servicio = Servicio.objects.get(id=servicio_id)
        except Servicio.DoesNotExist:
            messages.error(request, 'Servicio no encontrado')
            return redirect('admin:servicios_servicio_changelist')
        
        if request.method == 'POST':
            repuestos_ids = request.POST.getlist('repuestos')
            cantidad_default = request.POST.get('cantidad_default', 1)
            es_opcional_default = request.POST.get('es_opcional_default') == 'on'
            notas_default = request.POST.get('notas_default', '')
            
            agregados = 0
            duplicados = 0
            
            for repuesto_id in repuestos_ids:
                try:
                    repuesto = Repuesto.objects.get(id=repuesto_id)
                    servicio_repuesto, created = ServicioRepuesto.objects.get_or_create(
                        servicio=servicio,
                        repuesto=repuesto,
                        defaults={
                            'cantidad_estimada': int(cantidad_default),
                            'es_opcional': es_opcional_default,
                            'notas': notas_default
                        }
                    )
                    if created:
                        agregados += 1
                    else:
                        duplicados += 1
                except (Repuesto.DoesNotExist, ValueError):
                    continue
            
            if agregados > 0:
                messages.success(request, f'Se agregaron {agregados} repuestos al servicio "{servicio.nombre}"')
            if duplicados > 0:
                messages.warning(request, f'{duplicados} repuestos ya estaban asociados al servicio')
            
            return redirect('admin:servicios_servicio_change', servicio_id)
        
        # GET request - mostrar formulario
        repuestos_existentes = servicio.repuestos_necesarios.all()
        repuestos_existentes_ids = list(repuestos_existentes.values_list('repuesto_id', flat=True))
        
        # Obtener todos los repuestos activos ordenados por categoría
        repuestos_por_categoria = Repuesto.objects.filter(activo=True).order_by('categoria_repuesto', 'nombre')
        
        context = {
            'title': f'Agregar repuestos a: {servicio.nombre}',
            'servicio': servicio,
            'repuestos_existentes': repuestos_existentes,
            'repuestos_existentes_ids': repuestos_existentes_ids,
            'repuestos_por_categoria': repuestos_por_categoria,
            'todas_categorias': Repuesto.objects.values_list('categoria_repuesto', flat=True).distinct().order_by('categoria_repuesto'),
            'opts': self.model._meta,
            'has_change_permission': self.has_change_permission(request),
        }
        
        return render(request, 'admin/servicios/agregar_repuestos_bulk.html', context)
    
    def agregar_repuestos_bulk(self, request, queryset):
        """Acción para agregar repuestos en bulk a múltiples servicios"""
        if queryset.count() == 1:
            servicio = queryset.first()
            return HttpResponseRedirect(
                reverse('admin:servicios_servicio_agregar_repuestos_bulk', args=[servicio.id])
            )
        else:
            self.message_user(request, "Selecciona solo un servicio para agregar repuestos", level=messages.WARNING)
    
    agregar_repuestos_bulk.short_description = "Agregar repuestos en bulk"

@admin.register(DetalleServicio)
class DetalleServicioAdmin(admin.ModelAdmin):
    list_display = ('id', 'servicio', 'caracteristica')
    list_filter = ('servicio',)
    search_fields = ('caracteristica',)

@admin.register(OfertaServicio)
class OfertaServicioAdmin(admin.ModelAdmin):
    list_display = ('id', 'servicio', 'tipo_proveedor', 'nombre_proveedor', 'disponible', 'precio_con_repuestos', 'precio_sin_repuestos')
    list_filter = ('tipo_proveedor', 'disponible', 'servicio')
    search_fields = ('servicio__nombre', 'taller__nombre', 'mecanico__nombre')
    
    fieldsets = (
        ('Proveedor', {
            'fields': ('tipo_proveedor', 'taller', 'mecanico')
        }),
        ('Servicio', {
            'fields': ('servicio', 'disponible', 'duracion_estimada')
        }),
        ('Precios', {
            'fields': ('precio_con_repuestos', 'precio_sin_repuestos')
        }),
        ('Garantía', {
            'fields': ('incluye_garantia', 'duracion_garantia', 'detalles_adicionales')
        }),
    )
    
    def nombre_proveedor(self, obj):
        """Muestra el nombre del proveedor"""
        return obj.nombre_proveedor
    nombre_proveedor.short_description = 'Proveedor'
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Filtra los campos según el tipo de proveedor seleccionado"""
        if db_field.name == "taller" and request.POST.get('tipo_proveedor') == 'mecanico':
            kwargs["queryset"] = db_field.related_model.objects.none()
        elif db_field.name == "mecanico" and request.POST.get('tipo_proveedor') == 'taller':
            kwargs["queryset"] = db_field.related_model.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

@admin.register(Repuesto)
class RepuestoAdmin(admin.ModelAdmin):
    form = RepuestoAdminForm
    list_display = ('id', 'nombre', 'marca', 'categoria_repuesto', 'precio_referencia', 'activo', 'servicios_que_lo_usan_count', 'tipos_motor_resumen')
    list_filter = ('categoria_repuesto', 'marca', 'activo')
    search_fields = ('nombre', 'descripcion', 'codigo_fabricante', 'marca')
    filter_horizontal = ('marcas_compatibles', 'modelos_compatibles')
    fieldsets = (
        ('Información Básica', {
            'fields': ('nombre', 'descripcion', 'codigo_fabricante', 'marca', 'foto')
        }),
        ('Clasificación', {
            'fields': ('categoria_repuesto', 'precio_referencia', 'activo')
        }),
        ('Compatibilidad vehículo', {
            'fields': ('marcas_compatibles', 'modelos_compatibles', 'tipos_motor_compatibles'),
            'description': (
                'Marcas de vehículo (catálogo). Use modelos solo para restricción fina. '
                'El campo «marca» arriba es el fabricante del repuesto (Bosch, etc.). '
                'Tipos de motor vacíos = universal.'
            ),
        }),
    )

    def tipos_motor_resumen(self, obj):
        tipos = obj.tipos_motor_compatibles or []
        return 'Todos' if not tipos else ', '.join(tipos)
    tipos_motor_resumen.short_description = 'Motores'
    
    def servicios_que_lo_usan_count(self, obj):
        """Muestra la cantidad de servicios que usan este repuesto"""
        count = obj.servicios_que_lo_usan.count()
        if count > 0:
            return format_html(
                '<span style="color: green;">{} servicio{}</span>',
                count, 's' if count != 1 else ''
            )
        else:
            return format_html('<span style="color: red;">No usado</span>')
    servicios_que_lo_usan_count.short_description = 'Usado en servicios'

@admin.register(ServicioRepuesto)
class ServicioRepuestoAdmin(admin.ModelAdmin):
    list_display = ('id', 'servicio', 'repuesto', 'cantidad_estimada', 'es_opcional', 'categoria_repuesto')
    list_filter = ('es_opcional', 'servicio__categorias', 'repuesto__categoria_repuesto')
    search_fields = ('servicio__nombre', 'repuesto__nombre', 'repuesto__marca')
    autocomplete_fields = ['servicio', 'repuesto']  # Autocompletado para ambos campos
    list_editable = ('cantidad_estimada', 'es_opcional')  # Edición rápida en la lista
    
    fieldsets = (
        ('Relación Servicio-Repuesto', {
            'fields': ('servicio', 'repuesto')
        }),
        ('Configuración', {
            'fields': ('cantidad_estimada', 'es_opcional', 'notas')
        }),
    )
    
    def categoria_repuesto(self, obj):
        """Muestra la categoría del repuesto"""
        return obj.repuesto.get_categoria_repuesto_display()
    categoria_repuesto.short_description = 'Categoría'
    categoria_repuesto.admin_order_field = 'repuesto__categoria_repuesto'
    
    actions = ['marcar_como_opcional', 'marcar_como_obligatorio', 'duplicar_a_otros_servicios']
    
    def marcar_como_opcional(self, request, queryset):
        """Marca los repuestos seleccionados como opcionales"""
        updated = queryset.update(es_opcional=True)
        self.message_user(request, f'{updated} repuestos marcados como opcionales')
    marcar_como_opcional.short_description = "Marcar como opcional"
    
    def marcar_como_obligatorio(self, request, queryset):
        """Marca los repuestos seleccionados como obligatorios"""
        updated = queryset.update(es_opcional=False)
        self.message_user(request, f'{updated} repuestos marcados como obligatorios')
    marcar_como_obligatorio.short_description = "Marcar como obligatorio"
    
    def duplicar_a_otros_servicios(self, request, queryset):
        """Acción para duplicar relaciones de repuestos a otros servicios"""
        # Esta funcionalidad se puede implementar más adelante si es necesaria
        self.message_user(request, "Funcionalidad en desarrollo", level=messages.INFO)
    duplicar_a_otros_servicios.short_description = "Duplicar a otros servicios"

@admin.register(SolicitudRepuesto)
class SolicitudRepuestoAdmin(admin.ModelAdmin):
    list_display = ('id', 'linea_servicio', 'repuesto', 'cantidad', 'precio_unitario', 'precio_total')
    list_filter = ('incluido_en_garantia', 'repuesto__categoria_repuesto')
    search_fields = ('linea_servicio__solicitud__id', 'repuesto__nombre')
    raw_id_fields = ('linea_servicio', 'repuesto')
    readonly_fields = ('precio_total',) 