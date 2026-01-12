"""
Servicios para interactuar con la API de Mercado Pago Checkout Pro
"""
import os
import logging
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from decouple import config
import mercadopago

logger = logging.getLogger(__name__)


class MercadoPagoService:
    """
    Servicio para interactuar con la API de Mercado Pago Checkout Pro
    """
    
    def __init__(self):
        """Inicializa el cliente de Mercado Pago con credenciales frescas"""
        access_token = config('MERCADOPAGO_ACCESS_TOKEN', default='')
        modo = config('MERCADOPAGO_MODE', default='test')
        
        if not access_token:
            logger.error("MERCADOPAGO_ACCESS_TOKEN no configurado")
            raise ValueError("MERCADOPAGO_ACCESS_TOKEN no está configurado")
        
        logger.info(f"🔑 Inicializando MercadoPagoService")
        logger.info(f"   - Access Token: {access_token[:50]}...")
        logger.info(f"   - Modo: {modo.upper()}")
        
        self.mp = mercadopago.SDK(access_token)
        self.modo = modo
    
    def get_public_key(self):
        """
        Obtiene la public key de Mercado Pago (se carga dinámicamente)
        """
        # Para Checkout Pro, la public key se puede obtener del frontend
        # o desde configuración
        return config('MERCADOPAGO_PUBLIC_KEY_TEST', default='')
    
    def create_preference(self, preference_data):
        """
        Crea una preferencia de pago para Checkout Pro
        
        Args:
            preference_data: Diccionario con los datos de la preferencia:
                - items: Lista de items a pagar
                - payer: Información del pagador
                - back_urls: URLs de retorno (success, failure, pending)
                - external_reference: Referencia externa (ID del carrito)
                - notification_url: URL para recibir webhooks
                - statement_descriptor: Descripción que aparece en el estado de cuenta
        
        Returns:
            Diccionario con la respuesta de Mercado Pago
        """
        try:
            logger.info("📤 Creando preferencia de pago Checkout Pro")
            logger.info(f"   - Items: {len(preference_data.get('items', []))}")
            logger.info(f"   - Total: ${preference_data.get('items', [{}])[0].get('unit_price', 0) if preference_data.get('items') else 0}")
            
            # Crear la preferencia usando el SDK
            preference_response = self.mp.preference().create(preference_data)
            
            if preference_response.get('status') in [200, 201]:
                preference = preference_response.get('response', {})
                logger.info(f"✅ Preferencia creada exitosamente: {preference.get('id')}")
                logger.info(f"   - Init Point: {preference.get('init_point', 'N/A')}")
                logger.info(f"   - Sandbox Init Point: {preference.get('sandbox_init_point', 'N/A')}")
                logger.info(f"   - Modo configurado: {self.modo.upper()}")
                
                # Mercado Pago genera ambas URLs, pero init_point es la correcta según el token usado
                # Si el token es de producción, init_point será la URL de producción
                # Si el token es de prueba, init_point será la URL de sandbox
                init_point = preference.get('init_point')
                sandbox_init_point = preference.get('sandbox_init_point')
                
                if self.modo == 'production':
                    logger.info(f"   - 🚀 MODO PRODUCCIÓN: Usar init_point para pagos reales")
                else:
                    logger.info(f"   - 🧪 MODO TEST: Usar init_point (o sandbox_init_point si está disponible)")
                
                return {
                    'success': True,
                    'preference': preference,
                    'preference_id': preference.get('id'),
                    'init_point': init_point,
                    'sandbox_init_point': sandbox_init_point,
                }
            else:
                error_message = preference_response.get('response', {}).get('message', 'Error desconocido')
                logger.error(f"❌ Error creando preferencia: {error_message}")
                return {
                    'success': False,
                    'error': error_message,
                    'response': preference_response.get('response', {})
                }
        
        except Exception as e:
            logger.error(f"❌ Excepción creando preferencia: {str(e)}")
            return {
                'success': False,
                'error': f'Error al crear la preferencia: {str(e)}'
            }
    
    def get_payment(self, payment_id):
        """
        Obtiene información de un pago específico
        
        Args:
            payment_id: ID del pago en Mercado Pago
        
        Returns:
            Diccionario con la información del pago
        """
        try:
            logger.info(f"📥 Obteniendo información del pago {payment_id}")
            
            payment_response = self.mp.payment().get(payment_id)
            
            if payment_response.get('status') in [200, 201]:
                payment = payment_response.get('response', {})
                logger.info(f"✅ Pago obtenido exitosamente: {payment.get('status')}")
                
                return {
                    'success': True,
                    'payment': payment
                }
            else:
                error_message = payment_response.get('response', {}).get('message', 'Error desconocido')
                logger.error(f"❌ Error obteniendo pago: {error_message}")
                return {
                    'success': False,
                    'error': error_message
                }
        
        except Exception as e:
            logger.error(f"❌ Excepción obteniendo pago: {str(e)}")
            return {
                'success': False,
                'error': f'Error al obtener el pago: {str(e)}'
            }
    
    def get_payment_receipt_url(self, payment_id):
        """
        Obtiene la URL del comprobante de pago
        
        Args:
            payment_id: ID del pago en Mercado Pago
        
        Returns:
            URL del comprobante o None si no está disponible
        """
        try:
            payment_info = self.get_payment(payment_id)
            
            if payment_info.get('success'):
                payment = payment_info.get('payment', {})
                
                # Mercado Pago proporciona la URL del comprobante en diferentes campos
                receipt_url = (
                    payment.get('transaction_details', {}).get('transaction_receipt_url') or
                    payment.get('transaction_details', {}).get('external_resource_url') or
                    f"https://www.mercadopago.com.ar/activities/payments/{payment_id}"
                )
                
                return receipt_url
            
            return None
        
        except Exception as e:
            logger.error(f"❌ Excepción obteniendo URL del comprobante: {str(e)}")
            return None
    
    def search_payments_by_external_reference(self, external_reference):
        """
        Busca pagos por external_reference usando la API de Mercado Pago.
        
        Args:
            external_reference: Referencia externa (ej: "creditos_123")
        
        Returns:
            Diccionario con los pagos encontrados
        """
        try:
            logger.info(f"🔍 Buscando pagos con external_reference: {external_reference}")
            
            # Usar la API de búsqueda de pagos
            filters = {
                'external_reference': external_reference
            }
            
            search_response = self.mp.payment().search(filters)
            
            if search_response.get('status') in [200, 201]:
                results = search_response.get('response', {}).get('results', [])
                total = search_response.get('response', {}).get('paging', {}).get('total', 0)
                
                logger.info(f"✅ Búsqueda exitosa: {total} pago(s) encontrado(s)")
                
                # Ordenar por fecha de creación (más reciente primero)
                results.sort(key=lambda x: x.get('date_created', ''), reverse=True)
                
                return {
                    'success': True,
                    'payments': results,
                    'total': total
                }
            else:
                error_message = search_response.get('response', {}).get('message', 'Error desconocido')
                logger.error(f"❌ Error en búsqueda: {error_message}")
                return {
                    'success': False,
                    'error': error_message,
                    'payments': []
                }
        
        except Exception as e:
            logger.error(f"❌ Excepción buscando pagos: {str(e)}")
            return {
                'success': False,
                'error': f'Error al buscar pagos: {str(e)}',
                'payments': []
            }
    
    def process_webhook(self, webhook_data):
        """
        Procesa una notificación webhook de Mercado Pago
        
        Args:
            webhook_data: Datos del webhook recibido
        
        Returns:
            Diccionario con el resultado del procesamiento
        """
        try:
            notification_type = webhook_data.get('type')
            data = webhook_data.get('data', {})
            
            logger.info(f"📨 Procesando webhook tipo: {notification_type}")
            
            if notification_type == 'payment':
                payment_id = data.get('id')
                
                if payment_id:
                    logger.info(f"   - Payment ID: {payment_id}")
                    
                    # Obtener información actualizada del pago
                    payment_info = self.get_payment(payment_id)
                    
                    return {
                        'success': True,
                        'payment_id': payment_id,
                        'payment_info': payment_info
                    }
                else:
                    logger.warning("⚠️ Webhook de pago sin payment_id")
                    return {
                        'success': False,
                        'error': 'Payment ID no encontrado en webhook'
                    }
            
            else:
                logger.warning(f"⚠️ Tipo de webhook no manejado: {notification_type}")
                return {
                    'success': False,
                    'error': f'Tipo de webhook no manejado: {notification_type}'
                }
        
        except Exception as e:
            logger.error(f"❌ Excepción procesando webhook: {str(e)}")
            return {
                'success': False,
                'error': f'Error procesando webhook: {str(e)}'
            }


# Instancia singleton del servicio
_mercado_pago_service_instance = None

def get_mercado_pago_service():
    """
    Obtiene la instancia del servicio de Mercado Pago.
    Crea una nueva instancia cada vez para asegurar credenciales frescas.
    """
    return MercadoPagoService()
