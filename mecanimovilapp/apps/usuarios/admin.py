from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.gis.admin import GISModelAdmin
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.urls import reverse
from django import forms
from django.contrib import messages
from django.shortcuts import render, redirect
from django.urls import path
from django.http import HttpResponseRedirect
from .models import (
    Usuario, Cliente, Taller, MecanicoDomicilio, ZonaCobertura, 
    Resena, DireccionUsuario, HorarioProveedor, DocumentoOnboarding,
    ConfiguracionSemanalProveedor, MechanicServiceArea, ChileanCommune,
    PushToken, WebPushSubscription,
)


# Formulario personalizado para configuración semanal
class ConfiguracionSemanalProveedorForm(forms.ModelForm):
    """Formulario personalizado para configuración semanal con validaciones mejoradas"""
    
    class Meta:
        model = ConfiguracionSemanalProveedor
        fields = '__all__'
        widgets = {
            'hora_inicio_global': forms.TimeInput(attrs={'type': 'time'}),
            'hora_fin_global': forms.TimeInput(attrs={'type': 'time'}),
            'lunes_hora_inicio': forms.TimeInput(attrs={'type': 'time'}),
            'lunes_hora_fin': forms.TimeInput(attrs={'type': 'time'}),
            'martes_hora_inicio': forms.TimeInput(attrs={'type': 'time'}),
            'martes_hora_fin': forms.TimeInput(attrs={'type': 'time'}),
            'miercoles_hora_inicio': forms.TimeInput(attrs={'type': 'time'}),
            'miercoles_hora_fin': forms.TimeInput(attrs={'type': 'time'}),
            'jueves_hora_inicio': forms.TimeInput(attrs={'type': 'time'}),
            'jueves_hora_fin': forms.TimeInput(attrs={'type': 'time'}),
            'viernes_hora_inicio': forms.TimeInput(attrs={'type': 'time'}),
            'viernes_hora_fin': forms.TimeInput(attrs={'type': 'time'}),
            'sabado_hora_inicio': forms.TimeInput(attrs={'type': 'time'}),
            'sabado_hora_fin': forms.TimeInput(attrs={'type': 'time'}),
            'domingo_hora_inicio': forms.TimeInput(attrs={'type': 'time'}),
            'domingo_hora_fin': forms.TimeInput(attrs={'type': 'time'}),
        }


# Personalizar el admin para el modelo Usuario
class UsuarioAdmin(UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'es_mecanico', 'is_staff', 'tiene_push_token')
    fieldsets = UserAdmin.fieldsets + (
        ('Información Adicional', {'fields': ('es_mecanico', 'telefono', 'direccion', 'foto_perfil')}),
        ('Push Notifications', {'fields': ('expo_push_token',), 'classes': ('collapse',)}),
    )
    readonly_fields = ('expo_push_token',)
    search_fields = ('username', 'email', 'first_name', 'last_name', 'telefono')
    list_filter = UserAdmin.list_filter + ('es_mecanico',)
    actions = ['enviar_push_prueba', 'limpiar_push_token']

    def tiene_push_token(self, obj):
        if obj.expo_push_token:
            return format_html('<span style="color:green;">&#10003; {}</span>', obj.expo_push_token[:20] + '…')
        return format_html('<span style="color:red;">&#10007; Sin token</span>')
    tiene_push_token.short_description = 'Push Token'

    def enviar_push_prueba(self, request, queryset):
        from .tasks import send_expo_push_notification
        enviadas = 0
        sin_token = 0
        for user in queryset:
            if user.expo_push_token:
                send_expo_push_notification.delay(
                    user.id,
                    'Notificación de prueba',
                    f'Hola {user.username}, las notificaciones push están funcionando.',
                    {'type': 'test'},
                )
                enviadas += 1
            else:
                sin_token += 1
        msg = f'{enviadas} push(es) encolada(s).'
        if sin_token:
            msg += f' {sin_token} usuario(s) sin token.'
        self.message_user(request, msg)
    enviar_push_prueba.short_description = '📲 Enviar push de prueba'

    def limpiar_push_token(self, request, queryset):
        updated = queryset.update(expo_push_token=None)
        self.message_user(request, f'expo_push_token limpiado en {updated} usuario(s).')
    limpiar_push_token.short_description = '🗑️ Limpiar expo_push_token'


# Registrar el modelo Usuario con la configuración personalizada
admin.site.register(Usuario, UsuarioAdmin)


@admin.register(PushToken)
class PushTokenAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'token_preview', 'plataforma', 'dispositivo', 'activo', 'fecha_registro')
    list_filter = ('activo', 'plataforma', 'fecha_registro')
    search_fields = ('usuario__username', 'usuario__email', 'token', 'dispositivo')
    readonly_fields = ('token', 'fecha_registro', 'fecha_actualizacion')
    list_per_page = 30
    actions = ['activar_tokens', 'desactivar_tokens']

    def token_preview(self, obj):
        t = obj.token or ''
        preview = t[:22] + '…' + t[-6:] if len(t) > 30 else t
        color = 'green' if obj.activo else 'gray'
        return format_html('<span style="color:{};">{}</span>', color, preview)
    token_preview.short_description = 'Token'

    def activar_tokens(self, request, queryset):
        updated = queryset.update(activo=True)
        self.message_user(request, f'{updated} token(s) activado(s).')
    activar_tokens.short_description = 'Activar tokens seleccionados'

    def desactivar_tokens(self, request, queryset):
        updated = queryset.update(activo=False)
        self.message_user(request, f'{updated} token(s) desactivado(s).')
    desactivar_tokens.short_description = 'Desactivar tokens seleccionados'

# Personalizar el admin para el modelo Cliente
class ClienteAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'apellido', 'email', 'telefono', 'fecha_registro')
    search_fields = ('nombre', 'apellido', 'email', 'telefono', 'usuario__username')
    list_filter = ('fecha_registro',)
    date_hierarchy = 'fecha_registro'
    fieldsets = (
        ('Información Personal', {
            'fields': ('usuario', 'nombre', 'apellido', 'email', 'telefono', 'fecha_registro')
        }),
        ('Ubicación', {
            'fields': ('direccion', 'ubicacion'),
        }),
    )

# Registrar el modelo Cliente con la configuración personalizada
admin.site.register(Cliente, ClienteAdmin)

# Admin para DocumentoOnboarding
class DocumentoOnboardingInline(admin.TabularInline):
    model = DocumentoOnboarding
    extra = 0
    readonly_fields = ('fecha_subida', 'vista_previa')
    fields = ('tipo_documento', 'archivo', 'vista_previa', 'verificado', 'comentarios_verificacion', 'fecha_subida')
    
    def vista_previa(self, obj):
        if obj.archivo:
            if obj.es_imagen():
                return format_html(
                    '<img src="{}" style="max-width: 100px; max-height: 100px;" />',
                    obj.archivo.url
                )
            elif obj.es_pdf():
                return format_html(
                    '<a href="{}" target="_blank">📄 Ver PDF</a>',
                    obj.archivo.url
                )
            else:
                return format_html(
                    '<a href="{}" target="_blank">📎 Descargar archivo</a>',
                    obj.archivo.url
                )
        return "No disponible"
    vista_previa.short_description = 'Vista Previa'


# Inline mejorado para HorarioProveedor con configuración semanal completa
class HorarioProveedorInline(admin.TabularInline):
    model = HorarioProveedor
    extra = 0
    max_num = 7
    min_num = 7  # Siempre mostrar los 7 días
    fields = ('get_dia_display', 'activo', 'hora_inicio', 'hora_fin', 'duracion_slot', 'tiempo_descanso')
    readonly_fields = ('get_dia_display',)
    
    def get_dia_display(self, obj):
        """Mostrar el nombre del día en lugar del número"""
        dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
        if obj.dia_semana is not None:
            return dias[obj.dia_semana]
        return '-'
    get_dia_display.short_description = 'Día de la Semana'
    
    def get_queryset(self, request):
        """Ordenar por día de la semana y asegurar que existan los 7 días"""
        qs = super().get_queryset(request)
        return qs.order_by('dia_semana')
    
    def get_formset(self, request, obj=None, **kwargs):
        """Personalizar el formset para crear automáticamente los 7 días si no existen"""
        formset = super().get_formset(request, obj, **kwargs)
        
        # Si el objeto existe, asegurar que tenga los 7 días configurados
        if obj:
            existing_days = set(obj.horarios_configurados.values_list('dia_semana', flat=True))
            missing_days = set(range(7)) - existing_days
            
            # Crear horarios faltantes con valores por defecto
            for dia in missing_days:
                HorarioProveedor.objects.create(
                    taller=obj if hasattr(obj, 'horarios_configurados') and 'taller' in str(type(obj)).lower() else None,
                    mecanico=obj if hasattr(obj, 'horarios_configurados') and 'mecanico' in str(type(obj)).lower() else None,
                    dia_semana=dia,
                    activo=dia < 5,  # Lunes a Viernes activos por defecto
                    hora_inicio='08:00',
                    hora_fin='18:00',
                    duracion_slot=60,
                    tiempo_descanso=0
                )
        
        return formset


