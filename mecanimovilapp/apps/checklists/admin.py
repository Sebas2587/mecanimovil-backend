from django.contrib import admin
from django.utils.html import format_html
from django.urls import path, reverse
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.core.management import call_command
from django.db import models
from django.forms import widgets
from django import forms
from mecanimovilapp.apps.servicios.models import Servicio
from .models import (
    ChecklistItemCatalog, ChecklistTemplate, ChecklistItemTemplate, ChecklistInstance,
    ChecklistItemResponse, ChecklistPhoto
)
import json


# ===================================
# 1. WIDGET PERSONALIZADO PARA OPCIONES
# ===================================

class OptionsTextWidget(widgets.Textarea):
    """Widget personalizado para editar opciones de selección como texto"""
    
    def __init__(self, attrs=None):
        default_attrs = {
            'rows': 4,
            'cols': 50,
            'placeholder': 'Ingrese una opción por línea. Ejemplo:\nExcelente\nBueno\nRegular\nMalo'
        }
        if attrs:
            default_attrs.update(attrs)
        super().__init__(default_attrs)
    
    def format_value(self, value):
        """Convertir lista JSON a texto"""
        if value is None:
            return ''
        if isinstance(value, list):
            return '\n'.join(value)
        if isinstance(value, str):
            try:
                # Si es una cadena JSON, parsearla
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return '\n'.join(parsed)
            except (json.JSONDecodeError, TypeError):
                pass
        return str(value)
    
    def value_from_datadict(self, data, files, name):
        """Convertir texto a lista JSON"""
        value = data.get(name, '')
        if not value or not value.strip():
            return None
        
        # Dividir por líneas y limpiar
        options = [line.strip() for line in value.split('\n') if line.strip()]
        return options if options else None


class ChecklistItemCatalogForm(forms.ModelForm):
    """Formulario personalizado para ChecklistItemCatalog"""
    
    class Meta:
        model = ChecklistItemCatalog
        fields = '__all__'
        widgets = {
            'opciones_seleccion': OptionsTextWidget(),
            'pregunta_texto': widgets.Textarea(attrs={'rows': 3}),
            'descripcion_ayuda': widgets.Textarea(attrs={'rows': 3}),
        }
        help_texts = {
            'opciones_seleccion': 'Ingrese una opción por línea. Solo aplica para tipos SELECT y MULTISELECT.',
            'tipo_pregunta': 'Seleccione el tipo de pregunta según la información que desea recopilar.',
            'uso_frecuente': 'Marque si este item se usa frecuentemente en la mayoría de checklists.',
        }


# ===================================
# 2. ADMIN DEL CATÁLOGO DE ITEMS
# ===================================

@admin.register(ChecklistItemCatalog)
class ChecklistItemCatalogAdmin(admin.ModelAdmin):
    """
    Admin para gestionar el catálogo de items reutilizables.
    Este es el núcleo del sistema: aquí se crean los elementos que luego se pueden usar en cualquier checklist.
    """
    form = ChecklistItemCatalogForm
    
    list_display = [
        'nombre', 'categoria', 'tipo_pregunta', 'es_obligatorio_por_defecto', 
        'uso_frecuente', 'activo', 'templates_count', 'fecha_creacion'
    ]
    list_filter = [
        'categoria', 'tipo_pregunta', 'es_obligatorio_por_defecto', 
        'uso_frecuente', 'activo', 'fecha_creacion'
    ]
    search_fields = ['nombre', 'pregunta_texto', 'descripcion_ayuda']
    ordering = ['categoria', '-uso_frecuente', 'nombre']
    
    fieldsets = (
        ('📋 Información Básica', {
            'fields': ('nombre', 'categoria', 'tipo_pregunta', 'pregunta_texto')
        }),
        ('❓ Descripción y Ayuda', {
            'fields': ('descripcion_ayuda', 'placeholder'),
            'classes': ('collapse',)
        }),
        ('⚙️ Configuración', {
            'fields': ('es_obligatorio_por_defecto', 'uso_frecuente', 'activo')
        }),
        ('🔢 Opciones y Validación', {
            'fields': ('opciones_seleccion', 'valor_minimo', 'valor_maximo'),
            'classes': ('collapse',)
        }),
        ('📷 Configuración de Fotos', {
            'fields': ('min_fotos', 'max_fotos'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['marcar_uso_frecuente', 'desmarcar_uso_frecuente', 'activar_items', 'desactivar_items']
    
    def templates_count(self, obj):
        """Mostrar en cuántos templates se usa este item"""
        count = obj.template_usages.count() if hasattr(obj, 'template_usages') else 0
        if count > 0:
            color = 'green' if count > 5 else 'blue'
            return format_html(
                '<span style="color: {}; font-weight: bold;">{} templates</span>', 
                color, count
            )
        return format_html('<span style="color: gray;">Sin usar</span>')
    templates_count.short_description = 'Usado en'
    
    def marcar_uso_frecuente(self, request, queryset):
        """Marcar items como de uso frecuente"""
        count = queryset.update(uso_frecuente=True)
        self.message_user(request, f'{count} items marcados como de uso frecuente.')
    marcar_uso_frecuente.short_description = '⭐ Marcar como uso frecuente'
    
    def desmarcar_uso_frecuente(self, request, queryset):
        """Desmarcar items de uso frecuente"""
        count = queryset.update(uso_frecuente=False)
        self.message_user(request, f'{count} items desmarcados como uso frecuente.')
    desmarcar_uso_frecuente.short_description = '⭐ Desmarcar uso frecuente'
    
    def activar_items(self, request, queryset):
        """Activar items del catálogo"""
        count = queryset.update(activo=True)
        self.message_user(request, f'{count} items activados.')
    activar_items.short_description = '✅ Activar items'
    
    def desactivar_items(self, request, queryset):
        """Desactivar items del catálogo"""
        count = queryset.update(activo=False)
        self.message_user(request, f'{count} items desactivados.')
    desactivar_items.short_description = '❌ Desactivar items'


# ===================================
# 3. INLINE PARA ITEMS DEL TEMPLATE
# ===================================

class ChecklistItemTemplateInline(admin.TabularInline):
    """
    Inline para gestionar los items dentro de un template.
    Aquí se seleccionan los items del catálogo y se organizan por orden.
    La obligatoriedad se define en el catálogo, no se sobrescribe aquí.
    """
    model = ChecklistItemTemplate
    extra = 1
    fields = [
        'orden_visual', 'catalog_item'
    ]
    ordering = ['orden_visual']
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Personalizar el campo de selección del catalog_item"""
        if db_field.name == "catalog_item":
            # Solo mostrar items activos del catálogo, ordenados por uso frecuente
            try:
                kwargs["queryset"] = ChecklistItemCatalog.objects.filter(
                    activo=True
                ).order_by('-uso_frecuente', 'categoria', 'nombre')
                
                # Personalizar el widget para mostrar más información
                kwargs["widget"] = admin.widgets.Select(attrs={
                    'style': 'width: 400px;'
                })
            except:
                pass
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


# ===================================
# 4. ADMIN DE TEMPLATES DE CHECKLIST
# ===================================

@admin.register(ChecklistTemplate)
class ChecklistTemplateAdmin(admin.ModelAdmin):
    """
    Admin principal para gestionar templates de checklist.
    Aquí se crean los templates y se asignan a servicios de forma simple e intuitiva.
    """
    list_display = [
        'nombre', 'servicio_info', 'version', 'activo', 
        'total_items', 'items_frecuentes', 'created_info', 'acciones'
    ]
    list_filter = ['activo', 'fecha_creacion', 'servicio__categorias']
    search_fields = ['nombre', 'servicio__nombre', 'descripcion']
    readonly_fields = ['fecha_creacion', 'fecha_actualizacion']
    inlines = [ChecklistItemTemplateInline]
    
    fieldsets = (
        ('📋 Información Básica', {
            'fields': ('nombre', 'descripcion'),
            'description': 'Define el nombre y propósito de este checklist'
        }),
        ('🔧 Asignación a Servicio', {
            'fields': ('servicio',),
            'description': 'Selecciona el servicio al que se aplicará este checklist'
        }),
        ('⚙️ Configuración', {
            'fields': ('activo', 'version'),
            'classes': ('collapse',)
        }),
        ('📅 Información del Sistema', {
            'fields': ('fecha_creacion', 'fecha_actualizacion'),
            'classes': ('collapse',)
        }),
    )
    
    def servicio_info(self, obj):
        """Mostrar información del servicio asignado"""
        if obj.servicio:
            return format_html(
                '<strong>{}</strong><br><small style="color: gray;">{}</small>',
                obj.servicio.nombre,
                obj.servicio.categorias.first().nombre if obj.servicio.categorias.exists() else 'Sin categoría'
            )
        return format_html('<span style="color: red;">⚠️ Sin servicio asignado</span>')
    servicio_info.short_description = 'Servicio Asignado'
    
    def total_items(self, obj):
        """Mostrar total de items en el template"""
        count = obj.items.count()
        color = 'green' if count > 10 else 'blue' if count > 5 else 'orange'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{} items</span>', 
            color, count
        )
    total_items.short_description = 'Items'
    
    def items_frecuentes(self, obj):
        """Mostrar cuántos items frecuentes tiene"""
        try:
            count = obj.items.filter(catalog_item__uso_frecuente=True).count()
            if count > 0:
                return format_html('⭐ {} frecuentes', count)
            return '○'
        except:
            return '○'
    items_frecuentes.short_description = 'Frecuentes'
    
    def created_info(self, obj):
        """Información de creación más legible"""
        return format_html(
            '<small>{}</small>',
            obj.fecha_creacion.strftime('%d/%m/%Y')
        )
    created_info.short_description = 'Creado'
    
    def acciones(self, obj):
        """Botones de acciones rápidas"""
        buttons = []
        
        # Botón editar
        edit_url = reverse('admin:checklists_checklisttemplate_change', args=[obj.id])
        buttons.append(f'<a href="{edit_url}" style="margin-right: 5px; text-decoration: none;">📝 Editar</a>')
        
        return format_html(''.join(buttons))
    acciones.short_description = 'Acciones'
    acciones.allow_tags = True
    
    def get_queryset(self, request):
        """Optimizar consultas"""
        return super().get_queryset(request).select_related('servicio').prefetch_related('items', 'servicio__categorias')
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Personalizar el campo de selección de servicio"""
        if db_field.name == "servicio":
            # Todos los servicios disponibles ordenados por nombre
            kwargs["queryset"] = Servicio.objects.all().order_by('nombre')
            # Mejorar la visualización
            kwargs["empty_label"] = "Seleccionar servicio..."
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
    
    def response_add(self, request, obj, post_url_continue=None):
        """Personalizar respuesta después de crear"""
        if "_addanother" not in request.POST and "_continue" not in request.POST:
            # Si no se presionó "Agregar otro" o "Continuar editando"
            messages.success(
                request, 
                f'Template "{obj.nombre}" creado exitosamente y asignado al servicio "{obj.servicio}".'
            )
        return super().response_add(request, obj, post_url_continue)
    
    def response_change(self, request, obj):
        """Personalizar respuesta después de editar"""
        if "_addanother" not in request.POST and "_continue" not in request.POST:
            messages.success(
                request, 
                f'Template "{obj.nombre}" actualizado exitosamente.'
            )
        return super().response_change(request, obj)


# ===================================
# 5. ADMIN PARA INSTANCIAS Y RESPUESTAS
# ===================================

@admin.register(ChecklistInstance)
class ChecklistInstanceAdmin(admin.ModelAdmin):
    """Admin para ver las instancias de checklist ejecutadas"""
    list_display = [
        'id', 'orden_info', 'checklist_template', 'estado', 
        'progreso_visual', 'fecha_inicio', 'fecha_finalizacion'
    ]
    list_filter = ['estado', 'fecha_creacion', 'checklist_template']
    search_fields = ['orden__id', 'checklist_template__nombre']
    readonly_fields = [
        'fecha_creacion', 'fecha_finalizacion', 'tiempo_total_minutos',
        'progreso_porcentaje', 'ubicacion_finalizacion'
    ]
    
    def orden_info(self, obj):
        """Información de la orden"""
        return format_html(
            '<strong>Orden #{}</strong><br><small>{}</small>',
            obj.orden.id,
            obj.orden.carrito.cliente.usuario.get_full_name()
        )
    orden_info.short_description = 'Orden'
    
    def progreso_visual(self, obj):
        """Barra de progreso visual"""
        progreso = obj.progreso_porcentaje or 0
        color = 'green' if progreso == 100 else 'blue' if progreso > 50 else 'orange'
        return format_html(
            '<div style="width: 100px; background: #f0f0f0; border-radius: 3px;">'
            '<div style="width: {}%; background: {}; height: 20px; border-radius: 3px; text-align: center; color: white; font-size: 12px; line-height: 20px;">'
            '{}%'
            '</div></div>',
            progreso, color, progreso
        )
    progreso_visual.short_description = 'Progreso'


@admin.register(ChecklistItemResponse)
class ChecklistItemResponseAdmin(admin.ModelAdmin):
    """Admin para ver las respuestas individuales"""
    list_display = [
        'checklist_instance', 'item_info', 'completado', 
        'respuesta_resumen', 'fecha_respuesta'
    ]
    list_filter = ['completado', 'fecha_respuesta']
    search_fields = [
        'checklist_instance__orden__id', 
        'item_template__catalog_item__nombre'
    ]
    
    def item_info(self, obj):
        """Información del item"""
        return format_html(
            '<strong>{}</strong><br><small>{}</small>',
            obj.item_template.catalog_item.nombre,
            obj.item_template.catalog_item.tipo_pregunta
        )
    item_info.short_description = 'Item'
    
    def respuesta_resumen(self, obj):
        """Resumen de la respuesta"""
        if obj.respuesta_texto:
            return obj.respuesta_texto[:50] + '...' if len(obj.respuesta_texto) > 50 else obj.respuesta_texto
        elif obj.respuesta_numero is not None:
            return f"Número: {obj.respuesta_numero}"
        elif obj.respuesta_booleana is not None:
            return "Sí" if obj.respuesta_booleana else "No"
        elif obj.respuesta_seleccion:
            return f"Selección: {obj.respuesta_seleccion}"
        return "Sin respuesta"
    respuesta_resumen.short_description = 'Respuesta'


@admin.register(ChecklistPhoto)
class ChecklistPhotoAdmin(admin.ModelAdmin):
    """Admin para gestionar fotos de checklist"""
    list_display = [
        'response', 'orden_en_respuesta', 'fecha_captura'
    ]
    list_filter = ['fecha_captura']


# ===================================
# 6. PERSONALIZACIÓN DEL ADMIN
# ===================================

# Personalizar títulos del admin
admin.site.site_header = "MecaniMóvil - Gestión de Checklists"
admin.site.site_title = "Checklists Admin"
admin.site.index_title = "Panel de Administración de Checklists" 