"""Serializers del agente IA."""
from rest_framework import serializers

from mecanimovilapp.apps.agente_ia.models import (
    AgenteConversacionSesion,
    TallerAgenteConfig,
    TallerConocimientoDocumento,
)
from mecanimovilapp.storage.utils import get_image_url

_TITULO_MAX = 120


class TallerAgenteConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = TallerAgenteConfig
        fields = [
            'habilitado',
            'nombre_agente',
            'instrucciones_personalizadas',
            'canales_habilitados',
            'mensaje_bienvenida',
            'recargo_domicilio_clp',
            'nivel_insistencia',
            'permite_estimados_historicos',
            'tono_ventas',
            'requiere_direccion_antes_de_cotizar',
            'actualizado_en',
        ]
        read_only_fields = ['actualizado_en']


class TallerConocimientoDocumentoSerializer(serializers.ModelSerializer):
    archivo_url = serializers.SerializerMethodField()
    tipo = serializers.SerializerMethodField()

    class Meta:
        model = TallerConocimientoDocumento
        fields = [
            'id',
            'titulo',
            'archivo',
            'archivo_url',
            'tipo',
            'texto_pegado',
            'estado_procesamiento',
            'error_detalle',
            'creado_en',
            'actualizado_en',
        ]
        read_only_fields = [
            'id',
            'archivo_url',
            'tipo',
            'estado_procesamiento',
            'error_detalle',
            'creado_en',
            'actualizado_en',
        ]
        extra_kwargs = {
            'archivo': {'required': False, 'allow_null': True},
        }

    def validate_titulo(self, value: str) -> str:
        titulo = (value or '').strip()
        if not titulo:
            raise serializers.ValidationError('El título es obligatorio.')
        # Truncar en vez de fallar: nombres de PDF largos son comunes.
        if len(titulo) > _TITULO_MAX:
            titulo = titulo[:_TITULO_MAX].rstrip()
        return titulo

    def get_archivo_url(self, obj) -> str | None:
        if not obj.archivo:
            return None
        request = self.context.get('request')
        return get_image_url(obj.archivo, request)

    def get_tipo(self, obj) -> str:
        if obj.archivo:
            name = (getattr(obj.archivo, 'name', '') or '').lower()
            if name.endswith('.pdf') or 'pdf' in name:
                return 'pdf'
            return 'archivo'
        if (obj.texto_pegado or '').strip():
            return 'texto'
        return 'otro'


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
            'cita_en_negociacion',
            'ultima_interaccion_ia',
        ]
        read_only_fields = fields
