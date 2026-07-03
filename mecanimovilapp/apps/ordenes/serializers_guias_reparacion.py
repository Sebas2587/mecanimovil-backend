from rest_framework import serializers

from mecanimovilapp.apps.ordenes.models import GuiaReparacionGuardada


class GuiaReparacionGuardadaSerializer(serializers.ModelSerializer):
    class Meta:
        model = GuiaReparacionGuardada
        fields = [
            'id',
            'vehiculo_marca',
            'vehiculo_modelo',
            'vehiculo_anio',
            'vehiculo_patente',
            'titulo',
            'contenido',
            'origen',
            'origen_id',
            'creado_en',
        ]
        read_only_fields = fields


class GuardarGuiaReparacionSerializer(serializers.Serializer):
    origen = serializers.ChoiceField(choices=['orden', 'cita'])
    origen_id = serializers.IntegerField(min_value=1)
    diagnostico_id = serializers.IntegerField(min_value=1)
