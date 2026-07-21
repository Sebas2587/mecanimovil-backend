"""Serializers cotización canal."""
from __future__ import annotations

from rest_framework import serializers

from mecanimovilapp.apps.ordenes.models import CotizacionCanal, CotizacionCanalPlantilla


class RepuestoCotizacionSerializer(serializers.Serializer):
    id = serializers.CharField(required=False, allow_blank=True)
    nombre = serializers.CharField(max_length=200)
    cantidad = serializers.IntegerField(min_value=1, default=1)
    precio_unitario_clp = serializers.IntegerField(min_value=0, default=0)
    precio_referencia_ia = serializers.IntegerField(required=False, min_value=0)
    comentario = serializers.CharField(required=False, allow_blank=True, default='')


class CotizacionCanalSerializer(serializers.ModelSerializer):
    repuestos = RepuestoCotizacionSerializer(many=True, required=False)
    share_url = serializers.SerializerMethodField()
    canal = serializers.SerializerMethodField()
    cliente_display = serializers.SerializerMethodField()
    cita_personal_id = serializers.SerializerMethodField()

    def get_share_url(self, obj) -> str | None:
        if obj.url_publica:
            return obj.url_publica
        if obj.token and obj.es_libre:
            from mecanimovilapp.apps.ordenes.services.cotizacion_publica import construir_url_publica_cotizacion
            return construir_url_publica_cotizacion(obj.token)
        return None

    def get_canal(self, obj) -> str:
        if obj.es_libre or obj.conversation_id is None:
            return 'directo'
        channel = (getattr(obj.conversation, 'source_channel', None) or 'APP').lower()
        if channel in ('whatsapp', 'instagram', 'messenger'):
            return channel
        return 'canal'

    def get_cliente_display(self, obj) -> str:
        if (obj.cliente_nombre or '').strip():
            return obj.cliente_nombre.strip()
        conv = obj.conversation
        if conv is not None:
            ext = getattr(conv, 'external_contact', None)
            name = getattr(ext, 'display_name', None) if ext else None
            if name:
                return str(name)
        parts = [obj.vehiculo_marca, obj.vehiculo_modelo]
        joined = ' '.join(p for p in parts if p).strip()
        return joined or 'Cliente'

    def get_cita_personal_id(self, obj) -> int | None:
        cache = self.context.setdefault('_cita_id_by_cotizacion', {})
        if obj.pk in cache:
            return cache[obj.pk]
        cita = (
            obj.citas_generadas.filter(estado='activa')
            .order_by('-fecha_creacion')
            .values_list('id', flat=True)
            .first()
        )
        cache[obj.pk] = cita
        return cita

    def to_representation(self, instance):
        data = super().to_representation(instance)
        for key in ('mano_obra_clp', 'costo_repuestos_clp', 'total_clp'):
            if data.get(key) is not None:
                data[key] = int(data[key])
        for rep in data.get('repuestos') or []:
            if rep.get('precio_unitario_clp') is not None:
                rep['precio_unitario_clp'] = int(rep['precio_unitario_clp'])
            ref = rep.get('precio_referencia_ia')
            if ref is not None:
                rep['precio_referencia_ia'] = int(ref)
        return data

    class Meta:
        model = CotizacionCanal
        fields = (
            'id',
            'conversation',
            'es_libre',
            'cliente_nombre',
            'cliente_telefono',
            'cliente_display',
            'canal',
            'cita_personal_id',
            'token',
            'url_publica',
            'share_url',
            'visto_en',
            'estado',
            'modalidad',
            'vehiculo_marca',
            'vehiculo_modelo',
            'vehiculo_anio',
            'vehiculo_patente',
            'vehiculo_cilindraje',
            'vehiculo_vin',
            'tipo_motor',
            'tipo_motor_label',
            'aviso_motor',
            'servicio_nombre',
            'descripcion_problema',
            'repuestos',
            'mano_obra_clp',
            'costo_repuestos_clp',
            'total_clp',
            'duracion_minutos_estimada',
            'advertencias',
            'message_envio',
            'enviada_en',
            'aceptada_en',
            'rechazada_en',
            'creado_en',
            'actualizado_en',
        )
        read_only_fields = (
            'id',
            'conversation',
            'es_libre',
            'cliente_display',
            'canal',
            'cita_personal_id',
            'token',
            'url_publica',
            'share_url',
            'visto_en',
            'estado',
            'costo_repuestos_clp',
            'total_clp',
            'message_envio',
            'enviada_en',
            'aceptada_en',
            'rechazada_en',
            'creado_en',
            'actualizado_en',
        )


class GenerarCotizacionIaSerializer(serializers.Serializer):
    conversation_id = serializers.IntegerField(required=False, allow_null=True)
    cliente_nombre = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    cliente_telefono = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')
    servicio_nombre = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    descripcion_problema = serializers.CharField(required=False, allow_blank=True, default='')
    modalidad = serializers.ChoiceField(choices=('taller', 'domicilio'), default='taller')
    vehiculo = serializers.DictField(required=False, default=dict)
    plantilla_id = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        conversation_id = attrs.get('conversation_id')
        if conversation_id is None:
            nombre = (attrs.get('cliente_nombre') or '').strip()
            if not nombre:
                raise serializers.ValidationError(
                    {'cliente_nombre': 'Indica el nombre del cliente para cotización libre.'},
                )
        if attrs.get('plantilla_id'):
            return attrs
        if not (attrs.get('servicio_nombre') or '').strip():
            raise serializers.ValidationError(
                {'servicio_nombre': 'Indica el servicio a cotizar.'},
            )
        v = attrs.get('vehiculo') or {}
        marca = str(v.get('marca') or '').strip()
        modelo = str(v.get('modelo') or '').strip()
        patente = str(v.get('patente') or '').strip()
        if not marca and not modelo and not patente:
            raise serializers.ValidationError(
                {'vehiculo': 'Indica patente o marca y modelo del vehículo.'},
            )
        if (not marca or not modelo) and not patente:
            raise serializers.ValidationError(
                {'vehiculo': 'Marca y modelo son necesarios para estimar repuestos.'},
            )
        return attrs


class CotizacionCanalPlantillaSerializer(serializers.ModelSerializer):
    vehiculo_marca = serializers.SerializerMethodField()
    vehiculo_modelo = serializers.SerializerMethodField()
    vehiculo_cilindraje = serializers.SerializerMethodField()

    class Meta:
        model = CotizacionCanalPlantilla
        fields = (
            'id',
            'titulo',
            'snapshot',
            'vehiculo_marca',
            'vehiculo_modelo',
            'vehiculo_cilindraje',
            'uso_count',
            'creado_en',
            'actualizado_en',
        )
        read_only_fields = ('id', 'uso_count', 'creado_en', 'actualizado_en')

    def _snap(self, obj) -> dict:
        return obj.snapshot or {}

    def get_vehiculo_marca(self, obj) -> str:
        return str(self._snap(obj).get('vehiculo_marca') or '')

    def get_vehiculo_modelo(self, obj) -> str:
        return str(self._snap(obj).get('vehiculo_modelo') or '')

    def get_vehiculo_cilindraje(self, obj) -> str:
        return str(self._snap(obj).get('vehiculo_cilindraje') or '')


class GuardarPlantillaCotizacionSerializer(serializers.Serializer):
    titulo = serializers.CharField(max_length=255)
    cotizacion_id = serializers.IntegerField(required=False, allow_null=True)
    snapshot = serializers.DictField(required=False)
