"""
ViewSets para el sistema Pay-per-Win con créditos.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.conf import settings
from decouple import config
import logging

from .models import (
    CreditoProveedor,
    PaqueteCreditos,
    CompraCreditos,
    ConsumoCredito
)
from .serializers import (
    PaqueteCreditosSerializer,
    CompraCreditosSerializer,
    CreditoProveedorSerializer,
    ConsumoCreditoSerializer,
    EstadisticasCreditosSerializer
)
from mecanimovilapp.apps.ordenes.permissions import IsProveedor
from mecanimovilapp.apps.pagos.services import get_mercado_pago_service

logger = logging.getLogger(__name__)


# ============================================================================
# DATOS BANCARIOS OFICIALES DE MECANIMOVIL
# ============================================================================

DATOS_BANCARIOS_MECANIMOVIL = {
    'banco': 'Banco de Chile',
    'cuenta': '00-023-53241-50',
    'tipo_cuenta': 'Cuenta Vista',
    'rut': '77.931.633-5',
    'nombre': 'Mecanimovil SPA',
    'email': 'sebastian.marquez@mecanimovil.cl'
}

DATOS_MERCADOPAGO_MECANIMOVIL = {
    'nombre': 'MECANIMOVIL SPA',
    'rut': '77.931.633-5',
    'cuenta': '1001164410',
    'tipo_cuenta': 'Cuenta Vista Mercado Pago',
    'email': 'mmanrique0925@gmail.com'
}


# ============================================================================
# VIEWSETS DEL SISTEMA PAY-PER-WIN CON CRÉDITOS
# ============================================================================

class PaqueteCreditosViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet para listar y obtener paquetes de créditos.
    Solo lectura - los paquetes se gestionan desde el admin.
    """
    queryset = PaqueteCreditos.objects.filter(activo=True).order_by('orden', 'precio')
    serializer_class = PaqueteCreditosSerializer
    permission_classes = [IsAuthenticated]
    
    @action(detail=False, methods=['get'])
    def disponibles(self, request):
        """
        Lista todos los paquetes disponibles para compra.
        Endpoint: /api/creditos/paquetes/disponibles/
        """
        paquetes = self.get_queryset()
        serializer = self.get_serializer(paquetes, many=True)
        return Response(serializer.data)


class CompraCreditosViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar compras de créditos de proveedores.
    """
    serializer_class = CompraCreditosSerializer
    permission_classes = [IsAuthenticated, IsProveedor]
    
    def get_queryset(self):
        """Solo el proveedor puede ver sus propias compras"""
        return CompraCreditos.objects.filter(proveedor=self.request.user).order_by('-fecha_compra')
    
    def create(self, request, *args, **kwargs):
        """
        Crea una nueva compra de créditos.
        Endpoint: POST /api/creditos/compras/
        
        Para Mercado Pago: Crea la compra y retorna la URL de pago
        Para Transferencia: Crea la compra y retorna los datos bancarios
        """
        from .creditos_services import comprar_creditos
        
        proveedor = request.user
        paquete_id = request.data.get('paquete_id')
        metodo_pago = request.data.get('metodo_pago', 'mercadopago')
        
        if not paquete_id:
            return Response(
                {'error': 'paquete_id es requerido'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Obtener el paquete primero para tener los datos
            paquete = PaqueteCreditos.objects.filter(id=paquete_id, activo=True).first()
            if not paquete:
                return Response(
                    {'error': 'El paquete no existe o no está disponible'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Crear la compra (sin confirmar si es mercadopago)
            compra = comprar_creditos(proveedor, paquete_id, metodo_pago)
            serializer = self.get_serializer(compra)
            response_data = serializer.data
            
            # Si es transferencia, agregar datos bancarios reales
            if metodo_pago == 'transferencia':
                response_data['datos_bancarios'] = DATOS_BANCARIOS_MECANIMOVIL
                logger.info(f"💰 Compra de créditos por transferencia creada: {compra.id}")
            
            # Si es Mercado Pago, crear preferencia de pago
            elif metodo_pago == 'mercadopago':
                try:
                    preference_result = self._crear_preferencia_mercadopago(compra, paquete, proveedor)
                    
                    if preference_result.get('success'):
                        response_data['mercadopago'] = {
                            'preference_id': preference_result.get('preference_id'),
                            'init_point': preference_result.get('init_point'),
                            'sandbox_init_point': preference_result.get('sandbox_init_point'),
                        }
                        logger.info(f"💳 Preferencia de Mercado Pago creada para compra {compra.id}")
                    else:
                        # Si falla la creación de preferencia, cancelar la compra
                        compra.estado = 'cancelada'
                        compra.save()
                        return Response(
                            {'error': preference_result.get('error', 'Error al crear preferencia de Mercado Pago')},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                except Exception as e:
                    logger.error(f"Error creando preferencia MP para compra {compra.id}: {e}")
                    compra.estado = 'cancelada'
                    compra.save()
                    return Response(
                        {'error': f'Error al crear preferencia de Mercado Pago: {str(e)}'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            return Response(response_data, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Error creando compra de créditos: {e}", exc_info=True)
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    def _crear_preferencia_mercadopago(self, compra, paquete, proveedor):
        """
        Crea una preferencia de pago en Mercado Pago para la compra de créditos.
        """
        try:
            servicio = get_mercado_pago_service()
            
            # Construir descripción del item
            descripcion = f"Compra de {paquete.total_creditos} créditos"
            if paquete.bonificacion_creditos > 0:
                descripcion += f" (+{paquete.bonificacion_creditos} de bonificación)"
            
            # Construir información del pagador
            payer = {
                'name': proveedor.first_name or proveedor.username,
                'surname': proveedor.last_name or '',
                'email': proveedor.email,
            }
            
            # Agregar identificación si está disponible
            if hasattr(proveedor, 'rut') and proveedor.rut:
                payer['identification'] = {
                    'type': 'RUT',
                    'number': str(proveedor.rut).replace('.', '').replace('-', ''),
                }
            
            # Convertir precio a entero (Mercado Pago requiere enteros para CLP)
            precio_entero = int(round(float(paquete.precio)))
            
            # Construir la preferencia
            preference_data = {
                'items': [{
                    'title': f"Créditos MecaniMovil - {paquete.nombre}",
                    'description': descripcion,
                    'quantity': 1,
                    'unit_price': precio_entero,
                    'currency_id': 'CLP',
                }],
                'payer': payer,
                'external_reference': f"creditos_{compra.id}",
                'back_urls': {
                    'success': f"mecanimovil://creditos/compra/{compra.id}/success",
                    'failure': f"mecanimovil://creditos/compra/{compra.id}/failure",
                    'pending': f"mecanimovil://creditos/compra/{compra.id}/pending",
                },
                'auto_return': 'approved',
                'statement_descriptor': 'MECANIMOVIL CREDITOS',
                'binary_mode': False,
            }
            
            # Agregar notification_url si está configurada
            webhook_base_url = config('WEBHOOK_BASE_URL', default='')
            if webhook_base_url:
                preference_data['notification_url'] = f"{webhook_base_url}/api/suscripciones/creditos/compras/webhook-mp/"
            
            logger.info(f"📋 Creando preferencia de MP para compra de créditos {compra.id}")
            logger.info(f"   - Paquete: {paquete.nombre}")
            logger.info(f"   - Precio: ${precio_entero} CLP")
            logger.info(f"   - Créditos: {paquete.total_creditos}")
            
            # Crear la preferencia usando el servicio
            preference_result = servicio.create_preference(preference_data)
            
            if preference_result.get('success'):
                # Guardar el preference_id en la compra
                compra.payment_id_mp = preference_result.get('preference_id')
                compra.save(update_fields=['payment_id_mp', 'fecha_actualizacion'])
                
                logger.info(f"✅ Preferencia creada: {preference_result.get('preference_id')}")
                
                return preference_result
            else:
                logger.error(f"❌ Error creando preferencia: {preference_result.get('error')}")
                return preference_result
            
        except Exception as e:
            logger.error(f"❌ Excepción creando preferencia MP: {str(e)}")
            return {
                'success': False,
                'error': f'Error al crear la preferencia: {str(e)}'
            }
    
    @action(detail=True, methods=['post'], url_path='confirmar-pago')
    def confirmar_pago(self, request, pk=None):
        """
        Confirma el pago de una compra de créditos (webhook).
        Endpoint: POST /api/creditos/compras/{id}/confirmar-pago/
        """
        from .creditos_services import confirmar_compra_creditos
        
        compra = self.get_object()
        
        # Verificar que la compra pertenece al usuario
        if compra.proveedor != request.user:
            return Response(
                {'error': 'No tienes permiso para confirmar esta compra'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        payment_id_mp = request.data.get('payment_id_mp')
        
        try:
            credito_proveedor = confirmar_compra_creditos(compra.id, payment_id_mp)
            compra.refresh_from_db()
            serializer = self.get_serializer(compra)
            return Response(serializer.data)
        except Exception as e:
            logger.error(f"Error confirmando compra {compra.id}: {e}", exc_info=True)
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        """
        Cancela una compra pendiente de créditos.
        Endpoint: POST /api/creditos/compras/{id}/cancelar/
        """
        compra = self.get_object()
        
        # Verificar que la compra pertenece al usuario
        if compra.proveedor != request.user:
            return Response(
                {'error': 'No tienes permiso para cancelar esta compra'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if compra.estado != 'pendiente':
            return Response(
                {'error': f'No se puede cancelar una compra en estado: {compra.get_estado_display()}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        compra.estado = 'cancelada'
        compra.save(update_fields=['estado', 'fecha_actualizacion'])
        
        serializer = self.get_serializer(compra)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'], url_path='webhook-mp', permission_classes=[AllowAny])
    def webhook_mercadopago(self, request):
        """
        Webhook para recibir notificaciones de Mercado Pago sobre pagos de créditos.
        Endpoint: POST /api/suscripciones/creditos/compras/webhook-mp/
        
        Este endpoint es llamado automáticamente por Mercado Pago cuando hay un cambio
        en el estado de un pago.
        """
        from .creditos_services import confirmar_compra_creditos
        
        try:
            # Log de datos recibidos
            logger.info(f"📨 Webhook MP (créditos) recibido: {request.data}")
            
            # Mercado Pago envía el tipo de notificación y los datos
            notification_type = request.data.get('type') or request.query_params.get('type')
            data = request.data.get('data', {})
            
            # Para notificaciones IPN v1
            if request.query_params.get('topic') == 'payment':
                payment_id = request.query_params.get('id')
            # Para notificaciones Webhook v2
            elif notification_type == 'payment':
                payment_id = data.get('id')
            else:
                logger.info(f"📬 Tipo de notificación no procesada: {notification_type}")
                return Response({'status': 'ok'}, status=status.HTTP_200_OK)
            
            if not payment_id:
                logger.warning("⚠️ Webhook sin payment_id")
                return Response({'status': 'ok'}, status=status.HTTP_200_OK)
            
            logger.info(f"💰 Procesando pago MP: {payment_id}")
            
            # Obtener información del pago desde Mercado Pago
            servicio = get_mercado_pago_service()
            payment_info = servicio.get_payment(payment_id)
            
            if not payment_info.get('success'):
                logger.error(f"❌ Error obteniendo pago {payment_id}: {payment_info.get('error')}")
                return Response({'status': 'error'}, status=status.HTTP_200_OK)
            
            payment = payment_info.get('payment', {})
            payment_status = payment.get('status')
            external_reference = payment.get('external_reference', '')
            
            logger.info(f"📋 Estado del pago: {payment_status}")
            logger.info(f"📋 Referencia externa: {external_reference}")
            
            # Verificar que sea una compra de créditos
            if not external_reference.startswith('creditos_'):
                logger.info(f"⚠️ No es una compra de créditos: {external_reference}")
                return Response({'status': 'ok'}, status=status.HTTP_200_OK)
            
            # Obtener ID de la compra
            try:
                compra_id = int(external_reference.replace('creditos_', ''))
            except ValueError:
                logger.error(f"❌ Referencia inválida: {external_reference}")
                return Response({'status': 'error'}, status=status.HTTP_200_OK)
            
            # Buscar la compra
            try:
                compra = CompraCreditos.objects.get(id=compra_id)
            except CompraCreditos.DoesNotExist:
                logger.error(f"❌ Compra no encontrada: {compra_id}")
                return Response({'status': 'error'}, status=status.HTTP_200_OK)
            
            # Procesar según el estado del pago
            if payment_status == 'approved':
                # Pago aprobado - confirmar la compra y acreditar los créditos
                if compra.estado == 'pendiente':
                    try:
                        confirmar_compra_creditos(compra_id, str(payment_id))
                        logger.info(f"✅ Compra {compra_id} confirmada exitosamente")
                    except Exception as e:
                        logger.error(f"❌ Error confirmando compra {compra_id}: {e}")
                else:
                    logger.info(f"ℹ️ Compra {compra_id} ya está en estado: {compra.estado}")
            
            elif payment_status in ['rejected', 'cancelled']:
                # Pago rechazado o cancelado
                if compra.estado == 'pendiente':
                    compra.estado = 'cancelada'
                    compra.payment_id_mp = str(payment_id)
                    compra.save(update_fields=['estado', 'payment_id_mp', 'fecha_actualizacion'])
                    logger.info(f"❌ Compra {compra_id} cancelada por pago {payment_status}")
            
            elif payment_status in ['pending', 'in_process', 'in_mediation']:
                # Pago pendiente - mantener estado
                logger.info(f"⏳ Pago {payment_id} en estado: {payment_status}")
            
            return Response({'status': 'ok'}, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ Error procesando webhook MP (créditos): {e}", exc_info=True)
            # Siempre retornar 200 para que Mercado Pago no reintente
            return Response({'status': 'error'}, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['get', 'post'], url_path='verificar-pago')
    def verificar_pago(self, request, pk=None):
        """
        Verifica el estado de pago de una compra de créditos consultando a Mercado Pago.
        Si encuentra un pago aprobado, confirma automáticamente la compra.
        
        Endpoint: GET/POST /api/suscripciones/creditos/compras/{id}/verificar-pago/
        """
        from .creditos_services import confirmar_compra_creditos
        
        compra = self.get_object()
        
        # Verificar que la compra pertenece al usuario
        if compra.proveedor != request.user:
            return Response(
                {'error': 'No tienes permiso para verificar esta compra'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Si ya está completada, retornar estado actual
        if compra.estado == 'completada':
            serializer = self.get_serializer(compra)
            return Response({
                'status': 'completada',
                'compra': serializer.data,
                'mensaje': 'La compra ya está completada y los créditos fueron acreditados',
                'creditos_acreditados': True
            })
        
        # Si está cancelada, retornar estado
        if compra.estado == 'cancelada':
            return Response({
                'status': 'cancelada',
                'mensaje': 'La compra fue cancelada',
                'creditos_acreditados': False
            })
        
        # Verificar que sea una compra por Mercado Pago
        if compra.metodo_pago != 'mercadopago':
            return Response({
                'status': 'pendiente',
                'mensaje': 'Esta compra es por transferencia. Espera la confirmación del administrador.',
                'creditos_acreditados': False
            })
        
        # Buscar pagos en Mercado Pago por external_reference
        external_reference = f"creditos_{compra.id}"
        
        try:
            servicio = get_mercado_pago_service()
            search_result = servicio.search_payments_by_external_reference(external_reference)
            
            if not search_result.get('success'):
                logger.error(f"Error buscando pagos para compra {compra.id}: {search_result.get('error')}")
                return Response({
                    'status': 'pendiente',
                    'mensaje': 'No se pudo verificar el estado del pago. Intenta nuevamente.',
                    'creditos_acreditados': False,
                    'error': search_result.get('error')
                })
            
            payments = search_result.get('payments', [])
            
            if not payments:
                # No hay pagos registrados aún
                return Response({
                    'status': 'pendiente',
                    'mensaje': 'No se encontró ningún pago asociado. Si ya pagaste, espera unos segundos e intenta de nuevo.',
                    'creditos_acreditados': False,
                    'preference_id': compra.payment_id_mp
                })
            
            # Buscar un pago aprobado
            pago_aprobado = None
            ultimo_estado = None
            
            for payment in payments:
                payment_status = payment.get('status')
                ultimo_estado = payment_status
                
                if payment_status == 'approved':
                    pago_aprobado = payment
                    break
            
            if pago_aprobado:
                # Confirmar la compra automáticamente
                payment_id = str(pago_aprobado.get('id'))
                
                try:
                    confirmar_compra_creditos(compra.id, payment_id)
                    compra.refresh_from_db()
                    serializer = self.get_serializer(compra)
                    
                    logger.info(f"✅ Compra {compra.id} confirmada por verificación manual")
                    
                    return Response({
                        'status': 'completada',
                        'compra': serializer.data,
                        'mensaje': '¡Pago confirmado! Los créditos han sido acreditados a tu cuenta.',
                        'creditos_acreditados': True,
                        'payment_id': payment_id
                    })
                except Exception as e:
                    logger.error(f"Error confirmando compra {compra.id}: {e}")
                    return Response({
                        'status': 'error',
                        'mensaje': f'El pago fue aprobado pero hubo un error acreditando los créditos: {str(e)}',
                        'creditos_acreditados': False
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # Pago encontrado pero no aprobado
            estado_mensajes = {
                'pending': 'El pago está pendiente de procesamiento.',
                'in_process': 'El pago está siendo procesado.',
                'in_mediation': 'El pago está en mediación.',
                'rejected': 'El pago fue rechazado. Intenta con otro método de pago.',
                'cancelled': 'El pago fue cancelado.',
                'refunded': 'El pago fue reembolsado.',
                'charged_back': 'El pago tuvo un contracargo.',
            }
            
            mensaje = estado_mensajes.get(ultimo_estado, f'Estado del pago: {ultimo_estado}')
            
            # Si fue rechazado o cancelado, actualizar el estado de la compra
            if ultimo_estado in ['rejected', 'cancelled']:
                compra.estado = 'cancelada'
                compra.save(update_fields=['estado', 'fecha_actualizacion'])
            
            return Response({
                'status': ultimo_estado,
                'mensaje': mensaje,
                'creditos_acreditados': False
            })
            
        except Exception as e:
            logger.error(f"Error verificando pago de compra {compra.id}: {e}", exc_info=True)
            return Response({
                'status': 'error',
                'mensaje': 'Error al verificar el estado del pago. Intenta nuevamente.',
                'creditos_acreditados': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='datos-bancarios')
    def datos_bancarios(self, request):
        """
        Obtiene los datos bancarios oficiales de MecaniMovil para transferencias.
        Endpoint: GET /api/suscripciones/creditos/compras/datos-bancarios/
        """
        return Response({
            'transferencia': DATOS_BANCARIOS_MECANIMOVIL,
            'mercadopago': DATOS_MERCADOPAGO_MECANIMOVIL
        })
    
    @action(detail=False, methods=['get'], url_path='pendientes')
    def compras_pendientes(self, request):
        """
        Obtiene las compras pendientes del proveedor.
        Útil para mostrar compras que aún no han sido completadas.
        
        Endpoint: GET /api/suscripciones/creditos/compras/pendientes/
        """
        compras = CompraCreditos.objects.filter(
            proveedor=request.user,
            estado='pendiente'
        ).order_by('-fecha_compra')
        
        serializer = self.get_serializer(compras, many=True)
        
        # Agregar información adicional a cada compra
        data = serializer.data
        for i, compra_data in enumerate(data):
            compra = compras[i]
            if compra.metodo_pago == 'mercadopago':
                compra_data['puede_reintentar'] = True
                compra_data['mensaje'] = 'Pago pendiente. Puedes verificar el estado o reintentar.'
            else:
                compra_data['puede_reintentar'] = False
                compra_data['mensaje'] = 'Esperando confirmación de transferencia.'
        
        return Response({
            'compras': data,
            'total': len(data)
        })
    
    @action(detail=True, methods=['post'], url_path='reintentar-pago')
    def reintentar_pago(self, request, pk=None):
        """
        Genera una nueva URL de pago para una compra pendiente.
        Solo funciona para compras por Mercado Pago.
        
        Endpoint: POST /api/suscripciones/creditos/compras/{id}/reintentar-pago/
        """
        compra = self.get_object()
        
        # Verificar que la compra pertenece al usuario
        if compra.proveedor != request.user:
            return Response(
                {'error': 'No tienes permiso para esta operación'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Verificar que esté pendiente
        if compra.estado != 'pendiente':
            return Response(
                {'error': f'No se puede reintentar una compra en estado: {compra.get_estado_display()}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verificar que sea por Mercado Pago
        if compra.metodo_pago != 'mercadopago':
            return Response(
                {'error': 'Esta compra es por transferencia, no se puede reintentar el pago'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Crear nueva preferencia de pago
            paquete = compra.paquete
            proveedor = compra.proveedor
            
            preference_result = self._crear_preferencia_mercadopago(compra, paquete, proveedor)
            
            if preference_result.get('success'):
                serializer = self.get_serializer(compra)
                response_data = serializer.data
                response_data['mercadopago'] = {
                    'preference_id': preference_result.get('preference_id'),
                    'init_point': preference_result.get('init_point'),
                    'sandbox_init_point': preference_result.get('sandbox_init_point'),
                }
                
                logger.info(f"💳 Nueva preferencia creada para compra {compra.id}")
                return Response(response_data)
            else:
                return Response(
                    {'error': preference_result.get('error', 'Error al crear nueva preferencia')},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except Exception as e:
            logger.error(f"Error reintentando pago de compra {compra.id}: {e}")
            return Response(
                {'error': f'Error al reintentar el pago: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CreditoProveedorViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet para consultar créditos de proveedores.
    Solo lectura - los créditos se actualizan automáticamente.
    """
    serializer_class = CreditoProveedorSerializer
    permission_classes = [IsAuthenticated, IsProveedor]
    
    def get_queryset(self):
        """Solo el proveedor puede ver sus propios créditos"""
        return CreditoProveedor.objects.filter(proveedor=self.request.user)
    
    def retrieve(self, request, pk=None):
        """
        Obtiene el saldo actual del proveedor.
        Si no existe registro, lo crea con saldo 0.
        Endpoint: GET /api/creditos/mi-saldo/{id}/
        """
        from .creditos_services import obtener_credito_proveedor
        
        proveedor = request.user
        credito_proveedor = obtener_credito_proveedor(proveedor)
        serializer = self.get_serializer(credito_proveedor)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='mi-saldo')
    def mi_saldo(self, request):
        """
        Obtiene el saldo actual del proveedor autenticado.
        Endpoint: GET /api/creditos/mi-saldo/
        """
        from .creditos_services import obtener_credito_proveedor
        
        proveedor = request.user
        credito_proveedor = obtener_credito_proveedor(proveedor)
        serializer = self.get_serializer(credito_proveedor)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def estadisticas(self, request):
        """
        Obtiene estadísticas completas de créditos del proveedor.
        Endpoint: GET /api/creditos/estadisticas/
        """
        from .creditos_services import obtener_estadisticas_creditos
        
        proveedor = request.user
        
        try:
            estadisticas = obtener_estadisticas_creditos(proveedor)
            serializer = EstadisticasCreditosSerializer(estadisticas)
            return Response(serializer.data)
        except Exception as e:
            logger.error(f"Error obteniendo estadísticas para proveedor {proveedor.id}: {e}", exc_info=True)
            return Response(
                {'error': 'Error al obtener estadísticas'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'], url_path='historial-consumos')
    def historial_consumos(self, request):
        """
        Obtiene el historial de consumos de créditos.
        Endpoint: GET /api/creditos/historial-consumos/
        """
        proveedor = request.user
        limit = int(request.query_params.get('limit', 50))
        
        consumos = ConsumoCredito.objects.filter(
            proveedor=proveedor
        ).order_by('-fecha_consumo')[:limit]
        
        serializer = ConsumoCreditoSerializer(consumos, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='historial-compras')
    def historial_compras(self, request):
        """
        Obtiene el historial de compras de créditos.
        Endpoint: GET /api/creditos/historial-compras/
        """
        proveedor = request.user
        limit = int(request.query_params.get('limit', 50))
        
        compras = CompraCreditos.objects.filter(
            proveedor=proveedor
        ).order_by('-fecha_compra')[:limit]
        
        serializer = CompraCreditosSerializer(compras, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'], url_path='verificar-creditos-oferta')
    def verificar_creditos_oferta(self, request):
        """
        Verifica si el proveedor tiene créditos suficientes para crear una oferta.
        Calcula el total de créditos necesarios según los servicios de la solicitud.
        
        Endpoint: POST /api/creditos/mi-saldo/verificar-creditos-oferta/
        Body: {
            "solicitud_id": "uuid",
            "servicios_ids": [1, 2, 3]  # IDs de los servicios a ofertar
        }
        
        Returns: {
            "puede_ofertar": true/false,
            "saldo_actual": 10,
            "creditos_necesarios": 6,
            "creditos_faltantes": 0,
            "detalle_servicios": [
                {"servicio_id": 1, "nombre": "Cambio de aceite", "creditos": 2},
                ...
            ],
            "mensaje": "Tienes créditos suficientes"
        }
        """
        from .creditos_services import obtener_credito_proveedor, obtener_creditos_servicio
        from mecanimovilapp.apps.servicios.models import Servicio
        from mecanimovilapp.apps.ordenes.models import SolicitudServicio
        
        proveedor = request.user
        solicitud_id = request.data.get('solicitud_id')
        servicios_ids = request.data.get('servicios_ids', [])
        
        try:
            # Obtener saldo actual
            credito_proveedor = obtener_credito_proveedor(proveedor)
            saldo_actual = credito_proveedor.saldo_creditos
            
            # Si no se envían servicios_ids, obtener servicios de la solicitud
            if not servicios_ids and solicitud_id:
                try:
                    solicitud = SolicitudServicio.objects.get(id=solicitud_id)
                    servicios_ids = list(solicitud.servicios_solicitados.values_list('id', flat=True))
                except SolicitudServicio.DoesNotExist:
                    return Response(
                        {'error': 'Solicitud no encontrada'},
                        status=status.HTTP_404_NOT_FOUND
                    )
            
            if not servicios_ids:
                return Response(
                    {'error': 'Debe proporcionar solicitud_id o servicios_ids'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Calcular créditos necesarios por cada servicio
            detalle_servicios = []
            creditos_necesarios = 0
            
            for servicio_id in servicios_ids:
                try:
                    servicio = Servicio.objects.get(id=servicio_id)
                    creditos_servicio = obtener_creditos_servicio(servicio)
                    creditos_necesarios += creditos_servicio
                    detalle_servicios.append({
                        'servicio_id': servicio.id,
                        'nombre': servicio.nombre,
                        'creditos': creditos_servicio
                    })
                except Servicio.DoesNotExist:
                    logger.warning(f"Servicio {servicio_id} no encontrado")
                    continue
            
            # Determinar si puede ofertar
            puede_ofertar = saldo_actual >= creditos_necesarios
            creditos_faltantes = max(0, creditos_necesarios - saldo_actual)
            
            if puede_ofertar:
                mensaje = f"Tienes créditos suficientes ({saldo_actual} disponibles)"
            else:
                mensaje = (
                    f"No tienes créditos suficientes. "
                    f"Necesitas {creditos_necesarios} créditos, pero solo tienes {saldo_actual}. "
                    f"Te faltan {creditos_faltantes} créditos."
                )
            
            return Response({
                'puede_ofertar': puede_ofertar,
                'saldo_actual': saldo_actual,
                'creditos_necesarios': creditos_necesarios,
                'creditos_faltantes': creditos_faltantes,
                'detalle_servicios': detalle_servicios,
                'mensaje': mensaje
            })
            
        except Exception as e:
            logger.error(f"Error verificando créditos para oferta: {e}", exc_info=True)
            return Response(
                {'error': f'Error al verificar créditos: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