# Admin TEMPORALMENTE HABILITADO para mantenimiento de HorarioProveedor
class HorarioProveedorAdmin(admin.ModelAdmin):
    """
    ⚠️ TEMPORALMENTE HABILITADO PARA MANTENIMIENTO ⚠️
    
    Este admin está temporalmente habilitado para permitir eliminación de horarios
    problemáticos que impiden eliminar talleres/mecánicos.
    
    Para uso normal, use la configuración semanal desde Talleres/Mecánicos.
    """
    
    def has_add_permission(self, request):
        """Mantener deshabilitado agregar horarios individuales"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """TEMPORALMENTE HABILITADO para mantenimiento"""
        return True
    
    def has_delete_permission(self, request, obj=None):
        """TEMPORALMENTE HABILITADO para mantenimiento"""
        return True
    
    list_display = ('get_proveedor', 'get_dia_semana_display', 'activo', 'hora_inicio_12h', 'hora_fin_12h', 'duracion_slot')
    list_filter = ('dia_semana', 'activo', 'taller', 'mecanico')
    search_fields = ('taller__nombre', 'mecanico__nombre')
    ordering = ('taller', 'mecanico', 'dia_semana')
    
    # Habilitar acciones de eliminación
    actions = ['delete_selected']
    
    def get_proveedor(self, obj):
        """Mostrar el nombre del proveedor (taller o mecánico)"""
        if obj.taller:
            return f"Taller: {obj.taller.nombre}"
        elif obj.mecanico:
            return f"Mecánico: {obj.mecanico.nombre}"
        return "Sin proveedor"
    get_proveedor.short_description = 'Proveedor'
    
    def get_dia_semana_display(self, obj):
        """Mostrar el día de la semana"""
        dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
        return dias[obj.dia_semana] if obj.dia_semana is not None else '-'
    get_dia_semana_display.short_description = 'Día'
    
    def hora_inicio_12h(self, obj):
        """Mostrar hora de inicio en formato 12 horas"""
        if obj.hora_inicio:
            return obj.hora_inicio.strftime('%I:%M %p')
        return '-'
    hora_inicio_12h.short_description = 'Hora Inicio'
    
    def hora_fin_12h(self, obj):
        """Mostrar hora de fin en formato 12 horas"""
        if obj.hora_fin:
            return obj.hora_fin.strftime('%I:%M %p')
        return '-'
    hora_fin_12h.short_description = 'Hora Fin'
    
    def changelist_view(self, request, extra_context=None):
        """Agregar mensaje informativo en la vista de lista"""
        extra_context = extra_context or {}
        extra_context['title'] = 'Horarios de Proveedores - MODO MANTENIMIENTO'
        extra_context['subtitle'] = (
            '⚠️ MODO MANTENIMIENTO ACTIVADO ⚠️\n'
            'Permisos de edición/eliminación habilitados temporalmente.\n'
            'Para configuración normal use Talleres/Mecánicos → Configuración semanal.'
        )
        return super().changelist_view(request, extra_context)


# Admin para ConfiguracionSemanalProveedor
class ConfiguracionSemanalProveedorAdmin(admin.ModelAdmin):
    form = ConfiguracionSemanalProveedorForm
    
    fieldsets = (
        ('Proveedor', {
            'fields': ('taller', 'mecanico'),
            'description': 'Seleccione SOLO un taller O un mecánico (no ambos)'
        }),
        ('Configuración Global', {
            'fields': ('hora_inicio_global', 'hora_fin_global', 'duracion_slot_global', 'tiempo_descanso_global'),
            'description': 'Esta configuración se aplicará a todos los días habilitados que no tengan horarios específicos'
        }),
        ('Días Habilitados', {
            'fields': ('lunes_activo', 'martes_activo', 'miercoles_activo', 'jueves_activo', 'viernes_activo', 'sabado_activo', 'domingo_activo'),
            'classes': ('wide',),
        }),
        ('Horarios Específicos por Día (Opcional)', {
            'fields': (
                ('lunes_hora_inicio', 'lunes_hora_fin'),
                ('martes_hora_inicio', 'martes_hora_fin'),
                ('miercoles_hora_inicio', 'miercoles_hora_fin'),
                ('jueves_hora_inicio', 'jueves_hora_fin'),
                ('viernes_hora_inicio', 'viernes_hora_fin'),
                ('sabado_hora_inicio', 'sabado_hora_fin'),
                ('domingo_hora_inicio', 'domingo_hora_fin'),
            ),
            'classes': ('collapse',),
            'description': 'Deje en blanco para usar la configuración global. Solo complete si ese día tiene horarios diferentes.'
        }),
    )
    
    def save_model(self, request, obj, form, change):
        """Override para aplicar la configuración automáticamente al guardar"""
        try:
            # Aplicar la configuración
            horarios_creados = obj.aplicar_configuracion(eliminar_existente=True)
            
            proveedor_nombre = obj.taller.nombre if obj.taller else obj.mecanico.nombre
            tipo_proveedor = "taller" if obj.taller else "mecánico"
            
            self.message_user(
                request,
                f'Configuración semanal aplicada exitosamente para {tipo_proveedor} "{proveedor_nombre}". '
                f'Se crearon/actualizaron {len(horarios_creados)} horarios.',
                level=messages.SUCCESS
            )
            
            # No guardamos el objeto ConfiguracionSemanalProveedor ya que es solo auxiliar
            # En su lugar, redirigimos al admin del proveedor correspondiente
            if obj.taller:
                redirect_url = f'/admin/usuarios/taller/{obj.taller.id}/change/'
            else:
                redirect_url = f'/admin/usuarios/mecanicodomicilio/{obj.mecanico.id}/change/'
            
            return HttpResponseRedirect(redirect_url)
            
        except Exception as e:
            self.message_user(
                request,
                f'Error aplicando la configuración: {str(e)}',
                level=messages.ERROR
            )
            return super().save_model(request, obj, form, change)


# Admin para el modelo Taller
class TallerAdmin(GISModelAdmin):
    list_display = (
        'nombre', 'telefono', 'estado_verificacion', 
        'verificado', 'onboarding_completado', 'calificacion_promedio', 'get_horarios_configurados'
    )
    search_fields = ('nombre', 'telefono', 'rut')
    list_filter = ('estado_verificacion', 'verificado', 'onboarding_completado', 'activo', 'calificacion_promedio')
    inlines = [HorarioProveedorInline, DocumentoOnboardingInline]
    readonly_fields = ('fecha_registro', 'ultima_actualizacion', 'fecha_verificacion')
    
    # Agregar campos Many-to-Many para mostrar en el admin
    filter_horizontal = ('especialidades', 'marcas_atendidas')
    
    actions = ['aprobar_verificacion', 'rechazar_verificacion', 'marcar_en_revision', 'configurar_horarios_semanales']
    
    def get_horarios_configurados(self, obj):
        """Mostrar cuántos días tiene configurados con botón de configuración rápida"""
        horarios_activos = obj.horarios_configurados.filter(activo=True).count()
        total_horarios = obj.horarios_configurados.count()
        
        # Botón para configurar rápidamente
        config_url = f'/admin/usuarios/configurarsemana/?taller={obj.id}'
        config_button = f'<a href="{config_url}" style="background: #417690; color: white; padding: 3px 6px; border-radius: 3px; text-decoration: none; margin-left: 5px;">⚡ Configurar</a>'
        
        if total_horarios == 0:
            return format_html('<span style="color: red;">Sin horarios</span> {}', config_button)
        elif horarios_activos == 0:
            return format_html('<span style="color: orange;">{} días (todos inactivos)</span> {}', total_horarios, config_button)
        else:
            return format_html('<span style="color: green;">{} días activos / {} total</span> {}', horarios_activos, total_horarios, config_button)
    
    get_horarios_configurados.short_description = 'Horarios Configurados'
    
    def configurar_horarios_semanales(self, request, queryset):
        """Acción para configurar horarios semanales para talleres seleccionados"""
        if queryset.count() > 1:
            self.message_user(
                request, 
                "Seleccione solo un taller para configurar sus horarios semanales", 
                level=messages.ERROR
            )
            return
        
        taller = queryset.first()
        return HttpResponseRedirect(f'/admin/usuarios/configurarsemana/?taller={taller.id}')
    
    configurar_horarios_semanales.short_description = '⚡ Configurar horarios semanales'
    
    def change_view(self, request, object_id, form_url='', extra_context=None):
        """Personalizar la vista de edición con información sobre configuración de horarios"""
        extra_context = extra_context or {}
        
        if object_id:
            try:
                taller = Taller.objects.get(pk=object_id)
                horarios_count = taller.horarios_configurados.count()
                
                if horarios_count < 7:
                    extra_context['horarios_info'] = {
                        'tipo': 'warning',
                        'mensaje': f'⚠️ Solo {horarios_count} días configurados de 7. Los días faltantes se crearán automáticamente al guardar.',
                        'accion_url': f'/admin/usuarios/configurarsemana/?taller={object_id}',
                        'accion_texto': 'Configurar Semana Completa'
                    }
                elif taller.horarios_configurados.filter(activo=True).count() == 0:
                    extra_context['horarios_info'] = {
                        'tipo': 'error',
                        'mensaje': '❌ Todos los días están inactivos. Configure al menos un día de atención.',
                        'accion_url': f'/admin/usuarios/configurarsemana/?taller={object_id}',
                        'accion_texto': 'Activar Días de Atención'
                    }
                else:
                    activos = taller.horarios_configurados.filter(activo=True).count()
                    extra_context['horarios_info'] = {
                        'tipo': 'success',
                        'mensaje': f'✅ {activos} días activos configurados correctamente.',
                        'accion_url': f'/admin/usuarios/configurarsemana/?taller={object_id}',
                        'accion_texto': 'Modificar Configuración'
                    }
            except Taller.DoesNotExist:
                pass
        
        return super().change_view(request, object_id, form_url, extra_context)
    
    fieldsets = (
        ('Información General', {
            'fields': ('nombre', 'telefono', 'foto_perfil')
        }),
        ('Datos del Onboarding', {
            'fields': ('descripcion', 'rut'),
        }),
        ('Especialidades y Marcas', {
            'fields': ('especialidades', 'marcas_atendidas'),
            'description': 'Especialidades que ofrece el taller y marcas de vehículos que atiende'
        }),
        ('Ubicación', {
            'fields': ('ubicacion',),
        }),
        ('Configuración de Servicio', {
            'fields': ('horario_atencion', 'capacidad_diaria', 'activo'),
        }),
        ('Estado de Verificación', {
            'fields': (
                'estado_verificacion', 'verificado', 'onboarding_completado',
                'fecha_verificacion', 'verificado_por'
            ),
            'classes': ('collapse',),
        }),
        ('Calificaciones', {
            'fields': ('calificacion_promedio', 'numero_de_calificaciones'),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('fecha_registro', 'ultima_actualizacion'),
            'classes': ('collapse',),
        }),
    )
    
    def aprobar_verificacion(self, request, queryset):
        """Acción para aprobar la verificación de talleres seleccionados"""
        for taller in queryset:
            taller.aprobar_verificacion(request.user)
        self.message_user(request, f'{queryset.count()} taller(es) aprobado(s) exitosamente.')
    aprobar_verificacion.short_description = 'Aprobar verificación de talleres seleccionados'
    
    def rechazar_verificacion(self, request, queryset):
        """Acción para rechazar la verificación de talleres seleccionados"""
        for taller in queryset:
            taller.rechazar_verificacion(request.user)
        self.message_user(request, f'{queryset.count()} taller(es) rechazado(s).')
    rechazar_verificacion.short_description = 'Rechazar verificación de talleres seleccionados'
    
    def marcar_en_revision(self, request, queryset):
        """Acción para marcar talleres como en revisión"""
        for taller in queryset:
            taller.marcar_en_revision(request.user)
        self.message_user(request, f'{queryset.count()} taller(es) marcado(s) como en revisión.')
    marcar_en_revision.short_description = 'Marcar como en revisión'

admin.site.register(Taller, TallerAdmin)
admin.site.register(HorarioProveedor, HorarioProveedorAdmin)
admin.site.register(ConfiguracionSemanalProveedor, ConfiguracionSemanalProveedorAdmin)

# Admin para el modelo MecanicoDomicilio
class MecanicoDomicilioAdmin(GISModelAdmin):
    list_display = (
        'nombre', 'telefono', 'disponible', 'estado_verificacion', 
        'verificado', 'onboarding_completado', 'get_usuario', 'calificacion_promedio', 'get_horarios_configurados'
    )
    search_fields = ('nombre', 'telefono', 'usuario__username', 'usuario__email', 'dni')
    list_filter = ('disponible', 'estado_verificacion', 'verificado', 'onboarding_completado', 'calificacion_promedio')
    inlines = [HorarioProveedorInline, DocumentoOnboardingInline]
    readonly_fields = ('fecha_registro', 'ultima_actualizacion', 'fecha_verificacion')
    
    # Agregar campos Many-to-Many para mostrar en el admin
    filter_horizontal = ('especialidades', 'marcas_atendidas')
    
    actions = ['aprobar_verificacion', 'rechazar_verificacion', 'marcar_en_revision', 'configurar_horarios_semanales']
    
    def get_horarios_configurados(self, obj):
        """Mostrar cuántos días tiene configurados con botón de configuración rápida"""
        horarios_activos = obj.horarios_configurados.filter(activo=True).count()
        total_horarios = obj.horarios_configurados.count()
        
        # Botón para configurar rápidamente
        config_url = f'/admin/usuarios/configurarsemana/?mecanico={obj.id}'
        config_button = f'<a href="{config_url}" style="background: #417690; color: white; padding: 3px 6px; border-radius: 3px; text-decoration: none; margin-left: 5px;">⚡ Configurar</a>'
        
        if total_horarios == 0:
            return format_html('<span style="color: red;">Sin horarios</span> {}', config_button)
        elif horarios_activos == 0:
            return format_html('<span style="color: orange;">{} días (todos inactivos)</span> {}', total_horarios, config_button)
        else:
            return format_html('<span style="color: green;">{} días activos / {} total</span> {}', horarios_activos, total_horarios, config_button)
    
    get_horarios_configurados.short_description = 'Horarios Configurados'
    
    def configurar_horarios_semanales(self, request, queryset):
        """Acción para configurar horarios semanales para mecánicos seleccionados"""
        if queryset.count() > 1:
            self.message_user(
                request, 
                "Seleccione solo un mecánico para configurar sus horarios semanales", 
                level=messages.ERROR
            )
            return
        
        mecanico = queryset.first()
        return HttpResponseRedirect(f'/admin/usuarios/configurarsemana/?mecanico={mecanico.id}')
    
    configurar_horarios_semanales.short_description = '⚡ Configurar horarios semanales'
    
    def change_view(self, request, object_id, form_url='', extra_context=None):
        """Personalizar la vista de edición con información sobre configuración de horarios"""
        extra_context = extra_context or {}
        
        if object_id:
            try:
                mecanico = MecanicoDomicilio.objects.get(pk=object_id)
                horarios_count = mecanico.horarios_configurados.count()
                
                if horarios_count < 7:
                    extra_context['horarios_info'] = {
                        'tipo': 'warning',
                        'mensaje': f'⚠️ Solo {horarios_count} días configurados de 7. Los días faltantes se crearán automáticamente al guardar.',
                        'accion_url': f'/admin/usuarios/configurarsemana/?mecanico={object_id}',
                        'accion_texto': 'Configurar Semana Completa'
                    }
                elif mecanico.horarios_configurados.filter(activo=True).count() == 0:
                    extra_context['horarios_info'] = {
                        'tipo': 'error',
                        'mensaje': '❌ Todos los días están inactivos. Configure al menos un día de atención.',
                        'accion_url': f'/admin/usuarios/configurarsemana/?mecanico={object_id}',
                        'accion_texto': 'Activar Días de Atención'
                    }
                else:
                    activos = mecanico.horarios_configurados.filter(activo=True).count()
                    extra_context['horarios_info'] = {
                        'tipo': 'success',
                        'mensaje': f'✅ {activos} días activos configurados correctamente.',
                        'accion_url': f'/admin/usuarios/configurarsemana/?mecanico={object_id}',
                        'accion_texto': 'Modificar Configuración'
                    }
            except MecanicoDomicilio.DoesNotExist:
                pass
        
        return super().change_view(request, object_id, form_url, extra_context)
    
    fieldsets = (
        ('Información General', {
            'fields': ('usuario', 'nombre', 'telefono', 'disponible', 'foto_perfil')
        }),
        ('Datos del Onboarding', {
            'fields': ('descripcion', 'dni', 'experiencia_anos'),
        }),
        ('Especialidades y Marcas', {
            'fields': ('especialidades', 'marcas_atendidas'),
            'description': 'Especialidades que maneja el mecánico y marcas de vehículos que atiende'
        }),
        ('Ubicación y Cobertura', {
            'fields': ('ubicacion', 'radio_cobertura'),
        }),
        ('Disponibilidad', {
            'fields': ('disponibilidad',),
        }),
        ('Estado de Verificación', {
            'fields': (
                'estado_verificacion', 'verificado', 'onboarding_completado',
                'fecha_verificacion', 'verificado_por'
            ),
            'classes': ('collapse',),
        }),
        ('Calificaciones', {
            'fields': ('calificacion_promedio', 'numero_de_calificaciones'),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('fecha_registro', 'ultima_actualizacion'),
            'classes': ('collapse',),
        }),
    )
    
    def get_usuario(self, obj):
        return obj.usuario.username if obj.usuario else "No asociado"
    get_usuario.short_description = 'Usuario'
    
    def aprobar_verificacion(self, request, queryset):
        """Acción para aprobar la verificación de mecánicos seleccionados"""
        for mecanico in queryset:
            mecanico.aprobar_verificacion(request.user)
        self.message_user(request, f'{queryset.count()} mecánico(s) aprobado(s) exitosamente.')
    aprobar_verificacion.short_description = 'Aprobar verificación de mecánicos seleccionados'
    
    def rechazar_verificacion(self, request, queryset):
        """Acción para rechazar la verificación de mecánicos seleccionados"""
        for mecanico in queryset:
            mecanico.rechazar_verificacion(request.user)
        self.message_user(request, f'{queryset.count()} mecánico(s) rechazado(s).')
    rechazar_verificacion.short_description = 'Rechazar verificación de mecánicos seleccionados'
    
    def marcar_en_revision(self, request, queryset):
        """Acción para marcar mecánicos como en revisión"""
        for mecanico in queryset:
            mecanico.marcar_en_revision(request.user)
        self.message_user(request, f'{queryset.count()} mecánico(s) marcado(s) como en revisión.')
    marcar_en_revision.short_description = 'Marcar como en revisión'

admin.site.register(MecanicoDomicilio, MecanicoDomicilioAdmin)

# Admin para el modelo ZonaCobertura
class ZonaCoberturaAdmin(admin.ModelAdmin):
    list_display = ['proveedor', 'nombre', 'activa', 'fecha_creacion']
    list_filter = ['activa', 'fecha_creacion']
    search_fields = ['proveedor__nombre', 'nombre']
    readonly_fields = ['fecha_creacion']


# NUEVO: Admin para Zonas de Servicio
@admin.register(MechanicServiceArea)
class MechanicServiceAreaAdmin(admin.ModelAdmin):
    list_display = [
        'mechanic', 
        'name', 
        'area_type', 
        'get_commune_count', 
        'is_active', 
        'created_at'
    ]
    list_filter = [
        'area_type', 
        'is_active', 
        'created_at',
        'mechanic__verificado'
    ]
    search_fields = [
        'mechanic__nombre',
        'name',
        'commune_names'
    ]
    readonly_fields = ['id', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Información Básica', {
            'fields': ('id', 'mechanic', 'area_type', 'name', 'is_active')
        }),
        ('Zonas de Cobertura', {
            'fields': ('commune_names',),
            'description': 'Seleccione las comunas donde el mecánico presta servicios'
        }),
        ('Metadatos', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def get_commune_count(self, obj):
        """Muestra el número de comunas en la zona"""
        return obj.get_commune_count()
    get_commune_count.short_description = 'Comunas'
    get_commune_count.admin_order_field = 'commune_names'
    
    def get_queryset(self, request):
        """Optimizar consultas"""
        return super().get_queryset(request).select_related('mechanic')


# NUEVO: Admin para Comunas Chilenas
@admin.register(ChileanCommune)
class ChileanCommuneAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'region_name', 
        'province_name',
        'code',
        'is_active'
    ]
    list_filter = [
        'region_name',
        'province_name', 
        'is_active'
    ]
    search_fields = [
        'name',
        'code',
        'region_name',
        'province_name'
    ]
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('Información de la Comuna', {
            'fields': ('code', 'name', 'is_active')
        }),
        ('Ubicación Administrativa', {
            'fields': ('region_code', 'region_name', 'province_name')
        }),
        ('Metadatos', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        })
    )
    
    actions = ['activate_communes', 'deactivate_communes']
    
    def activate_communes(self, request, queryset):
        """Activar comunas seleccionadas"""
        updated = queryset.update(is_active=True)
        self.message_user(
            request,
            f'{updated} comunas han sido activadas.'
        )
    activate_communes.short_description = "Activar comunas seleccionadas"
    
    def deactivate_communes(self, request, queryset):
        """Desactivar comunas seleccionadas"""
        updated = queryset.update(is_active=False)
        self.message_user(
            request,
            f'{updated} comunas han sido desactivadas.'
        )
    deactivate_communes.short_description = "Desactivar comunas seleccionadas"

# Admin para el modelo Resena
class ResenaAdmin(admin.ModelAdmin):
    list_display = ('cliente', 'get_resena_para', 'calificacion', 'fecha_hora_resena')
    list_filter = ('calificacion', 'fecha_hora_resena')
    search_fields = ('cliente__nombre', 'cliente__apellido', 'taller__nombre', 'mecanico__nombre', 'comentario')
    date_hierarchy = 'fecha_hora_resena'
    
    def get_resena_para(self, obj):
        if obj.taller:
            return f"Taller: {obj.taller.nombre}"
        elif obj.mecanico:
            return f"Mecánico: {obj.mecanico.nombre}"
        return "No especificado"
    get_resena_para.short_description = 'Reseña para'

admin.site.register(Resena, ResenaAdmin)

@admin.register(DireccionUsuario)
class DireccionUsuarioAdmin(admin.ModelAdmin):
    list_display = ('id', 'usuario', 'direccion', 'etiqueta', 'es_principal', 'fecha_creacion')
    list_filter = ('es_principal', 'etiqueta', 'fecha_creacion')
    search_fields = ('direccion', 'detalles', 'usuario__username')
    list_per_page = 20
    raw_id_fields = ('usuario',)

# Admin para DocumentoOnboarding
class DocumentoOnboardingAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'tipo_documento', 'fecha_subida', 'verificado', 'get_proveedor')
    list_filter = ('tipo_documento', 'verificado', 'fecha_subida')
    search_fields = ('taller__nombre', 'mecanico__nombre', 'nombre_original')
    readonly_fields = ('fecha_subida', 'vista_previa')
    
    fieldsets = (
        ('Información del Documento', {
            'fields': ('tipo_documento', 'archivo', 'vista_previa', 'nombre_original', 'fecha_subida')
        }),
        ('Proveedor', {
            'fields': ('taller', 'mecanico')
        }),
        ('Verificación', {
            'fields': ('verificado', 'comentarios_verificacion')
        }),
    )
    
    def vista_previa(self, obj):
        if obj.archivo:
            if obj.es_imagen():
                return format_html(
                    '<img src="{}" style="max-width: 100px; max-height: 100px;" />',
                    obj.archivo.url
                )
            elif obj.es_pdf():
                return format_html(
                    '<a href="{}" target="_blank">📄 Ver PDF</a>',
                    obj.archivo.url
                )
            else:
                return format_html(
                    '<a href="{}" target="_blank">📎 Descargar archivo</a>',
                    obj.archivo.url
                )
        return "No disponible"
    vista_previa.short_description = 'Vista Previa'
    
    def get_proveedor(self, obj):
        if obj.taller:
            return f"Taller: {obj.taller.nombre}"
        elif obj.mecanico:
            return f"Mecánico: {obj.mecanico.nombre}"
        return "No especificado"
    get_proveedor.short_description = 'Proveedor'

admin.site.register(DocumentoOnboarding, DocumentoOnboardingAdmin)


@admin.register(WebPushSubscription)
class WebPushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'endpoint_preview', 'user_agent_preview', 'activo', 'fecha_creacion')
    list_filter = ('activo', 'fecha_creacion')
    search_fields = ('usuario__username', 'usuario__email', 'endpoint')
    readonly_fields = ('endpoint', 'p256dh', 'auth', 'fecha_creacion', 'fecha_actualizacion')
    list_per_page = 30
    actions = ['desactivar_suscripciones']

    def endpoint_preview(self, obj):
        ep = obj.endpoint or ''
        preview = ep[:60] + '…' if len(ep) > 60 else ep
        color = 'green' if obj.activo else 'gray'
        return format_html('<span style="color:{};">{}</span>', color, preview)
    endpoint_preview.short_description = 'Endpoint'

    def user_agent_preview(self, obj):
        ua = obj.user_agent or ''
        return ua[:60] + '…' if len(ua) > 60 else ua
    user_agent_preview.short_description = 'Navegador'

    def desactivar_suscripciones(self, request, queryset):
        updated = queryset.update(activo=False)
        self.message_user(request, f'{updated} suscripcion(es) desactivada(s).')
    desactivar_suscripciones.short_description = 'Desactivar suscripciones seleccionadas'