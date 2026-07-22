"""
Serializers para el sistema Pay-per-Win con créditos y Suscripciones Mensuales.
"""
from rest_framework import serializers
from .models import (
    CreditoProveedor,
    PaqueteCreditos,
    CompraCreditos,
    ConsumoCredito,
    ConfiguracionCreditos,
    ConfiguracionCreditosServicio,
    PlanSuscripcion,
    SuscripcionProveedor,
)


# ============================================================================
# SERIALIZERS DEL SISTEMA PAY-PER-WIN CON CRÉDITOS
# ============================================================================

class PaqueteCreditosSerializer(serializers.ModelSerializer):
    """Serializer para PaqueteCreditos"""
    precio_por_credito = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        read_only=True
    )
    total_creditos = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = PaqueteCreditos
        fields = [
            'id',
            'nombre',
            'cantidad_creditos',
            'precio',
            'precio_por_credito',
            'bonificacion_creditos',
            'total_creditos',
            'activo',
            'orden',
            'destacado',
            'fecha_creacion',
            'fecha_actualizacion'
        ]
        read_only_fields = ['id', 'fecha_creacion', 'fecha_actualizacion']


class CompraCreditosSerializer(serializers.ModelSerializer):
    """Serializer para CompraCreditos"""
    estado_display = serializers.CharField(source='get_estado_display', read_only=True)
    metodo_pago_display = serializers.CharField(source='get_metodo_pago_display', read_only=True)
    paquete = PaqueteCreditosSerializer(read_only=True)
    paquete_id = serializers.PrimaryKeyRelatedField(
        queryset=PaqueteCreditos.objects.filter(activo=True),
        source='paquete',
        write_only=True,
        required=False,
        allow_null=True
    )
    cantidad_creditos = serializers.IntegerField(required=False, min_value=1)
    proveedor_nombre = serializers.CharField(source='proveedor.username', read_only=True)
    
    class Meta:
        model = CompraCreditos
        fields = [
            'id',
            'proveedor',
            'proveedor_nombre',
            'paquete',
            'paquete_id',
            'cantidad_creditos',
            'precio_total',
            'metodo_pago',
            'metodo_pago_display',
            'estado',
            'estado_display',
            'payment_id_mp',
            'fecha_compra',
            'fecha_expiracion_creditos',
            'fecha_actualizacion'
        ]
        read_only_fields = [
            'id',
            'proveedor',
            'precio_total',
            'estado',
            'fecha_compra',
            'fecha_expiracion_creditos',
            'fecha_actualizacion'
        ]


class CreditoProveedorSerializer(serializers.ModelSerializer):
    """Serializer para CreditoProveedor"""
    proveedor_nombre = serializers.CharField(source='proveedor.username', read_only=True)
    
    class Meta:
        model = CreditoProveedor
        fields = [
            'id',
            'proveedor',
            'proveedor_nombre',
            'saldo_creditos',
            'fecha_ultima_compra',
            'fecha_ultimo_consumo',
            'creditos_expirados',
            'fecha_creacion',
            'fecha_actualizacion'
        ]
        read_only_fields = [
            'id',
            'proveedor',
            'saldo_creditos',
            'fecha_ultima_compra',
            'fecha_ultimo_consumo',
            'creditos_expirados',
            'fecha_creacion',
            'fecha_actualizacion'
        ]


class ConsumoCreditoSerializer(serializers.ModelSerializer):
    """Serializer para ConsumoCredito"""
    servicio_nombre = serializers.CharField(source='servicio.nombre', read_only=True)
    proveedor_nombre = serializers.CharField(source='proveedor.username', read_only=True)
    oferta_id = serializers.UUIDField(source='oferta.id', read_only=True)
    
    class Meta:
        model = ConsumoCredito
        fields = [
            'id',
            'proveedor',
            'proveedor_nombre',
            'oferta',
            'oferta_id',
            'servicio',
            'servicio_nombre',
            'creditos_consumidos',
            'precio_credito',
            'fecha_consumo',
            'fecha_actualizacion'
        ]
        read_only_fields = [
            'id',
            'proveedor',
            'oferta',
            'servicio',
            'creditos_consumidos',
            'precio_credito',
            'fecha_consumo',
            'fecha_actualizacion'
        ]


class EstadisticasCreditosSerializer(serializers.Serializer):
    """
    Serializer para estadísticas completas de créditos.
    No está basado en un modelo, sino en el resultado de obtener_estadisticas_creditos()
    """
    saldo_actual = serializers.IntegerField()
    precio_credito_unitario_clp = serializers.FloatField()
    creditos_consumidos_mes = serializers.IntegerField()
    creditos_comprados_mes = serializers.IntegerField()
    creditos_expirados = serializers.IntegerField()
    fecha_ultima_compra = serializers.CharField(allow_null=True)
    fecha_ultimo_consumo = serializers.CharField(allow_null=True)
    proxima_expiracion = serializers.DictField()
    historial_consumos = serializers.ListField()
    historial_compras = serializers.ListField()
    
    def to_representation(self, instance):
        """Retorna la representación de las estadísticas"""
        return instance


class ConfiguracionCreditosSerializer(serializers.ModelSerializer):
    """Serializer para ConfiguracionCreditos (solo lectura para admin)"""
    
    class Meta:
        model = ConfiguracionCreditos
        fields = [
            'id',
            'aov_promedio',
            'tasa_comision',
            'k_promedio',
            'precio_credito_base',
            'creditos_expiracion_meses',
            'activo',
            'fecha_creacion',
            'fecha_actualizacion'
        ]
        read_only_fields = [
            'id',
            'precio_credito_base',
            'fecha_creacion',
            'fecha_actualizacion'
        ]


# ============================================================================
# SERIALIZERS DEL SISTEMA DE SUSCRIPCIONES MENSUALES
# ============================================================================

class PlanSuscripcionSerializer(serializers.ModelSerializer):
    """Serializer para PlanSuscripcion — solo lectura en la API pública."""

    class Meta:
        model = PlanSuscripcion
        fields = [
            'id',
            'nombre',
            'descripcion',
            'precio',
            'creditos_mensuales',
            'cotizaciones_ia_mensuales',
            'diagnosticos_ia_mensuales',
            'consultas_patente_mensuales',
            'canales_mensajeria_max',
            'conversaciones_salientes_max',
            'overage_cotizaciones_por_credito',
            'overage_diagnosticos_por_credito',
            'overage_patentes_por_credito',
            'acceso_endpoints_patente_pro',
            'agente_ia_incluido',
            'conversaciones_agente_ia_max',
            'destacado',
            'orden',
            'fecha_creacion',
        ]
        read_only_fields = fields


class SuscripcionProveedorSerializer(serializers.ModelSerializer):
    """Serializer para SuscripcionProveedor con datos del plan embebidos."""

    plan = PlanSuscripcionSerializer(read_only=True)
    estado_display = serializers.CharField(source='get_estado_display', read_only=True)
    esta_activa = serializers.BooleanField(read_only=True)

    class Meta:
        model = SuscripcionProveedor
        fields = [
            'id',
            'plan',
            'estado',
            'estado_display',
            'esta_activa',
            'mp_preapproval_id',
            'mp_init_point',
            'fecha_inicio',
            'fecha_proximo_cobro',
            'fecha_cancelacion',
            'fecha_actualizacion',
        ]
        read_only_fields = fields
