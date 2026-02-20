"""
Admin adicional para modelos de créditos y suscripciones mensuales.
Se importa desde admin.py principal.
"""
from django.contrib import admin
from .models import (
    CreditoProveedor,
    PaqueteCreditos,
    CompraCreditos,
    ConsumoCredito,
    ConfiguracionCreditos,
    ConfiguracionCreditosServicio,
    ProveedorCancelaciones,
    PlanSuscripcion,
    SuscripcionProveedor,
)


@admin.register(ConfiguracionCreditos)
class ConfiguracionCreditosAdmin(admin.ModelAdmin):
    """Admin para ConfiguracionCreditos"""
    list_display = [
        'aov_promedio',
        'tasa_comision',
        'k_promedio',
        'precio_credito_base',
        'creditos_expiracion_meses',
        'activo',
        'fecha_actualizacion'
    ]
    list_filter = ['activo']
    readonly_fields = ['precio_credito_base', 'fecha_creacion', 'fecha_actualizacion']
    
    fieldsets = (
        ('Configuración Financiera', {
            'fields': ('aov_promedio', 'tasa_comision', 'k_promedio', 'precio_credito_base')
        }),
        ('Configuración de Expiración', {
            'fields': ('creditos_expiracion_meses',)
        }),
        ('Estado', {
            'fields': ('activo',)
        }),
        ('Fechas', {
            'fields': ('fecha_creacion', 'fecha_actualizacion'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        """Recalcular precio_credito_base al guardar"""
        obj.save()  # El save() del modelo ya calcula precio_credito_base


@admin.register(ConfiguracionCreditosServicio)
class ConfiguracionCreditosServicioAdmin(admin.ModelAdmin):
    """Admin para ConfiguracionCreditosServicio"""
    list_display = [
        'servicio',
        'creditos_requeridos',
        'activo',
        'fecha_actualizacion'
    ]
    list_filter = ['activo']
    search_fields = ['servicio__nombre']
    ordering = ['servicio__nombre']
    readonly_fields = ['fecha_creacion', 'fecha_actualizacion']
    
    fieldsets = (
        ('Servicio', {
            'fields': ('servicio',)
        }),
        ('Configuración', {
            'fields': ('creditos_requeridos', 'activo')
        }),
        ('Fechas', {
            'fields': ('fecha_creacion', 'fecha_actualizacion'),
            'classes': ('collapse',)
        }),
    )


@admin.register(PaqueteCreditos)
class PaqueteCreditosAdmin(admin.ModelAdmin):
    """Admin para PaqueteCreditos"""
    list_display = [
        'nombre',
        'cantidad_creditos',
        'bonificacion_creditos',
        'precio',
        'precio_por_credito',
        'total_creditos',
        'activo',
        'orden',
        'destacado'
    ]
    list_filter = ['activo', 'destacado']
    search_fields = ['nombre']
    ordering = ['orden', 'precio']
    readonly_fields = ['precio_por_credito', 'total_creditos', 'fecha_creacion', 'fecha_actualizacion']
    
    fieldsets = (
        ('Información Básica', {
            'fields': ('nombre', 'activo', 'orden', 'destacado')
        }),
        ('Créditos y Precio', {
            'fields': ('cantidad_creditos', 'bonificacion_creditos', 'precio', 'precio_por_credito', 'total_creditos')
        }),
        ('Fechas', {
            'fields': ('fecha_creacion', 'fecha_actualizacion'),
            'classes': ('collapse',)
        }),
    )


@admin.register(CreditoProveedor)
class CreditoProveedorAdmin(admin.ModelAdmin):
    """Admin para CreditoProveedor"""
    list_display = [
        'proveedor',
        'saldo_creditos',
        'creditos_expirados',
        'fecha_ultima_compra',
        'fecha_ultimo_consumo',
        'fecha_actualizacion'
    ]
    list_filter = ['fecha_ultima_compra', 'fecha_ultimo_consumo']
    search_fields = ['proveedor__username', 'proveedor__email']
    ordering = ['-fecha_actualizacion']
    readonly_fields = ['fecha_creacion', 'fecha_actualizacion']
    
    fieldsets = (
        ('Proveedor', {
            'fields': ('proveedor',)
        }),
        ('Saldo', {
            'fields': ('saldo_creditos', 'creditos_expirados')
        }),
        ('Fechas', {
            'fields': ('fecha_ultima_compra', 'fecha_ultimo_consumo', 'fecha_creacion', 'fecha_actualizacion')
        }),
    )


@admin.register(CompraCreditos)
class CompraCreditosAdmin(admin.ModelAdmin):
    """Admin para CompraCreditos"""
    list_display = [
        'proveedor',
        'paquete',
        'cantidad_creditos',
        'precio_total',
        'metodo_pago',
        'estado',
        'fecha_compra',
        'fecha_expiracion_creditos'
    ]
    list_filter = ['estado', 'metodo_pago', 'fecha_compra']
    search_fields = ['proveedor__username', 'proveedor__email', 'payment_id_mp']
    ordering = ['-fecha_compra']
    readonly_fields = ['fecha_compra', 'fecha_actualizacion']
    
    fieldsets = (
        ('Proveedor y Paquete', {
            'fields': ('proveedor', 'paquete')
        }),
        ('Detalles de Compra', {
            'fields': ('cantidad_creditos', 'precio_total', 'metodo_pago', 'estado', 'payment_id_mp')
        }),
        ('Fechas', {
            'fields': ('fecha_compra', 'fecha_expiracion_creditos', 'fecha_actualizacion')
        }),
    )
    
    def save_model(self, request, obj, form, change):
        """
        Intercepta el guardado para asegurar que los créditos se acrediten
        cuando se marca una compra como completada.
        """
        from .creditos_services import confirmar_compra_creditos
        
        # Si es una actualización (change=True) y el estado cambió a 'completada'
        if change:
            # Obtener el objeto original de la base de datos
            try:
                obj_original = CompraCreditos.objects.get(pk=obj.pk)
                estado_original = obj_original.estado
                estado_nuevo = obj.estado
                
                # Si el estado cambió de algo diferente a 'completada' a 'completada'
                if estado_original != 'completada' and estado_nuevo == 'completada':
                    # Usar confirmar_compra_creditos para asegurar que los créditos se agreguen
                    try:
                        confirmar_compra_creditos(obj.id, obj.payment_id_mp)
                        # El objeto ya fue actualizado por confirmar_compra_creditos
                        return
                    except Exception as e:
                        from django.contrib import messages
                        messages.error(
                            request,
                            f'Error al confirmar la compra y acreditar créditos: {str(e)}. '
                            f'Los créditos NO fueron agregados al saldo del proveedor.'
                        )
                        # Si falla, no guardar el cambio de estado
                        obj.estado = estado_original
                        obj.save()
                        return
                # Si ya estaba completada y se intenta cambiar a otra cosa, prevenir
                elif estado_original == 'completada' and estado_nuevo != 'completada':
                    from django.contrib import messages
                    messages.warning(
                        request,
                        'No se puede cambiar el estado de una compra completada. '
                        'Los créditos ya fueron acreditados.'
                    )
                    # Mantener el estado original
                    obj.estado = estado_original
                    obj.save()
                    return
            except CompraCreditos.DoesNotExist:
                pass
        
        # Guardar normalmente si no hay cambios de estado a completada
        obj.save()


@admin.register(ConsumoCredito)
class ConsumoCreditoAdmin(admin.ModelAdmin):
    """Admin para ConsumoCredito"""
    list_display = [
        'proveedor',
        'servicio',
        'creditos_consumidos',
        'precio_credito',
        'fecha_consumo',
        'oferta'
    ]
    list_filter = ['fecha_consumo', 'servicio']
    search_fields = ['proveedor__username', 'servicio__nombre', 'oferta__id']
    ordering = ['-fecha_consumo']
    readonly_fields = ['fecha_consumo', 'fecha_actualizacion']
    
    fieldsets = (
        ('Proveedor y Oferta', {
            'fields': ('proveedor', 'oferta')
        }),
        ('Servicio y Consumo', {
            'fields': ('servicio', 'creditos_consumidos', 'precio_credito')
        }),
        ('Fechas', {
            'fields': ('fecha_consumo', 'fecha_actualizacion')
        }),
    )


@admin.register(ProveedorCancelaciones)
class ProveedorCancelacionesAdmin(admin.ModelAdmin):
    """Admin para ProveedorCancelaciones"""
    list_display = [
        'proveedor',
        'cancelaciones_mes_actual',
        'suspension_temporal',
        'fecha_suspension',
        'fecha_reset_cancelaciones',
        'fecha_actualizacion'
    ]
    list_filter = ['suspension_temporal', 'fecha_suspension']
    search_fields = ['proveedor__username', 'proveedor__email']
    ordering = ['-fecha_actualizacion']
    readonly_fields = ['fecha_creacion', 'fecha_actualizacion']
    
    fieldsets = (
        ('Proveedor', {
            'fields': ('proveedor',)
        }),
        ('Cancelaciones', {
            'fields': ('cancelaciones_mes_actual', 'fecha_reset_cancelaciones')
        }),
        ('Suspensión', {
            'fields': ('suspension_temporal', 'fecha_suspension')
        }),
        ('Fechas', {
            'fields': ('fecha_creacion', 'fecha_actualizacion'),
            'classes': ('collapse',)
        }),
    )



# ============================================================================
# ADMIN PARA SUSCRIPCIONES MENSUALES
# ============================================================================

@admin.register(PlanSuscripcion)
class PlanSuscripcionAdmin(admin.ModelAdmin):
    """Admin para PlanSuscripcion — gestión de planes disponibles."""
    list_display = ['nombre', 'precio', 'creditos_mensuales', 'activo', 'destacado', 'orden']
    list_filter = ['activo', 'destacado']
    search_fields = ['nombre']
    ordering = ['orden', 'precio']
    readonly_fields = ['fecha_creacion', 'fecha_actualizacion']

    fieldsets = (
        ('Información del Plan', {
            'fields': ('nombre', 'descripcion', 'activo', 'destacado', 'orden')
        }),
        ('Precios y Créditos', {
            'fields': ('precio', 'creditos_mensuales')
        }),
        ('MercadoPago (opcional)', {
            'fields': ('mp_preapproval_plan_id',),
            'classes': ('collapse',),
        }),
        ('Fechas', {
            'fields': ('fecha_creacion', 'fecha_actualizacion'),
            'classes': ('collapse',)
        }),
    )


@admin.register(SuscripcionProveedor)
class SuscripcionProveedorAdmin(admin.ModelAdmin):
    """Admin para SuscripcionProveedor — estado de suscripciones por proveedor."""
    list_display = [
        'proveedor', 'plan', 'estado',
        'mp_preapproval_id', 'fecha_inicio', 'fecha_proximo_cobro',
    ]
    list_filter = ['estado', 'plan']
    search_fields = ['proveedor__username', 'proveedor__email', 'mp_preapproval_id']
    ordering = ['-fecha_inicio']
    readonly_fields = [
        'fecha_inicio', 'fecha_actualizacion',
        'mp_preapproval_id', 'mp_init_point', 'ultimo_charge_id',
    ]

    fieldsets = (
        ('Proveedor y Plan', {
            'fields': ('proveedor', 'plan', 'estado')
        }),
        ('MercadoPago', {
            'fields': ('mp_preapproval_id', 'mp_init_point', 'ultimo_charge_id'),
        }),
        ('Fechas', {
            'fields': ('fecha_inicio', 'fecha_proximo_cobro', 'fecha_cancelacion', 'fecha_actualizacion'),
        }),
    )
