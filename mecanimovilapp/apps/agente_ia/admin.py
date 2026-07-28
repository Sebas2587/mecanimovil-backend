from django.contrib import admin

from mecanimovilapp.apps.agente_ia.models import (
    AgenteAprendizajeDiario,
    AgenteConversacionSesion,
    AgenteMensajeLog,
    LeadCalificacion,
    TallerAgenteConfig,
    TallerConocimientoChunk,
    TallerConocimientoDocumento,
)


@admin.register(TallerAgenteConfig)
class TallerAgenteConfigAdmin(admin.ModelAdmin):
    list_display = ('taller', 'nombre_agente', 'habilitado', 'actualizado_en')
    list_filter = ('habilitado',)
    search_fields = ('taller__nombre', 'nombre_agente')


@admin.register(TallerConocimientoDocumento)
class TallerConocimientoDocumentoAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'taller', 'estado_procesamiento', 'creado_en')
    list_filter = ('estado_procesamiento',)


@admin.register(TallerConocimientoChunk)
class TallerConocimientoChunkAdmin(admin.ModelAdmin):
    list_display = ('id', 'taller', 'fuente', 'referencia_externa', 'fecha_actualizacion')
    list_filter = ('fuente',)


@admin.register(AgenteConversacionSesion)
class AgenteConversacionSesionAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'taller', 'estado', 'pausado_por_taller')
    list_filter = ('estado', 'pausado_por_taller')


@admin.register(AgenteMensajeLog)
class AgenteMensajeLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'sesion', 'accion', 'fecha')
    list_filter = ('accion',)


@admin.register(LeadCalificacion)
class LeadCalificacionAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'taller', 'categoria', 'score', 'actualizado_en')
    list_filter = ('categoria', 'taller')
    search_fields = ('conversation_id',)


@admin.register(AgenteAprendizajeDiario)
class AgenteAprendizajeDiarioAdmin(admin.ModelAdmin):
    list_display = ('id', 'taller', 'fecha', 'tipo_hallazgo', 'creado_en')
    list_filter = ('tipo_hallazgo', 'fecha', 'taller')
    date_hierarchy = 'fecha'
