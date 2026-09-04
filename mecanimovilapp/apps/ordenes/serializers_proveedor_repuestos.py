"""Serializers de casas de repuestos y precios propios del taller."""
from __future__ import annotations

from rest_framework import serializers

from mecanimovilapp.apps.ordenes.models import PrecioProveedorTaller, ProveedorRepuestos


class ProveedorRepuestosSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProveedorRepuestos
        fields = (
            'id',
            'nombre',
            'tipo',
            'comuna',
            'telefono',
            'direccion',
            'dominio',
            'descuento_pct',
            'dias_credito',
            'entrega',
            'es_preferido',
            'activo',
            'notas',
            'creado_en',
            'actualizado_en',
        )
        read_only_fields = ('id', 'creado_en', 'actualizado_en')


class PrecioProveedorTallerSerializer(serializers.ModelSerializer):
    proveedor_nombre = serializers.CharField(source='proveedor.nombre', read_only=True, default='')
    vigente = serializers.SerializerMethodField()

    class Meta:
        model = PrecioProveedorTaller
        fields = (
            'id',
            'proveedor',
            'proveedor_nombre',
            'nombre_repuesto',
            'marca_repuesto',
            'codigo_parte',
            'especificacion',
            'categoria',
            'precio_clp',
            'precio_venta_clp',
            'vehiculo_marca',
            'vehiculo_modelo',
            'vehiculo_anio',
            'tipo_motor',
            'cilindraje',
            'origen',
            'precio_referencia_web_clp',
            'vigente_hasta',
            'vigente',
            'registrado_en',
        )
        read_only_fields = ('id', 'registrado_en', 'proveedor_nombre', 'vigente')

    def get_vigente(self, obj) -> bool:
        from mecanimovilapp.apps.ordenes.services.precios_proveedor import _vigente
        from django.utils import timezone

        return _vigente(obj, timezone.now())


class ConfirmarPrecioRepuestoSerializer(serializers.Serializer):
    repuesto_id = serializers.CharField(max_length=64)
    precio_clp = serializers.IntegerField(min_value=1)
    proveedor_id = serializers.IntegerField(required=False, allow_null=True)
    proveedor_nombre = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    especificacion = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')
    guardar_en_mis_precios = serializers.BooleanField(required=False, default=True)


class AsumirPrecioRepuestoSerializer(serializers.Serializer):
    repuesto_id = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        allow_empty=True,
    )


class DefinirEspecificacionSerializer(serializers.Serializer):
    repuesto_id = serializers.CharField(max_length=64)
    especificacion = serializers.CharField(max_length=120)


class DefinirCalidadSerializer(serializers.Serializer):
    repuesto_id = serializers.CharField(max_length=64)
    calidad = serializers.ChoiceField(choices=('original', 'oem', 'alternativo'))


class UsarOpcionRepuestoSerializer(serializers.Serializer):
    repuesto_id = serializers.CharField(max_length=64)
    opcion_id = serializers.CharField(max_length=64)
    guardar_en_mis_precios = serializers.BooleanField(required=False, default=False)


class RegistrarCompraItemSerializer(serializers.Serializer):
    repuesto_id = serializers.CharField(max_length=64)
    precio_clp = serializers.IntegerField(min_value=1)
    proveedor_id = serializers.IntegerField(required=False, allow_null=True)
    proveedor_nombre = serializers.CharField(max_length=120, required=False, allow_blank=True, default='')


class RegistrarCompraRepuestosSerializer(serializers.Serializer):
    items = RegistrarCompraItemSerializer(many=True)
