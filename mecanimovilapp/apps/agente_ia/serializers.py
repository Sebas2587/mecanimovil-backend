"""Serializers del agente IA."""
from rest_framework import serializers

from mecanimovilapp.apps.agente_ia.models import (
    AgenteConversacionSesion,
    TallerAgenteConfig,
    TallerConocimientoDocumento,
)


class TallerAgenteConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = TallerAgenteConfig
        fields = [
            'habilitado',
            'instrucciones_personalizadas',
            'canales_habilitados',
            'mensaje_bienvenida',
            'actualizado_en',
        ]
        read_only_fields = ['actualizado_en']


class TallerConocimientoDocumentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TallerConocimientoDocumento
        fields = [
            'id',
            'titulo',
            'archivo',
            'texto_pegado',
            'estado_procesamiento',
            'error_detalle',
            'creado_en',
            'actualizado_en',
        ]
        read_only_fields = [
            'id',
            'estado_procesamiento',
            'error_detalle',
            'creado_en',
            'actualizado_en',
        ]


class AgenteSesionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgenteConversacionSesion
        fields = [
            'id',
            'conversation_id',
            'estado',
            'datos_capturados',
            'habilitado_en_chat',
            'pausado_por_taller',
            'pausado_hasta',
            'cotizacion_borrador',
            'ultima_interaccion_ia',
        ]
        read_only_fields = fields
