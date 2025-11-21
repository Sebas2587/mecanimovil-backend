"""
Serializers para la app de pagos con Mercado Pago Checkout Pro
"""
from rest_framework import serializers
from .models import PreferenciaPago, Pago, WebhookNotificacion
from django.contrib.auth import get_user_model

User = get_user_model()


class PreferenciaPagoCreateSerializer(serializers.Serializer):
    """
    Serializer para crear una preferencia de pago
    """
    carrito_id = serializers.UUIDField(required=True)
    back_urls = serializers.DictField(required=False, default=dict)
    notification_url = serializers.URLField(required=False, allow_null=True)


class PreferenciaPagoSerializer(serializers.ModelSerializer):
    """
    Serializer para preferencias de pago
    """
    class Meta:
        model = PreferenciaPago
        fields = [
            'id',
            'preference_id_mp',
            'init_point',
            'sandbox_init_point',
            'total_amount',
            'currency_id',
            'procesada',
            'fecha_creacion',
            'carrito',
        ]
        read_only_fields = [
            'id',
            'preference_id_mp',
            'init_point',
            'sandbox_init_point',
            'procesada',
            'fecha_creacion',
        ]


class PagoSerializer(serializers.ModelSerializer):
    """
    Serializer para pagos
    """
    class Meta:
        model = Pago
        fields = [
            'id',
            'payment_id_mp',
            'transaction_amount',
            'currency_id',
            'description',
            'status',
            'status_detail',
            'payment_method_id',
            'payment_type_id',
            'payer_email',
            'payer_first_name',
            'payer_last_name',
            'external_reference',
            'receipt_url',
            'fecha_creacion',
            'fecha_actualizacion',
            'date_approved_mp',
        ]
        read_only_fields = [
            'id',
            'payment_id_mp',
            'status',
            'status_detail',
            'fecha_creacion',
            'fecha_actualizacion',
            'date_approved_mp',
        ]


class PaymentStatusSerializer(serializers.Serializer):
    """
    Serializer para el estado de un pago
    """
    payment_id = serializers.IntegerField(required=False, allow_null=True)
    status = serializers.CharField(required=True)
    status_detail = serializers.CharField(required=False, allow_null=True)
    success = serializers.BooleanField(required=True)
    payment = serializers.DictField(required=False, allow_null=True)