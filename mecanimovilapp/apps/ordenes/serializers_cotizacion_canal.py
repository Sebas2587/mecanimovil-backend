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
    conversation_id = serializers.IntegerField()
    servicio_nombre = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    descripcion_problema = serializers.CharField(required=False, allow_blank=True, default='')
    modalidad = serializers.ChoiceField(choices=('taller', 'domicilio'), default='taller')
    vehiculo = serializers.DictField(required=False, default=dict)
    plantilla_id = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
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
    class Meta:
        model = CotizacionCanalPlantilla
        fields = (
            'id',
            'titulo',
            'snapshot',
            'uso_count',
            'creado_en',
            'actualizado_en',
        )
        read_only_fields = ('id', 'uso_count', 'creado_en', 'actualizado_en')


class GuardarPlantillaCotizacionSerializer(serializers.Serializer):
    titulo = serializers.CharField(max_length=255)
    cotizacion_id = serializers.IntegerField(required=False, allow_null=True)
    snapshot = serializers.DictField(required=False)
