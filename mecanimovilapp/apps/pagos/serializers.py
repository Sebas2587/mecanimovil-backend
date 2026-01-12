"""
Serializers para la app de pagos con Mercado Pago Checkout Pro
"""
from rest_framework import serializers
from .models import PreferenciaPago, Pago, WebhookNotificacion, CuentaMercadoPagoProveedor
from django.contrib.auth import get_user_model

User = get_user_model()


class CuentaMercadoPagoProveedorSerializer(serializers.ModelSerializer):
    """
    Serializer para la cuenta de Mercado Pago del proveedor
    """
    estado_display = serializers.CharField(source='get_estado_display', read_only=True)
    puede_recibir_pagos = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = CuentaMercadoPagoProveedor
        fields = [
            'id',
            'estado',
            'estado_display',
            'email_mp',
            'user_id_mp',
            'nombre_cuenta',
            'fecha_conexion',
            'fecha_actualizacion',
            'puede_recibir_pagos',
            'mensaje_estado',
        ]
        read_only_fields = [
            'id',
            'estado',
            'estado_display',
            'email_mp',
            'user_id_mp',
            'nombre_cuenta',
            'fecha_conexion',
            'fecha_actualizacion',
            'puede_recibir_pagos',
            'mensaje_estado',
        ]


class IniciarConexionMPSerializer(serializers.Serializer):
    """
    Serializer para la respuesta de iniciar conexión OAuth
    """
    auth_url = serializers.URLField()
    redirect_uri = serializers.URLField()
    state = serializers.CharField()


class CallbackOAuthSerializer(serializers.Serializer):
    """
    Serializer para el callback de OAuth
    """
    code = serializers.CharField(required=True)
    state = serializers.CharField(required=True)


class EstadisticasPagosMPSerializer(serializers.Serializer):
    """
    Serializer para las estadísticas de pagos recibidos
    """
    total_recibido = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_recibido_mes = serializers.DecimalField(max_digits=12, decimal_places=2)
    cantidad_transacciones = serializers.IntegerField()
    cantidad_transacciones_mes = serializers.IntegerField()
    ultima_transaccion = serializers.DateTimeField(allow_null=True)
    moneda = serializers.CharField(default='CLP')


