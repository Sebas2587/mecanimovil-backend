"""
Views para la app de pagos con Mercado Pago Checkout Pro
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, Count, F, Q
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from decouple import config
import secrets
import requests
import hashlib
import base64
from urllib.parse import quote
from .models import PreferenciaPago, Pago, WebhookNotificacion, CuentaMercadoPagoProveedor
from .serializers import (
    PreferenciaPagoSerializer,
    PreferenciaPagoCreateSerializer,
    PagoSerializer,
    PaymentStatusSerializer,
    CuentaMercadoPagoProveedorSerializer,
    IniciarConexionMPSerializer,
    CallbackOAuthSerializer,
    EstadisticasPagosMPSerializer,
)
from .services import get_mercado_pago_service
from mecanimovilapp.apps.ordenes.models import CarritoAgendamiento
import logging
import hmac
import time
import json
import os
import hashlib

logger = logging.getLogger(__name__)


def respuesta_estadisticas_pagos_vacia():
    """
    Payload estable para GET estadisticas-pagos cuando no hay cuenta MP conectada.
    Evita HTTP 400 en casos esperados (la app móvil ya mapeaba 400 a ceros).
    """
    return {
        'total_recibido': 0.0,
        'total_recibido_mes': 0.0,
        'total_recibido_mes_anterior': 0.0,
        'cantidad_transacciones': 0,
        'cantidad_transacciones_mes': 0,
        'cantidad_transacciones_mes_anterior': 0,
        'ultima_transaccion': None,
        'cantidad_pagos_repuestos': 0,
        'total_repuestos': 0.0,
        'moneda': 'CLP',
    }


def respuesta_historial_pagos_vacio():
    """Historial vacío sin error HTTP cuando no hay cuenta MP."""
    return {
        'historial': [],
        'total_resultados': 0,
        'moneda': 'CLP',
    }


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
        Soporta tanto carrito_id (flujo tradicional) como solicitud_servicio_id (ofertas secundarias)
        """
        serializer = PreferenciaPagoCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        carrito_id = serializer.validated_data.get('carrito_id')
        solicitud_servicio_id = serializer.validated_data.get('solicitud_servicio_id')
        
        try:
            # Obtener el cliente asociado al usuario autenticado
            from mecanimovilapp.apps.usuarios.models import Cliente
            from mecanimovilapp.apps.ordenes.models import SolicitudServicio
            cliente = Cliente.objects.get(usuario=request.user)
            usuario = request.user
            
            carrito = None
            solicitud_servicio = None
            items_mp = []
            total_amount = 0
            external_reference = None
            
            # Procesar según el tipo de origen (carrito o solicitud de servicio)
            if carrito_id:
                # Flujo tradicional - Carrito
                logger.info(f"📦 Creando preferencia desde carrito: {carrito_id}")
                carrito = CarritoAgendamiento.objects.select_related('cliente', 'vehiculo').prefetch_related('items__oferta_servicio__servicio').get(
                    id=carrito_id,
                    cliente=cliente,
                    activo=True
                )
                
                # Verificar que el carrito tenga items
                items_carrito = carrito.items.all()
                if not items_carrito.exists():
                    return Response(
                        {'error': 'El carrito está vacío'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                # Construir items para Mercado Pago desde el carrito
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
                
                external_reference = str(carrito.id)
                
            elif solicitud_servicio_id:
                # Flujo de oferta secundaria o solicitud pública - SolicitudServicio
                logger.info(f"📦 Creando preferencia desde solicitud de servicio: {solicitud_servicio_id}")
                solicitud_servicio = SolicitudServicio.objects.select_related(
                    'cliente', 'vehiculo', 'taller', 'mecanico'
                ).prefetch_related(
                    'lineas__oferta_servicio__servicio'
                ).get(
                    id=solicitud_servicio_id,
                    cliente=cliente
                )
                
                # Verificar que la solicitud tenga líneas de servicio
                # El related_name en LineaServicio es 'lineas', no 'lineas_servicio'
                lineas_servicio = solicitud_servicio.lineas.all()
                if not lineas_servicio.exists():
                    return Response(
                        {'error': 'La solicitud de servicio no tiene servicios asociados'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                # Construir items para Mercado Pago desde las líneas de servicio
                for linea in lineas_servicio:
                    precio_sin_iva = float(linea.precio_final) / 1.19
                    total_amount += precio_sin_iva
                    
                    # Nombre del servicio con información adicional
                    nombre_servicio = linea.oferta_servicio.servicio.nombre
                    if solicitud_servicio.fecha_servicio and solicitud_servicio.hora_servicio:
                        nombre_servicio += f" ({solicitud_servicio.fecha_servicio} {solicitud_servicio.hora_servicio})"
                    
                    # Calcular precio unitario sin IVA y convertirlo a entero
                    precio_unitario_sin_iva = precio_sin_iva / linea.cantidad
                    precio_unitario_entero = int(round(precio_unitario_sin_iva))
                    
                    logger.info(f"📦 Item: {nombre_servicio}")
                    logger.info(f"   - Precio final (con IVA): ${linea.precio_final}")
                    logger.info(f"   - Precio sin IVA: ${precio_sin_iva:.2f}")
                    logger.info(f"   - Cantidad: {linea.cantidad}")
                    logger.info(f"   - Precio unitario sin IVA: ${precio_unitario_sin_iva:.2f}")
                    logger.info(f"   - Precio unitario entero (para MP): ${precio_unitario_entero}")
                    
                    items_mp.append({
                        'title': nombre_servicio,
                        'description': linea.oferta_servicio.servicio.descripcion or nombre_servicio,
                        'quantity': linea.cantidad,
                        'unit_price': precio_unitario_entero,
                        'currency_id': 'CLP',
                    })
                
                external_reference = str(solicitud_servicio.id)
            
            if not items_mp:
                return Response(
                    {'error': 'No se encontraron items para procesar'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
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
            
            # Construir back_urls
            back_urls_config = {
                'success': back_urls.get('success', ''),
                'failure': back_urls.get('failure', ''),
                'pending': back_urls.get('pending', ''),
            }
            # auto_return solo funciona con URLs HTTPS válidas.
            # Los deep links nativos (mecanimovil://) son manejados por el WebView/app,
            # por lo que auto_return no es necesario para mobile.
            success_url = back_urls_config.get('success', '')
            use_auto_return = success_url.startswith('https://')

            # Construir la preferencia según mejores prácticas de Mercado Pago
            preference_data = {
                'items': items_mp,
                'payer': payer,
                'external_reference': external_reference,
                'back_urls': back_urls_config,
                'statement_descriptor': 'MECANIMOVIL',  # Descripción en el estado de cuenta
                'binary_mode': False,  # Permitir estados intermedios
                'expires': True,
                'expiration_date_from': None,
                'expiration_date_to': None,
            }
            if use_auto_return:
                preference_data['auto_return'] = 'approved'
            
            # Agregar notification_url si está disponible
            if notification_url:
                preference_data['notification_url'] = notification_url
            
            logger.info(f"📋 Preferencia completa que se enviará a Mercado Pago:")
            logger.info(f"   - Payer name: {preference_data['payer'].get('name')}")
            logger.info(f"   - Payer email: {preference_data['payer'].get('email')}")
            logger.info(f"   - External reference: {external_reference}")
            
            # Crear la preferencia usando el servicio
            servicio = get_mercado_pago_service()
            preference_result = servicio.create_preference(preference_data)
            
            if not preference_result.get('success'):
                return Response(
                    {'error': preference_result.get('error', 'Error al crear la preferencia')},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Guardar la preferencia en la base de datos
            preferencia = PreferenciaPago.objects.create(
                usuario=usuario,
                preference_id_mp=preference_result.get('preference_id'),
                carrito=carrito,
                solicitud_servicio=solicitud_servicio,
                init_point=preference_result.get('init_point'),
                sandbox_init_point=preference_result.get('sandbox_init_point'),
                total_amount=total_amount,
                currency_id='CLP',
            )
            
            logger.info(f"✅ Preferencia guardada: {preferencia.id}")
            
            serializer_response = PreferenciaPagoSerializer(preferencia)
            return Response(serializer_response.data, status=status.HTTP_201_CREATED)
        
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
        except SolicitudServicio.DoesNotExist:
            return Response(
                {'error': 'Solicitud de servicio no encontrada o no disponible'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"❌ Error creando preferencia: {str(e)}", exc_info=True)
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
    
    @action(detail=False, methods=['get'])
    def historial_completo(self, request):
        """
        Obtiene el historial completo de pagos, incluyendo pagos históricos desde ofertas pagadas
        que no tienen registro de Pago en la base de datos
        """
        from mecanimovilapp.apps.ordenes.models import OfertaProveedor
        from mecanimovilapp.apps.usuarios.models import Cliente
        from django.utils import timezone
        from datetime import timedelta
        
        try:
            # Obtener cliente del usuario
            cliente = Cliente.objects.get(usuario=request.user)
            
            # Obtener pagos existentes en la base de datos
            pagos_db = list(Pago.objects.filter(
                usuario=request.user,
                status='approved'
            ).order_by('-fecha_creacion'))
            
            # Obtener ofertas pagadas del cliente que no tienen registro de Pago
            # IMPORTANTE: Usar la misma lógica que en la app de proveedores
            # Incluir ofertas que tienen pagos confirmados, incluso si el estado no es exactamente 'pagada'
            # Esto incluye ofertas con estado_pago_repuestos='pagado' o estado_pago_servicio='pagado'
            
            # Primero, actualizar fecha_respuesta_cliente para ofertas pagadas que no la tengan
            ofertas_sin_fecha = OfertaProveedor.objects.filter(
                solicitud__cliente=cliente,
                fecha_respuesta_cliente__isnull=True
            ).filter(
                Q(estado__in=['pagada', 'pagada_parcialmente', 'en_ejecucion', 'completada']) |
                Q(estado_pago_repuestos='pagado') |
                Q(estado_pago_servicio='pagado')
            )
            
            if ofertas_sin_fecha.exists():
                logger.info(f"📋 Actualizando fecha_respuesta_cliente para {ofertas_sin_fecha.count()} ofertas pagadas sin fecha (cliente)")
                for oferta in ofertas_sin_fecha:
                    oferta.fecha_respuesta_cliente = oferta.fecha_envio if oferta.fecha_envio else timezone.now()
                    oferta.save(update_fields=['fecha_respuesta_cliente'])
            
            # Buscar ofertas pagadas (incluyendo secundarias)
            # IMPORTANTE: Incluir ofertas con pagos confirmados, no solo por estado
            ofertas_pagadas = OfertaProveedor.objects.filter(
                solicitud__cliente=cliente
            ).filter(
                Q(estado__in=['pagada', 'pagada_parcialmente', 'en_ejecucion', 'completada']) |
                Q(estado_pago_repuestos='pagado') |
                Q(estado_pago_servicio='pagado')
            ).select_related(
                'proveedor', 'solicitud', 'solicitud__cliente', 'solicitud__cliente__usuario'
            ).order_by(
                F('fecha_respuesta_cliente').desc(nulls_last=True),
                '-fecha_envio'
            )[:100]  # Últimas 100 ofertas pagadas
            
            logger.info(f"📋 Historial completo - Cliente: {cliente.id}, Ofertas pagadas encontradas: {ofertas_pagadas.count()}")
            
            # Crear registros virtuales de pago desde ofertas pagadas que no tienen Pago asociado
            pagos_virtuales = []
            for oferta in ofertas_pagadas:
                # Verificar si ya existe un Pago para esta oferta
                tiene_pago = any(
                    pago.external_reference and f'oferta_{oferta.id}' in pago.external_reference
                    for pago in pagos_db
                )
                
                if not tiene_pago:
                    # Determinar monto y tipo de pago basado en estados
                    if oferta.es_oferta_secundaria:
                        # Oferta secundaria (servicio adicional)
                        monto = float(oferta.precio_total_ofrecido)
                        tipo_pago = 'servicio_secundario'
                    elif oferta.estado_pago_repuestos == 'pagado' and oferta.estado_pago_servicio == 'pagado':
                        # Pago completo
                        monto = float(oferta.precio_total_ofrecido)
                        tipo_pago = 'servicio_completo'
                    elif oferta.estado_pago_repuestos == 'pagado' and oferta.estado_pago_servicio == 'pendiente':
                        # Pago parcial (solo repuestos)
                        costo_repuestos = float(oferta.costo_repuestos or 0)
                        costo_gestion = float(oferta.costo_gestion_compra or 0)
                        monto = costo_repuestos + (costo_gestion * 1.19)
                        tipo_pago = 'servicio_parcial'
                    else:
                        # Pago completo (caso por defecto)
                        monto = float(oferta.precio_total_ofrecido)
                        tipo_pago = 'servicio_completo'
                    
                    # Crear objeto virtual de pago
                    pago_virtual = {
                        'id': f'virtual_{oferta.id}',
                        'payment_id_mp': None,
                        'transaction_amount': str(monto),
                        'currency_id': 'CLP',
                        'description': f"Pago de oferta - {oferta.solicitud.descripcion_problema[:50] if oferta.solicitud.descripcion_problema else 'Servicio'}",
                        'status': 'approved',
                        'status_detail': 'accredited',
                        'payment_method_id': None,
                        'payment_type_id': None,
                        'payer_email': request.user.email,
                        'payer_first_name': request.user.first_name or '',
                        'payer_last_name': request.user.last_name or '',
                        'external_reference': f'oferta_{oferta.id}_total',
                        'receipt_url': None,
                        'fecha_creacion': (oferta.fecha_respuesta_cliente or oferta.fecha_envio or timezone.now()).isoformat(),
                        'fecha_actualizacion': (oferta.fecha_respuesta_cliente or oferta.fecha_envio or timezone.now()).isoformat(),
                        'date_approved_mp': (oferta.fecha_respuesta_cliente or oferta.fecha_envio).isoformat() if (oferta.fecha_respuesta_cliente or oferta.fecha_envio) else None,
                        'oferta_info': {
                            'id': str(oferta.id),
                            'precio_total': str(oferta.precio_total_ofrecido),
                            'es_oferta_secundaria': oferta.es_oferta_secundaria,
                            'estado_pago_repuestos': oferta.estado_pago_repuestos,
                            'estado_pago_servicio': oferta.estado_pago_servicio,
                            'metodo_pago_cliente': oferta.metodo_pago_cliente,
                        },
                        'solicitud_info': {
                            'id': str(oferta.solicitud.id),
                            'tipo': 'publica',
                            'descripcion': oferta.solicitud.descripcion_problema[:100] if oferta.solicitud.descripcion_problema else '',
                        },
                        'tipo_pago': tipo_pago,
                        'proveedor_info': {
                            'id': oferta.proveedor.id,
                            'nombre': oferta.nombre_proveedor,
                            'tipo': oferta.tipo_proveedor,
                        },
                    }
                    pagos_virtuales.append(pago_virtual)
            
            # Combinar pagos de BD y virtuales, ordenar por fecha
            todos_los_pagos = pagos_db + pagos_virtuales
            
            # Serializar pagos de BD
            pagos_serializados = [PagoSerializer(pago).data for pago in pagos_db]
            
            # Combinar y ordenar
            todos_los_pagos_ordenados = sorted(
                pagos_serializados + pagos_virtuales,
                key=lambda x: x.get('date_approved_mp') or x.get('fecha_creacion') or '',
                reverse=True
            )
            
            return Response(todos_los_pagos_ordenados)
            
        except Cliente.DoesNotExist:
            return Response(
                {'error': 'No se encontró perfil de cliente para este usuario'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error obteniendo historial completo de pagos: {e}", exc_info=True)
            return Response(
                {'error': 'Error al obtener historial de pagos'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
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
        logger.info("📨 Webhook recibido de Mercado Pago")
        logger.info(f"   - Headers: {dict(request.headers)}")
        logger.info(f"   - Data: {request.data}")
        
        # Verificar la firma del webhook si está configurada
        webhook_secret = getattr(settings, 'MERCADOPAGO_WEBHOOK_SECRET', '')
        
        # Mercado Pago puede enviar la firma en diferentes headers
        x_signature = (
            request.headers.get('x-signature', '') or 
            request.headers.get('X-Signature', '') or
            request.headers.get('x-signature-id', '')
        )
        
        # Log para debug
        logger.info(f"   - Webhook Secret configurado: {'Sí' if webhook_secret else 'No'}")
        logger.info(f"   - X-Signature recibido: {'Sí' if x_signature else 'No'}")
        
        # Solo verificar firma si ambos están presentes
        # NOTA: En producción, habilitar verificación estricta
        verificar_firma = False  # Temporalmente deshabilitado para pruebas
        
        if verificar_firma and webhook_secret and x_signature:
            signature_hash = None
            
            # Mercado Pago envía la firma como: sha256=hash o ts=...,v1=...
            if '=' in x_signature:
                # Intentar parsear formato ts=...,v1=...
                if ',v1=' in x_signature:
                    parts = x_signature.split(',')
                    for part in parts:
                        if part.startswith('v1='):
                            signature_hash = part[3:]
                            break
                else:
                    # Formato sha256=hash
                    signature_type, signature_hash = x_signature.split('=', 1)
                    if signature_type != 'sha256':
                        logger.warning(f"Tipo de firma no soportado: {signature_type}")
                        signature_hash = None
            else:
                # Si no tiene prefijo, asumir que es el hash directamente
                signature_hash = x_signature
            
            if signature_hash:
                # Obtener el body
                import json
                if request.body:
                    body_str = request.body.decode('utf-8') if isinstance(request.body, bytes) else str(request.body)
                else:
                    body_str = json.dumps(request.data, separators=(',', ':'))
                
                # Calcular hash del body
                calculated_hash = hmac.new(
                    webhook_secret.encode('utf-8'),
                    body_str.encode('utf-8'),
                    hashlib.sha256
                ).hexdigest()
                
                logger.info(f"   - Hash calculado: {calculated_hash[:20]}...")
                logger.info(f"   - Hash recibido: {signature_hash[:20] if signature_hash else 'N/A'}...")
                
                # Comparar hashes usando comparación segura
                if not hmac.compare_digest(calculated_hash, signature_hash):
                    logger.warning("⚠️ Webhook: firma no válida, pero continuando...")
                    # En lugar de rechazar, solo logueamos la advertencia
                    # return Response(
                    #     {'error': 'Firma inválida'},
                    #     status=status.HTTP_401_UNAUTHORIZED
                    # )
                else:
                    logger.info("✅ Firma del webhook verificada correctamente")
        
        # Registrar la notificación
        notification_type = (
            request.data.get('type')
            or request.data.get('action')
            or request.query_params.get('type')
            or 'payment'
        )

        webhook = WebhookNotificacion.objects.create(
            notification_type=notification_type,
            payment_id_mp=request.data.get('data', {}).get('id'),
            data=request.data,
        )

        # Suscripciones: delegar a su propio handler y retornar temprano
        SUBSCRIPTION_TYPES = (
            'subscription_authorized_payment',
            'authorized_payment',
            'subscription_preapproval',
            'preapproval',
        )
        if notification_type in SUBSCRIPTION_TYPES:
            from mecanimovilapp.apps.suscripciones.suscripcion_services import (
                acreditar_creditos_suscripcion,
                sincronizar_estado_suscripcion,
                obtener_detalle_pago_autorizado,
                verificar_pago_mp,
                MECANIMOVIL_COLLECTOR_ID,
            )
            from mecanimovilapp.apps.suscripciones.models import SuscripcionProveedor

            data = request.data.get('data') or {}
            resource_id = (
                data.get('id')
                or request.query_params.get('data.id')
                or request.query_params.get('id')
            )
            logger.info(
                f"[Webhook General → Suscripciones] type={notification_type}, resource_id={resource_id}"
            )

            if notification_type in ('subscription_authorized_payment', 'authorized_payment'):
                if resource_id:
                    try:
                        detalle_pago = obtener_detalle_pago_autorizado(resource_id)
                        if not detalle_pago:
                            logger.warning(
                                f"[Webhook General] No se pudo obtener detalle del "
                                f"authorized_payment {resource_id}"
                            )
                        else:
                            pago_status = detalle_pago.get('status', '')
                            preapproval_id = detalle_pago.get('preapproval_id')
                            monto = detalle_pago.get('transaction_amount')

                            logger.info(
                                f"[Webhook General] Cobro {resource_id}: "
                                f"status={pago_status}, monto={monto}, "
                                f"preapproval_id={preapproval_id}"
                            )

                            ESTADOS_PAGO_EXITOSO = ('approved', 'authorized', 'processed')
                            if pago_status not in ESTADOS_PAGO_EXITOSO:
                                logger.warning(
                                    f"[Webhook General] Cobro {resource_id} NO aprobado "
                                    f"(status={pago_status}). No se acreditan créditos."
                                )
                            elif not preapproval_id:
                                logger.warning(
                                    f"[Webhook General] Cobro {resource_id} aprobado pero "
                                    f"sin preapproval_id en la respuesta de MP."
                                )
                            else:
                                payment_inner = detalle_pago.get('payment') or {}
                                payment_id = payment_inner.get('id')
                                pago_verificado_data = None
                                if payment_id:
                                    pago_verificado_data = verificar_pago_mp(payment_id)
                                    if pago_verificado_data:
                                        if pago_verificado_data.get('status') != 'approved':
                                            logger.warning(
                                                f"[Webhook General] Payment {payment_id} no aprobado."
                                            )
                                            pago_verificado_data = None
                                        elif pago_verificado_data.get('collector_id') != MECANIMOVIL_COLLECTOR_ID:
                                            logger.error(
                                                f"[Webhook General] ALERTA FRAUDE: "
                                                f"collector {pago_verificado_data.get('collector_id')} "
                                                f"!= {MECANIMOVIL_COLLECTOR_ID}"
                                            )
                                            pago_verificado_data = None

                                if pago_verificado_data or not payment_id:
                                    resultado = acreditar_creditos_suscripcion(
                                        preapproval_id=preapproval_id,
                                        charge_id=resource_id,
                                        pago_verificado=pago_verificado_data,
                                    )
                                    logger.info(f"[Webhook General] Acreditación: {resultado}")
                    except Exception as e:
                        logger.error(f"[Webhook General] Error acreditando: {e}", exc_info=True)

            elif notification_type in ('subscription_preapproval', 'preapproval'):
                preapproval_id = resource_id
                if preapproval_id:
                    try:
                        suscripcion = SuscripcionProveedor.objects.filter(
                            mp_preapproval_id=preapproval_id
                        ).select_related('plan').first()
                        if suscripcion:
                            sincronizar_estado_suscripcion(suscripcion)
                            logger.info(f"[Webhook General] Suscripción {preapproval_id} sincronizada")
                    except Exception as e:
                        logger.error(f"[Webhook General] Error sincronizando: {e}", exc_info=True)

            webhook.procesado = True
            webhook.fecha_procesamiento = timezone.now()
            webhook.save()
            return Response({'status': 'ok'}, status=status.HTTP_200_OK)

        # Procesar el webhook de pagos
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
                        
                        # Obtener external_reference (puede ser carrito_id o oferta_id)
                        external_reference = payment_data.get('external_reference')
                        
                        if external_reference:
                            # Verificar si es una oferta (formato: oferta_{uuid}_{tipo})
                            if external_reference.startswith('oferta_'):
                                try:
                                    from mecanimovilapp.apps.ordenes.models import OfertaProveedor
                                    
                                    # Extraer oferta_id del external_reference
                                    parts = external_reference.split('_')
                                    if len(parts) >= 2:
                                        oferta_id = parts[1]
                                        tipo_pago = parts[2] if len(parts) >= 3 else 'total'
                                        
                                        oferta = OfertaProveedor.objects.select_related(
                                            'solicitud', 'proveedor', 'solicitud__cliente', 'solicitud__cliente__usuario'
                                        ).get(id=oferta_id)
                                        
                                        # Obtener usuario del cliente
                                        usuario = oferta.solicitud.cliente.usuario
                                        
                                        # Crear o actualizar registro de Pago para ofertas
                                        pago, created = Pago.objects.get_or_create(
                                            payment_id_mp=payment_id,
                                            defaults={
                                                'usuario': usuario,
                                                'carrito': None,  # Los pagos de ofertas no tienen carrito
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
                                        
                                        logger.info(f"✅ Pago de oferta {'creado' if created else 'actualizado'}: {pago.id} para oferta {oferta_id}")
                                        
                                        # Si el pago está aprobado, actualizar el estado de la oferta
                                        if payment_data.get('status') == 'approved':
                                            # Actualizar estados según el tipo de pago (misma lógica que confirmar_pago_oferta)
                                            solicitud = oferta.solicitud
                                            
                                            if tipo_pago == 'repuestos':
                                                oferta.estado_pago_repuestos = 'pagado'
                                                oferta.metodo_pago_cliente = 'repuestos_adelantado'
                                                oferta.estado = 'pagada_parcialmente'  # Cambiar a estado parcial
                                                if solicitud.estado not in ['en_ejecucion', 'completada']:
                                                    solicitud.estado = 'pagada'
                                            elif tipo_pago == 'servicio':
                                                from mecanimovilapp.apps.ordenes.services.pago_oferta_cliente import (
                                                    aplicar_confirmacion_pago_servicio,
                                                )
                                                aplicar_confirmacion_pago_servicio(oferta, solicitud)
                                            else:  # total
                                                oferta.estado_pago_repuestos = 'pagado' if oferta.costo_repuestos and float(oferta.costo_repuestos) > 0 else 'no_aplica'
                                                oferta.estado_pago_servicio = 'pagado'
                                                oferta.metodo_pago_cliente = 'todo_adelantado'
                                                oferta.estado = 'pagada'
                                                solicitud.estado = 'pagada'
                                            
                                            oferta.save()
                                            solicitud.save()
                                            logger.info(f"✅ Oferta {oferta_id} actualizada desde webhook: estado={oferta.estado}")
                                        
                                except OfertaProveedor.DoesNotExist:
                                    logger.warning(f"Oferta no encontrada para external_reference: {external_reference}")
                                except Exception as e:
                                    logger.error(f"Error actualizando oferta desde webhook: {e}", exc_info=True)
                            else:
                                # Procesar carrito (código existente) - solo si NO es una oferta
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

# ============================================================================
# ViewSet para Cuenta de Mercado Pago del Proveedor
# ============================================================================

class CuentaMercadoPagoProveedorViewSet(viewsets.GenericViewSet):
    """
    ViewSet para gestionar la cuenta de Mercado Pago del proveedor.
    Permite conectar, desconectar y verificar el estado de la cuenta.
    """
    serializer_class = CuentaMercadoPagoProveedorSerializer
    permission_classes = [IsAuthenticated]
    
    def get_proveedor(self, user):
        """
        Obtiene el proveedor (Taller o MecanicoDomicilio) asociado al usuario.
        """
        from mecanimovilapp.apps.usuarios.models import Taller, MecanicoDomicilio
        
        # Intentar obtener Taller
        try:
            taller = Taller.objects.get(usuario=user)
            return taller, ContentType.objects.get_for_model(Taller)
        except Taller.DoesNotExist:
            pass
        
        # Intentar obtener MecanicoDomicilio
        try:
            mecanico = MecanicoDomicilio.objects.get(usuario=user)
            return mecanico, ContentType.objects.get_for_model(MecanicoDomicilio)
        except MecanicoDomicilio.DoesNotExist:
            pass
        
        return None, None
    
    def get_cuenta(self, user):
        """
        Obtiene o crea la cuenta de Mercado Pago del proveedor.
        """
        try:
            return CuentaMercadoPagoProveedor.objects.get(usuario=user)
        except CuentaMercadoPagoProveedor.DoesNotExist:
            return None
    
    @staticmethod
    def obtener_redirect_uri_ngrok():
        """
        Obtiene el redirect_uri usando la URL de ngrok detectada automáticamente.
        Retorna el redirect_uri normalizado que debe coincidir EXACTAMENTE con el registrado en Mercado Pago.
        """
        ngrok_url = None
        
        try:
            # Intentar obtener la URL de ngrok desde la API local
            ngrok_response = requests.get('http://localhost:4040/api/tunnels', timeout=2)
            if ngrok_response.status_code == 200:
                tunnels_data = ngrok_response.json()
                tunnels_list = tunnels_data.get('tunnels', []) if isinstance(tunnels_data, dict) else []
                
                if tunnels_list:
                    # Buscar el túnel HTTPS (preferido)
                    for tunnel in tunnels_list:
                        if isinstance(tunnel, dict) and tunnel.get('proto') == 'https':
                            ngrok_url = tunnel.get('public_url')
                            if ngrok_url:
                                break
                    # Si no hay HTTPS, usar el primero disponible
                    if not ngrok_url and tunnels_list:
                        first_tunnel = tunnels_list[0]
                        if isinstance(first_tunnel, dict):
                            ngrok_url = first_tunnel.get('public_url')
                
                if ngrok_url:
                    # IMPORTANTE: Normalizar la URL - remover espacios y trailing slashes
                    # El redirect_uri debe ser EXACTAMENTE como está registrado en Mercado Pago
                    ngrok_url = ngrok_url.strip().rstrip('/')
                    redirect_uri = f"{ngrok_url}/api/mercadopago/cuenta-proveedor/callback-oauth/"
                    logger.info(f"✅ URL de ngrok detectada: {ngrok_url}")
                    logger.info(f"✅ Redirect URI generado: {redirect_uri}")
                    return redirect_uri
        except Exception as e:
            logger.debug(f"No se pudo detectar ngrok automáticamente: {e}")
        
        return None
    
    @action(detail=False, methods=['get'], url_path='mi-cuenta')
    def mi_cuenta(self, request):
        """
        Obtiene el estado actual de la cuenta de Mercado Pago del proveedor.
        Devuelve estado 'no_configurada' si el usuario aún no tiene perfil de proveedor.
        """
        cuenta = self.get_cuenta(request.user)
        
        if not cuenta:
            # Verificar si el usuario es proveedor
            proveedor, content_type = self.get_proveedor(request.user)
            
            if not proveedor:
                # Devolver respuesta con estado no_configurada en lugar de error 400
                # Esto permite que el frontend maneje graciosamente usuarios que aún no completaron onboarding
                return Response({
                    'id': None,
                    'estado': 'no_configurada',
                    'estado_display': 'Sin configurar',
                    'email_mp': None,
                    'user_id_mp': None,
                    'nombre_cuenta': None,
                    'fecha_conexion': None,
                    'fecha_actualizacion': None,
                    'puede_recibir_pagos': False,
                    'mensaje_estado': 'Completa tu perfil de proveedor para configurar Mercado Pago.'
                })
            
            # Crear cuenta con estado no_configurada
            cuenta = CuentaMercadoPagoProveedor.objects.create(
                usuario=request.user,
                content_type=content_type,
                object_id=proveedor.id,
                estado='no_configurada'
            )
        
        serializer = self.get_serializer(cuenta)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='iniciar-conexion')
    def iniciar_conexion(self, request):
        """
        Inicia el proceso de conexión OAuth con Mercado Pago.
        Genera la URL de autorización para redirigir al usuario.
        Implementa PKCE (Proof Key for Code Exchange) para mayor seguridad.
        """
        
        # Verificar que el usuario es proveedor
        proveedor, content_type = self.get_proveedor(request.user)
        
        if not proveedor:
            return Response(
                {'error': 'No eres un proveedor registrado'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Obtener o crear la cuenta
        cuenta, created = CuentaMercadoPagoProveedor.objects.get_or_create(
            usuario=request.user,
            defaults={
                'content_type': content_type,
                'object_id': proveedor.id,
                'estado': 'pendiente'
            }
        )
        
        # Si la cuenta ya existe, actualizar content_type y object_id por si cambió
        if not created:
            cuenta.content_type = content_type
            cuenta.object_id = proveedor.id
        
        # Limpiar cualquier estado OAuth anterior para evitar conflictos
        # Esto es importante cuando se reconecta después de desconectar
        cuenta.oauth_state = None
        cuenta.code_verifier = None
        
        # Generar state token único para validar el callback
        state = secrets.token_urlsafe(32)
        
        # Generar PKCE code_verifier y code_challenge
        # code_verifier: string aleatorio de 43-128 caracteres
        code_verifier = secrets.token_urlsafe(64)  # Genera ~86 caracteres
        
        # code_challenge: SHA256 hash del code_verifier, codificado en base64url
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode('utf-8')).digest()
        ).decode('utf-8').rstrip('=')  # Remover padding '='
        
        # Guardar state y code_verifier en la cuenta
        cuenta.oauth_state = state
        cuenta.code_verifier = code_verifier
        cuenta.estado = 'pendiente'
        cuenta.mensaje_estado = 'Esperando autorización de Mercado Pago...'
        cuenta.save()
        
        # Obtener credenciales de la configuración ANTES de modificar la cuenta
        # Esto evita marcar la cuenta como pendiente si hay un error de configuración
        client_id = config('MERCADOPAGO_CLIENT_ID', default='')
        
        if not client_id:
            logger.error("MERCADOPAGO_CLIENT_ID no configurado")
            return Response(
                {'error': 'La integración con Mercado Pago no está configurada correctamente. Por favor, contacta al administrador del sistema.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        
        logger.info(f"OAuth state y code_verifier generados para cuenta {cuenta.id} (usuario {request.user.id})")
        
        # URL de redirect (debe estar configurada en Mercado Pago y coincidir EXACTAMENTE)
        # En desarrollo, SIEMPRE intentar detectar ngrok primero ya que las URLs de ngrok free cambian
        redirect_uri = None
        
        # En modo DEBUG, siempre intentar detectar ngrok automáticamente PRIMERO
        # Las URLs de ngrok free rotan, así que la detección automática es más confiable
        if settings.DEBUG:
            redirect_uri = self.obtener_redirect_uri_ngrok()
        
        # Si no se detectó ngrok o no estamos en DEBUG, usar la configuración de entorno
        if not redirect_uri:
            redirect_uri = config('MERCADOPAGO_REDIRECT_URI', default='')
        
        if not redirect_uri:
            # Fallback a URL del backend (más confiable que frontend)
            # El callback debe ser manejado por el backend
            from django.contrib.sites.models import Site
            try:
                current_site = Site.objects.get_current()
                domain = current_site.domain
            except:
                # Si no hay Site configurado, usar settings
                domain = getattr(settings, 'ALLOWED_HOSTS', ['localhost'])[0]
                if domain == '*':
                    domain = 'localhost'
            
            # Usar el dominio del backend para el callback
            protocol = 'https' if not settings.DEBUG else 'http'
            port = getattr(settings, 'PORT', '8000') if settings.DEBUG else ''
            port_str = f':{port}' if port and settings.DEBUG else ''
            redirect_uri = f"{protocol}://{domain}{port_str}/api/mercadopago/cuenta-proveedor/callback-oauth/"
            logger.warning(f"⚠️ Usando URL local como fallback: {redirect_uri}")
            logger.warning(f"⚠️ Asegúrate de que esta URL esté registrada en Mercado Pago o configura MERCADOPAGO_REDIRECT_URI")
        
        # IMPORTANTE: Normalizar el redirect_uri
        # - Remover espacios en blanco
        # - Asegurar que termine con / (Mercado Pago es estricto con esto)
        redirect_uri_before_normalize = redirect_uri
        redirect_uri = redirect_uri.strip()
        if not redirect_uri.endswith('/'):
            redirect_uri = redirect_uri + '/'
        
        # IMPORTANTE: El redirect_uri debe estar URL-encoded para la query string
        # NO codificar la barra final ya que es parte de la URL
        redirect_uri_encoded = quote(redirect_uri, safe='/')
        
        # Construir URL de autorización de Mercado Pago con PKCE
        # Documentación: https://www.mercadopago.com.ar/developers/es/docs/checkout-api/oauth
        # IMPORTANTE: Todos los parámetros deben estar URL-encoded excepto los que ya lo están
        auth_url = (
            f"https://auth.mercadopago.com/authorization"
            f"?client_id={quote(str(client_id), safe='')}"
            f"&response_type=code"
            f"&platform_id=mp"
            f"&redirect_uri={redirect_uri_encoded}"
            f"&state={quote(state, safe='')}"
            f"&code_challenge={quote(code_challenge, safe='')}"
            f"&code_challenge_method=S256"
        )
        
        logger.info(f"Iniciando conexión OAuth (con PKCE) para proveedor {proveedor.id}")
        logger.info(f"  - Redirect URI (original): {redirect_uri}")
        logger.info(f"  - Redirect URI (encoded): {redirect_uri_encoded}")
        logger.info(f"  - Client ID: {client_id}")
        logger.info(f"  - State: {state[:20]}...")
        logger.info(f"  - Code Challenge: {code_challenge[:20]}...")
        logger.info(f"  - Auth URL completa: {auth_url}")
        
        return Response({
            'auth_url': auth_url,
            'redirect_uri': redirect_uri,
            'state': state
        })
    
    @action(detail=False, methods=['get', 'post'], url_path='callback-oauth', permission_classes=[])
    def callback_oauth(self, request):
        """
        Procesa el callback de OAuth después de la autorización.
        Intercambia el código por tokens de acceso.
        
        NOTA: Este endpoint es PÚBLICO porque Mercado Pago redirige directamente al navegador.
        La seguridad se garantiza mediante el state token único generado al iniciar la conexión.
        """
        # Obtener parámetros de GET o POST
        code = request.GET.get('code') or request.data.get('code')
        state = request.GET.get('state') or request.data.get('state')
        
        # Función para generar página HTML de respuesta
        def html_response(success, title, message, details=None):
            color = '#3DB6B1' if success else '#FF5555'
            icon = '✅' if success else '❌'
            # Solución simple: NO usar deep links, solo mostrar mensaje y cerrar
            # El usuario cierra el navegador manualmente y la app detecta el cambio
            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <title>{title} - MecaniMovil</title>
                <style>
                    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                    body {{
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        min-height: 100vh;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        padding: 20px;
                    }}
                    .container {{
                        background: white;
                        border-radius: 20px;
                        padding: 40px;
                        max-width: 400px;
                        width: 100%;
                        text-align: center;
                        box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                    }}
                    .icon {{
                        font-size: 64px;
                        margin-bottom: 20px;
                    }}
                    h1 {{
                        color: {color};
                        margin-bottom: 10px;
                        font-size: 24px;
                    }}
                    p {{
                        color: #666;
                        line-height: 1.6;
                        margin-bottom: 20px;
                    }}
                    .details {{
                        background: #f5f5f5;
                        padding: 15px;
                        border-radius: 10px;
                        font-size: 12px;
                        color: #999;
                        margin-bottom: 20px;
                        text-align: left;
                    }}
                    .btn {{
                        display: inline-block;
                        background: {color};
                        color: white;
                        padding: 15px 30px;
                        border-radius: 10px;
                        text-decoration: none;
                        font-weight: 600;
                        cursor: pointer;
                        border: none;
                        font-size: 16px;
                    }}
                    .btn:active {{ transform: scale(0.98); opacity: 0.9; }}
                    .logo {{
                        margin-bottom: 20px;
                        font-size: 28px;
                        font-weight: bold;
                        color: #333;
                    }}
                    .close-hint {{
                        background: #f0f9f9;
                        border: 2px dashed {color};
                        border-radius: 10px;
                        padding: 15px;
                        margin-top: 20px;
                    }}
                    .close-hint p {{
                        margin: 0;
                        color: #555;
                        font-size: 14px;
                    }}
                    .arrow {{
                        font-size: 24px;
                        margin-bottom: 5px;
                    }}
                </style>
                <script>
                    function cerrarVentana() {{
                        // Intentar cerrar la ventana/tab
                        window.close();
                        // Si no funciona (restricciones del navegador), mostrar instrucciones
                        setTimeout(function() {{
                            document.getElementById('close-instructions').style.display = 'block';
                        }}, 500);
                    }}
                </script>
            </head>
            <body>
                <div class="container">
                    <div class="logo">🚗 MecaniMovil</div>
                    <div class="icon">{icon}</div>
                    <h1>{title}</h1>
                    <p>{message}</p>
                    {f'<div class="details">{details}</div>' if details else ''}
                    <button class="btn" onclick="cerrarVentana()">
                        ✓ Cerrar y Volver a la App
                    </button>
                    <div class="close-hint">
                        <div class="arrow">👆</div>
                        <p><strong>Presiona el botón</strong> o usa el botón de <strong>atrás/cerrar</strong> de tu navegador para volver a la aplicación.</p>
                    </div>
                    <p id="close-instructions" style="display: none; margin-top: 15px; font-size: 13px; color: #999; background: #fff3cd; padding: 10px; border-radius: 8px;">
                        Si la ventana no se cerró, usa el botón ← atrás de tu teléfono o cierra esta pestaña manualmente.
                    </p>
                </div>
            </body>
            </html>
            """
            from django.http import HttpResponse
            return HttpResponse(html, content_type='text/html')
        
        # Validar parámetros
        if not code or not state:
            logger.warning(f"Callback OAuth sin code o state. code={code}, state={state}")
            return html_response(
                False,
                'Parámetros Inválidos',
                'No se recibieron los parámetros necesarios de Mercado Pago.',
                f'code: {"✓" if code else "✗"}, state: {"✓" if state else "✗"}'
            )
        
        # Verificar que existe una cuenta con este state (sin requerir usuario autenticado)
        try:
            cuenta = CuentaMercadoPagoProveedor.objects.get(oauth_state=state)
        except CuentaMercadoPagoProveedor.DoesNotExist:
            logger.warning(f"State no encontrado en callback OAuth: {state[:20]}...")
            return html_response(
                False,
                'Sesión Expirada',
                'El enlace de autorización ha expirado o es inválido. Por favor, vuelve a la app e inicia el proceso nuevamente.'
            )
        
        # Obtener credenciales
        client_id = config('MERCADOPAGO_CLIENT_ID', default='')
        client_secret = config('MERCADOPAGO_CLIENT_SECRET', default='')
        
        if not client_id or not client_secret:
            logger.error("Credenciales de Mercado Pago no configuradas")
            cuenta.marcar_error('Error de configuración del sistema')
            return html_response(
                False,
                'Error de Configuración',
                'El sistema no está configurado correctamente. Contacta al soporte.'
            )
        
        # En modo DEBUG, siempre detectar ngrok automáticamente PRIMERO (igual que en iniciar_conexion)
        redirect_uri = None
        if settings.DEBUG:
            redirect_uri = CuentaMercadoPagoProveedorViewSet.obtener_redirect_uri_ngrok()
        
        # Si no se detectó ngrok, usar configuración de entorno
        if not redirect_uri:
            redirect_uri = config('MERCADOPAGO_REDIRECT_URI', default='')
        
        if not redirect_uri:
            # Usar el mismo método que en iniciar_conexion
            from django.contrib.sites.models import Site
            try:
                current_site = Site.objects.get_current()
                domain = current_site.domain
            except:
                domain = getattr(settings, 'ALLOWED_HOSTS', ['localhost'])[0]
                if domain == '*':
                    domain = 'localhost'
            
            protocol = 'https' if not settings.DEBUG else 'http'
            port = getattr(settings, 'PORT', '8000') if settings.DEBUG else ''
            port_str = f':{port}' if port and settings.DEBUG else ''
            redirect_uri = f"{protocol}://{domain}{port_str}/api/mercadopago/cuenta-proveedor/callback-oauth/"
        
        # Normalizar el redirect_uri (igual que en iniciar_conexion)
        redirect_uri_before_normalize = redirect_uri
        redirect_uri = redirect_uri.strip()
        if not redirect_uri.endswith('/'):
            redirect_uri = redirect_uri + '/'
        
        try:
            # Intercambiar código por tokens (con PKCE code_verifier)
            logger.info(f"Intercambiando código OAuth para cuenta {cuenta.id}")
            
            # Preparar datos del request
            token_data_request = {
                'grant_type': 'authorization_code',
                'client_id': client_id,
                'client_secret': client_secret,
                'code': code,
                'redirect_uri': redirect_uri,
            }
            
            # Agregar code_verifier si está disponible (PKCE)
            if cuenta.code_verifier:
                token_data_request['code_verifier'] = cuenta.code_verifier
                logger.info("Usando PKCE code_verifier en el intercambio de tokens")
            
            token_response = requests.post(
                'https://api.mercadopago.com/oauth/token',
                data=token_data_request
            )
            
            logger.info(f"Respuesta de token OAuth: status={token_response.status_code}")
            
            if token_response.status_code == 200:
                token_data = token_response.json()
                
                # Conectar la cuenta con los tokens obtenidos
                cuenta.conectar(
                    access_token=token_data.get('access_token'),
                    refresh_token=token_data.get('refresh_token'),
                    user_id_mp=str(token_data.get('user_id', '')),
                    public_key=token_data.get('public_key'),
                    expires_in=token_data.get('expires_in', 15552000)  # 6 meses por defecto
                )
                
                # Intentar obtener información adicional del usuario de Mercado Pago
                try:
                    user_info_response = requests.get(
                        'https://api.mercadopago.com/users/me',
                        headers={'Authorization': f'Bearer {token_data.get("access_token")}'}
                    )
                    
                    if user_info_response.status_code == 200:
                        user_info = user_info_response.json()
                        cuenta.email_mp = user_info.get('email')
                        cuenta.nombre_cuenta = f"{user_info.get('first_name', '')} {user_info.get('last_name', '')}".strip()
                        cuenta.save()
                        logger.info(f"Info de usuario MP obtenida: {cuenta.email_mp}")
                except Exception as e:
                    logger.warning(f"No se pudo obtener info del usuario MP: {e}")
                
                logger.info(f"Cuenta de Mercado Pago conectada exitosamente para usuario {cuenta.usuario.id}")
                
                return html_response(
                    True,
                    '¡Conexión Exitosa!',
                    f'Tu cuenta de Mercado Pago ({cuenta.email_mp or "configurada"}) ha sido conectada correctamente. Ya puedes recibir pagos directos de tus clientes.'
                )
            else:
                error_data = token_response.json()
                error_message = error_data.get('message', error_data.get('error', 'Error al obtener tokens'))
                logger.error(f"Error en OAuth de Mercado Pago: {error_message}")
                cuenta.marcar_error(f'Error de autorización: {error_message}')
                
                return html_response(
                    False,
                    'Error de Autorización',
                    'No se pudo completar la autorización con Mercado Pago. Por favor, intenta nuevamente.',
                    f'Detalle: {error_message}'
                )
        
        except requests.RequestException as e:
            logger.error(f"Error de conexión con Mercado Pago: {e}")
            cuenta.marcar_error('Error de conexión con Mercado Pago')
            return html_response(
                False,
                'Error de Conexión',
                'No se pudo conectar con los servidores de Mercado Pago. Verifica tu conexión e intenta nuevamente.'
            )
        except Exception as e:
            logger.error(f"Error procesando callback OAuth: {e}")
            cuenta.marcar_error('Error inesperado durante la conexión')
            return html_response(
                False,
                'Error Inesperado',
                'Ocurrió un error inesperado. Por favor, intenta nuevamente o contacta al soporte.',
                f'Error: {str(e)}'
            )
    
    @action(detail=False, methods=['post'], url_path='desconectar')
    def desconectar(self, request):
        """
        Desconecta la cuenta de Mercado Pago del proveedor.
        También permite cancelar conexiones pendientes.
        """
        cuenta = self.get_cuenta(request.user)
        
        if not cuenta:
            return Response(
                {'error': 'No tienes una cuenta de Mercado Pago configurada'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Permitir desconectar cuentas conectadas, con error o pendientes
        if cuenta.estado not in ['conectada', 'error', 'pendiente']:
            return Response(
                {'error': 'La cuenta no está en un estado que permita desconexión'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        cuenta.desconectar()
        
        logger.info(f"Cuenta de Mercado Pago desconectada/cancelada para usuario {request.user.id}")
        
        serializer = self.get_serializer(cuenta)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='reconectar')
    def reconectar(self, request):
        """
        Reconecta una cuenta previamente desconectada.
        Mismo flujo que iniciar_conexion pero para cuentas existentes.
        """
        cuenta = self.get_cuenta(request.user)
        
        if not cuenta:
            return Response(
                {'error': 'No tienes una cuenta de Mercado Pago configurada'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if cuenta.estado == 'conectada':
            return Response(
                {'error': 'La cuenta ya está conectada'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Usar el mismo flujo que iniciar_conexion
        return self.iniciar_conexion(request)
    
    @action(detail=False, methods=['get'], url_path='verificar-conexion')
    def verificar_conexion(self, request):
        """
        Verifica el estado de la conexión con Mercado Pago.
        """
        cuenta = self.get_cuenta(request.user)
        
        if not cuenta or cuenta.estado != 'conectada':
            return Response({
                'conectado': False,
                'mensaje': 'No hay cuenta conectada'
            })
        
        # Verificar que el token sigue siendo válido
        if cuenta.token_expirado:
            return Response({
                'conectado': False,
                'mensaje': 'El token ha expirado. Por favor reconecta tu cuenta.'
            })
        
        # Intentar hacer una petición de prueba a Mercado Pago
        try:
            test_response = requests.get(
                'https://api.mercadopago.com/users/me',
                headers={'Authorization': f'Bearer {cuenta.access_token}'}
            )
            
            if test_response.status_code == 200:
                return Response({
                    'conectado': True,
                    'mensaje': 'Conexión verificada correctamente'
                })
            else:
                cuenta.marcar_error('Error al verificar la conexión')
                return Response({
                    'conectado': False,
                    'mensaje': 'Error al verificar la conexión. Por favor reconecta tu cuenta.'
                })
        except Exception as e:
            logger.error(f"Error verificando conexión MP: {e}")
            return Response({
                'conectado': False,
                'mensaje': 'Error de conexión. Por favor intenta más tarde.'
            })
    
    @action(detail=False, methods=['get'], url_path='estadisticas-pagos')
    def estadisticas_pagos(self, request):
        """
        Obtiene estadísticas de pagos recibidos por el proveedor.
        """
        cuenta = self.get_cuenta(request.user)

        if not cuenta or cuenta.estado != 'conectada':
            return Response(respuesta_estadisticas_pagos_vacia())

        # Obtener el proveedor
        proveedor, _ = self.get_proveedor(request.user)

        if not proveedor:
            return Response(respuesta_estadisticas_pagos_vacia())
        
        # Calcular estadísticas desde las ofertas pagadas
        from mecanimovilapp.apps.ordenes.models import OfertaProveedor
        
        # Obtener inicio del mes actual y del mes anterior
        now = timezone.now()
        inicio_mes = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        inicio_mes_anterior = (inicio_mes - timezone.timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Filtrar ofertas pagadas del proveedor
        try:
            # Las ofertas pagadas son las que tienen estado 'pagada', 'en_ejecucion' o 'completada'
            ofertas_base = OfertaProveedor.objects.filter(
                proveedor=request.user
            )
            
            # Total histórico - ofertas pagadas (incluye pagadas parcialmente)
            # IMPORTANTE: Incluir también ofertas que tienen pagos confirmados aunque el estado no sea exactamente 'pagada'
            
            # Verificar ofertas con pagos confirmados
            ofertas_con_pagos_confirmados = ofertas_base.filter(
                Q(estado_pago_repuestos='pagado') | Q(estado_pago_servicio='pagado')
            )
            logger.info(f"📊 Ofertas con pagos confirmados (estado_pago_repuestos='pagado' o estado_pago_servicio='pagado'): {ofertas_con_pagos_confirmados.count()}")
            
            if ofertas_con_pagos_confirmados.exists():
                detalles_pagos_estadisticas = list(ofertas_con_pagos_confirmados.values('id', 'estado', 'estado_pago_repuestos', 'estado_pago_servicio')[:5])
                logger.info(f"   - Detalles de ofertas con pagos confirmados: {detalles_pagos_estadisticas}")
            
            ofertas_pagadas = ofertas_base.filter(
                Q(estado__in=['pagada', 'pagada_parcialmente', 'en_ejecucion', 'completada']) |
                Q(estado_pago_repuestos='pagado') |
                Q(estado_pago_servicio='pagado')
            )
            
            # Logging para debugging
            logger.info(f"📊 Estadísticas de pagos - Usuario: {request.user.id}")
            logger.info(f"   - Total ofertas del proveedor: {ofertas_base.count()}")
            logger.info(f"   - Ofertas pagadas: {ofertas_pagadas.count()}")
# Calcular total recibido considerando pagos parciales
            # Para cada oferta, calcular el monto realmente recibido según el tipo de pago
            total_recibido = 0
            for oferta in ofertas_pagadas:
                # Verificar si es pago parcial (solo repuestos pagados)
                if (oferta.estado_pago_repuestos == 'pagado' and 
                    oferta.estado_pago_servicio in ['pendiente', None]):
                    # Solo repuestos y gestión pagados
                    costo_repuestos = float(oferta.costo_repuestos or 0)
                    costo_gestion = float(oferta.costo_gestion_compra or 0)
                    total_recibido += costo_repuestos + (costo_gestion * 1.19)
                elif oferta.estado == 'pagada_parcialmente':
                    # Si es pago parcial, solo contar lo que se pagó (repuestos + gestión)
                    costo_repuestos = float(oferta.costo_repuestos or 0)
                    costo_gestion = float(oferta.costo_gestion_compra or 0)
                    total_recibido += costo_repuestos + (costo_gestion * 1.19)
                elif (oferta.estado_pago_servicio == 'pagado' and 
                      oferta.estado_pago_repuestos in ['pendiente', 'no_aplica', None]):
                    # Solo servicio pagado (después de haber pagado repuestos antes)
                    costo_mano_obra = float(oferta.costo_mano_obra or 0)
                    total_recibido += costo_mano_obra * 1.19
                else:
                    # Si está completamente pagada, contar el total
                    total_recibido += float(oferta.precio_total_ofrecido or 0)
            
            cantidad_transacciones = ofertas_pagadas.count()
            
            # Este mes - ofertas con fecha de respuesta del cliente en este mes
            # IMPORTANTE: Incluir también ofertas que tienen pagos confirmados aunque el estado no sea exactamente 'pagada'
            ofertas_mes = ofertas_base.filter(
                (Q(estado__in=['pagada', 'pagada_parcialmente', 'en_ejecucion', 'completada']) |
                 Q(estado_pago_repuestos='pagado') |
                 Q(estado_pago_servicio='pagado')),
                fecha_respuesta_cliente__gte=inicio_mes
            )
            
            # Calcular total recibido este mes considerando pagos parciales
            total_recibido_mes = 0
            for oferta in ofertas_mes:
                # Verificar si es pago parcial (solo repuestos pagados)
                if (oferta.estado_pago_repuestos == 'pagado' and 
                    oferta.estado_pago_servicio in ['pendiente', None]):
                    # Solo repuestos y gestión pagados
                    costo_repuestos = float(oferta.costo_repuestos or 0)
                    costo_gestion = float(oferta.costo_gestion_compra or 0)
                    total_recibido_mes += costo_repuestos + (costo_gestion * 1.19)
                elif oferta.estado == 'pagada_parcialmente':
                    # Si es pago parcial, solo contar lo que se pagó (repuestos + gestión)
                    costo_repuestos = float(oferta.costo_repuestos or 0)
                    costo_gestion = float(oferta.costo_gestion_compra or 0)
                    total_recibido_mes += costo_repuestos + (costo_gestion * 1.19)
                elif (oferta.estado_pago_servicio == 'pagado' and 
                      oferta.estado_pago_repuestos in ['pendiente', 'no_aplica', None]):
                    # Solo servicio pagado (después de haber pagado repuestos antes)
                    costo_mano_obra = float(oferta.costo_mano_obra or 0)
                    total_recibido_mes += costo_mano_obra * 1.19
                else:
                    # Si está completamente pagada, contar el total
                    total_recibido_mes += float(oferta.precio_total_ofrecido or 0)
            
            cantidad_transacciones_mes = ofertas_mes.count()
            
            # Mes anterior
            ofertas_mes_anterior = ofertas_base.filter(
                (Q(estado__in=['pagada', 'pagada_parcialmente', 'en_ejecucion', 'completada']) |
                 Q(estado_pago_repuestos='pagado') |
                 Q(estado_pago_servicio='pagado')),
                fecha_respuesta_cliente__gte=inicio_mes_anterior,
                fecha_respuesta_cliente__lt=inicio_mes
            )
            
            total_recibido_mes_anterior = 0
            for oferta in ofertas_mes_anterior:
                if (oferta.estado_pago_repuestos == 'pagado' and 
                    oferta.estado_pago_servicio in ['pendiente', None]):
                    costo_repuestos = float(oferta.costo_repuestos or 0)
                    costo_gestion = float(oferta.costo_gestion_compra or 0)
                    total_recibido_mes_anterior += costo_repuestos + (costo_gestion * 1.19)
                elif oferta.estado == 'pagada_parcialmente':
                    costo_repuestos = float(oferta.costo_repuestos or 0)
                    costo_gestion = float(oferta.costo_gestion_compra or 0)
                    total_recibido_mes_anterior += costo_repuestos + (costo_gestion * 1.19)
                elif (oferta.estado_pago_servicio == 'pagado' and 
                      oferta.estado_pago_repuestos in ['pendiente', 'no_aplica', None]):
                    costo_mano_obra = float(oferta.costo_mano_obra or 0)
                    total_recibido_mes_anterior += costo_mano_obra * 1.19
                else:
                    total_recibido_mes_anterior += float(oferta.precio_total_ofrecido or 0)
            
            cantidad_transacciones_mes_anterior = ofertas_mes_anterior.count()
            
            # Última transacción - usar fecha_respuesta_cliente o fecha_envio como fallback
            ultima = ofertas_pagadas.order_by('-fecha_respuesta_cliente', '-fecha_envio').first()
            ultima_transaccion = None
            if ultima:
                fecha_transaccion = ultima.fecha_respuesta_cliente if ultima.fecha_respuesta_cliente else ultima.fecha_envio
                if fecha_transaccion:
                    ultima_transaccion = fecha_transaccion.isoformat()
            
            # También contar pagos parciales (solo repuestos pagados)
            ofertas_repuestos_pagados = ofertas_base.filter(
                estado_pago_repuestos='pagado'
            )
            cantidad_pagos_repuestos = ofertas_repuestos_pagados.count()
            total_repuestos = ofertas_repuestos_pagados.aggregate(
                total=Sum('costo_repuestos')
            )['total'] or 0
            
        except Exception as e:
            logger.warning(f"Error calculando estadísticas: {e}")
            total_recibido = 0
            total_recibido_mes = 0
            total_recibido_mes_anterior = 0
            cantidad_transacciones = 0
            cantidad_transacciones_mes = 0
            cantidad_transacciones_mes_anterior = 0
            ultima_transaccion = None
            cantidad_pagos_repuestos = 0
            total_repuestos = 0
        
        return Response({
            'total_recibido': float(total_recibido),
            'total_recibido_mes': float(total_recibido_mes),
            'total_recibido_mes_anterior': float(total_recibido_mes_anterior),
            'cantidad_transacciones': cantidad_transacciones,
            'cantidad_transacciones_mes': cantidad_transacciones_mes,
            'cantidad_transacciones_mes_anterior': cantidad_transacciones_mes_anterior,
            'ultima_transaccion': ultima_transaccion,
            'cantidad_pagos_repuestos': cantidad_pagos_repuestos if 'cantidad_pagos_repuestos' in dir() else 0,
            'total_repuestos': float(total_repuestos) if 'total_repuestos' in dir() else 0,
            'moneda': 'CLP'
        })
    
    @action(detail=False, methods=['get'], url_path='historial-pagos')
    def historial_pagos(self, request):
        """
        Obtiene el historial de pagos recibidos por el proveedor.
        Incluye información del cliente y detalles del servicio.
        """
        cuenta = self.get_cuenta(request.user)

        if not cuenta or cuenta.estado != 'conectada':
            return Response(respuesta_historial_pagos_vacio())

        from mecanimovilapp.apps.ordenes.models import OfertaProveedor

        # Obtener ofertas pagadas del proveedor
        try:
            # Primero, actualizar fecha_respuesta_cliente para ofertas pagadas que no la tengan
            # Esto corrige ofertas pagadas antes de que se implementara esta actualización
            ofertas_sin_fecha = OfertaProveedor.objects.filter(
                proveedor=request.user,
                estado__in=['pagada', 'pagada_parcialmente', 'en_ejecucion', 'completada'],
                fecha_respuesta_cliente__isnull=True
            )
            
            if ofertas_sin_fecha.exists():
                logger.info(f"📋 Actualizando fecha_respuesta_cliente para {ofertas_sin_fecha.count()} ofertas pagadas sin fecha")
                # Actualizar cada oferta individualmente para usar fecha_envio como fallback
                for oferta in ofertas_sin_fecha:
                    oferta.fecha_respuesta_cliente = oferta.fecha_envio if oferta.fecha_envio else timezone.now()
                    oferta.save(update_fields=['fecha_respuesta_cliente'])
            
            # IMPORTANTE: Incluir ofertas que tienen pagos confirmados, incluso si el estado no es exactamente 'pagada'
            # Esto incluye ofertas con estado_pago_repuestos='pagado' o estado_pago_servicio='pagado'
            
            # Primero, verificar qué ofertas tienen pagos confirmados
            todas_las_ofertas = OfertaProveedor.objects.filter(proveedor=request.user)
            ofertas_con_pagos = todas_las_ofertas.filter(
                Q(estado_pago_repuestos='pagado') | Q(estado_pago_servicio='pagado')
            )
            logger.info(f"📋 Historial de pagos - Usuario: {request.user.id}")
            logger.info(f"   - Total ofertas del proveedor: {todas_las_ofertas.count()}")
            logger.info(f"   - Ofertas con pagos confirmados (estado_pago_repuestos='pagado' o estado_pago_servicio='pagado'): {ofertas_con_pagos.count()}")
            
            if ofertas_con_pagos.exists():
                detalles_pagos = list(ofertas_con_pagos.values('id', 'estado', 'estado_pago_repuestos', 'estado_pago_servicio', 'fecha_respuesta_cliente')[:10])
                logger.info(f"   - Detalles de ofertas con pagos: {detalles_pagos}")
            
            # También verificar ofertas con estado pagada_parcialmente
            ofertas_parciales = todas_las_ofertas.filter(estado='pagada_parcialmente')
            logger.info(f"   - Ofertas con estado 'pagada_parcialmente': {ofertas_parciales.count()}")
            if ofertas_parciales.exists():
                detalles_parciales = list(ofertas_parciales.values('id', 'estado', 'estado_pago_repuestos', 'estado_pago_servicio', 'fecha_respuesta_cliente')[:10])
                logger.info(f"   - Detalles de ofertas parciales: {detalles_parciales}")
            
            ofertas_pagadas = OfertaProveedor.objects.filter(
                proveedor=request.user
            ).filter(
                Q(estado__in=['pagada', 'pagada_parcialmente', 'en_ejecucion', 'completada']) |
                Q(estado_pago_repuestos='pagado') |
                Q(estado_pago_servicio='pagado')
            ).select_related(
                'solicitud__cliente__usuario',
                'solicitud__vehiculo'
            ).prefetch_related(
                'solicitud__servicios_solicitados'
            ).order_by(
                F('fecha_respuesta_cliente').desc(nulls_last=True),
                '-fecha_envio'
            )[:50]  # Últimas 50 transacciones
            
            logger.info(f"   - Ofertas pagadas encontradas después del filtro: {ofertas_pagadas.count()}")
            
            # Log adicional para ver qué estados tienen las ofertas
            if ofertas_pagadas.exists():
                estados_encontrados = list(ofertas_pagadas.values_list('estado', 'estado_pago_repuestos', 'estado_pago_servicio')[:10])
                logger.info(f"   - Estados de ofertas encontradas (primeras 10): {estados_encontrados}")
            
            historial = []
            for idx, oferta in enumerate(ofertas_pagadas):
                try:
                    # Obtener información del cliente
                    cliente = oferta.solicitud.cliente
                    cliente_nombre = 'Cliente'
                    cliente_email = None
                    if cliente and cliente.usuario:
                        nombre = f"{cliente.usuario.first_name or ''} {cliente.usuario.last_name or ''}".strip()
                        cliente_nombre = nombre if nombre else cliente.usuario.username
                        cliente_email = cliente.usuario.email
                    
                    # Obtener servicios
                    servicios = list(oferta.solicitud.servicios_solicitados.values_list('nombre', flat=True))
                    servicios_texto = ', '.join(servicios[:2]) if servicios else 'Servicio'
                    if len(servicios) > 2:
                        servicios_texto += f' (+{len(servicios) - 2})'
                    
                    # Obtener vehículo
                    vehiculo = oferta.solicitud.vehiculo
                    vehiculo_texto = f"{vehiculo.marca} {vehiculo.modelo}" if vehiculo else 'Vehículo'
                    
                    # Determinar tipo de pago y monto según el estado
                    tipo_pago = 'Pago completo'
                    monto_pagado = float(oferta.precio_total_ofrecido or 0)
                    
                    if oferta.estado == 'pagada_parcialmente':
                        # Pago parcial: solo repuestos y gestión de compra pagados
                        if oferta.estado_pago_repuestos == 'pagado' and oferta.estado_pago_servicio == 'pendiente':
                            costo_repuestos = float(oferta.costo_repuestos or 0)
                            costo_gestion = float(oferta.costo_gestion_compra or 0)
                            monto_pagado = costo_repuestos + (costo_gestion * 1.19)
                            tipo_pago = 'Pago de repuestos y gestión'
                        # Si pagó el servicio después de repuestos (aunque esto no debería estar en pagada_parcialmente)
                        elif oferta.estado_pago_servicio == 'pagado' and oferta.estado_pago_repuestos == 'pagado':
                            # Esto no debería ocurrir, pero por si acaso
                            monto_pagado = float(oferta.precio_total_ofrecido or 0)
                            tipo_pago = 'Pago completo'
                    elif oferta.estado_pago_repuestos == 'pagado' and oferta.estado_pago_servicio == 'pendiente':
                        # Solo repuestos pagados (aunque el estado no sea pagada_parcialmente)
                        costo_repuestos = float(oferta.costo_repuestos or 0)
                        costo_gestion = float(oferta.costo_gestion_compra or 0)
                        monto_pagado = costo_repuestos + (costo_gestion * 1.19)
                        tipo_pago = 'Pago de repuestos y gestión'
                    elif oferta.estado_pago_servicio == 'pagado' and oferta.estado_pago_repuestos == 'pagado':
                        # Pago completo
                        monto_pagado = float(oferta.precio_total_ofrecido or 0)
                        tipo_pago = 'Pago completo'
                    elif oferta.estado_pago_servicio == 'pagado' and oferta.estado_pago_repuestos in ['pendiente', 'no_aplica']:
                        # Solo servicio pagado (después de haber pagado repuestos antes)
                        costo_mano_obra = float(oferta.costo_mano_obra or 0)
                        monto_pagado = costo_mano_obra * 1.19  # Con IVA
                        tipo_pago = 'Pago de mano de obra'
                    
                    # Usar fecha_respuesta_cliente en lugar de fecha_aceptacion_cliente
                    fecha_pago = None
                    if oferta.fecha_respuesta_cliente:
                        fecha_pago = oferta.fecha_respuesta_cliente.isoformat()
                    elif oferta.fecha_envio:
                        fecha_pago = oferta.fecha_envio.isoformat()
                    
                    historial.append({
                        'id': str(oferta.id),
                        'fecha': fecha_pago,
                        'monto': monto_pagado,
                        'cliente_nombre': cliente_nombre,
                        'cliente_email': cliente_email,
                        'servicios': servicios_texto,
                        'vehiculo': vehiculo_texto,
                        'tipo_pago': tipo_pago,
                        'estado_oferta': oferta.estado,
                        'estado_pago_repuestos': oferta.estado_pago_repuestos,
                        'estado_pago_servicio': oferta.estado_pago_servicio,
                        'costo_repuestos': float(oferta.costo_repuestos or 0),
                        'costo_mano_obra': float(oferta.costo_mano_obra or 0),
                        'costo_gestion_compra': float(oferta.costo_gestion_compra or 0),
                        'precio_total': float(oferta.precio_total_ofrecido or 0),
                    })
                except Exception as item_error:
                    logger.warning(f"Error procesando oferta {oferta.id} en historial: {item_error}")
                    continue
            
            return Response({
                'historial': historial,
                'total_resultados': len(historial),
                'moneda': 'CLP'
            })
            
        except Exception as e:
            logger.error(f"Error obteniendo historial de pagos: {e}", exc_info=True)
            return Response(
                {'error': 'Error al obtener el historial de pagos'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'], url_path='actualizar-info')
    def actualizar_info(self, request):
        """
        Actualiza la información de la cuenta (sincroniza con Mercado Pago).
        """
        cuenta = self.get_cuenta(request.user)
        
        if not cuenta or cuenta.estado != 'conectada':
            return Response(
                {'error': 'No tienes una cuenta de Mercado Pago conectada'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Obtener información actualizada del usuario de Mercado Pago
            user_info_response = requests.get(
                'https://api.mercadopago.com/users/me',
                headers={'Authorization': f'Bearer {cuenta.access_token}'}
            )
            
            if user_info_response.status_code == 200:
                user_info = user_info_response.json()
                cuenta.email_mp = user_info.get('email')
                cuenta.nombre_cuenta = f"{user_info.get('first_name', '')} {user_info.get('last_name', '')}".strip()
                cuenta.user_id_mp = str(user_info.get('id', ''))
                cuenta.save()
                
                serializer = self.get_serializer(cuenta)
                return Response(serializer.data)
            else:
                return Response(
                    {'error': 'Error al obtener información de Mercado Pago'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except Exception as e:
            logger.error(f"Error actualizando info de cuenta MP: {e}")
            return Response(
                {'error': 'Error al actualizar la información'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

# ============================================================================
# ENDPOINT PARA PAGO DIRECTO AL PROVEEDOR
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def crear_preferencia_pago_proveedor(request):
    """
    Crea una preferencia de pago que va directamente a la cuenta de Mercado Pago del proveedor.
    
    El cliente paga y el dinero va directo al proveedor, sin pasar por Mecanimovil.
    
    Body esperado:
    {
        "oferta_id": "uuid-de-la-oferta",
        "tipo_pago": "repuestos" | "servicio" | "total",
        "back_urls": {
            "success": "url",
            "failure": "url", 
            "pending": "url"
        }
    }
    """
    from mecanimovilapp.apps.ordenes.models import OfertaProveedor
    import mercadopago
    
    oferta_id = request.data.get('oferta_id')
    tipo_pago = request.data.get('tipo_pago', 'total')  # repuestos, servicio, total
    back_urls = request.data.get('back_urls', {})
    
    if not oferta_id:
        return Response(
            {'error': 'Se requiere oferta_id'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        # Obtener la oferta
        oferta = OfertaProveedor.objects.select_related(
            'proveedor', 'solicitud', 'solicitud__cliente', 'solicitud__vehiculo'
        ).get(id=oferta_id)
        
        # Verificar que el usuario sea el cliente de la solicitud
        if oferta.solicitud.cliente.usuario != request.user:
            return Response(
                {'error': 'No tienes permiso para pagar esta oferta'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Verificar que la oferta esté en estado válido para pagar
        estados_validos = ['aceptada', 'pendiente_pago']
        estados_validos_saldo_servicio = ['pagada_parcialmente', 'en_ejecucion']

        saldo_servicio_pendiente = (
            tipo_pago == 'servicio'
            and oferta.estado_pago_repuestos == 'pagado'
            and oferta.estado_pago_servicio == 'pendiente'
        )

        # ✅ Pago del saldo restante (mano de obra): repuestos ya pagados, servicio pendiente.
        # Aplica en pagada_parcialmente o en_ejecucion (proveedor ya inició el servicio).
        if saldo_servicio_pendiente and oferta.estado in estados_validos_saldo_servicio:
            logger.info(
                f"✅ Permitiendo pago parcial de servicio para oferta {oferta.id}: "
                f"estado={oferta.estado}, "
                f"estado_pago_repuestos={oferta.estado_pago_repuestos}, "
                f"estado_pago_servicio={oferta.estado_pago_servicio}"
            )
        elif oferta.estado == 'pagada_parcialmente':
            if tipo_pago == 'servicio':
                return Response(
                    {
                        'error': f'No se puede pagar el servicio. Estado actual: '
                        f'repuestos={oferta.estado_pago_repuestos}, servicio={oferta.estado_pago_servicio}'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            return Response(
                {
                    'error': f'La oferta ya tiene un pago parcial. Solo puedes pagar el saldo restante del servicio. '
                    f'Estado actual: {oferta.estado}'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        elif oferta.estado not in estados_validos:
            return Response(
                {'error': f'La oferta no está en un estado válido para pagar. Estado actual: {oferta.estado}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Obtener la cuenta de Mercado Pago del proveedor
        cuenta_proveedor = CuentaMercadoPagoProveedor.objects.filter(
            usuario=oferta.proveedor,
            estado='conectada'
        ).first()
        
        if not cuenta_proveedor or not cuenta_proveedor.access_token:
            return Response(
                {'error': 'El proveedor no tiene configurado Mercado Pago para recibir pagos'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Obtener descripción de la solicitud (usar servicios solicitados o descripción del problema)
        servicios_nombres = list(oferta.solicitud.servicios_solicitados.values_list('nombre', flat=True))
        titulo_servicio = ', '.join(servicios_nombres[:2]) if servicios_nombres else 'Servicio mecánico'
        if len(servicios_nombres) > 2:
            titulo_servicio += f' (+{len(servicios_nombres) - 2} más)'
        
        # Calcular el monto según el tipo de pago (Decimal, sin redondear a entero)
        from decimal import Decimal
        IVA = Decimal('1.19')

        if tipo_pago == 'repuestos':
            costo_repuestos = Decimal(str(oferta.costo_repuestos or 0))
            costo_gestion = Decimal(str(oferta.costo_gestion_compra or 0))
            monto = costo_repuestos + costo_gestion * IVA
            
            if costo_gestion > 0:
                descripcion = f"Repuestos + Gestión de compra - {titulo_servicio}"
            else:
                descripcion = f"Repuestos - {titulo_servicio}"
            
            if float(monto) <= 0:
                return Response(
                    {'error': 'Esta oferta no tiene repuestos para pagar'},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        elif tipo_pago == 'servicio':
            monto = Decimal(str(oferta.costo_mano_obra or 0)) * IVA
            descripcion = f"Mano de obra - {titulo_servicio}"
            
        else:  # total
            monto = Decimal(str(oferta.precio_total_ofrecido or 0))
            descripcion = f"Servicio completo - {titulo_servicio}"
        
        # Crear el SDK de Mercado Pago con el access_token del PROVEEDOR
        sdk = mercadopago.SDK(cuenta_proveedor.access_token)
        
        # Información del pagador (cliente)
        payer_info = {
            'name': request.user.first_name or 'Cliente',
            'surname': request.user.last_name or 'MecaniMovil',
            'email': request.user.email,
        }
        
        # Construir la preferencia
        # IMPORTANTE: Las back_urls pueden ser HTTPS (web) o mecanimovil:// (nativo).
        # Mercado Pago agregará automáticamente los parámetros de query (status, payment_id, etc.)
        back_urls_config = {
            'success': back_urls.get('success', ''),
            'failure': back_urls.get('failure', ''),
            'pending': back_urls.get('pending', ''),
        }

        # auto_return requiere URLs HTTPS válidas; los deep links nativos (mecanimovil://)
        # son manejados internamente por el WebView/app y no necesitan auto_return.
        success_url_proveedor = back_urls_config.get('success', '')
        use_auto_return_proveedor = success_url_proveedor.startswith('https://')
        
        # CLP no admite decimales (restricción de MP y del peso chileno). Redondeamos a peso
        # entero con HALF_UP, igual que la boleta del SII y que la app (Math.round), de modo que
        # el monto cobrado coincida exactamente con el mostrado al usuario.
        from decimal import ROUND_HALF_UP
        unit_price = int(Decimal(str(monto)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        if unit_price <= 0:
            unit_price = 1

        preference_data = {
            'items': [
                {
                    'id': str(oferta.id),
                    'title': descripcion,
                    'description': f"Servicio para {oferta.solicitud.vehiculo.marca} {oferta.solicitud.vehiculo.modelo}",
                    'quantity': 1,
                    'unit_price': unit_price,
                    'currency_id': 'CLP',
                }
            ],
            'payer': payer_info,
            'external_reference': f"oferta_{oferta.id}_{tipo_pago}",
            'back_urls': back_urls_config,
            'statement_descriptor': 'MECANIMOVIL',
            'binary_mode': False,
        }
        if use_auto_return_proveedor:
            preference_data['auto_return'] = 'approved'

        logger.info(f"📤 Creando preferencia de pago directo al proveedor")
        logger.info(f"   - Oferta: {oferta.id}")
        logger.info(f"   - Tipo pago: {tipo_pago}")
        logger.info(f"   - Monto: ${monto}")
        logger.info(f"   - Unit price (CLP): ${unit_price}")
        logger.info(f"   - Proveedor: {oferta.nombre_proveedor}")
        logger.info(f"   - Back URLs: {back_urls_config}")
        logger.info(f"   - Auto Return: {'approved (HTTPS)' if use_auto_return_proveedor else 'desactivado (deep link nativo)'}")
# Crear la preferencia usando el SDK del proveedor
        preference_response = sdk.preference().create(preference_data)
        
        if preference_response.get('status') in [200, 201]:
            preference = preference_response.get('response', {})
            
            logger.info(f"✅ Preferencia creada exitosamente: {preference.get('id')}")
            
            # Actualizar el estado de la oferta
            # ✅ No cambiar el estado si ya está en 'pagada_parcialmente' (pago del saldo restante)
            # Solo actualizar si está en 'aceptada' (primer pago)
            if oferta.estado == 'aceptada':
                oferta.estado = 'pendiente_pago'
                oferta.save(update_fields=['estado'])
            elif oferta.estado in estados_validos_saldo_servicio and tipo_pago == 'servicio':
                # Mantener estado hasta confirmar el pago completo del servicio
                logger.info(
                    f"✅ Manteniendo estado '{oferta.estado}' para pago del saldo restante"
                )
            
            return Response({
                'success': True,
                'preference_id': preference.get('id'),
                'init_point': preference.get('init_point'),
                'sandbox_init_point': preference.get('sandbox_init_point'),
                'monto': unit_price,
                'tipo_pago': tipo_pago,
                'proveedor': oferta.nombre_proveedor,
                'external_reference': f"oferta_{oferta.id}_{tipo_pago}",
            })
        else:
            logger.error(f"❌ Error creando preferencia: {preference_response}")
            return Response(
                {'error': 'Error al crear la preferencia de pago con Mercado Pago'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            
    except OfertaProveedor.DoesNotExist:
        return Response(
            {'error': 'Oferta no encontrada'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"❌ Error creando preferencia de pago al proveedor: {e}", exc_info=True)
        return Response(
            {'error': f'Error al procesar el pago: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def confirmar_pago_oferta(request):
    """
    Confirma el pago de una oferta después del retorno de Mercado Pago.
    
    Este endpoint se llama desde el frontend cuando el usuario regresa de Mercado Pago
    con un pago exitoso. Verifica el estado del pago con MP y actualiza los estados
    de la oferta y solicitud según corresponda.
    
    Body esperado:
    {
        "oferta_id": "uuid-de-la-oferta",
        "tipo_pago": "repuestos" | "servicio" | "total",
        "payment_id": "id-del-pago-mp" (opcional),
        "external_reference": "oferta_xxx_tipo" (opcional),
        "status": "approved" | "pending" | ... (opcional)
    }
    
    Returns:
    {
        "success": true,
        "oferta_estado": "pagada",
        "solicitud_estado": "pagada",
        "estado_pago_repuestos": "pagado",
        "estado_pago_servicio": "pagado",
        "puede_pagar_servicio": false,
        "monto_pendiente_servicio": 0,
        "message": "Pago confirmado exitosamente"
    }
    """
    from mecanimovilapp.apps.ordenes.models import OfertaProveedor
    import mercadopago
    
    oferta_id = request.data.get('oferta_id')
    tipo_pago = request.data.get('tipo_pago', 'total')
    payment_id = request.data.get('payment_id')
    payment_status = request.data.get('status', 'approved')
    external_reference = request.data.get('external_reference')
    
    # Extraer oferta_id del external_reference si no se proporciona directamente
    if not oferta_id and external_reference:
        try:
            # external_reference tiene formato: oferta_{uuid}_{tipo}
            parts = external_reference.split('_')
            if len(parts) >= 2 and parts[0] == 'oferta':
                oferta_id = parts[1]
                if len(parts) >= 3:
                    tipo_pago = parts[2]
        except Exception as e:
            logger.warning(f"Error parseando external_reference: {e}")
    
    if not oferta_id:
        return Response(
            {'error': 'Se requiere oferta_id o external_reference'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    from mecanimovilapp.apps.ordenes.services.resolver_oferta_pago import (
        resolver_oferta_pago_por_id,
    )

    try:
        oferta = resolver_oferta_pago_por_id(oferta_id, request.user)
        oferta_id = str(oferta.id)
        
        # Verificar el estado del pago con Mercado Pago si se proporciona payment_id
        pago_verificado = False
        payment_data = {}
        
        if payment_id:
            try:
                # Obtener la cuenta de MP del proveedor para verificar
                cuenta_proveedor = CuentaMercadoPagoProveedor.objects.filter(
                    usuario=oferta.proveedor,
                    estado='conectada'
                ).first()
                
                if cuenta_proveedor and cuenta_proveedor.access_token:
                    sdk = mercadopago.SDK(cuenta_proveedor.access_token)
                    payment_response = sdk.payment().get(payment_id)
                    
                    if payment_response.get('status') in [200, 201]:
                        payment_data = payment_response.get('response', {})
                        payment_status = payment_data.get('status', payment_status)
                        pago_verificado = True
                        logger.info(f"✅ Pago {payment_id} verificado con MP: {payment_status}")
            except Exception as e:
                logger.warning(f"⚠️ No se pudo verificar el pago con MP: {e}")
        
        # Si el pago no está aprobado, no confirmar (a menos que no haya payment_id y el status sea 'approved')
        # En algunos casos, el frontend puede confirmar el pago sin payment_id si el usuario completó el pago
        if payment_status not in ['approved', 'success']:
            # Si no hay payment_id pero el status es 'approved', permitir la confirmación
            # Esto puede ocurrir cuando el WebView detecta que el pago se completó pero no captura el deep link
            if not payment_id and payment_status == 'approved':
                logger.info(f"⚠️ Confirmando pago sin payment_id (status: {payment_status})")
                logger.info(f"   - Esto puede ocurrir cuando el WebView detecta el pago pero no captura el deep link")
            else:
                return Response({
                    'success': False,
                    'error': f'El pago no fue aprobado. Estado: {payment_status}',
                    'oferta_estado': oferta.estado,
                    'payment_status': payment_status,
                }, status=status.HTTP_400_BAD_REQUEST)
        
        # Actualizar estados según el tipo de pago
        solicitud = oferta.solicitud
        
        logger.info(f"📤 Confirmando pago de oferta {oferta_id}")
        logger.info(f"   - Tipo pago: {tipo_pago}")
        logger.info(f"   - Payment ID: {payment_id}")
        logger.info(f"   - Estado anterior oferta: {oferta.estado}")
        logger.info(f"   - Estado anterior solicitud: {solicitud.estado}")
        
        # Actualizar fecha_respuesta_cliente cuando se confirma cualquier pago
        # Esto es importante para que aparezca en estadísticas e historial
        # IMPORTANTE: Actualizar siempre, no solo si no existe, para reflejar la fecha real del pago
        oferta.fecha_respuesta_cliente = timezone.now()
        
        if tipo_pago == 'repuestos':
            # Solo pagó repuestos - El servicio se paga después
            oferta.estado_pago_repuestos = 'pagado'
            oferta.metodo_pago_cliente = 'repuestos_adelantado'
            # IMPORTANTE: Usar estado 'pagada_parcialmente' para indicar que falta pagar el servicio
            oferta.estado = 'pagada_parcialmente'
            
            # Calcular monto pendiente del servicio
            costo_mano_obra = float(oferta.costo_mano_obra or 0)
            monto_pendiente = costo_mano_obra * 1.19  # Con IVA
            
            # La solicitud pública pasa a 'pagada' (parcialmente pagado es info del nivel de oferta,
            # no de la solicitud — 'pagada_parcialmente' no existe como choice en SolicitudServicioPublica)
            if solicitud.estado not in ['en_ejecucion', 'completada']:
                solicitud.estado = 'pagada'
            
            message = 'Pago de repuestos confirmado. El servicio se pagará al finalizar.'
            puede_pagar_servicio = True
            
        elif tipo_pago == 'servicio':
            from mecanimovilapp.apps.ordenes.services.pago_oferta_cliente import (
                aplicar_confirmacion_pago_servicio,
            )
            aplicar_confirmacion_pago_servicio(oferta, solicitud)
            monto_pendiente = 0
            puede_pagar_servicio = False
            if oferta.metodo_pago_cliente == 'cliente_compra_repuestos':
                message = 'Pago de mano de obra confirmado. El cliente comprará los repuestos por su cuenta.'
            else:
                message = 'Pago del servicio confirmado. ¡Pago completo!'
            
        else:  # total
            # Pagó todo de una vez
            oferta.estado_pago_repuestos = 'pagado' if oferta.costo_repuestos and float(oferta.costo_repuestos) > 0 else 'no_aplica'
            oferta.estado_pago_servicio = 'pagado'
            oferta.metodo_pago_cliente = 'todo_adelantado'
            oferta.estado = 'pagada'
            
            solicitud.estado = 'pagada'
            
            monto_pendiente = 0
            puede_pagar_servicio = False
            
            message = '¡Pago completo confirmado exitosamente!'
        
        # Guardar cambios
        oferta.save()
        solicitud.save()
        
        logger.info(f"✅ Pago confirmado exitosamente")
        logger.info(f"   - Estado nuevo oferta: {oferta.estado}")
        logger.info(f"   - Estado nuevo solicitud: {solicitud.estado}")
        logger.info(f"   - Estado pago repuestos: {oferta.estado_pago_repuestos}")
        logger.info(f"   - Estado pago servicio: {oferta.estado_pago_servicio}")

        # Notificar al proveedor via WebSocket para que refresque su lista de órdenes
        try:
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer
            channel_layer = get_channel_layer()
            if channel_layer:
                async_to_sync(channel_layer.group_send)(
                    f"proveedor_{oferta.proveedor.id}",
                    {
                        'type': 'pago_completado',
                        'oferta_id': str(oferta.id),
                        'solicitud_id': str(solicitud.id),
                        'tipo_pago': tipo_pago,
                        'estado_oferta': oferta.estado,
                        'timestamp': str(timezone.now().isoformat()),
                    },
                )
                logger.info(f"✅ Notificación WebSocket pago_completado enviada al proveedor {oferta.proveedor.id}")
        except Exception as ws_err:
            logger.warning(f"⚠️ No se pudo enviar notificación WebSocket al proveedor: {ws_err}")

        return Response({
            'success': True,
            'oferta_id': str(oferta.id),
            'oferta_estado': oferta.estado,
            'solicitud_estado': solicitud.estado,
            'estado_pago_repuestos': oferta.estado_pago_repuestos,
            'estado_pago_servicio': oferta.estado_pago_servicio,
            'metodo_pago_cliente': oferta.metodo_pago_cliente,
            'puede_pagar_servicio': puede_pagar_servicio,
            'monto_pendiente_servicio': monto_pendiente if tipo_pago == 'repuestos' else 0,
            'payment_id': payment_id,
            'payment_verified': pago_verificado,
            'message': message,
        })
    
    except OfertaProveedor.DoesNotExist:
        return Response(
            {'error': 'Oferta no encontrada'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"❌ Error confirmando pago de oferta: {e}", exc_info=True)
        return Response(
            {'error': f'Error al confirmar el pago: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def obtener_estado_pago_oferta(request, oferta_id):
    """
    Obtiene el estado actual de pago de una oferta.
    
    Útil para verificar si el usuario ya pagó o qué le falta pagar.
    
    Returns:
    {
        "oferta_id": "uuid",
        "oferta_estado": "pagada",
        "estado_pago_repuestos": "pagado",
        "estado_pago_servicio": "pendiente",
        "metodo_pago_cliente": "repuestos_adelantado",
        "puede_pagar_servicio": true,
        "monto_pendiente_servicio": 50000,
        "costo_repuestos": 40000,
        "costo_mano_obra": 42016,  // Sin IVA
        "costo_gestion_compra": 5000,
        "precio_total": 103571
    }
    """
    from mecanimovilapp.apps.ordenes.services.resolver_oferta_pago import (
        resolver_oferta_pago_por_id,
    )

    try:
        oferta = resolver_oferta_pago_por_id(oferta_id, request.user)
        
        # Calcular monto pendiente del servicio
        costo_mano_obra = float(oferta.costo_mano_obra or 0)
        monto_pendiente_servicio = 0
        puede_pagar_servicio = False
        
        if oferta.estado_pago_repuestos == 'pagado' and oferta.estado_pago_servicio == 'pendiente':
            monto_pendiente_servicio = costo_mano_obra * 1.19  # Con IVA
            puede_pagar_servicio = True
        
        return Response({
            'oferta_id': str(oferta.id),
            'oferta_estado': oferta.estado,
            'solicitud_estado': oferta.solicitud.estado,
            'estado_pago_repuestos': oferta.estado_pago_repuestos,
            'estado_pago_servicio': oferta.estado_pago_servicio,
            'metodo_pago_cliente': oferta.metodo_pago_cliente,
            'puede_pagar_servicio': puede_pagar_servicio,
            'monto_pendiente_servicio': monto_pendiente_servicio,
            'costo_repuestos': float(oferta.costo_repuestos or 0),
            'costo_mano_obra': costo_mano_obra,
            'costo_gestion_compra': float(oferta.costo_gestion_compra or 0),
            'precio_total': float(oferta.precio_total_ofrecido or 0),
        })
        
    except OfertaProveedor.DoesNotExist:
        return Response(
            {'error': 'Oferta no encontrada'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"❌ Error obteniendo estado de pago: {e}", exc_info=True)
        return Response(
            {'error': f'Error al obtener estado de pago: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verificar_pago_mercadopago(request):
    """
    Verificar directamente con Mercado Pago si un pago fue completado.
    
    Este endpoint busca pagos en Mercado Pago usando el external_reference
    y confirma el pago si encuentra uno aprobado.
    
    Body esperado:
    {
        "oferta_id": "uuid-de-la-oferta",
        "tipo_pago": "repuestos" | "servicio" | "total",
        "preference_id": "preference-id-opcional"
    }
    
    Returns:
    {
        "success": true,
        "payment_found": true,
        "payment_approved": true,
        "payment_id": "payment-id",
        "oferta_estado": "pagada",
        "message": "Pago verificado y confirmado"
    }
    """
    from mecanimovilapp.apps.ordenes.services.resolver_oferta_pago import (
        resolver_oferta_pago_por_id,
    )
    import mercadopago

    oferta_id = request.data.get('oferta_id')
    tipo_pago = request.data.get('tipo_pago', 'total')
    preference_id = request.data.get('preference_id')

    if not oferta_id:
        return Response(
            {'error': 'Se requiere oferta_id'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        oferta = resolver_oferta_pago_por_id(oferta_id, request.user)
        oferta_id = str(oferta.id)
        
        # Obtener la cuenta de Mercado Pago del proveedor
        cuenta_proveedor = CuentaMercadoPagoProveedor.objects.filter(
            usuario=oferta.proveedor,
            estado='conectada'
        ).first()
        
        if not cuenta_proveedor or not cuenta_proveedor.access_token:
            return Response(
                {'error': 'El proveedor no tiene configurado Mercado Pago'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Crear SDK de Mercado Pago con el token del proveedor
        sdk = mercadopago.SDK(cuenta_proveedor.access_token)
        
        # Construir el external_reference esperado
        external_reference = f"oferta_{oferta_id}_{tipo_pago}"
        
        logger.info(f"🔍 Verificando pago  directo en Mercado Pago")
        logger.info(f"   - Oferta: {oferta_id}")
        logger.info(f"   - External reference: {external_reference}")
        logger.info(f"   - Preference ID: {preference_id}")
        
        # Buscar pagos relacionados a esta preferencia o external_reference
        # Mercado Pago permite buscar pagos por external_reference
        search_filters = {
            "external_reference": external_reference,
            "limit": 10,
            "offset": 0
        }
        
        try:
            # Buscar pagos con el external_reference
            search_response = sdk.payment().search(filters=search_filters)
            
            logger.info(f"📥 Respuesta de búsqueda de pagos: status={search_response.get('status')}")
            
            if search_response.get('status') in [200, 201]:
                search_data = search_response.get('response', {})
                results = search_data.get('results', [])
                
                logger.info(f"   - Pagos encontrados: {len(results)}")
                
                if results:
                    # Tomar el pago más reciente
                    payment_data = results[0]
                    payment_id = payment_data.get('id')
                    payment_status = payment_data.get('status')
                    
                    logger.info(f"   - Payment ID: {payment_id}")
                    logger.info(f"   - Payment Status: {payment_status}")
                    logger.info(f"   - Payment Data: {json.dumps(payment_data, indent=2)}")
                    
                    # Si el pago está aprobado, confirmarlo en nuestro sistema
                    if payment_status == 'approved':
                        logger.info(f"✅ Pago encontrado y aprobado en Mercado Pago: {payment_id}")
                        
                        # Actualizar estados según el tipo de pago (misma lógica que confirmar_pago_oferta)
                        solicitud = oferta.solicitud
                        
                        # Actualizar fecha_respuesta_cliente
                        oferta.fecha_respuesta_cliente = timezone.now()
                        
                        if tipo_pago == 'repuestos':
                            oferta.estado_pago_repuestos = 'pagado'
                            oferta.metodo_pago_cliente = 'repuestos_adelantado'
                            oferta.estado = 'pagada_parcialmente'
                            
                            if solicitud.estado not in ['en_ejecucion', 'completada']:
                                solicitud.estado = 'pagada'
                            
                            message = 'Pago de repuestos verificado y confirmado'
                            
                        elif tipo_pago == 'servicio':
                            from mecanimovilapp.apps.ordenes.services.pago_oferta_cliente import (
                                aplicar_confirmacion_pago_servicio,
                            )
                            aplicar_confirmacion_pago_servicio(oferta, solicitud)
                            if oferta.metodo_pago_cliente == 'cliente_compra_repuestos':
                                message = 'Pago de mano de obra verificado (repuestos por el cliente)'
                            else:
                                message = 'Pago del servicio verificado y confirmado'
                            
                        else:  # total
                            oferta.estado_pago_repuestos = 'pagado' if oferta.costo_repuestos and float(oferta.costo_repuestos) > 0 else 'no_aplica'
                            oferta.estado_pago_servicio = 'pagado'
                            oferta.metodo_pago_cliente = 'todo_adelantado'
                            oferta.estado = 'pagada'
                            solicitud.estado = 'pagada'
                            
                            message = 'Pago completo verificado y confirmado'
                        
                        # Guardar cambios
                        oferta.save()
                        solicitud.save()
                        
                        logger.info(f"✅ Pago confirmado exitosamente desde verificación directa")
                        logger.info(f"   - Estado oferta: {oferta.estado}")
                        logger.info(f"   - Estado solicitud: {solicitud.estado}")
                        logger.info(f"   - Estado pago repuestos: {oferta.estado_pago_repuestos}")
                        logger.info(f"   - Estado pago servicio: {oferta.estado_pago_servicio}")
                        
                        # Crear o actualizar el registro de Pago
                        pago, created = Pago.objects.get_or_create(
                            payment_id_mp=str(payment_id),
                            defaults={
                                'usuario': request.user,
                                'carrito': None,
                                'transaction_amount': payment_data.get('transaction_amount', 0),
                                'currency_id': payment_data.get('currency_id', 'CLP'),
                                'description': payment_data.get('description', ''),
                                'status': payment_status,
                                'status_detail': payment_data.get('status_detail', ''),
                                'payment_method_id': payment_data.get('payment_method_id'),
                                'payment_type_id': payment_data.get('payment_type_id'),
                                'payer_email': payment_data.get('payer', {}).get('email', ''),
                                'external_reference': external_reference,
                                'date_created_mp': payment_data.get('date_created'),
                                'date_approved_mp': payment_data.get('date_approved'),
                            }
                        )
                        
                        if not created:
                            logger.info(f"   - Pago  ya existía en BD: {pago.id}")
                        
                        return Response({
                            'success': True,
                            'payment_found': True,
                            'payment_approved': True,
                            'payment_id': str(payment_id),
                            'oferta_id': str(oferta.id),
                            'oferta_estado': oferta.estado,
                            'solicitud_estado': solicitud.estado,
                            'estado_pago_repuestos': oferta.estado_pago_repuestos,
                            'estado_pago_servicio': oferta.estado_pago_servicio,
                            'payment_status': payment_status,
                            'message': message
                        })
                    else:
                        # Pago encontrado pero no está aprobado
                        logger.info(f"⏳ Pago encontrado pero no aprobado: {payment_status}")
                        return Response({
                            'success': False,
                            'payment_found': True,
                            'payment_approved': False,
                            'payment_id': str(payment_id),
                            'payment_status': payment_status,
                            'message': f'Pago encontrado pero está en estado: {payment_status}'
                        })
                else:
                    # No se encontraron pagos
                    logger.info(f"⚠️ No se encontraron pagos para el external_reference: {external_reference}")
                    return Response({
                        'success': False,
                        'payment_found': False,
                        'payment_approved': False,
                        'message': 'No se encontró ningún pago en Mercado Pago para esta oferta'
                    })
            else:
                logger.error(f"❌ Error en búsqueda de pagos: {search_response}")
                return Response({
                    'success': False,
                    'error': 'Error al buscar pagos en Mercado Pago',
                    'mp_response': search_response
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as search_error:
            logger.error(f"❌ Error en búsqueda de pagos: {search_error}", exc_info=True)
            return Response({
                'success': False,
                'error': f'Error al buscar pagos: {str(search_error)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
    except OfertaProveedor.DoesNotExist:
        return Response(
            {'error': 'Oferta no encontrada'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"❌ Error verificando pago: {e}", exc_info=True)
        return Response(
            {'error': f'Error al verificar el pago: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )