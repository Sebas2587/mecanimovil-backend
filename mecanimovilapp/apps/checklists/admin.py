from django.contrib import admin
from django.utils.html import format_html
from django.urls import path, reverse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.core.management import call_command
from django.db import models, transaction
from django.forms import widgets
from django import forms
from mecanimovilapp.apps.servicios.models import Servicio
from .models import (
    ChecklistItemCatalog, ChecklistTemplate, ChecklistItemTemplate, ChecklistInstance,
    ChecklistItemResponse, ChecklistPhoto
)
import json


# ===================================
# FORMULARIO PARA BULK ADD ITEMS
# ===================================

class BulkAddItemsForm(forms.Form):
    """Formulario para agregar items en bulk al template desde catálogo por categoría."""

    TIPO_EVALUACION_CHOICES = [
        ('rapida', 'Rápida — 1 item SELECT por componente (inspección cualitativa)'),
        ('completa', 'Completa — SELECT + COMPONENT_HEALTH por componente (inspección cuantitativa)'),
        ('reemplazo', 'Reemplazo — 1 item BOOLEAN por componente (confirmar que se reemplazó)'),
    ]

    categoria = forms.ChoiceField(
        choices=[('', '— Seleccionar categoría —')] + ChecklistItemCatalog.CATEGORIA_CHOICES,
        label='Categoría del catálogo',
        help_text='Los items del catálogo de esta categoría se usarán como base.',
    )
    componentes = forms.ModelMultipleChoiceField(
        queryset=None,
        label='Componentes de salud a evaluar',
        help_text='Selecciona los ComponenteSalud que quieres cubrir con estos items.',
        widget=forms.CheckboxSelectMultiple,
    )
    tipo_evaluacion = forms.ChoiceField(
        choices=TIPO_EVALUACION_CHOICES,
        label='Tipo de evaluación',
        initial='completa',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            from mecanimovilapp.apps.vehiculos.models_health import ComponenteSalud
            self.fields['componentes'].queryset = ComponenteSalud.objects.all().order_by('nombre')
        except Exception:
            from django.db.models import QuerySet
            self.fields['componentes'].queryset = ChecklistItemCatalog.objects.none()


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


def _build_bulk_items_for_componente(template, componente, categoria, tipo_evaluacion, orden_base):
    """
    Retorna lista de (catalog_item, tipo_actualizacion, orden_visual) para el componente dado.
    Crea los ChecklistItemCatalog base si no existen.
    """
    items = []
    nombre_componente = componente.nombre

    if tipo_evaluacion in ('rapida', 'completa'):
        nombre_select = f'Estado {nombre_componente}'
        catalog_select, _ = ChecklistItemCatalog.objects.get_or_create(
            nombre=nombre_select,
            categoria=categoria,
            defaults={
                'tipo_pregunta': 'SELECT',
                'pregunta_texto': f'¿Cuál es el estado de {nombre_componente}?',
                'opciones_seleccion': ['Excelente', 'Bueno', 'Regular', 'Malo', 'Crítico'],
                'es_obligatorio_por_defecto': True,
                'uso_frecuente': True,
            },
        )
        items.append((catalog_select, 'INSPECCIONA', orden_base + len(items) + 1))

    if tipo_evaluacion == 'completa':
        nombre_health = f'Vida útil — {nombre_componente}'
        catalog_health, _ = ChecklistItemCatalog.objects.get_or_create(
            nombre=nombre_health,
            categoria=categoria,
            defaults={
                'tipo_pregunta': 'COMPONENT_HEALTH',
                'pregunta_texto': f'Indica el porcentaje de vida útil restante de {nombre_componente} (0–100%)',
                'descripcion_ayuda': '0% = componente al final de su vida útil. 100% = componente nuevo.',
                'valor_minimo': 0,
                'valor_maximo': 100,
                'es_obligatorio_por_defecto': False,
                'uso_frecuente': True,
            },
        )
        items.append((catalog_health, 'INSPECCIONA', orden_base + len(items) + 1))

    if tipo_evaluacion == 'reemplazo':
        nombre_bool = f'{nombre_componente} reemplazado'
        catalog_bool, _ = ChecklistItemCatalog.objects.get_or_create(
            nombre=nombre_bool,
            categoria=categoria,
            defaults={
                'tipo_pregunta': 'BOOLEAN',
                'pregunta_texto': f'¿Se realizó el reemplazo de {nombre_componente}?',
                'es_obligatorio_por_defecto': True,
                'uso_frecuente': True,
            },
        )
        items.append((catalog_bool, 'REEMPLAZA', orden_base + len(items) + 1))

    return items


def _save_builder(template, sections_data):
    """
    Rebuild all ChecklistItemTemplate rows for *template* from the JSON
    payload produced by the template builder UI.

    Each section → category; each item → ChecklistItemCatalog (get_or_create)
    + ChecklistItemTemplate.  The whole operation runs in a single transaction
    so a partial failure leaves the template unchanged.
    """
    import json as _json
    with transaction.atomic():
        # Wipe existing items; catalog entries are preserved (shared resource).
        ChecklistItemTemplate.objects.filter(checklist_template=template).delete()

        orden = 1
        items_creados = 0

        for section in sections_data:
            categoria = section.get('categoria') or 'INFORMACION_GENERAL'
            for item_data in section.get('items', []):
                label = (item_data.get('label') or '').strip()
                if not label:
                    continue

                tipo              = item_data.get('tipo') or 'TEXT'
                opciones_raw      = item_data.get('opciones') or []
                opciones          = [o for o in opciones_raw if o] or None
                requerido         = bool(item_data.get('requerido', True))
                componente_id     = item_data.get('componente_id') or None
                tipo_actualizacion = item_data.get('tipo_actualizacion') or None

                # Reuse or create the catalog entry for (nombre, categoria, tipo).
                catalog_item, created = ChecklistItemCatalog.objects.get_or_create(
                    nombre=label,
                    categoria=categoria,
                    tipo_pregunta=tipo,
                    defaults={
                        'pregunta_texto': label,
                        'opciones_seleccion': opciones,
                        'es_obligatorio_por_defecto': requerido,
                        'activo': True,
                        'uso_frecuente': True,
                    },
                )

                if not created:
                    needs_save = False
                    if catalog_item.opciones_seleccion != opciones:
                        catalog_item.opciones_seleccion = opciones
                        needs_save = True
                    if catalog_item.es_obligatorio_por_defecto != requerido:
                        catalog_item.es_obligatorio_por_defecto = requerido
                        needs_save = True
                    if needs_save:
                        catalog_item.save(update_fields=['opciones_seleccion', 'es_obligatorio_por_defecto'])

                # Resolve health component FK if provided.
                componente_obj = None
                if componente_id:
                    try:
                        from mecanimovilapp.apps.vehiculos.models_health import ComponenteSalud
                        componente_obj = ComponenteSalud.objects.get(pk=componente_id)
                    except Exception:
                        pass

                ChecklistItemTemplate.objects.create(
                    checklist_template=template,
                    catalog_item=catalog_item,
                    orden_visual=orden,
                    tipo_actualizacion=tipo_actualizacion,
                    componente_salud_asociado=componente_obj,
                )

                orden += 1
                items_creados += 1

        return items_creados


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
    Incluye los campos de semántica de salud (tipo_actualizacion, componente_salud_asociado)
    para que los administradores puedan configurar el impacto en métricas de salud.
    """
    model = ChecklistItemTemplate
    extra = 1
    fields = [
        'orden_visual', 'catalog_item', 'tipo_actualizacion', 'componente_salud_asociado',
    ]
    ordering = ['orden_visual']

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "catalog_item":
            try:
                kwargs["queryset"] = ChecklistItemCatalog.objects.filter(
                    activo=True
                ).order_by('-uso_frecuente', 'categoria', 'nombre')
                kwargs["widget"] = admin.widgets.Select(attrs={'style': 'width: 350px;'})
            except Exception:
                pass
        if db_field.name == "componente_salud_asociado":
            try:
                from mecanimovilapp.apps.vehiculos.models_health import ComponenteSalud
                kwargs["queryset"] = ComponenteSalud.objects.all().order_by('nombre')
                kwargs["widget"] = admin.widgets.Select(attrs={'style': 'width: 200px;'})
            except Exception:
                pass
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
    

# ===================================
# 4. ADMIN DE TEMPLATES DE CHECKLIST
# ===================================

@admin.register(ChecklistTemplate)
class ChecklistTemplateAdmin(admin.ModelAdmin):
    """
    Admin principal para gestionar templates de checklist.
    Incluye acción para agregar items en bulk por categoría y componente de salud.
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
        edit_url = reverse('admin:checklists_checklisttemplate_change', args=[obj.id])
        buttons.append(f'<a href="{edit_url}" style="margin-right: 5px; text-decoration: none;">📝 Editar</a>')
        builder_url = reverse('admin:checklist_template_builder', args=[obj.id])
        buttons.append(f'<a href="{builder_url}" style="margin-right: 5px; text-decoration: none; color: #28a745; font-weight: bold;">🏗 Builder</a>')
        return format_html(''.join(buttons))
    acciones.short_description = 'Acciones'
    acciones.allow_tags = True

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:template_id>/bulk-add-items/',
                self.admin_site.admin_view(self.bulk_add_items_view),
                name='checklist_template_bulk_add_items',
            ),
            path(
                '<int:template_id>/builder/',
                self.admin_site.admin_view(self.template_builder_view),
                name='checklist_template_builder',
            ),
        ]
        return custom_urls + urls

    def bulk_add_items_view(self, request, template_id):
        """Vista admin para agregar items en bulk por categoría y componente de salud."""
        template = ChecklistTemplate.objects.get(pk=template_id)

        if request.method == 'POST':
            form = BulkAddItemsForm(request.POST)
            if form.is_valid():
                categoria = form.cleaned_data['categoria']
                componentes = form.cleaned_data['componentes']
                tipo_evaluacion = form.cleaned_data['tipo_evaluacion']

                items_creados = 0
                items_existentes = 0
                orden_base = template.items.count()

                for componente in componentes:
                    items_para_tipo = _build_bulk_items_for_componente(
                        template, componente, categoria, tipo_evaluacion, orden_base
                    )
                    for catalog_item, tipo_act, orden in items_para_tipo:
                        _, created = ChecklistItemTemplate.objects.get_or_create(
                            checklist_template=template,
                            catalog_item=catalog_item,
                            defaults={
                                'orden_visual': orden,
                                'tipo_actualizacion': tipo_act,
                                'componente_salud_asociado': componente,
                            },
                        )
                        if created:
                            items_creados += 1
                            orden_base += 1
                        else:
                            items_existentes += 1

                messages.success(
                    request,
                    f'Bulk completado: {items_creados} items creados, {items_existentes} ya existentes '
                    f'en template "{template.nombre}".',
                )
                return redirect(
                    reverse('admin:checklists_checklisttemplate_change', args=[template_id])
                )
        else:
            form = BulkAddItemsForm()

        context = {
            **self.admin_site.each_context(request),
            'form': form,
            'template': template,
            'title': f'Agregar items en bulk — {template.nombre}',
            'opts': self.model._meta,
        }
        return render(request, 'admin/checklists/bulk_add_items.html', context)

    def template_builder_view(self, request, template_id):
        """Template Builder — interfaz tipo Google Forms para crear/editar un template."""
        import json as _json
        template = get_object_or_404(ChecklistTemplate, pk=template_id)

        if request.method == 'POST':
            try:
                data = _json.loads(request.body)
                count = _save_builder(template, data.get('sections', []))
                return JsonResponse({'ok': True, 'items_creados': count})
            except Exception as exc:
                import traceback
                return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

        # GET — reconstruct sections from existing items.
        items_qs = template.items.select_related(
            'catalog_item', 'componente_salud_asociado'
        ).order_by('orden_visual')

        sections_map = {}
        sections_order = []
        cat_display = dict(ChecklistItemCatalog.CATEGORIA_CHOICES)

        for item in items_qs:
            cat = item.catalog_item.categoria if item.catalog_item else 'INFORMACION_GENERAL'
            if cat not in sections_map:
                sections_map[cat] = {
                    'nombre': cat_display.get(cat, cat),
                    'categoria': cat,
                    'items': [],
                }
                sections_order.append(cat)
            sections_map[cat]['items'].append({
                'label': item.catalog_item.nombre if item.catalog_item else '',
                'tipo': item.catalog_item.tipo_pregunta if item.catalog_item else 'TEXT',
                'opciones': item.catalog_item.opciones_seleccion or [],
                'requerido': item.catalog_item.es_obligatorio_por_defecto if item.catalog_item else True,
                'componente_id': item.componente_salud_asociado_id or '',
                'componente_nombre': item.componente_salud_asociado.nombre if item.componente_salud_asociado else '',
                'tipo_actualizacion': item.tipo_actualizacion or 'INSPECCIONA',
            })

        sections_data = [sections_map[c] for c in sections_order]

        try:
            from mecanimovilapp.apps.vehiculos.models_health import ComponenteSalud
            componentes = list(ComponenteSalud.objects.order_by('nombre').values('id', 'nombre'))
        except Exception:
            componentes = []

        context = {
            **self.admin_site.each_context(request),
            'template_obj': template,
            'title': f'Builder — {template.nombre}',
            'opts': self.model._meta,
            'sections_data': sections_data,
            'componentes_data': componentes,
            'categorias_data': list(ChecklistItemCatalog.CATEGORIA_CHOICES),
        }
        return render(request, 'admin/checklists/template_builder.html', context)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('servicio').prefetch_related('items', 'servicio__categorias')

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "servicio":
            kwargs["queryset"] = Servicio.objects.all().order_by('nombre')
            kwargs["empty_label"] = "Seleccionar servicio..."
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def response_add(self, request, obj, post_url_continue=None):
        if "_addanother" not in request.POST and "_continue" not in request.POST:
            messages.success(
                request,
                f'Template "{obj.nombre}" creado exitosamente y asignado al servicio "{obj.servicio}".'
            )
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if "_addanother" not in request.POST and "_continue" not in request.POST:
            messages.success(request, f'Template "{obj.nombre}" actualizado exitosamente.')
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