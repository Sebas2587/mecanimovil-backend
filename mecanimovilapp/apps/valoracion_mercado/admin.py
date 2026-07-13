from django.contrib import admin

from .models import (
    AvisoExternoVehiculo,
    CurvaDepreciacionSegmento,
    SegmentoValorHistorial,
    TasacionHistorial,
    ValoracionVehiculo,
)


@admin.register(AvisoExternoVehiculo)
class AvisoExternoVehiculoAdmin(admin.ModelAdmin):
    list_display = ('fuente', 'external_id', 'marca_texto', 'modelo_texto', 'year', 'precio', 'activo')
    list_filter = ('fuente', 'activo')
    search_fields = ('external_id', 'marca_texto', 'modelo_texto', 'titulo_raw')


@admin.register(SegmentoValorHistorial)
class SegmentoValorHistorialAdmin(admin.ModelAdmin):
    list_display = (
        'marca',
        'modelo',
        'year_bucket',
        'fecha_snapshot',
        'n_anuncios_activos',
        'precio_mediana',
        'tasa_rotacion_30d_pct',
    )
    list_filter = ('fecha_snapshot',)


@admin.register(TasacionHistorial)
class TasacionHistorialAdmin(admin.ModelAdmin):
    list_display = ('vehiculo', 'fecha', 'precio_mercado_promedio', 'banda_min', 'banda_max')
    list_filter = ('fecha',)


@admin.register(CurvaDepreciacionSegmento)
class CurvaDepreciacionSegmentoAdmin(admin.ModelAdmin):
    list_display = ('tipo_vehiculo', 'tasa_anual_pct', 'activo')


@admin.register(ValoracionVehiculo)
class ValoracionVehiculoAdmin(admin.ModelAdmin):
    list_display = (
        'vehiculo',
        'valor_real_hoy',
        'confianza',
        'liquidez_label',
        'liquidez_score',
        'fecha_calculo',
    )
    list_filter = ('confianza', 'liquidez_label')