class PreferenciaPagoCreateSerializer(serializers.Serializer):
    """
    Serializer para crear una preferencia de pago
    Soporta tanto carrito_id (flujo tradicional) como solicitud_servicio_id (ofertas secundarias)
    """
    carrito_id = serializers.UUIDField(required=False, allow_null=True)
    solicitud_servicio_id = serializers.UUIDField(required=False, allow_null=True)
    back_urls = serializers.DictField(required=False, default=dict)
    notification_url = serializers.URLField(required=False, allow_null=True)
    
    def validate(self, data):
        """Valida que se proporcione al menos uno de los IDs"""
        carrito_id = data.get('carrito_id')
        solicitud_servicio_id = data.get('solicitud_servicio_id')
        
        if not carrito_id and not solicitud_servicio_id:
            raise serializers.ValidationError(
                'Debe proporcionar carrito_id o solicitud_servicio_id'
            )
        
        if carrito_id and solicitud_servicio_id:
            raise serializers.ValidationError(
                'Solo puede proporcionar carrito_id o solicitud_servicio_id, no ambos'
            )
        
        return data


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
            'solicitud_servicio',
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
    Serializer para pagos con información de ofertas y solicitudes
    """
    oferta_info = serializers.SerializerMethodField()
    solicitud_info = serializers.SerializerMethodField()
    tipo_pago = serializers.SerializerMethodField()
    proveedor_info = serializers.SerializerMethodField()
    
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
            'oferta_info',
            'solicitud_info',
            'tipo_pago',
            'proveedor_info',
        ]
        read_only_fields = [
            'id',
            'payment_id_mp',
            'status',
            'status_detail',
            'fecha_creacion',
            'fecha_actualizacion',
            'date_approved_mp',
            'oferta_info',
            'solicitud_info',
            'tipo_pago',
            'proveedor_info',
        ]
    
    def get_oferta_info(self, obj):
        """Obtiene información de la oferta relacionada si existe"""
        try:
            import uuid
            from mecanimovilapp.apps.ordenes.models import OfertaProveedor
            
            # Intentar obtener oferta desde external_reference
            # Formato puede ser: "oferta_{oferta_id}_{tipo_pago}" o UUID directo
            if obj.external_reference:
                oferta_id = None
                tipo_pago = None
                
                # Verificar si es formato "oferta_{id}_{tipo}"
                if obj.external_reference.startswith('oferta_'):
                    parts = obj.external_reference.split('_')
                    if len(parts) >= 2:
                        try:
                            oferta_id = uuid.UUID(parts[1])
                            tipo_pago = parts[2] if len(parts) >= 3 else 'total'
                        except (ValueError, IndexError):
                            pass
                else:
                    # Intentar como UUID directo
                    try:
                        oferta_id = uuid.UUID(obj.external_reference)
                    except ValueError:
                        pass
                
                if oferta_id:
                    try:
                        oferta = OfertaProveedor.objects.select_related(
                            'proveedor', 'solicitud', 'solicitud__cliente'
                        ).get(id=oferta_id)
                        
                        return {
                            'id': str(oferta.id),
                            'precio_total': str(oferta.precio_total_ofrecido),
                            'es_oferta_secundaria': oferta.es_oferta_secundaria,
                            'estado_pago_repuestos': oferta.estado_pago_repuestos,
                            'estado_pago_servicio': oferta.estado_pago_servicio,
                            'metodo_pago_cliente': oferta.metodo_pago_cliente,
                            'tipo_pago_detectado': tipo_pago,
                        }
                    except OfertaProveedor.DoesNotExist:
                        pass
            
            # Intentar obtener desde preferencia -> solicitud_servicio -> oferta_proveedor
            if obj.preferencia and obj.preferencia.solicitud_servicio:
                solicitud_servicio = obj.preferencia.solicitud_servicio
                if hasattr(solicitud_servicio, 'oferta_proveedor') and solicitud_servicio.oferta_proveedor:
                    oferta = solicitud_servicio.oferta_proveedor
                    return {
                        'id': str(oferta.id),
                        'precio_total': str(oferta.precio_total_ofrecido),
                        'es_oferta_secundaria': oferta.es_oferta_secundaria,
                        'estado_pago_repuestos': oferta.estado_pago_repuestos,
                        'estado_pago_servicio': oferta.estado_pago_servicio,
                        'metodo_pago_cliente': oferta.metodo_pago_cliente,
                    }
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error obteniendo oferta_info en PagoSerializer: {e}")
        
        return None
    
    def get_solicitud_info(self, obj):
        """Obtiene información de la solicitud relacionada"""
        try:
            import uuid
            from mecanimovilapp.apps.ordenes.models import SolicitudServicioPublica, SolicitudServicio
            
            # Intentar obtener desde oferta
            oferta_info = self.get_oferta_info(obj)
            if oferta_info:
                try:
                    oferta_id = uuid.UUID(oferta_info['id'])
                    from mecanimovilapp.apps.ordenes.models import OfertaProveedor
                    oferta = OfertaProveedor.objects.select_related('solicitud').get(id=oferta_id)
                    solicitud_publica = oferta.solicitud
                    
                    return {
                        'id': str(solicitud_publica.id),
                        'tipo': 'publica',
                        'descripcion': solicitud_publica.descripcion_problema[:100] if solicitud_publica.descripcion_problema else '',
                    }
                except Exception:
                    pass
            
            # Intentar obtener desde preferencia -> solicitud_servicio
            if obj.preferencia and obj.preferencia.solicitud_servicio:
                solicitud_servicio = obj.preferencia.solicitud_servicio
                return {
                    'id': str(solicitud_servicio.id),
                    'tipo': 'servicio',
                    'descripcion': solicitud_servicio.notas_cliente[:100] if solicitud_servicio.notas_cliente else '',
                }
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error obteniendo solicitud_info en PagoSerializer: {e}")
        
        return None
    
    def get_tipo_pago(self, obj):
        """Determina el tipo de pago basado en la información disponible"""
        oferta_info = self.get_oferta_info(obj)
        
        if not oferta_info:
            return 'servicio_completo'  # Pago tradicional de carrito
        
        # Determinar tipo según estados de pago
        estado_repuestos = oferta_info.get('estado_pago_repuestos')
        estado_servicio = oferta_info.get('estado_pago_servicio')
        es_secundaria = oferta_info.get('es_oferta_secundaria', False)
        
        if es_secundaria:
            return 'servicio_secundario'
        elif estado_repuestos == 'pagado' and estado_servicio == 'pendiente':
            return 'servicio_parcial'
        elif estado_repuestos == 'pagado' and estado_servicio == 'pagado':
            return 'servicio_completo'
        else:
            return 'servicio_completo'
    
    def get_proveedor_info(self, obj):
        """Obtiene información del proveedor relacionado"""
        try:
            oferta_info = self.get_oferta_info(obj)
            if oferta_info:
                try:
                    import uuid
                    from mecanimovilapp.apps.ordenes.models import OfertaProveedor
                    oferta_id = uuid.UUID(oferta_info['id'])
                    oferta = OfertaProveedor.objects.select_related(
                        'proveedor'
                    ).get(id=oferta_id)
                    
                    return {
                        'id': oferta.proveedor.id,
                        'nombre': oferta.nombre_proveedor,
                        'tipo': oferta.tipo_proveedor,
                    }
                except Exception:
                    pass
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error obteniendo proveedor_info en PagoSerializer: {e}")
        
        return None


class PaymentStatusSerializer(serializers.Serializer):
    """
    Serializer para el estado de un pago
    """
    payment_id = serializers.IntegerField(required=False, allow_null=True)
    status = serializers.CharField(required=True)
    status_detail = serializers.CharField(required=False, allow_null=True)
    success = serializers.BooleanField(required=True)
    payment = serializers.DictField(required=False, allow_null=True)