from django.contrib import admin

from mecanimovilapp.apps.agente_ia.models import (
    AgenteConversacionSesion,
    AgenteMensajeLog,
    TallerAgenteConfig,
    TallerConocimientoChunk,
    TallerConocimientoDocumento,
)


@admin.register(TallerAgenteConfig)
class TallerAgenteConfigAdmin(admin.ModelAdmin):
    list_display = ('taller', 'habilitado', 'actualizado_en')
    list_filter = ('habilitado',)


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
