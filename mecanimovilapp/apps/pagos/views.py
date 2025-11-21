"""
Views para la app de pagos con Mercado Pago Checkout Pro
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db import transaction
from django.conf import settings
from .models import PreferenciaPago, Pago, WebhookNotificacion
from .serializers import (
    PreferenciaPagoSerializer,
    PreferenciaPagoCreateSerializer,
    PagoSerializer,
    PaymentStatusSerializer,
)
from .services import get_mercado_pago_service
from mecanimovilapp.apps.ordenes.models import CarritoAgendamiento
import logging
import hmac
import hashlib

logger = logging.getLogger(__name__)


class PreferenciaPagoViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet para gestionar preferencias de pago
    """
    serializer_class = PreferenciaPagoSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Retorna solo las preferencias del usuario autenticado"""
        return PreferenciaPago.objects.filter(
            usuario=self.request.user
        ).order_by('-fecha_creacion')
    
    @action(detail=False, methods=['post'])
    def create_preference(self, request):
        """
        Crea una preferencia de pago para Checkout Pro
        """
        serializer = PreferenciaPagoCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        carrito_id = serializer.validated_data['carrito_id']
        
        try:
            # Obtener el cliente asociado al usuario autenticado
            from mecanimovilapp.apps.usuarios.models import Cliente
            cliente = Cliente.objects.get(usuario=request.user)
            
            # Obtener el carrito y verificar que pertenezca al cliente
            carrito = CarritoAgendamiento.objects.select_related('cliente', 'vehiculo').prefetch_related('items__oferta_servicio__servicio').get(
                id=carrito_id,
                cliente=cliente,
                activo=True
            )
        except Cliente.DoesNotExist:
            return Response(
                {'error': 'Usuario no tiene perfil de cliente asociado'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except CarritoAgendamiento.DoesNotExist:
            return Response(
                {'error': 'Carrito no encontrado o no disponible'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Verificar que el carrito tenga items
        items_carrito = carrito.items.all()
        if not items_carrito.exists():
            return Response(
                {'error': 'El carrito está vacío'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Obtener información del usuario y del cliente
            usuario = request.user
            
            # Construir items para Mercado Pago
            items_mp = []
            total_amount = 0
            
            for item in items_carrito:
                precio_sin_iva = float(item.precio_estimado) / 1.19
                total_amount += precio_sin_iva
                
                # Nombre del servicio con información adicional
                nombre_servicio = item.oferta_servicio.servicio.nombre
                if item.fecha_servicio and item.hora_servicio:
                    nombre_servicio += f" ({item.fecha_servicio} {item.hora_servicio})"
                
                # Calcular precio unitario sin IVA y convertirlo a entero (Mercado Pago requiere enteros)
                precio_unitario_sin_iva = precio_sin_iva / item.cantidad
                precio_unitario_entero = int(round(precio_unitario_sin_iva))
                
                logger.info(f"📦 Item: {nombre_servicio}")
                logger.info(f"   - Precio estimado (con IVA): ${item.precio_estimado}")
                logger.info(f"   - Precio sin IVA: ${precio_sin_iva:.2f}")
                logger.info(f"   - Cantidad: {item.cantidad}")
                logger.info(f"   - Precio unitario sin IVA: ${precio_unitario_sin_iva:.2f}")
                logger.info(f"   - Precio unitario entero (para MP): ${precio_unitario_entero}")
                
                items_mp.append({
                    'title': nombre_servicio,
                    'description': item.oferta_servicio.servicio.descripcion or nombre_servicio,
                    'quantity': item.cantidad,
                    'unit_price': precio_unitario_entero,  # Precio unitario sin IVA como entero
                    'currency_id': 'CLP',
                })
            
            # Construir información del pagador
            # En modo de prueba, usar datos reales del usuario pero con email de prueba si es necesario
            is_test_mode = getattr(settings, 'MERCADOPAGO_MODE', 'test') == 'test'
            
            if is_test_mode:
                # En modo de prueba, usar datos reales del usuario pero asegurar email válido para pruebas
                # Esto permite que el formulario de Mercado Pago pre-llene correctamente
                payer_name = cliente.nombre if hasattr(cliente, 'nombre') and cliente.nombre else (usuario.first_name or 'Usuario')
                payer_surname = cliente.apellido if hasattr(cliente, 'apellido') and cliente.apellido else (usuario.last_name or '')
                
                # En modo de prueba, usar el email real del usuario (puede ser cualquier email)
                # Las tarjetas de prueba funcionan con cualquier email
                payer_email = cliente.email if hasattr(cliente, 'email') and cliente.email else usuario.email
                
                # Identificación: usar datos reales si están disponibles
                identification_number = None
                if hasattr(cliente, 'rut') and cliente.rut:
                    identification_number = str(cliente.rut).replace('.', '').replace('-', '')
                elif hasattr(cliente, 'documento') and cliente.documento:
                    identification_number = str(cliente.documento).replace('.', '').replace('-', '')
                elif hasattr(usuario, 'rut') and usuario.rut:
                    identification_number = str(usuario.rut).replace('.', '').replace('-', '')
                elif hasattr(usuario, 'documento') and usuario.documento:
                    identification_number = str(usuario.documento).replace('.', '').replace('-', '')
                
                # Si no hay identificación, usar una de prueba
                if not identification_number:
                    identification_number = '12345678909'
                
                logger.info("🧪 Modo de prueba: Usando datos reales del usuario para preferencia")
                logger.info(f"   - Nombre: {payer_name} {payer_surname}")
                logger.info(f"   - Email: {payer_email}")
                logger.info(f"   - ⚠️ IMPORTANTE: En el formulario del sandbox, ingresa nombre 'APRO' para tarjetas de prueba")
            else:
                # En producción, usar datos reales del usuario
                payer_name = cliente.nombre if hasattr(cliente, 'nombre') and cliente.nombre else (usuario.first_name or '')
                payer_surname = cliente.apellido if hasattr(cliente, 'apellido') and cliente.apellido else (usuario.last_name or '')
                payer_email = cliente.email if hasattr(cliente, 'email') and cliente.email else usuario.email
                
                # Agregar identificación si está disponible (buscar en Cliente primero)
                identification_number = None
                if hasattr(cliente, 'rut') and cliente.rut:
                    identification_number = str(cliente.rut).replace('.', '').replace('-', '')
                elif hasattr(cliente, 'documento') and cliente.documento:
                    identification_number = str(cliente.documento).replace('.', '').replace('-', '')
                elif hasattr(usuario, 'rut') and usuario.rut:
                    identification_number = str(usuario.rut).replace('.', '').replace('-', '')
                elif hasattr(usuario, 'documento') and usuario.documento:
                    identification_number = str(usuario.documento).replace('.', '').replace('-', '')
            
            payer = {
                'name': payer_name,
                'surname': payer_surname,
                'email': payer_email,
            }
            
            # Agregar identificación si está disponible
            if identification_number:
                payer['identification'] = {
                    'type': 'RUT' if is_test_mode else 'RUT',  # En pruebas también usamos RUT
                    'number': identification_number,
                }
            
            logger.info(f"👤 Datos del pagador que se enviarán a Mercado Pago:")
            logger.info(f"   - Nombre completo: {payer.get('name')} {payer.get('surname')}")
            logger.info(f"   - Email: {payer.get('email')}")
            if payer.get('identification'):
                logger.info(f"   - Documento: {payer.get('identification').get('type')} - {payer.get('identification').get('number')}")
            
            # Obtener URLs de retorno y notificación del serializer
            back_urls = serializer.validated_data.get('back_urls', {})
            notification_url = serializer.validated_data.get('notification_url')
            
            # Construir la preferencia según mejores prácticas de Mercado Pago
            preference_data = {
                'items': items_mp,
                'payer': payer,
                'external_reference': str(carrito.id),
                'back_urls': {
                    'success': back_urls.get('success', ''),
                    'failure': back_urls.get('failure', ''),
                    'pending': back_urls.get('pending', ''),
                },
                'auto_return': 'approved',  # Redirigir automáticamente si se aprueba
                'statement_descriptor': 'MECANIMOVIL',  # Descripción en el estado de cuenta
                'binary_mode': False,  # Permitir estados intermedios
                'expires': True,
                'expiration_date_from': None,
                'expiration_date_to': None,
            }
            
            # Agregar notification_url si está disponible
            if notification_url:
                preference_data['notification_url'] = notification_url
            
            logger.info(f"📋 Preferencia completa que se enviará a Mercado Pago:")
            logger.info(f"   - Payer name: {preference_data['payer'].get('name')}")
            logger.info(f"   - Payer email: {preference_data['payer'].get('email')}")
            
            # Crear la preferencia usando el servicio
            servicio = get_mercado_pago_service()
            preference_result = servicio.create_preference(preference_data)
            
            if not preference_result.get('success'):
                return Response(
                    {'error': preference_result.get('error', 'Error al crear la preferencia')},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Guardar la preferencia en la base de datos
            preference_info = preference_result.get('preference', {})
            
            preferencia = PreferenciaPago.objects.create(
                usuario=usuario,
                preference_id_mp=preference_result.get('preference_id'),
                carrito=carrito,
                init_point=preference_result.get('init_point'),
                sandbox_init_point=preference_result.get('sandbox_init_point'),
                total_amount=total_amount,
                currency_id='CLP',
            )
            
            logger.info(f"✅ Preferencia guardada: {preferencia.id}")
            
            serializer_response = PreferenciaPagoSerializer(preferencia)
            return Response(serializer_response.data, status=status.HTTP_201_CREATED)
        
        except Exception as e:
            logger.error(f"❌ Error creando preferencia: {str(e)}")
            return Response(
                {'error': f'Error al crear la preferencia: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PagoViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet para gestionar pagos
    """
    serializer_class = PagoSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Retorna solo los pagos del usuario autenticado"""
        return Pago.objects.filter(usuario=self.request.user).order_by('-fecha_creacion')
    
    @action(detail=True, methods=['get'])
    def status(self, request, pk=None):
        """
        Obtiene el estado de un pago específico
        """
        pago = self.get_object()
        
        # Si el pago tiene un payment_id_mp, obtener información actualizada de Mercado Pago
        if pago.payment_id_mp:
            servicio = get_mercado_pago_service()
            payment_info = servicio.get_payment(pago.payment_id_mp)
            
            if payment_info.get('success'):
                payment_data = payment_info.get('payment', {})
                
                # Actualizar el estado del pago localmente
                pago.status = payment_data.get('status', pago.status)
                pago.status_detail = payment_data.get('status_detail', pago.status_detail)
                pago.date_last_updated_mp = payment_data.get('date_last_updated')
                
                # Actualizar URL del comprobante si está aprobado
                if pago.status == 'approved' and not pago.receipt_url:
                    receipt_url = servicio.get_payment_receipt_url(pago.payment_id_mp)
                    if receipt_url:
                        pago.receipt_url = receipt_url
                
                pago.save()
        
        serializer = self.get_serializer(pago)
        return Response({
            'payment_id': pago.payment_id_mp or str(pago.id),
            'status': pago.status,
            'status_detail': pago.status_detail,
            'success': pago.esta_aprobado,
            'payment': serializer.data,
        })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_public_key(request):
    """
    Obtiene la public key de Mercado Pago
    La public key no es sensible y puede ser accesible públicamente
    """
    servicio = get_mercado_pago_service()
    public_key = servicio.get_public_key()
    
    if not public_key:
        return Response(
            {'error': 'Public key no configurada'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    
    return Response({
        'public_key': public_key,
    })


@api_view(['POST'])
@permission_classes([])  # Sin autenticación para webhooks
def webhook_notification(request):
    """
    Endpoint para recibir notificaciones webhook de Mercado Pago
    """
    try:
        # Verificar la firma del webhook si está configurada
        webhook_secret = getattr(settings, 'MERCADOPAGO_WEBHOOK_SECRET', '')
        x_signature = request.headers.get('x-signature', '')
        
        if webhook_secret and x_signature:
            # Mercado Pago envía la firma como: sha256=hash
            if '=' in x_signature:
                signature_type, signature_hash = x_signature.split('=', 1)
                if signature_type == 'sha256':
                    # Calcular hash del body
                    body_str = request.body.decode('utf-8') if isinstance(request.body, bytes) else str(request.body)
                    calculated_hash = hmac.new(
                        webhook_secret.encode('utf-8'),
                        body_str.encode('utf-8'),
                        hashlib.sha256
                    ).hexdigest()
                    
                    # Comparar hashes usando comparación segura
                    if not hmac.compare_digest(calculated_hash, signature_hash):
                        logger.warning("Webhook rechazado: firma no válida")
                        return Response(
                            {'error': 'Firma inválida'},
                            status=status.HTTP_401_UNAUTHORIZED
                        )
        
        # Registrar la notificación
        webhook = WebhookNotificacion.objects.create(
            notification_type=request.data.get('type', 'payment'),
            payment_id_mp=request.data.get('data', {}).get('id'),
            data=request.data,
        )
        
        # Procesar el webhook
        servicio = get_mercado_pago_service()
        webhook_result = servicio.process_webhook(request.data)
        
        if webhook_result.get('success'):
            webhook.procesado = True
            webhook.fecha_procesamiento = timezone.now()
            
            # Actualizar el pago correspondiente si existe
            payment_id = webhook_result.get('payment_id')
            if payment_id:
                try:
                    # Buscar o crear el pago
                    payment_info = webhook_result.get('payment_info', {})
                    if payment_info.get('success'):
                        payment_data = payment_info.get('payment', {})
                        
                        # Obtener external_reference (carrito_id)
                        external_reference = payment_data.get('external_reference')
                        
                        if external_reference:
                            try:
                                carrito = CarritoAgendamiento.objects.get(id=external_reference)
                                usuario = carrito.cliente.usuario  # Obtener el Usuario desde el Cliente
                                
                                # Buscar o crear el pago
                                pago, created = Pago.objects.get_or_create(
                                    payment_id_mp=payment_id,
                                    defaults={
                                        'usuario': usuario,
                                        'carrito': carrito,
                                        'transaction_amount': payment_data.get('transaction_amount', 0),
                                        'currency_id': payment_data.get('currency_id', 'CLP'),
                                        'description': payment_data.get('description', ''),
                                        'status': payment_data.get('status', 'pending'),
                                        'status_detail': payment_data.get('status_detail', ''),
                                        'payment_method_id': payment_data.get('payment_method_id'),
                                        'payment_type_id': payment_data.get('payment_type_id'),
                                        'payer_email': payment_data.get('payer', {}).get('email', ''),
                                        'payer_first_name': payment_data.get('payer', {}).get('first_name', ''),
                                        'payer_last_name': payment_data.get('payer', {}).get('last_name', ''),
                                        'payer_identification_type': payment_data.get('payer', {}).get('identification', {}).get('type'),
                                        'payer_identification_number': payment_data.get('payer', {}).get('identification', {}).get('number'),
                                        'external_reference': external_reference,
                                        'date_created_mp': payment_data.get('date_created'),
                                        'date_approved_mp': payment_data.get('date_approved'),
                                        'date_last_updated_mp': payment_data.get('date_last_updated'),
                                    }
                                )
                                
                                # Actualizar el pago si ya existía
                                if not created:
                                    pago.status = payment_data.get('status', pago.status)
                                    pago.status_detail = payment_data.get('status_detail', pago.status_detail)
                                    pago.date_last_updated_mp = payment_data.get('date_last_updated')
                                
                                # Actualizar URL del comprobante si está aprobado
                                if pago.status == 'approved' and not pago.receipt_url:
                                    receipt_url = servicio.get_payment_receipt_url(payment_id)
                                    if receipt_url:
                                        pago.receipt_url = receipt_url
                                
                                pago.save()
                                
                                logger.info(f"✅ Pago {'creado' if created else 'actualizado'}: {pago.id}")
                                
                            except CarritoAgendamiento.DoesNotExist:
                                logger.warning(f"Carrito {external_reference} no encontrado para pago {payment_id}")
                        else:
                            logger.warning(f"External reference no encontrado en payment_data")
                
                except Exception as e:
                    logger.error(f"Error procesando pago desde webhook: {str(e)}")
            
            webhook.save()
            
            return Response({'message': 'Webhook procesado exitosamente'}, status=status.HTTP_200_OK)
        else:
            webhook.error_procesamiento = webhook_result.get('error', 'Error desconocido')
            webhook.save()
            
            return Response(
                {'error': webhook_result.get('error', 'Error procesando webhook')},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    except Exception as e:
        logger.error(f"Error procesando webhook: {str(e)}")
        return Response(
            {'error': f'Error procesando webhook: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )