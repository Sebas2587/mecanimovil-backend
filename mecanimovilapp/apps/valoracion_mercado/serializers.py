from rest_framework import serializers


class ValoracionVehiculoSerializer(serializers.Serializer):
    vehiculo_id = serializers.IntegerField()
    valor_real_hoy = serializers.IntegerField()
    valor_real_rango_min = serializers.IntegerField()
    valor_real_rango_max = serializers.IntegerField()
    confianza = serializers.CharField()
    liquidez = serializers.DictField()
    demanda = serializers.DictField(required=False)
    proyeccion = serializers.ListField()
    histograma = serializers.ListField()
    meta = serializers.DictField()
    fecha_calculo = serializers.CharField()
    currency = serializers.CharField(default='CLP')
