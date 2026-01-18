from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from django.db.models import Q, Avg, Count, Sum
from django.utils import timezone
from datetime import datetime, timedelta, time
from .models import (
    SolicitudServicio, LineaServicio, 
    CarritoAgendamiento, ItemCarritoAgendamiento,
    ConfiguracionPrecio, AuditAccesoCliente,
    SolicitudServicioPublica, OfertaProveedor, DetalleServicioOferta, ChatSolicitud,
    AlertaDescartada
)
from .serializers import (
    SolicitudServicioSerializer, LineaServicioSerializer,
    CarritoAgendamientoSerializer, ItemCarritoAgendamientoSerializer, 
    AgendamientoDisponibilidadSerializer,
    ConfirmarAgendamientoSerializer, SolicitudServicioProveedorSerializer,
    AcceptOrderSerializer, RejectOrderSerializer, UpdateOrderStatusSerializer,
    OrdenEstadisticasSerializer,
    SolicitudServicioPublicaSerializer, OfertaProveedorSerializer,
    DetalleServicioOfertaSerializer, ChatSolicitudSerializer
)
from mecanimovilapp.apps.servicios.models import Servicio
from mecanimovilapp.apps.servicios.serializers import ServicioSerializer
from .permissions import IsProveedor, IsOrderOwnerForProvider, CanManageOrder
from rest_framework.permissions import IsAuthenticated
from django.db import models, transaction
from collections import defaultdict
import logging
from decimal import Decimal
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from mecanimovilapp.apps.usuarios.models import Cliente, Usuario, Taller, MecanicoDomicilio, ConnectionStatus
from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification
from mecanimovilapp.apps.servicios.models import Servicio
from django.contrib.gis.geos import Point
from rest_framework import serializers
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

# ============================================================================
# FUNCIONES HELPER PARA PROCESAMIENTO DE SOLICITUDES EXPIRADAS
# ============================================================================

def procesar_solicitudes_expiradas():
    """
    Procesa solicitudes/ofertas expiradas sin pago y las cancela automáticamente.
    Esta función se integra en el flujo normal de la aplicación.
    
    ✅ POLÍTICA DE CRÉDITOS:
    - Los créditos NO se devuelven cuando una solicitud expira automáticamente
    - Una vez que la oferta es adjudicada, los créditos se consumen permanentemente
    - Esto previene gaming y es más justo para el proveedor
    
    ✅ IMPORTANTE - INDEPENDENCIA DE OFERTAS:
    - Las ofertas pagadas/en_ejecucion/completadas NUNCA se afectan
    - Si una solicitud tiene ofertas pagadas/completadas, NO se cancela la solicitud
    - Solo se rechazan las ofertas individuales que expiraron sin pago
    - Las ofertas secundarias son independientes de la principal
    
    Retorna el número de ofertas/solicitudes procesadas.
    """
    try:
        ahora = timezone.now()
        # ✅ PLAZO MÁXIMO PARA PAGO: 48 horas desde que se aceptó la oferta
        # Esto es independiente de fecha_limite_pago (que se basa en fecha_disponible del servicio)
        # El proveedor no puede quedar esperando indefinidamente con una orden pendiente de pago
        from datetime import timedelta
        PLAZO_MAXIMO_PAGO_HORAS = 48
        plazo_maximo_pago = timedelta(hours=PLAZO_MAXIMO_PAGO_HORAS)
        
        # ✅ ESTADOS QUE INDICAN QUE UNA OFERTA YA FUE PROCESADA EXITOSAMENTE
        # Estas ofertas NUNCA deben ser canceladas/rechazadas
        ESTADOS_OFERTA_PROTEGIDOS = ['pagada', 'en_ejecucion', 'completada']
        
        # ✅ ESTADOS QUE INDICAN QUE UNA SOLICITUD TIENE SERVICIOS ACTIVOS
        # Si una solicitud tiene estos estados, NO debe cancelarse completamente
        ESTADOS_SOLICITUD_CON_SERVICIO_ACTIVO = ['pagada', 'en_ejecucion', 'completada']
        
        procesadas = 0
        channel_layer = get_channel_layer()
        fecha_limite_aceptacion = ahora - plazo_maximo_pago
        
        # =========================================================================
        # PASO 1: Procesar ofertas individuales expiradas (PRINCIPAL y SECUNDARIAS)
        # =========================================================================
        # Buscar ofertas en estados 'aceptada' o 'pendiente_pago' que han expirado
        # EXCLUIR ofertas protegidas (pagadas, en_ejecucion, completadas)
        ofertas_expiradas = OfertaProveedor.objects.filter(
            estado__in=['aceptada', 'pendiente_pago'],
        ).filter(
            # Condición 1: Fecha respuesta cliente + 48h < ahora
            Q(fecha_respuesta_cliente__lt=fecha_limite_aceptacion, fecha_respuesta_cliente__isnull=False) |
            # Condición 2: Solicitud tiene fecha_limite_pago pasada
            Q(solicitud__fecha_limite_pago__lt=ahora, solicitud__fecha_limite_pago__isnull=False)
        ).select_related(
            'solicitud', 'solicitud__cliente', 'solicitud__cliente__usuario', 'proveedor', 'oferta_original'
        )
        
        ofertas_procesadas = 0
        for oferta_exp in ofertas_expiradas:
            try:
                with transaction.atomic():
                    solicitud = oferta_exp.solicitud
                    
                    # ✅ VERIFICAR: ¿Esta solicitud tiene ofertas protegidas (pagadas/completadas)?
                    tiene_ofertas_protegidas = OfertaProveedor.objects.filter(
                        solicitud=solicitud,
                        estado__in=ESTADOS_OFERTA_PROTEGIDOS
                    ).exists()
                    
                    # ✅ Rechazar SOLO esta oferta específica
                    oferta_exp.estado = 'rechazada'
                    oferta_exp.fecha_respuesta_cliente = ahora
                    oferta_exp.save(update_fields=['estado', 'fecha_respuesta_cliente'])
                    
                    ofertas_procesadas += 1
                    
                    # Determinar si es oferta principal o secundaria
                    es_secundaria = oferta_exp.es_oferta_secundaria
                    tipo_oferta = "secundaria" if es_secundaria else "principal"
                    
                    # Determinar el motivo de cancelación
                    if solicitud.fecha_limite_pago and solicitud.fecha_limite_pago < ahora:
                        motivo = f"fecha límite de pago expirada"
                    elif oferta_exp.fecha_respuesta_cliente:
                        horas_pasadas = (ahora - oferta_exp.fecha_respuesta_cliente).total_seconds() / 3600
                        motivo = f"plazo máximo de {PLAZO_MAXIMO_PAGO_HORAS}h excedido ({horas_pasadas:.1f}h)"
                    else:
                        motivo = "expiración automática"
                    
                    logger.info(
                        f"✅ Oferta {tipo_oferta} {oferta_exp.id} rechazada por {motivo}. "
                        f"Solicitud {solicitud.id} tiene ofertas protegidas: {tiene_ofertas_protegidas}"
                    )
                    
                    # ✅ DECIDIR SI CANCELAR LA SOLICITUD COMPLETA
                    # Solo cancelar si:
                    # 1. NO tiene ofertas protegidas (pagadas/en_ejecucion/completadas)
                    # 2. NO está ya en un estado protegido
                    # 3. Esta era la oferta seleccionada principal
                    if not tiene_ofertas_protegidas and solicitud.estado not in ESTADOS_SOLICITUD_CON_SERVICIO_ACTIVO:
                        # Verificar si era la oferta seleccionada principal
                        if solicitud.oferta_seleccionada_id == oferta_exp.id:
                            solicitud.estado = 'cancelada'
                            solicitud.save(update_fields=['estado'])
                            logger.info(f"✅ Solicitud {solicitud.id} cancelada porque la oferta principal expiró")
                            
                            # Rechazar otras ofertas pendientes (no protegidas)
                            OfertaProveedor.objects.filter(
                                solicitud=solicitud,
                                estado__in=['enviada', 'vista', 'en_chat', 'aceptada', 'pendiente_pago']
                            ).exclude(id=oferta_exp.id).update(
                                estado='rechazada',
                                fecha_respuesta_cliente=ahora
                            )
                    else:
                        # La solicitud tiene ofertas protegidas, mantener el estado actual
                        # Solo registrar que esta oferta específica (posiblemente secundaria) fue rechazada
                        logger.info(
                            f"ℹ️ Solicitud {solicitud.id} NO cancelada: tiene ofertas protegidas o está en servicio activo. "
                            f"Estado actual: {solicitud.estado}"
                        )
                    
                    # Notificar al cliente vía WebSocket
                    try:
                        if channel_layer and solicitud.cliente and solicitud.cliente.usuario:
                            mensaje = (
                                f'La oferta {tipo_oferta} ha expirado por falta de pago.' 
                                if tiene_ofertas_protegidas 
                                else 'El plazo para pagar ha expirado. La solicitud ha sido cancelada.'
                            )
                            async_to_sync(channel_layer.group_send)(
                                f"cliente_{solicitud.cliente.usuario.id}",
                                {
                                    'type': 'pago_expirado',
                                    'solicitud_id': str(solicitud.id),
                                    'oferta_id': str(oferta_exp.id),
                                    'es_oferta_secundaria': es_secundaria,
                                    'mensaje': mensaje,
                                    'solicitud_cancelada': not tiene_ofertas_protegidas,
                                    'timestamp': ahora.isoformat()
                                }
                            )
                    except Exception as e:
                        logger.error(f"Error enviando notificación WebSocket al cliente: {e}", exc_info=True)
                    
                    # Notificar al proveedor vía WebSocket
                    try:
                        if channel_layer and oferta_exp.proveedor:
                            async_to_sync(channel_layer.group_send)(
                                f"proveedor_{oferta_exp.proveedor.id}",
                                {
                                    'type': 'pago_expirado',
                                    'oferta_id': str(oferta_exp.id),
                                    'solicitud_id': str(solicitud.id),
                                    'es_oferta_secundaria': es_secundaria,
                                    'mensaje': f'El cliente no pagó la oferta {tipo_oferta} a tiempo. Los créditos no se devuelven.',
                                    'creditos_devueltos': False,
                                    'timestamp': ahora.isoformat()
                                }
                            )
                    except Exception as e:
                        logger.error(f"Error enviando notificación WebSocket al proveedor: {e}", exc_info=True)
                    
            except Exception as e:
                logger.error(f"Error procesando oferta expirada {oferta_exp.id}: {e}", exc_info=True)
        
        procesadas += ofertas_procesadas
        if ofertas_procesadas > 0:
            logger.info(f"✅ Procesadas {ofertas_procesadas} ofertas expiradas individualmente")
        
        # =========================================================================
        # PASO 2: Procesar solicitudes sin ofertas protegidas con fecha límite pasada
        # =========================================================================
        # Solo cancelar solicitudes que:
        # 1. Tienen fecha_limite_pago pasada
        # 2. NO tienen ofertas pagadas/en_ejecucion/completadas
        # 3. NO están ya en estado pagada/en_ejecucion/completada
        try:
            solicitudes_con_fecha_pasada = SolicitudServicioPublica.objects.filter(
                fecha_limite_pago__isnull=False,
                fecha_limite_pago__lt=ahora,
                oferta_seleccionada__isnull=False
            ).exclude(
                # Excluir solicitudes ya finalizadas o con servicios activos
                estado__in=['cancelada', 'expirada', 'pagada', 'en_ejecucion', 'completada']
            ).select_related(
                'oferta_seleccionada', 'cliente', 'cliente__usuario'
            )
            
            for solicitud in solicitudes_con_fecha_pasada:
                try:
                    with transaction.atomic():
                        # ✅ VERIFICAR: ¿Esta solicitud tiene ofertas protegidas?
                        tiene_ofertas_protegidas = OfertaProveedor.objects.filter(
                            solicitud=solicitud,
                            estado__in=ESTADOS_OFERTA_PROTEGIDOS
                        ).exists()
                        
                        if tiene_ofertas_protegidas:
                            # NO cancelar la solicitud, solo rechazar ofertas pendientes no protegidas
                            ofertas_pendientes_rechazadas = OfertaProveedor.objects.filter(
                                solicitud=solicitud,
                                estado__in=['enviada', 'vista', 'en_chat', 'aceptada', 'pendiente_pago']
                            ).update(
                                estado='rechazada',
                                fecha_respuesta_cliente=ahora
                            )
                            
                            if ofertas_pendientes_rechazadas > 0:
                                logger.info(
                                    f"ℹ️ Solicitud {solicitud.id} tiene ofertas protegidas. "
                                    f"Solo se rechazaron {ofertas_pendientes_rechazadas} ofertas pendientes. "
                                    f"Estado de solicitud mantenido: {solicitud.estado}"
                                )
                        else:
                            # Sin ofertas protegidas: cancelar la solicitud completa
                            oferta = solicitud.oferta_seleccionada
                            
                            solicitud.estado = 'cancelada'
                            solicitud.save(update_fields=['estado'])
                            
                            # Rechazar la oferta seleccionada si está en estados problemáticos
                            if oferta and oferta.estado in ['aceptada', 'pendiente_pago']:
                                oferta.estado = 'rechazada'
                                oferta.fecha_respuesta_cliente = ahora
                                oferta.save(update_fields=['estado', 'fecha_respuesta_cliente'])
                            
                            # Rechazar todas las otras ofertas pendientes
                            OfertaProveedor.objects.filter(
                                solicitud=solicitud,
                                estado__in=['enviada', 'vista', 'en_chat', 'aceptada', 'pendiente_pago']
                            ).exclude(id=oferta.id if oferta else None).update(
                                estado='rechazada',
                                fecha_respuesta_cliente=ahora
                            )
                            
                            procesadas += 1
                            logger.info(
                                f"✅ Solicitud {solicitud.id} cancelada por fecha límite pasada. "
                                f"Oferta {oferta.id if oferta else 'N/A'} rechazada."
                            )
                except Exception as e:
                    logger.error(f"Error procesando solicitud con fecha pasada {solicitud.id}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Error procesando solicitudes con fecha pasada: {e}", exc_info=True)
        
        if procesadas > 0:
            logger.info(f"✅ Total procesadas: {procesadas} ofertas/solicitudes expiradas")
        
        return procesadas
        
    except Exception as e:
        logger.error(f"Error en procesar_solicitudes_expiradas: {e}", exc_info=True)
        return 0

# ============================================================================
# FUNCIONES HELPER PARA INTEGRACIÓN CON CARRITO
# ============================================================================

def obtener_o_crear_carrito(cliente, vehiculo):
    """
    Obtiene o crea un carrito activo para el cliente y vehículo.
    Si ya existe un carrito activo para ese vehículo, lo retorna.
    Si no existe, crea uno nuevo.
    """
    # CarritoAgendamiento ya está importado al inicio del archivo
    # Buscar carrito activo para el cliente y vehículo
    carrito = CarritoAgendamiento.objects.filter(
        cliente=cliente,
        vehiculo=vehiculo,
        activo=True
    ).first()
    
    if carrito:
        logger.info(f"Carrito existente encontrado: {carrito.id}")
        return carrito
    
    # Si no existe, crear uno nuevo
    # CRÍTICO: Si hay un carrito activo para otro vehículo, desactivarlo
    # (solo puede haber un carrito activo por cliente)
    CarritoAgendamiento.objects.filter(
        cliente=cliente,
        activo=True
    ).update(activo=False)
    
    carrito = CarritoAgendamiento.objects.create(
        cliente=cliente,
        vehiculo=vehiculo,
        activo=True
    )
    logger.info(f"Carrito nuevo creado: {carrito.id}")
    
    return carrito

def crear_chat_inicial_oferta(oferta, solicitud):
    """
    Crea un mensaje inicial en el chat mostrando la solicitud original.
    Este mensaje se envía automáticamente cuando se acepta una oferta.
    """
    from .models import ChatSolicitud
    
    # Obtener información de los servicios solicitados
    servicios_nombres = list(solicitud.servicios_solicitados.values_list('nombre', flat=True))
    servicios_texto = ", ".join(servicios_nombres) if servicios_nombres else "Servicios varios"
    
    # Construir mensaje con información de la solicitud
    mensaje_parts = [
        "¡Hola! He aceptado tu oferta para mi solicitud de servicio.",
        "",
        "📋 **Detalles de la solicitud original:**",
        f"• Descripción: {solicitud.descripcion_problema or 'Sin descripción adicional'}",
        f"• Servicios: {servicios_texto}",
        f"• Ubicación: {solicitud.direccion_servicio_texto or 'Ubicación no especificada'}",
        f"• Fecha preferida: {solicitud.fecha_preferida.strftime('%d/%m/%Y') if solicitud.fecha_preferida else 'No especificada'}",
    ]
    
    if solicitud.hora_preferida:
        mensaje_parts.append(f"• Hora preferida: {solicitud.hora_preferida.strftime('%H:%M')}")
    
    if solicitud.detalles_ubicacion:
        mensaje_parts.append(f"• Detalles adicionales: {solicitud.detalles_ubicacion}")
    
    mensaje_parts.extend([
        "",
        "Puedes contactarme a través de este chat para coordinar los detalles del servicio.",
    ])
    
    mensaje = "\n".join(mensaje_parts)
    
    # Crear mensaje del chat (enviado por el cliente)
    chat_mensaje = ChatSolicitud.objects.create(
        oferta=oferta,
        mensaje=mensaje,
        enviado_por=solicitud.cliente.usuario,
        es_proveedor=False
    )
    
    logger.info(f"Mensaje inicial del chat creado: {chat_mensaje.id} para oferta: {oferta.id}")
    
    return chat_mensaje

# DISPONIBILIDADVIEWSET ELIMINADO - REEMPLAZADO POR ENDPOINTS EN USUARIOS APP
# (Los horarios ahora se manejan desde usuarios/talleres/{id}/horarios_disponibles/ y usuarios/mecanicos-domicilio/{id}/horarios_disponibles/)

class SolicitudServicioViewSet(viewsets.ModelViewSet):
    """
    ViewSet para el modelo SolicitudServicio
    """
    queryset = SolicitudServicio.objects.all()
    serializer_class = SolicitudServicioSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['fecha_hora_solicitud', 'fecha_servicio', 'total']
    ordering = ['-fecha_hora_solicitud']
    
    def get_queryset(self):
        """
        Filtra las solicitudes según los parámetros de consulta
        """
        user = self.request.user
        
        # Si es admin o staff, puede ver todas las solicitudes
        if user.is_staff or user.is_superuser:
            queryset = SolicitudServicio.objects.all()
        else:
            # Para usuarios normales, solo sus propias solicitudes
            try:
                from mecanimovilapp.apps.usuarios.models import Cliente
                cliente = Cliente.objects.get(usuario=user)
                queryset = SolicitudServicio.objects.filter(cliente=cliente)
            except Cliente.DoesNotExist:
                queryset = SolicitudServicio.objects.none()
        
        # Filtros de solicitud
        cliente_id = self.request.query_params.get('cliente_id', None)
        estado = self.request.query_params.get('estado', None)
        taller_id = self.request.query_params.get('taller_id', None)
        mecanico_id = self.request.query_params.get('mecanico_id', None)
        fecha_desde = self.request.query_params.get('fecha_desde', None)
        fecha_hasta = self.request.query_params.get('fecha_hasta', None)
        
        if cliente_id is not None:
            queryset = queryset.filter(cliente_id=cliente_id)
        
        if estado is not None:
            queryset = queryset.filter(estado=estado)
            
        if taller_id is not None:
            queryset = queryset.filter(taller_id=taller_id)
        
        if mecanico_id is not None:
            queryset = queryset.filter(mecanico_id=mecanico_id)
            
        if fecha_desde is not None:
            queryset = queryset.filter(fecha_servicio__gte=fecha_desde)
            
        if fecha_hasta is not None:
            queryset = queryset.filter(fecha_servicio__lte=fecha_hasta)
        
        return queryset.select_related('cliente', 'taller', 'mecanico', 'vehiculo')
    
    @action(detail=False, methods=['get'])
    def activas(self, request):
        """
        Obtiene las solicitudes activas del cliente (no completadas ni canceladas)
        """
        try:
            from mecanimovilapp.apps.usuarios.models import Cliente
            
            # Obtener el cliente del usuario autenticado
            cliente = Cliente.objects.get(usuario=request.user)
            
            # Estados que se consideran "activos" para el cliente
            estados_activos = [
                'pendiente',
                'pago_validado', 
                'confirmado',
                'en_proceso',
                'pendiente_aceptacion_proveedor',
                'aceptada_por_proveedor'
            ]
            
            solicitudes_activas = SolicitudServicio.objects.filter(
                cliente=cliente,
                estado__in=estados_activos
            ).select_related(
                'cliente', 'taller', 'mecanico', 'vehiculo'
            ).prefetch_related(
                'lineas__oferta_servicio'
            ).order_by('fecha_servicio', 'hora_servicio')
            
            serializer = self.get_serializer(solicitudes_activas, many=True)
            return Response(serializer.data)
            
        except Cliente.DoesNotExist:
            return Response(
                {"error": "No se encontró perfil de cliente para este usuario"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Error obteniendo solicitudes activas: {str(e)}")
            return Response(
                {"error": f"Error al obtener solicitudes activas: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def historial(self, request):
        """
        Obtiene el historial completo de solicitudes del cliente (todas, incluyendo completadas y canceladas)
        """
        try:
            from mecanimovilapp.apps.usuarios.models import Cliente
            
            # Obtener el cliente del usuario autenticado
            cliente = Cliente.objects.get(usuario=request.user)
            
            # Obtener todas las solicitudes del cliente
            queryset = SolicitudServicio.objects.filter(cliente=cliente)
            
            # Aplicar filtros opcionales
            estado = request.query_params.get('estado')
            fecha_desde = request.query_params.get('fecha_desde')
            fecha_hasta = request.query_params.get('fecha_hasta')
            
            if estado:
                # Permitir múltiples estados separados por coma
                estados = estado.split(',')
                queryset = queryset.filter(estado__in=estados)
            
            if fecha_desde:
                queryset = queryset.filter(fecha_servicio__gte=fecha_desde)
            
            if fecha_hasta:
                queryset = queryset.filter(fecha_servicio__lte=fecha_hasta)
            
            # Obtener solicitudes con relaciones optimizadas
            solicitudes_historial = queryset.select_related(
                'cliente', 'taller', 'mecanico', 'vehiculo'
            ).prefetch_related(
                'lineas__oferta_servicio'
            ).order_by('-fecha_hora_solicitud')  # Más recientes primero
            
            serializer = self.get_serializer(solicitudes_historial, many=True)
            return Response(serializer.data)
            
        except Cliente.DoesNotExist:
            return Response(
                {"error": "No se encontró perfil de cliente para este usuario"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Error obteniendo historial de solicitudes: {str(e)}")
            return Response(
                {"error": f"Error al obtener historial de solicitudes: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        """
        Cancela una solicitud de servicio del cliente
        """
        try:
            from mecanimovilapp.apps.usuarios.models import Cliente
            from django.utils import timezone
            
            # Obtener la solicitud
            solicitud = self.get_object()
            
            # Verificar que el usuario es el dueño de la solicitud
            cliente = Cliente.objects.get(usuario=request.user)
            if solicitud.cliente != cliente:
                return Response(
                    {"error": "No tienes permisos para cancelar esta solicitud"}, 
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Verificar que la solicitud puede ser cancelada
            if not solicitud.puede_cancelar_directamente():
                if solicitud.requiere_proceso_cancelacion():
                    # Cambiar estado a solicitud de cancelación
                    solicitud.estado = 'solicitud_cancelacion'
                    solicitud.fecha_cancelacion = timezone.now()
                    solicitud.motivo_cancelacion = request.data.get('motivo', 'Cancelación solicitada por el cliente')
                    solicitud.save()
                    
                    return Response({
                        "mensaje": "Se ha enviado tu solicitud de cancelación. Se procesará la devolución correspondiente.",
                        "estado": solicitud.estado,
                        "requiere_devolucion": True
                    })
                else:
                    return Response(
                        {"error": f"No se puede cancelar una solicitud en estado '{solicitud.estado}'"}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            # ✅ NUEVO: Si la solicitud tiene oferta_proveedor y ya se consumieron créditos,
            # NO devolver créditos al proveedor (política: créditos consumidos permanentemente)
            # Esto previene gaming y es más justo para el proveedor
            if solicitud.oferta_proveedor:
                logger.info(
                    f"Cancelando solicitud {solicitud.id} con oferta_proveedor {solicitud.oferta_proveedor.id} - "
                    f"Créditos NO se devuelven (política: créditos consumidos permanentemente al adjudicar)"
                )
                # ✅ NO devolver créditos - una vez adjudicada, los créditos se consumen permanentemente
                # Esto previene que los clientes cancelen después de adjudicar para evitar el consumo de créditos
            
            # Cancelación directa para solicitudes pendientes sin pago validado
            solicitud.estado = 'cancelado'
            solicitud.fecha_cancelacion = timezone.now()
            solicitud.motivo_cancelacion = request.data.get('motivo', 'Cancelación directa por el cliente')
            solicitud.save()
            
            return Response({
                "mensaje": "Solicitud cancelada exitosamente",
                "estado": solicitud.estado,
                "fecha_cancelacion": solicitud.fecha_cancelacion
            })
            
        except Cliente.DoesNotExist:
            return Response(
                {"error": "No se encontró perfil de cliente para este usuario"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except SolicitudServicio.DoesNotExist:
            return Response(
                {"error": "Solicitud no encontrada"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Error cancelando solicitud {pk}: {str(e)}")
            return Response(
                {"error": f"Error al cancelar solicitud: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class LineaServicioViewSet(viewsets.ModelViewSet):
    """
    ViewSet para el modelo LineaServicio
    """
    queryset = LineaServicio.objects.all()
    serializer_class = LineaServicioSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['precio_final']
    ordering = ['-precio_final']

class CarritoAgendamientoViewSet(viewsets.ModelViewSet):
    """
    ViewSet para el modelo CarritoAgendamiento
    """
    queryset = CarritoAgendamiento.objects.all()
    serializer_class = CarritoAgendamientoSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['fecha_creacion', 'fecha_actualizacion']
    ordering = ['-fecha_actualizacion']
    
    def get_queryset(self):
        """
        Filtra los carritos según el cliente autenticado
        """
        user = self.request.user
        
        # Verificar que el usuario esté autenticado
        if not user or not user.is_authenticated:
            return CarritoAgendamiento.objects.none()
        
        # Obtener el cliente del usuario autenticado
        try:
            from mecanimovilapp.apps.usuarios.models import Cliente
            cliente = Cliente.objects.get(usuario=user)
            return CarritoAgendamiento.objects.filter(cliente=cliente).select_related(
                'cliente', 'vehiculo'
            ).prefetch_related('items__oferta_servicio')
        except Cliente.DoesNotExist:
            # Log para debugging
            logger = logging.getLogger(__name__)
            logger.warning(f"Usuario {user.username} no tiene perfil de cliente asociado")
            return CarritoAgendamiento.objects.none()
        except Exception as e:
            # Log para debugging
            logger = logging.getLogger(__name__)
            logger.error(f"Error en get_queryset: {str(e)}")
            return CarritoAgendamiento.objects.none()
    
    @action(detail=False, methods=['get'])
    def activos(self, request):
        """
        Obtiene todos los carritos activos del cliente (solo los que tienen items)
        """
        try:
            # MEJORADO: Solo retornar carritos que realmente tienen servicios
            carritos_activos = self.get_queryset().filter(activo=True).prefetch_related('items')
            
            # Filtrar carritos que tienen al menos un item
            carritos_con_servicios = []
            carritos_vacios_para_limpiar = []
            
            for carrito in carritos_activos:
                if carrito.items.exists():
                    carritos_con_servicios.append(carrito)
                else:
                    carritos_vacios_para_limpiar.append(carrito)
            
            # NUEVO: Limpiar automáticamente carritos vacíos antiguos (más de 1 hora)
            from django.utils import timezone
            from datetime import timedelta
            
            hora_limite = timezone.now() - timedelta(hours=1)
            carritos_vacios_antiguos = [
                carrito for carrito in carritos_vacios_para_limpiar 
                if carrito.fecha_actualizacion < hora_limite
            ]
            
            if carritos_vacios_antiguos:
                logger = logging.getLogger(__name__)
                logger.info(f"Limpiando {len(carritos_vacios_antiguos)} carritos vacíos antiguos")
                
                for carrito in carritos_vacios_antiguos:
                    carrito.delete()
            
            # Serializar solo carritos con servicios
            serializer = self.get_serializer(carritos_con_servicios, many=True)
            
            return Response({
                "carritos": serializer.data,
                "total_carritos": len(carritos_con_servicios),
                "carritos_limpiados": len(carritos_vacios_antiguos)
            })
            
        except Exception as e:
            # Log del error para debugging
            logger = logging.getLogger(__name__)
            logger.error(f"Error en carritos activos: {str(e)}")
            
            # Respuesta de error en formato JSON
            return Response(
                {
                    "error": "Error obteniendo carritos activos",
                    "detail": str(e),
                    "carritos": []
                }, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def activo(self, request):
        """
        Obtiene el carrito activo para un vehículo específico (solo si tiene items)
        """
        vehiculo_id = request.query_params.get('vehiculo_id')
        if not vehiculo_id:
            return Response(
                {"error": "Se requiere vehiculo_id"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # MEJORADO: Buscar carrito activo con items
            carrito = self.get_queryset().filter(
                vehiculo_id=vehiculo_id, 
                activo=True
            ).prefetch_related('items').first()
            
            if not carrito:
                return Response(
                    {"error": "No hay carrito activo para este vehículo"}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # NUEVO: Verificar si el carrito tiene items
            if not carrito.items.exists():
                # Carrito vacío - eliminarlo automáticamente si es antiguo
                from django.utils import timezone
                from datetime import timedelta
                
                hora_limite = timezone.now() - timedelta(minutes=30)  # 30 minutos para carritos individuales
                
                if carrito.fecha_actualizacion < hora_limite:
                    logger = logging.getLogger(__name__)
                    logger.info(f"Eliminando carrito vacío antiguo {carrito.id} para vehículo {vehiculo_id}")
                    carrito.delete()
                
                return Response(
                    {"error": "No hay carrito activo para este vehículo"}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Carrito válido con items
            serializer = self.get_serializer(carrito)
            return Response(serializer.data)
            
        except CarritoAgendamiento.DoesNotExist:
            return Response(
                {"error": "No hay carrito activo para este vehículo"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Error obteniendo carrito activo para vehículo {vehiculo_id}: {str(e)}")
            
            return Response(
                {"error": "Error interno del servidor"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def agregar_servicio(self, request, pk=None):
        """
        Agrega un servicio al carrito
        """
        carrito = self.get_object()
        
        # Validar datos requeridos
        oferta_servicio_id = request.data.get('oferta_servicio_id')
        con_repuestos = request.data.get('con_repuestos', True)
        cantidad = request.data.get('cantidad', 1)
        fecha_servicio = request.data.get('fecha_servicio')
        hora_servicio = request.data.get('hora_servicio')
        
        if not oferta_servicio_id:
            return Response(
                {"error": "Se requiere oferta_servicio_id"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            from mecanimovilapp.apps.servicios.models import OfertaServicio
            oferta_servicio = OfertaServicio.objects.get(id=oferta_servicio_id)
            
            # Crear o actualizar item del carrito
            item, created = ItemCarritoAgendamiento.objects.get_or_create(
                carrito=carrito,
                oferta_servicio=oferta_servicio,
                defaults={
                    'con_repuestos': con_repuestos,
                    'cantidad': cantidad,
                    'fecha_servicio': fecha_servicio,
                    'hora_servicio': hora_servicio,
                }
            )
            
            if not created:
                # Actualizar item existente
                item.con_repuestos = con_repuestos
                item.cantidad = cantidad
                if fecha_servicio:
                    item.fecha_servicio = fecha_servicio
                if hora_servicio:
                    item.hora_servicio = hora_servicio
                item.save()
            
            # Serializar y retornar el carrito actualizado
            serializer = self.get_serializer(carrito)
            return Response(serializer.data)
            
        except OfertaServicio.DoesNotExist:
            return Response(
                {"error": "Oferta de servicio no encontrada"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {"error": f"Error al agregar servicio: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def remover_servicio(self, request, pk=None):
        """
        Remueve un servicio del carrito
        """
        carrito = self.get_object()
        item_id = request.data.get('item_id')
        
        if not item_id:
            return Response(
                {"error": "Se requiere item_id"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            item = ItemCarritoAgendamiento.objects.get(id=item_id, carrito=carrito)
            item.delete()
            
            # Serializar y retornar el carrito actualizado
            serializer = self.get_serializer(carrito)
            return Response(serializer.data)
            
        except ItemCarritoAgendamiento.DoesNotExist:
            return Response(
                {"error": "Item no encontrado en el carrito"}, 
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=['post'])
    def seleccionar_fecha_hora(self, request, pk=None):
        """
        Selecciona fecha y hora para todos los servicios del carrito
        """
        carrito = self.get_object()
        fecha_servicio = request.data.get('fecha_servicio')
        hora_servicio = request.data.get('hora_servicio')
        
        if not fecha_servicio or not hora_servicio:
            return Response(
                {"error": "Se requieren fecha_servicio y hora_servicio"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Actualizar todos los items del carrito
        carrito.items.update(
            fecha_servicio=fecha_servicio,
            hora_servicio=hora_servicio
        )
        
        # Serializar y retornar el carrito actualizado
        serializer = self.get_serializer(carrito)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def confirmar(self, request, pk=None):
        """
        Confirma el carrito y crea las solicitudes de servicio
        """
        carrito = self.get_object()
        
        if not carrito.puede_confirmar():
            return Response(
                {"error": "El carrito no puede ser confirmado. Verifique que tenga servicios y fechas/horas seleccionadas."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
            
        metodo_pago = request.data.get('metodo_pago', 'transferencia')
        notas_cliente = request.data.get('notas_cliente', '')
        
        try:
            # Crear una solicitud de servicio por cada item del carrito
            solicitudes_creadas = []
            
            for item in carrito.items.all():
                # Determinar proveedor
                taller = item.oferta_servicio.taller
                mecanico = item.oferta_servicio.mecanico
                tipo_servicio = 'taller' if taller else 'domicilio'
                
                # Si es servicio a domicilio, obtener la dirección del cliente
                ubicacion_servicio = None
                if tipo_servicio == 'domicilio':
                    try:
                        from mecanimovilapp.apps.usuarios.models import DireccionUsuario
                        # Buscar dirección principal del cliente
                        direccion_principal = DireccionUsuario.objects.filter(
                            usuario=carrito.cliente.usuario,
                            es_principal=True
                        ).first()
                        
                        if direccion_principal:
                            # Construir dirección completa con detalles si existen
                            ubicacion_completa = direccion_principal.direccion
                            if direccion_principal.detalles:
                                ubicacion_completa += f", {direccion_principal.detalles}"
                            if direccion_principal.etiqueta:
                                ubicacion_completa += f" ({direccion_principal.etiqueta})"
                            ubicacion_servicio = ubicacion_completa
                        else:
                            # Si no hay principal, buscar la más reciente
                            direccion_reciente = DireccionUsuario.objects.filter(
                                usuario=carrito.cliente.usuario
                            ).order_by('-es_principal', '-fecha_actualizacion').first()
                            
                            if direccion_reciente:
                                ubicacion_completa = direccion_reciente.direccion
                                if direccion_reciente.detalles:
                                    ubicacion_completa += f", {direccion_reciente.detalles}"
                                if direccion_reciente.etiqueta:
                                    ubicacion_completa += f" ({direccion_reciente.etiqueta})"
                                ubicacion_servicio = ubicacion_completa
                    except Exception as e:
                        logger = logging.getLogger(__name__)
                        logger.warning(f"No se pudo obtener dirección del cliente para servicio a domicilio: {e}")
                
                # ✅ CAMBIO: Estado inicial 'confirmado'
                # Si el carrito proviene de una oferta aceptada (nuevo flujo de solicitudes públicas),
                # la orden se crea directamente como 'confirmado' sin requerir aceptación del proveedor.
                # Esto es porque el proveedor ya aceptó implícitamente al enviar la oferta.
                
                # Crear solicitud
                solicitud = SolicitudServicio.objects.create(
                    cliente=carrito.cliente,
                    vehiculo=carrito.vehiculo,
                    tipo_servicio=tipo_servicio,
                    taller=taller,
                    mecanico=mecanico,
                    fecha_servicio=item.fecha_servicio,
                    hora_servicio=item.hora_servicio,
                    metodo_pago=metodo_pago,
                    total=item.precio_estimado,
                    estado='confirmado',  # ✅ Directamente confirmado (el proveedor ya ofreció)
                    notas_cliente=notas_cliente,
                    ubicacion_servicio=ubicacion_servicio,
                    comprobante_validado=False,
                    devolucion_procesada=False,
                    requiere_devolucion=False
                )
                
                # Crear línea de servicio
                linea_data = {
                    'solicitud': solicitud,
                    'oferta_servicio': item.oferta_servicio,
                    'con_repuestos': item.con_repuestos,
                    'cantidad': item.cantidad,
                    'precio_unitario': item.precio_estimado / Decimal(item.cantidad),
                    'precio_final': item.precio_estimado
                }
                
                LineaServicio.objects.create(**linea_data)
                
                solicitudes_creadas.append(solicitud)
            
            # Marcar carrito como inactivo
            carrito.activo = False
            carrito.save()
            
            # Serializar solicitudes creadas
            solicitudes_data = SolicitudServicioSerializer(solicitudes_creadas, many=True).data
            
            return Response({
                "mensaje": f"Se crearon {len(solicitudes_creadas)} solicitudes de servicio",
                "solicitudes": solicitudes_data
            })
            
        except Exception as e:
            return Response(
                {"error": f"Error al confirmar carrito: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['post'])
    def limpiar_vacios(self, request):
        """
        Limpia carritos vacíos (sin items) para un vehículo específico
        """
        vehiculo_id = request.data.get('vehiculo_id')
        if not vehiculo_id:
            return Response(
                {"error": "Se requiere vehiculo_id"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Buscar carritos activos vacíos para este vehículo del usuario autenticado
            carritos_vacios = self.get_queryset().filter(
                vehiculo_id=vehiculo_id,
                activo=True,
                items__isnull=True
            ).distinct()
            
            carritos_eliminados = 0
            for carrito in carritos_vacios:
                # Verificar que realmente no tiene items
                if not carrito.items.exists():
                    logger = logging.getLogger(__name__)
                    logger.info(f"Eliminando carrito vacío {carrito.id} para vehículo {vehiculo_id}")
                    carrito.delete()
                    carritos_eliminados += 1
            
            return Response({
                "mensaje": f"Se eliminaron {carritos_eliminados} carritos vacíos",
                "carritos_eliminados": carritos_eliminados
            })
            
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Error limpiando carritos vacíos para vehículo {vehiculo_id}: {str(e)}")
            
            return Response(
                {"error": f"Error al limpiar carritos vacíos: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def create(self, request, *args, **kwargs):
        """
        Crea un nuevo carrito de agendamiento
        NUEVO: Implementa UN SOLO CARRITO TEMPORAL POR CLIENTE
        """
        try:
            from mecanimovilapp.apps.usuarios.models import Cliente
            cliente = Cliente.objects.get(usuario=request.user)
            
            # NUEVA LÓGICA: UN SOLO CARRITO TEMPORAL POR CLIENTE
            # Eliminar cualquier carrito activo existente del cliente
            carritos_existentes = CarritoAgendamiento.objects.filter(
                cliente=cliente, 
                activo=True
            )
            
            if carritos_existentes.exists():
                logger = logging.getLogger(__name__)
                logger.info(f"Eliminando {carritos_existentes.count()} carritos activos existentes del cliente {cliente.id} para crear nuevo carrito temporal")
                carritos_existentes.delete()
            
            # CORRECCIÓN: Agregar cliente a los datos ANTES de la validación
            data = request.data.copy()
            data['cliente'] = cliente.id
            
            # Crear el nuevo carrito (único para el cliente)
            serializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            
            # Ya no necesitamos asignar cliente aquí porque está en los datos validados
            carrito = serializer.save()
            
            logger = logging.getLogger(__name__)
            logger.info(f"Nuevo carrito temporal {carrito.id} creado para cliente {cliente.id}")
            
            return Response(
                self.get_serializer(carrito).data, 
                status=status.HTTP_201_CREATED
            )
            
        except Cliente.DoesNotExist:
            return Response(
                {"error": "Usuario no tiene perfil de cliente asociado"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Error creando carrito: {str(e)}")
            return Response(
                {"error": f"Error creando carrito: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class AgendamientoViewSet(viewsets.ViewSet):
    """
    ViewSet para operaciones de agendamiento
    NOTA: Algunas operaciones se mantienen para compatibilidad pero 
    ahora usan HorarioProveedor en lugar de Disponibilidad
    """
    permission_classes = [permissions.IsAuthenticated]
    
    @action(detail=False, methods=['get'])
    def disponibilidad_taller(self, request):
        """
        Obtiene la disponibilidad de un taller específico
        DEPRECADO: Usar /api/usuarios/talleres/{id}/horarios_disponibles/ en su lugar
        """
        serializer = AgendamientoDisponibilidadSerializer(data=request.query_params)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        data = serializer.validated_data
        taller_id = data['taller_id']
        fecha_inicio = data['fecha_inicio']
        fecha_fin = data['fecha_fin']
        duracion_servicio = data['duracion_servicio']
        
        # NUEVA IMPLEMENTACIÓN: Usar HorarioProveedor
        try:
            from mecanimovilapp.apps.usuarios.models import Taller, HorarioProveedor
            
            taller = Taller.objects.get(id=taller_id)
        
            slots_disponibles = []
            fecha_actual = fecha_inicio
            
            while fecha_actual <= fecha_fin:
                dia_semana = fecha_actual.weekday()
                
                try:
                    horario = HorarioProveedor.objects.get(
                        taller=taller,
                        dia_semana=dia_semana,
                        activo=True
                    )
                    
                    # Generar slots para este día
                    slots_dia = horario.generar_slots_disponibles(fecha_actual)
                    
                    # Verificar disponibilidad real vs citas existentes
                    for slot in slots_dia:
                        slot_ocupado = SolicitudServicio.objects.filter(
                            taller=taller,
                            fecha_servicio=fecha_actual,
                            hora_servicio=slot['hora_inicio'],
                            estado__in=['pendiente', 'confirmado', 'en_proceso']
                        ).exists()
                        
                        if not slot_ocupado:
                            slots_disponibles.append({
                                'fecha': fecha_actual,
                                'hora_inicio': slot['hora_inicio'],
                                'hora_fin': slot['hora_fin'],
                                'disponible': True
                            })
                
                except HorarioProveedor.DoesNotExist:
                    # No hay horario configurado para este día
                    pass
                
                fecha_actual += timedelta(days=1)
        
            return Response({
                'taller_id': taller_id,
                'fecha_inicio': fecha_inicio,
                'fecha_fin': fecha_fin,
                'slots_disponibles': slots_disponibles,
                'mensaje': 'DEPRECADO: Use /api/usuarios/talleres/{id}/horarios_disponibles/ en su lugar'
            })
            
        except Taller.DoesNotExist:
            return Response(
                {"error": "Taller no encontrado"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {"error": f"Error obteniendo disponibilidad: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    def confirmar_agendamiento(self, request):
        """
        Confirma un agendamiento desde carrito
        """
        serializer = ConfirmarAgendamientoSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        data = serializer.validated_data
        carrito_id = data['carrito_id']
        metodo_pago = data['metodo_pago']
        notas_cliente = data.get('notas_cliente', '')
        
        try:
            carrito = CarritoAgendamiento.objects.get(id=carrito_id, activo=True)
            
            # Verificar que el carrito puede ser confirmado
            if not carrito.puede_confirmar():
                return Response(
                    {"error": "El carrito no puede ser confirmado. Verifique que tenga servicios y fechas/horas seleccionadas."}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Lógica de confirmación directa (sin usar ViewSet)
            solicitudes_creadas = []
            
            for item in carrito.items.all():
                # Determinar proveedor
                taller = item.oferta_servicio.taller
                mecanico = item.oferta_servicio.mecanico
                tipo_servicio = 'taller' if taller else 'domicilio'
                
                # Si es servicio a domicilio, obtener la dirección del cliente
                ubicacion_servicio = None
                if tipo_servicio == 'domicilio':
                    try:
                        from mecanimovilapp.apps.usuarios.models import DireccionUsuario
                        # Buscar dirección principal del cliente
                        direccion_principal = DireccionUsuario.objects.filter(
                            usuario=carrito.cliente.usuario,
                            es_principal=True
                        ).first()
                        
                        if direccion_principal:
                            # Construir dirección completa con detalles si existen
                            ubicacion_completa = direccion_principal.direccion
                            if direccion_principal.detalles:
                                ubicacion_completa += f", {direccion_principal.detalles}"
                            if direccion_principal.etiqueta:
                                ubicacion_completa += f" ({direccion_principal.etiqueta})"
                            ubicacion_servicio = ubicacion_completa
                        else:
                            # Si no hay principal, buscar la más reciente
                            direccion_reciente = DireccionUsuario.objects.filter(
                                usuario=carrito.cliente.usuario
                            ).order_by('-es_principal', '-fecha_actualizacion').first()
                            
                            if direccion_reciente:
                                ubicacion_completa = direccion_reciente.direccion
                                if direccion_reciente.detalles:
                                    ubicacion_completa += f", {direccion_reciente.detalles}"
                                if direccion_reciente.etiqueta:
                                    ubicacion_completa += f" ({direccion_reciente.etiqueta})"
                                ubicacion_servicio = ubicacion_completa
                    except Exception as e:
                        logger = logging.getLogger(__name__)
                        logger.warning(f"No se pudo obtener dirección del cliente para servicio a domicilio: {e}")
                
                # ✅ CAMBIO: Estado inicial 'confirmado'
                # Similar al método 'confirmar', las órdenes del nuevo flujo de solicitudes públicas
                # se crean directamente como 'confirmado' sin requerir aceptación del proveedor.
                
                # Crear solicitud
                solicitud = SolicitudServicio.objects.create(
                    cliente=carrito.cliente,
                    vehiculo=carrito.vehiculo,
                    tipo_servicio=tipo_servicio,
                    taller=taller,
                    mecanico=mecanico,
                    fecha_servicio=item.fecha_servicio,
                    hora_servicio=item.hora_servicio,
                    metodo_pago=metodo_pago,
                    total=item.precio_estimado,
                    estado='confirmado',  # ✅ Directamente confirmado (el proveedor ya ofreció)
                    notas_cliente=notas_cliente,
                    ubicacion_servicio=ubicacion_servicio,
                    comprobante_validado=False,
                    devolucion_procesada=False,
                    requiere_devolucion=False
                )
                
                # Crear línea de servicio
                linea_data = {
                    'solicitud': solicitud,
                    'oferta_servicio': item.oferta_servicio,
                    'con_repuestos': item.con_repuestos,
                    'cantidad': item.cantidad,
                    'precio_unitario': item.precio_estimado / Decimal(item.cantidad),
                    'precio_final': item.precio_estimado
                }
                
                LineaServicio.objects.create(**linea_data)
                
                solicitudes_creadas.append(solicitud)
            
            # Marcar carrito como inactivo
            carrito.activo = False
            carrito.save()
            
            # Serializar solicitudes creadas
            solicitudes_data = SolicitudServicioSerializer(solicitudes_creadas, many=True).data
            
            return Response({
                "mensaje": f"Se crearon {len(solicitudes_creadas)} solicitudes de servicio",
                "solicitudes": solicitudes_data
            })
            
        except CarritoAgendamiento.DoesNotExist:
            return Response(
                {"error": "Carrito no encontrado o no está activo"}, 
                status=status.HTTP_404_NOT_FOUND
            ) 
        except Exception as e:
            return Response(
                {"error": f"Error al confirmar carrito: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['post'])
    def confirmar_agendamiento_debug(self, request):
        """
        Endpoint temporal para diagnosticar problemas en confirmar_agendamiento
        """
        print("🔍 DEBUG: Iniciando confirmación de agendamiento")
        print(f"🔍 DEBUG: Datos recibidos: {request.data}")
        
        # Validar datos básicos
        carrito_id = request.data.get('carrito_id')
        metodo_pago = request.data.get('metodo_pago')
        acepta_terminos = request.data.get('acepta_terminos', True)
        notas_cliente = request.data.get('notas_cliente', '')
        
        print(f"🔍 DEBUG: carrito_id={carrito_id}, metodo_pago={metodo_pago}")
        
        if not carrito_id:
            return Response(
                {"error": "carrito_id es requerido"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not metodo_pago:
            return Response(
                {"error": "metodo_pago es requerido"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Obtener carrito
            print(f"🔍 DEBUG: Buscando carrito {carrito_id}")
            carrito = CarritoAgendamiento.objects.get(id=carrito_id, activo=True)
            print(f"🔍 DEBUG: Carrito encontrado: {carrito}")
            
            # Verificar items
            items = carrito.items.all()
            print(f"🔍 DEBUG: Items en carrito: {items.count()}")
            
            for item in items:
                print(f"🔍 DEBUG: Item {item.id}:")
                print(f"   - Servicio: {item.oferta_servicio.servicio.nombre}")
                print(f"   - Fecha: {item.fecha_servicio}")
                print(f"   - Hora: {item.hora_servicio}")
                print(f"   - Precio: {item.precio_estimado}")
                print(f"   - Taller: {item.oferta_servicio.taller}")
                print(f"   - Mecánico: {item.oferta_servicio.mecanico}")
            
            # Verificar si puede confirmar
            print(f"🔍 DEBUG: Verificando si puede confirmar...")
            puede_confirmar = carrito.puede_confirmar()
            print(f"🔍 DEBUG: Puede confirmar: {puede_confirmar}")
            
            if not puede_confirmar:
                # Diagnóstico detallado
                print("❌ DEBUG: Carrito no puede ser confirmado")
                print(f"   - Activo: {carrito.activo}")
                print(f"   - Tiene items: {carrito.items.exists()}")
                
                items_sin_fecha_hora = []
                for item in items:
                    if not item.fecha_servicio or not item.hora_servicio:
                        items_sin_fecha_hora.append(item.id)
                
                print(f"   - Items sin fecha/hora: {items_sin_fecha_hora}")
                
                return Response({
                    "error": "El carrito no puede ser confirmado",
                    "debug": {
                        "activo": carrito.activo,
                        "tiene_items": carrito.items.exists(),
                        "items_sin_fecha_hora": items_sin_fecha_hora
                    }
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Procesar confirmación
            print(f"🔍 DEBUG: Iniciando proceso de confirmación...")
            solicitudes_creadas = []
            
            for item in items:
                print(f"🔍 DEBUG: Procesando item {item.id}")
                
                # Determinar proveedor
                taller = item.oferta_servicio.taller
                mecanico = item.oferta_servicio.mecanico
                tipo_servicio = 'taller' if taller else 'domicilio'
                
                print(f"   - Tipo servicio: {tipo_servicio}")
                print(f"   - Taller: {taller}")
                print(f"   - Mecánico: {mecanico}")
                
                # Si es servicio a domicilio, obtener la dirección del cliente
                ubicacion_servicio = None
                if tipo_servicio == 'domicilio':
                    try:
                        from mecanimovilapp.apps.usuarios.models import DireccionUsuario
                        # Buscar dirección principal del cliente
                        direccion_principal = DireccionUsuario.objects.filter(
                            usuario=carrito.cliente.usuario,
                            es_principal=True
                        ).first()
                        
                        if direccion_principal:
                            # Construir dirección completa con detalles si existen
                            ubicacion_completa = direccion_principal.direccion
                            if direccion_principal.detalles:
                                ubicacion_completa += f", {direccion_principal.detalles}"
                            if direccion_principal.etiqueta:
                                ubicacion_completa += f" ({direccion_principal.etiqueta})"
                            ubicacion_servicio = ubicacion_completa
                        else:
                            # Si no hay principal, buscar la más reciente
                            direccion_reciente = DireccionUsuario.objects.filter(
                                usuario=carrito.cliente.usuario
                            ).order_by('-es_principal', '-fecha_actualizacion').first()
                            
                            if direccion_reciente:
                                ubicacion_completa = direccion_reciente.direccion
                                if direccion_reciente.detalles:
                                    ubicacion_completa += f", {direccion_reciente.detalles}"
                                if direccion_reciente.etiqueta:
                                    ubicacion_completa += f" ({direccion_reciente.etiqueta})"
                                ubicacion_servicio = ubicacion_completa
                    except Exception as e:
                        logger = logging.getLogger(__name__)
                        logger.warning(f"No se pudo obtener dirección del cliente para servicio a domicilio: {e}")
                
                # Crear solicitud
                print(f"🔍 DEBUG: Creando solicitud...")
                solicitud_data = {
                    'cliente': carrito.cliente,
                    'vehiculo': carrito.vehiculo,
                    'tipo_servicio': tipo_servicio,
                    'taller': taller,
                    'mecanico': mecanico,
                    'fecha_servicio': item.fecha_servicio,
                    'hora_servicio': item.hora_servicio,
                    'metodo_pago': metodo_pago,
                    'total': item.precio_estimado,
                    'estado': 'pendiente',
                    'notas_cliente': notas_cliente,
                    'ubicacion_servicio': ubicacion_servicio,
                    'comprobante_validado': False,
                    'devolucion_procesada': False,
                    'requiere_devolucion': False
                }
                print(f"   - Datos solicitud: {solicitud_data}")
                
                solicitud = SolicitudServicio.objects.create(**solicitud_data)
                print(f"   - Solicitud creada: {solicitud.id}")
                
                # Crear línea de servicio
                print(f"🔍 DEBUG: Creando línea de servicio...")
                linea_data = {
                    'solicitud': solicitud,
                    'oferta_servicio': item.oferta_servicio,
                    'con_repuestos': item.con_repuestos,
                    'cantidad': item.cantidad,
                    'precio_unitario': item.precio_estimado / Decimal(item.cantidad),
                    'precio_final': item.precio_estimado
                }
                print(f"   - Datos línea: {linea_data}")
                
                LineaServicio.objects.create(**linea_data)
                
                solicitudes_creadas.append(solicitud)
            
            # Marcar carrito como inactivo
            print(f"🔍 DEBUG: Marcando carrito como inactivo...")
            carrito.activo = False
            carrito.save()
            print(f"🔍 DEBUG: Carrito marcado como inactivo")
            
            # Serializar respuesta
            print(f"🔍 DEBUG: Creando respuesta...")
            solicitudes_data = SolicitudServicioSerializer(solicitudes_creadas, many=True).data
            
            response = {
                "mensaje": f"Se crearon {len(solicitudes_creadas)} solicitudes de servicio",
                "solicitudes": solicitudes_data,
                "debug": "Proceso completado exitosamente"
            }
            
            print(f"✅ DEBUG: Proceso completado: {len(solicitudes_creadas)} solicitudes creadas")
            return Response(response)
            
        except CarritoAgendamiento.DoesNotExist:
            print(f"❌ DEBUG: Carrito {carrito_id} no encontrado")
            return Response(
                {"error": "Carrito no encontrado o no está activo"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            print(f"❌ DEBUG: Error inesperado: {e}")
            import traceback
            traceback.print_exc()
            return Response(
                {"error": f"Error al confirmar carrito: {str(e)}", "debug": "Ver logs del servidor"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def validar_disponibilidad_taller(request):
    """
    Valida si un taller está disponible en una fecha y hora específica
    ACTUALIZADO: Usa HorarioProveedor en lugar de Disponibilidad
    """
    taller_id = request.GET.get('taller_id')
    fecha_servicio = request.GET.get('fecha_servicio')
    hora_servicio = request.GET.get('hora_servicio')
    
    if not all([taller_id, fecha_servicio, hora_servicio]):
        return Response(
            {
                'disponible': False,
                'error': 'Se requieren taller_id, fecha_servicio y hora_servicio'
            }, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        from mecanimovilapp.apps.usuarios.models import Taller, HorarioProveedor
        from datetime import datetime
        
        # Validar que el taller existe
        taller = Taller.objects.get(id=taller_id)
        
        # Convertir fecha string a objeto date
        fecha_obj = datetime.strptime(fecha_servicio, '%Y-%m-%d').date()
        hora_obj = datetime.strptime(hora_servicio, '%H:%M').time()
        
        # Obtener día de la semana (0=Lunes, 6=Domingo)
        dia_semana = fecha_obj.weekday()
        
        # Verificar si el taller tiene horario configurado para ese día
        try:
            horario = HorarioProveedor.objects.get(
            taller=taller,
            dia_semana=dia_semana,
            activo=True
            )
            
            # Verificar si la hora está dentro del rango de atención
            if not (horario.hora_inicio <= hora_obj <= horario.hora_fin):
                return Response({
                    'disponible': False,
                    'error': f'La hora {hora_servicio} está fuera del horario de atención ({horario.hora_inicio}-{horario.hora_fin})'
                })
            
        except HorarioProveedor.DoesNotExist:
            return Response({
                'disponible': False,
                'error': 'El taller no atiende este día de la semana'
            })
        
        # Verificar si ya tiene una cita a esa hora
        cita_existente = SolicitudServicio.objects.filter(
            taller=taller,
            fecha_servicio=fecha_obj,
            hora_servicio=hora_obj,
            estado__in=['pendiente', 'confirmado', 'en_proceso']
        ).exists()
        
        if cita_existente:
            return Response({
                'disponible': False,
                'error': 'El taller ya tiene una cita programada a esa hora'
            })
        
        return Response({
            'disponible': True,
            'mensaje': 'Horario disponible',
            'taller': taller.nombre,
            'horario_configurado': {
                'hora_inicio': horario.hora_inicio,
                'hora_fin': horario.hora_fin,
                'duracion_slot': horario.duracion_slot
            }
        })
        
    except Taller.DoesNotExist:
            return Response(
                {
                    'disponible': False,
                'error': 'Taller no encontrado'
                }, 
                status=status.HTTP_404_NOT_FOUND
            )
    except ValueError as e:
            return Response(
                {
                    'disponible': False,
                'error': f'Error en formato de fecha/hora: {str(e)}'
            }, 
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        return Response(
            {
                'disponible': False,
                'error': f'Error validando disponibilidad: {str(e)}'
            }, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def validar_disponibilidad_mecanico(request):
    """
    Valida si un mecánico está disponible en una fecha y hora específica
    ACTUALIZADO: Usa HorarioProveedor en lugar de validación básica
    """
    mecanico_id = request.GET.get('mecanico_id')
    fecha_servicio = request.GET.get('fecha_servicio')
    hora_servicio = request.GET.get('hora_servicio')
    
    if not all([mecanico_id, fecha_servicio, hora_servicio]):
        return Response(
            {
                'disponible': False,
                'error': 'Se requieren mecanico_id, fecha_servicio y hora_servicio'
            }, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        from mecanimovilapp.apps.usuarios.models import MecanicoDomicilio, HorarioProveedor
        from datetime import datetime
        
        # Validar que el mecánico existe
        mecanico = MecanicoDomicilio.objects.get(id=mecanico_id)
        
        # Convertir fecha string a objeto date
        fecha_obj = datetime.strptime(fecha_servicio, '%Y-%m-%d').date()
        hora_obj = datetime.strptime(hora_servicio, '%H:%M').time()
        
        # Obtener día de la semana (0=Lunes, 6=Domingo)
        dia_semana = fecha_obj.weekday()
        
        # Verificar si el mecánico tiene horario configurado para ese día
        try:
            horario = HorarioProveedor.objects.get(
                mecanico=mecanico,
            dia_semana=dia_semana,
            activo=True
            )
            
            # Verificar si la hora está dentro del rango de atención
            if not (horario.hora_inicio <= hora_obj <= horario.hora_fin):
                return Response({
                    'disponible': False,
                    'error': f'La hora {hora_servicio} está fuera del horario de atención ({horario.hora_inicio}-{horario.hora_fin})'
                })
            
        except HorarioProveedor.DoesNotExist:
            return Response({
                'disponible': False,
                'error': 'El mecánico no atiende este día de la semana'
            })
        
        # Verificar si ya tiene una cita a esa hora
        cita_existente = SolicitudServicio.objects.filter(
            mecanico=mecanico,
            fecha_servicio=fecha_obj,
            hora_servicio=hora_obj,
            estado__in=['pendiente', 'confirmado', 'en_proceso']
        ).exists()
        
        if cita_existente:
            return Response({
                'disponible': False,
                'error': 'El mecánico ya tiene una cita programada a esa hora'
            })
        
        return Response({
            'disponible': True,
            'mensaje': 'Horario disponible',
            'mecanico': mecanico.nombre,
            'horario_configurado': {
                'hora_inicio': horario.hora_inicio,
                'hora_fin': horario.hora_fin,
                'duracion_slot': horario.duracion_slot
            }
        })
        
    except MecanicoDomicilio.DoesNotExist:
        return Response(
                {
                    'disponible': False,
                'error': 'Mecánico no encontrado'
                }, 
            status=status.HTTP_404_NOT_FOUND
        )
    except ValueError as e:
        return Response(
                {
                    'disponible': False,
                'error': f'Error en formato de fecha/hora: {str(e)}'
            }, 
            status=status.HTTP_400_BAD_REQUEST
        ) 
    except Exception as e:
        return Response(
            {
                'disponible': False,
                'error': f'Error validando disponibilidad: {str(e)}'
            }, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def obtener_configuracion_precio(request):
    """
    Obtiene la configuración activa de precios (IVA y tarifa de servicio)
    """
    try:
        config = ConfiguracionPrecio.objects.filter(activo=True).first()
        
        if not config:
            # Crear configuración por defecto si no existe
            config = ConfiguracionPrecio.objects.create(
                iva_porcentaje=19.0,
                tarifa_servicio_porcentaje=3.0,
                activo=True
            )
        
        return Response({
            'iva_porcentaje': float(config.iva_porcentaje),
            'tarifa_servicio_porcentaje': float(config.tarifa_servicio_porcentaje),
            'activo': config.activo
        })
        
    except Exception as e:
        return Response(
            {'error': f'Error obteniendo configuración: {str(e)}'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def calcular_precio_detallado(request):
    """
    Calcula el desglose detallado de precios (subtotal, IVA, tarifa de servicio, total)
    """
    subtotal = request.data.get('subtotal')
        
    if not subtotal:
        return Response(
            {'error': 'Se requiere el subtotal'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
    try:
        # Obtener configuración activa
        config = ConfiguracionPrecio.objects.filter(activo=True).first()
        
        if not config:
            config = ConfiguracionPrecio.objects.create(
                iva_porcentaje=19.0,
                tarifa_servicio_porcentaje=3.0,
                activo=True
            )
        
        # Convertir a Decimal para precisión
        subtotal_decimal = Decimal(str(subtotal))
        
        # Calcular tarifa de servicio sobre el subtotal
        tarifa_servicio = subtotal_decimal * (config.tarifa_servicio_porcentaje / Decimal('100'))
        
        # Calcular IVA sobre subtotal + tarifa
        base_iva = subtotal_decimal + tarifa_servicio
        iva = base_iva * (config.iva_porcentaje / Decimal('100'))
        
        # Total final
        total = subtotal_decimal + tarifa_servicio + iva
        
        return Response({
            'subtotal': float(subtotal_decimal.quantize(Decimal('0.01'))),
            'tarifa_servicio': float(tarifa_servicio.quantize(Decimal('0.01'))),
            'iva': float(iva.quantize(Decimal('0.01'))),
            'total': float(total.quantize(Decimal('0.01'))),
            'iva_porcentaje': float(config.iva_porcentaje),
            'tarifa_porcentaje': float(config.tarifa_servicio_porcentaje)
        })
        
    except (ValueError, TypeError) as e:
        return Response(
            {'error': f'Error en el subtotal proporcionado: {str(e)}'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        return Response(
            {'error': f'Error calculando precios: {str(e)}'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

class ProveedorOrdenesViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet para que los proveedores gestionen sus órdenes con protección de datos
    """
    serializer_class = SolicitudServicioProveedorSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """
        Filtrar órdenes para el proveedor autenticado
        """
        user = self.request.user
        
        # Determinar si es taller o mecánico
        try:
            if hasattr(user, 'taller'):
                return SolicitudServicio.objects.filter(
                    taller=user.taller
                ).select_related(
                    'cliente', 'cliente__usuario', 'vehiculo', 'taller', 'mecanico', 'oferta_proveedor'
                ).prefetch_related('lineas__oferta_servicio__servicio')
            elif hasattr(user, 'mecanico_domicilio'):
                return SolicitudServicio.objects.filter(
                    mecanico=user.mecanico_domicilio
                ).select_related(
                    'cliente', 'cliente__usuario', 'vehiculo', 'taller', 'mecanico', 'oferta_proveedor'
                ).prefetch_related('lineas__oferta_servicio__servicio')
            else:
                return SolicitudServicio.objects.none()
        except:
            return SolicitudServicio.objects.none()
    
    def list(self, request, *args, **kwargs):
        """
        Lista órdenes con filtros opcionales de estado
        """
        queryset = self.get_queryset()
        
        # Aplicar filtro de estado si se proporciona
        estado = request.query_params.get('estado')
        if estado:
            queryset = queryset.filter(estado=estado)
        
        # Ordenar por fecha de servicio
        queryset = queryset.order_by('fecha_servicio', 'hora_servicio')
        
        # Aplicar paginación
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def pendientes(self, request):
        """
        Obtiene las órdenes pendientes de aceptación
        """
        ordenes = self.get_queryset().filter(
            estado='pendiente_aceptacion_proveedor'
        ).order_by('fecha_hora_solicitud')
        
        serializer = self.get_serializer(ordenes, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def activas(self, request):
        """
        Obtiene todas las órdenes abiertas (no finalizadas)
        Incluye órdenes con estado 'confirmado' que provienen de ofertas pagadas o en ejecución.
        También busca ofertas pagadas/en_ejecucion sin SolicitudServicio y las crea si no existen.
        Excluye órdenes finalizadas: completado, cancelado, rechazada_por_proveedor, devuelto
        Excluye órdenes cuya oferta_proveedor esté rechazada, expirada o retirada
        """
        user = request.user
        
        # Determinar proveedor
        taller = None
        mecanico = None
        if hasattr(user, 'taller'):
            taller = user.taller
        elif hasattr(user, 'mecanico_domicilio'):
            mecanico = user.mecanico_domicilio
        else:
            return Response([])
        
        # ✅ Estados finalizados de SolicitudServicio que NO deben aparecer
        estados_finalizados = [
            'completado',
            'cancelado',
            'rechazada_por_proveedor',
            'devuelto'
        ]
        
        # ✅ Estados de OfertaProveedor que indican que la oferta ya no está activa
        estados_oferta_no_activos = [
            'rechazada',
            'retirada',
            'expirada'
        ]
        
        # 1. Obtener todas las órdenes NO finalizadas (SolicitudServicio)
        # Incluir todos los estados abiertos: pendiente, pago_validado, confirmado, 
        # pendiente_aceptacion_proveedor, aceptada_por_proveedor, checklist_en_progreso,
        # checklist_completado, en_proceso, solicitud_cancelacion, pendiente_devolucion
        ordenes = self.get_queryset().exclude(
            estado__in=estados_finalizados
        )
        
        # ✅ 1.1 NUEVO: Excluir órdenes cuya oferta_proveedor esté rechazada/expirada/retirada
        # Esto asegura que ofertas rechazadas no aparezcan como órdenes activas
        ordenes = ordenes.exclude(
            oferta_proveedor__estado__in=estados_oferta_no_activos
        )
        
        # 2. Buscar ofertas pagadas o en ejecución que no tengan SolicitudServicio asociada
        # Incluir tanto ofertas principales como secundarias
        # y crear la SolicitudServicio si no existe
        # ✅ El queryset principal ya incluye todas las SolicitudServicio no finalizadas,
        # incluyendo las que tienen oferta_proveedor asociada (tanto principales como secundarias)
        # Obtener todas las ofertas pagadas/en_ejecucion del proveedor
        todas_ofertas_pagadas = OfertaProveedor.objects.filter(
            proveedor=user,
            estado__in=['pagada', 'en_ejecucion']
        ).select_related('solicitud', 'solicitud__cliente', 'solicitud__vehiculo')
        
        # Filtrar las que no tienen SolicitudServicio asociada
        # Incluir tanto ofertas principales como secundarias
        ofertas_pagadas_sin_orden = []
        for oferta in todas_ofertas_pagadas:
            tiene_solicitud_servicio = SolicitudServicio.objects.filter(oferta_proveedor=oferta).exists()
            if not tiene_solicitud_servicio:
                logger.info(f"Oferta {oferta.id} (secundaria: {oferta.es_oferta_secundaria}) sin SolicitudServicio, será creada")
                ofertas_pagadas_sin_orden.append(oferta)
            else:
                logger.info(f"Oferta {oferta.id} ya tiene SolicitudServicio asociada")
        
        logger.info(f"Total ofertas pagadas sin orden encontradas: {len(ofertas_pagadas_sin_orden)}")
        
        ordenes_creadas = []
        for oferta in ofertas_pagadas_sin_orden:
            try:
                # Las ofertas secundarias también tienen una relación directa con solicitud
                # Usar la solicitud de la oferta secundaria directamente
                if not oferta.solicitud:
                    logger.warning(f"Oferta {oferta.id} (secundaria: {oferta.es_oferta_secundaria}) no tiene solicitud asociada")
                    continue
                
                solicitud_publica = oferta.solicitud
                logger.info(f"Procesando oferta {oferta.id} (secundaria: {oferta.es_oferta_secundaria}) para crear SolicitudServicio")
                
                # Determinar tipo de servicio y proveedor
                if oferta.tipo_proveedor == 'taller':
                    if not taller:
                        continue
                    tipo_servicio = 'taller'
                    ubicacion_servicio = taller.direccion if taller else None
                else:
                    if not mecanico:
                        continue
                    tipo_servicio = 'domicilio'
                    ubicacion_servicio = solicitud_publica.direccion_servicio_texto
                
                # Crear SolicitudServicio para esta oferta
                with transaction.atomic():
                    solicitud_servicio = SolicitudServicio.objects.create(
                        cliente=solicitud_publica.cliente,
                        vehiculo=solicitud_publica.vehiculo,
                        tipo_servicio=tipo_servicio,
                        taller=taller,
                        mecanico=mecanico,
                        fecha_servicio=oferta.fecha_disponible or timezone.now().date(),
                        hora_servicio=oferta.hora_disponible or timezone.now().time(),
                        metodo_pago='transferencia',  # Default, ya fue pagado
                        total=oferta.precio_total_ofrecido,
                        estado='confirmado',
                        notas_cliente=solicitud_publica.descripcion_problema or '',
                        ubicacion_servicio=ubicacion_servicio,
                        comprobante_validado=True,  # Ya fue pagado
                        devolucion_procesada=False,
                        requiere_devolucion=False,
                        oferta_proveedor=oferta
                    )
                    
                    # Crear líneas de servicio
                    from mecanimovilapp.apps.servicios.models import OfertaServicio
                    detalles_servicios = list(oferta.detalles_servicios.all())
                    tipo_proveedor_servicio = oferta.tipo_proveedor
                    
                    for detalle in detalles_servicios:
                        try:
                            oferta_servicio = OfertaServicio.objects.get(
                                servicio=detalle.servicio,
                                tipo_proveedor=tipo_proveedor_servicio,
                                taller=taller,
                                mecanico=mecanico
                            )
                        except OfertaServicio.DoesNotExist:
                            # Crear OfertaServicio temporal si no existe
                            precio_ofrecido = Decimal(str(detalle.precio_servicio))
                            precio_sin_iva = precio_ofrecido / Decimal('1.19')
                            
                            if oferta.incluye_repuestos:
                                costo_mano_de_obra = precio_sin_iva * Decimal('0.70')
                                costo_repuestos = precio_sin_iva * Decimal('0.30')
                            else:
                                costo_mano_de_obra = precio_sin_iva
                                costo_repuestos = Decimal('0')
                            
                            oferta_servicio = OfertaServicio.objects.create(
                                servicio=detalle.servicio,
                                tipo_proveedor=tipo_proveedor_servicio,
                                taller=taller,
                                mecanico=mecanico,
                                costo_mano_de_obra_sin_iva=costo_mano_de_obra,
                                costo_repuestos_sin_iva=costo_repuestos,
                                disponible=True
                            )
                        
                        LineaServicio.objects.create(
                            solicitud=solicitud_servicio,
                            oferta_servicio=oferta_servicio,
                            con_repuestos=oferta.incluye_repuestos,
                            cantidad=1,
                            precio_unitario=detalle.precio_servicio,
                            precio_final=detalle.precio_servicio
                        )
                    
                    logger.info(f"✅ SolicitudServicio creada automáticamente para oferta {oferta.id} (secundaria: {oferta.es_oferta_secundaria}): {solicitud_servicio.id}")
                    ordenes_creadas.append(solicitud_servicio)
                    
                    # ✅ Crear checklist automáticamente si existe template
                    try:
                        from mecanimovilapp.apps.checklists.models import ChecklistTemplate, ChecklistInstance
                        detalles_servicios = list(oferta.detalles_servicios.all())
                        for detalle in detalles_servicios:
                            servicio = detalle.servicio
                            template = ChecklistTemplate.objects.filter(
                                servicio=servicio,
                                activo=True
                            ).first()
                            if template:
                                existing_instance = ChecklistInstance.objects.filter(orden=solicitud_servicio).first()
                                if not existing_instance:
                                    checklist_instance = ChecklistInstance.objects.create(
                                        orden=solicitud_servicio,
                                        checklist_template=template,
                                        estado='PENDIENTE'
                                    )
                                    logger.info(f'✅ Checklist creado automáticamente al crear orden: {checklist_instance.id} para orden {solicitud_servicio.id}')
                                    solicitud_servicio.estado = 'checklist_en_progreso'
                                    solicitud_servicio.save(update_fields=['estado'])
                                break
                    except Exception as checklist_error:
                        logger.warning(f'⚠️ Error creando checklist para orden {solicitud_servicio.id}: {checklist_error}')
                    
            except Exception as e:
                logger.error(f"❌ Error creando SolicitudServicio para oferta {oferta.id}: {e}", exc_info=True)
                continue
        
        logger.info(f"📊 Total SolicitudServicio creadas automáticamente: {len(ordenes_creadas)}")
        
        # ✅ 3. Verificar órdenes existentes sin checklist y crearlos si corresponde
        try:
            from mecanimovilapp.apps.checklists.models import ChecklistTemplate, ChecklistInstance
            ordenes_sin_checklist = ordenes.filter(
                oferta_proveedor__isnull=False,
                estado__in=['confirmado', 'en_ejecucion', 'checklist_en_progreso']
            ).exclude(
                id__in=ChecklistInstance.objects.values_list('orden_id', flat=True)
            )
            
            checklist_creados_retroactivos = 0
            for orden_sin_checklist in ordenes_sin_checklist:
                if orden_sin_checklist.oferta_proveedor:
                    oferta = orden_sin_checklist.oferta_proveedor
                    detalles_servicios = list(oferta.detalles_servicios.all())
                    for detalle in detalles_servicios:
                        servicio = detalle.servicio
                        template = ChecklistTemplate.objects.filter(
                            servicio=servicio,
                            activo=True
                        ).first()
                        if template:
                            checklist_instance = ChecklistInstance.objects.create(
                                orden=orden_sin_checklist,
                                checklist_template=template,
                                estado='PENDIENTE'
                            )
                            logger.info(f'✅ Checklist creado retroactivamente: {checklist_instance.id} para orden {orden_sin_checklist.id}')
                            if orden_sin_checklist.estado == 'confirmado':
                                orden_sin_checklist.estado = 'checklist_en_progreso'
                                orden_sin_checklist.save(update_fields=['estado'])
                            checklist_creados_retroactivos += 1
                            break
            
            if checklist_creados_retroactivos > 0:
                logger.info(f'📊 Total checklists creados retroactivamente: {checklist_creados_retroactivos}')
        except Exception as e:
            logger.warning(f'⚠️ Error verificando checklists retroactivos: {e}')
        
        # 4. Incluir las órdenes recién creadas en el queryset
        if ordenes_creadas:
            ordenes_ids = [o.id for o in ordenes_creadas]
            ordenes_adicionales = self.get_queryset().filter(id__in=ordenes_ids)
            ordenes = ordenes | ordenes_adicionales
            logger.info(f"📊 Órdenes adicionales incluidas: {ordenes_adicionales.count()}")
        
        # 5. Ordenar y serializar
        ordenes = ordenes.order_by('fecha_servicio', 'hora_servicio')
        total_ordenes = ordenes.count()
        logger.info(f"📊 Total órdenes activas retornadas: {total_ordenes}")
        serializer = self.get_serializer(ordenes, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def completadas(self, request):
        """
        Obtiene las órdenes completadas del proveedor (con restricciones de tiempo)
        """
        # Solo mostrar órdenes completadas de los últimos 30 días
        fecha_limite = timezone.now() - timezone.timedelta(days=30)
        
        ordenes = self.get_queryset().filter(
            estado='completado',
            fecha_respuesta_proveedor__gte=fecha_limite
        ).order_by('-fecha_servicio')
        
        serializer = self.get_serializer(ordenes, many=True)
        return Response(serializer.data)
    
    def _inicializar_servicio_y_crear_checklist(self, orden):
        """
        Función auxiliar para inicializar el servicio y crear el checklist automáticamente
        """
        logger = logging.getLogger(__name__)
        
        try:
            # Refrescar la orden con las relaciones necesarias para asegurar que las líneas estén cargadas
            orden.refresh_from_db()
            # Prefechar las líneas con sus relaciones
            from django.db.models import Prefetch
            from .models import LineaServicio
            orden = SolicitudServicio.objects.prefetch_related(
                Prefetch('lineas', queryset=LineaServicio.objects.select_related('oferta_servicio__servicio'))
            ).get(id=orden.id)
            
            # Obtener el servicio de la primera línea de la orden
            primera_linea = orden.lineas.first()
            if not primera_linea or not primera_linea.oferta_servicio or not primera_linea.oferta_servicio.servicio:
                logger.warning(f'⚠️ No se pudo obtener servicio de la orden {orden.id}')
                return False
            
            servicio = primera_linea.oferta_servicio.servicio
            
            # Intentar importar modelos de checklist
            try:
                from mecanimovilapp.apps.checklists.models import ChecklistTemplate, ChecklistInstance
                
                # Buscar template activo para este servicio
                template = ChecklistTemplate.objects.filter(
                    servicio=servicio,
                    activo=True
                ).first()
                
                if template:
                    # Verificar que no exista ya una instancia para esta orden
                    existing_instance = ChecklistInstance.objects.filter(orden=orden).first()
                    if not existing_instance:
                        # Crear automáticamente la instancia de checklist
                        checklist_instance = ChecklistInstance.objects.create(
                            orden=orden,
                            checklist_template=template,
                            estado='PENDIENTE'
                        )
                        logger.info(f'✅ Checklist creado automáticamente: {checklist_instance.id} para orden {orden.id} con template {template.id}')
                        
                        # Cambiar estado de orden a checklist_en_progreso
                        orden.estado = 'checklist_en_progreso'
                        orden.save()
                        return True
                    else:
                        logger.info(f'⚠️ Ya existe checklist para orden {orden.id}: {existing_instance.id}')
                        # Si ya existe checklist, cambiar a checklist_en_progreso
                        orden.estado = 'checklist_en_progreso'
                        orden.save()
                        return True
                else:
                    logger.info(f'💭 No hay template de checklist para servicio: {servicio.nombre} - manteniendo estado actual')
                    # Si no hay template, cambiar estado a servicio_iniciado
                    orden.estado = 'servicio_iniciado'
                    orden.save()
                    return True
            except ImportError:
                logger.warning('⚠️ App de checklists no disponible')
                # Si no hay app de checklists, cambiar estado a servicio_iniciado
                orden.estado = 'servicio_iniciado'
                orden.save()
                return True
        except Exception as e:
            logger.error(f'⚠️ Error procesando checklist para orden {orden.id}: {str(e)}', exc_info=True)
            # En caso de error, al menos cambiar a servicio_iniciado
            orden.estado = 'servicio_iniciado'
            orden.save()
            return False

    @action(detail=True, methods=['post'])
    def aceptar(self, request, pk=None):
        """
        Permite al proveedor aceptar una orden
        NOTA: La inicialización del servicio es manual, se debe llamar a iniciar_servicio después
        """
        orden = self.get_object()
        
        # Verificar que la orden puede ser aceptada
        if orden.estado != 'pendiente_aceptacion_proveedor':
            return Response(
                {'error': 'Esta orden no puede ser aceptada en su estado actual'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = AcceptOrderSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        with transaction.atomic():
            # Actualizar estado y notas
            orden.estado = 'aceptada_por_proveedor'
            orden.fecha_respuesta_proveedor = timezone.now()
            orden.notas_proveedor = serializer.validated_data.get('notas', '')
            orden.save()
        
        # Retornar orden actualizada
        response_serializer = self.get_serializer(orden)
        return Response({
            'message': 'Orden aceptada exitosamente',
            'orden': response_serializer.data
        })
    
    @action(detail=True, methods=['post'])
    def rechazar(self, request, pk=None):
        """
        Permite al proveedor rechazar una orden
        """
        orden = self.get_object()
        
        # Verificar que la orden puede ser rechazada
        if orden.estado != 'pendiente_aceptacion_proveedor':
            return Response(
                {'error': 'Esta orden no puede ser rechazada en su estado actual'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = RejectOrderSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        with transaction.atomic():
            # Actualizar estado y motivo
            orden.estado = 'rechazada_por_proveedor'
            orden.fecha_respuesta_proveedor = timezone.now()
            orden.motivo_rechazo = serializer.validated_data['motivo_rechazo']
            orden.notas_proveedor = serializer.validated_data.get('notas', '')
            orden.save()
            
            # Notificar vía Push al cliente
            try:
                if orden.cliente and orden.cliente.usuario:
                    send_expo_push_notification.delay(
                        orden.cliente.usuario.id,
                        "Solicitud rechazada ❌",
                        f"El proveedor ha rechazado tu solicitud para el {orden.vehiculo.marca}. Puedes buscar otro proveedor.",
                        {"type": "order_rejected", "order_id": str(orden.id)}
                    )
            except Exception as e:
                logger.error(f"Error enviando push en rechazar (SolicitudServicio): {e}")
        
        # Retornar confirmación
        return Response({
            'message': 'Orden rechazada exitosamente'
        })
    
    @action(detail=False, methods=['get'])
    def estadisticas(self, request):
        """
        Retorna estadísticas del proveedor
        """
        queryset = self.get_queryset()
        
        # Calcular estadísticas básicas
        total_ordenes = queryset.count()
        ordenes_pendientes = queryset.filter(estado='pendiente_aceptacion_proveedor').count()
        ordenes_completadas = queryset.filter(estado='completado').count()
        ordenes_rechazadas = queryset.filter(estado='rechazada_por_proveedor').count()
        
        # Calcular ingresos del mes actual
        mes_actual = timezone.now().replace(day=1)
        ingresos_mes = queryset.filter(
            estado='completado',
            fecha_respuesta_proveedor__gte=mes_actual
        ).aggregate(total=Sum('total'))['total'] or 0
        
        estadisticas = {
            'total_ordenes': total_ordenes,
            'ordenes_pendientes': ordenes_pendientes,
            'ordenes_completadas': ordenes_completadas,
            'ordenes_rechazadas': ordenes_rechazadas,
            'ingresos_mes_actual': ingresos_mes,
            'calificacion_promedio': 4.5  # Placeholder - implementar sistema de calificaciones
        }
        
        serializer = OrdenEstadisticasSerializer(estadisticas)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def iniciar_servicio(self, request, pk=None):
        """
        Permite al proveedor iniciar el servicio después de aceptar la orden
        Al inicializar, se crea automáticamente el checklist asociado al servicio
        """
        orden = self.get_object()
        
        # Verificar que la orden puede iniciarse
        if orden.estado != 'aceptada_por_proveedor':
            return Response(
                {'error': f'El servicio no puede iniciarse desde el estado actual: {orden.estado}'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        checklist_creado = False
        checklist_id = None
        tiene_checklist = False
        
        with transaction.atomic():
            # Usar la función auxiliar para inicializar y crear checklist
            resultado = self._inicializar_servicio_y_crear_checklist(orden)
            
            # Verificar si se creó un checklist
            try:
                from mecanimovilapp.apps.checklists.models import ChecklistInstance
                checklist_instance = ChecklistInstance.objects.filter(orden=orden).first()
                if checklist_instance:
                    tiene_checklist = True
                    checklist_id = checklist_instance.id
                    checklist_creado = True
            except ImportError:
                pass
        
        # Retornar orden actualizada con información del checklist
        response_serializer = self.get_serializer(orden)
        response_data = {
            'message': 'Servicio iniciado exitosamente',
            'orden': response_serializer.data,
            'checklist_creado': checklist_creado,
            'tiene_checklist': tiene_checklist,
        }
        
        if checklist_id:
            response_data['checklist_id'] = checklist_id
            response_data['aviso'] = 'Debe completar el checklist asociado al servicio antes de continuar'
        
        return Response(response_data)
    
    @action(detail=True, methods=['post'])
    def actualizar_estado(self, request, pk=None):
        """
        Permite actualizar el estado de una orden
        """
        orden = self.get_object()
        nuevo_estado = request.data.get('estado')
        
        if not nuevo_estado:
            return Response(
                {'error': 'Se requiere el campo estado'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validar transiciones de estado válidas
        transiciones_validas = {
            'pendiente_aceptacion_proveedor': ['aceptada_por_proveedor', 'rechazada_por_proveedor'],
            'aceptada_por_proveedor': ['servicio_iniciado', 'cancelado'],
            'servicio_iniciado': ['checklist_en_progreso', 'en_proceso'],
            'checklist_en_progreso': ['checklist_completado', 'pausado'],
            'checklist_completado': ['en_proceso'],
            'en_proceso': ['completado', 'pausado'],
            'pausado': ['en_proceso', 'checklist_en_progreso'],
        }
        
        estados_validos = transiciones_validas.get(orden.estado, [])
        
        if nuevo_estado not in estados_validos:
            return Response(
                {
                    'error': f'Transición inválida de {orden.estado} a {nuevo_estado}',
                    'estados_validos': estados_validos
                }, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        with transaction.atomic():
            orden.estado = nuevo_estado
            orden.save()
            
            # Notificar vía Push
            try:
                estado_nombres = {
                    'aceptada_por_proveedor': 'Aceptada',
                    'servicio_iniciado': 'En camino',
                    'en_proceso': 'En ejecución',
                    'completado': 'Finalizado',
                    'rechazada_por_proveedor': 'Rechazada',
                }
                estado_str = estado_nombres.get(nuevo_estado, nuevo_estado.replace('_', ' '))
                
                # Al cliente
                if orden.cliente and orden.cliente.usuario:
                    send_expo_push_notification.delay(
                        orden.cliente.usuario.id,
                        f"Actualización de servicio: {estado_str}",
                        f"Tu servicio para el {orden.vehiculo.marca} {orden.vehiculo.modelo} ha pasado a estado: {estado_str}",
                        {"type": "status_update", "order_id": str(orden.id), "status": nuevo_estado}
                    )
            except Exception as e:
                logger.error(f"Error enviando push en actualizar_estado: {e}")
        
        response_serializer = self.get_serializer(orden)
        return Response({
            'message': f'Estado actualizado a {nuevo_estado}',
            'orden': response_serializer.data
        })
    
    @action(detail=True, methods=['post'])
    def finalizar_servicio(self, request, pk=None):
        """
        Permite finalizar el servicio
        """
        orden = self.get_object()
        
        # Verificar que el servicio puede finalizarse
        if orden.estado not in ['en_proceso', 'checklist_completado']:
            return Response(
                {'error': f'El servicio no puede finalizarse desde el estado: {orden.estado}'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Si hay checklist, verificar que esté completado
        try:
            from mecanimovilapp.apps.checklists.models import ChecklistInstance
            checklist = ChecklistInstance.objects.filter(orden=orden).first()
            
            if checklist and checklist.estado != 'COMPLETADO':
                return Response(
                    {'error': 'No se puede finalizar el servicio sin completar el checklist'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        except ImportError:
            pass  # Si no hay app de checklists, continuar
        
        with transaction.atomic():
            orden.estado = 'completado'
            orden.fecha_finalizacion = timezone.now()
            
            # Agregar notas si se proporcionan
            notas = request.data.get('notas')
            if notas:
                orden.notas_proveedor = (orden.notas_proveedor or '') + f'\nNotas de finalización: {notas}'
            
            orden.save()
            
            # Notificar vía Push al cliente
            try:
                if orden.cliente and orden.cliente.usuario:
                    send_expo_push_notification.delay(
                        orden.cliente.usuario.id,
                        "Servicio Finalizado 🏁",
                        f"¡Buenas noticias! El servicio para tu {orden.vehiculo.marca} {orden.vehiculo.modelo} ha sido completado.",
                        {"type": "order_completed", "order_id": str(orden.id)}
                    )
            except Exception as e:
                logger.error(f"Error enviando push en finalizar_servicio: {e}")
        
        response_serializer = self.get_serializer(orden)
        return Response({
            'message': 'Servicio finalizado exitosamente',
            'orden': response_serializer.data
        })

# ============================================================================
# VIEWSETS DEL SISTEMA DE POSTULACIONES
# ============================================================================

class SolicitudPublicaViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar solicitudes públicas de servicios
    """
    queryset = SolicitudServicioPublica.objects.all()
    serializer_class = SolicitudServicioPublicaSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.OrderingFilter, filters.SearchFilter]
    ordering_fields = ['fecha_creacion', 'fecha_expiracion', 'total_ofertas']
    ordering = ['-fecha_creacion']
    search_fields = ['descripcion_problema', 'direccion_servicio_texto']
    
    def get_queryset(self):
        """
        Filtra solicitudes según el rol del usuario
        - Cliente: solo sus propias solicitudes
        - Proveedor: solicitudes disponibles para ofertar
        - Admin: todas
        """
        # ✅ Procesar solicitudes expiradas antes de obtener el queryset
        procesar_solicitudes_expiradas()
        
        user = self.request.user
        
        if user.is_staff or user.is_superuser:
            return SolicitudServicioPublica.objects.select_related(
                'cliente', 'cliente__usuario', 'vehiculo', 'direccion_usuario'
            ).prefetch_related('servicios_solicitados', 'proveedores_dirigidos', 'ofertas')
        
        # Cliente viendo sus solicitudes
        if hasattr(user, 'cliente'):
            return SolicitudServicioPublica.objects.filter(
                cliente=user.cliente
            ).select_related(
                'cliente', 'cliente__usuario', 'vehiculo', 'direccion_usuario'
            ).prefetch_related('servicios_solicitados', 'proveedores_dirigidos', 'ofertas')
        
        # Proveedor viendo solicitudes disponibles
        # IMPORTANTE: Las solicitudes dirigidas SOLO deben aparecer para el proveedor seleccionado
        # Las solicitudes globales aparecen para todos los proveedores que atienden la marca
        
        # Obtener marcas atendidas del proveedor
        marcas_atendidas = []
        if hasattr(user, 'taller') and user.taller:
            marcas_atendidas = list(user.taller.marcas_atendidas.values_list('id', flat=True))
        elif hasattr(user, 'mecanico_domicilio') and user.mecanico_domicilio:
            marcas_atendidas = list(user.mecanico_domicilio.marcas_atendidas.values_list('id', flat=True))
        
        # Construir query usando Q objects para evitar problemas al combinar querysets
        from django.db.models import Q
        
        # Iniciar con una query imposible (que no devuelve nada)
        query = Q(pk=None)
        
        # 1. Solicitudes GLOBALES: filtradas por marca del vehículo y no vencidas
        if marcas_atendidas:
            query |= Q(
                estado__in=['publicada', 'con_ofertas'],
                fecha_expiracion__gt=timezone.now(),
                tipo_solicitud='global',
                vehiculo__marca__id__in=marcas_atendidas
            )
        
        # 2. Solicitudes DIRIGIDAS: SOLO para este proveedor específico y no vencidas
        query |= Q(
            proveedores_dirigidos=user,
            estado__in=['publicada', 'con_ofertas'],
            fecha_expiracion__gt=timezone.now(),
            tipo_solicitud='dirigida'
        )
        
        # 3. ✅ INCLUIR solicitudes donde el proveedor ya tiene una oferta (incluso vencidas)
        # Esto permite que el proveedor pueda ver el detalle de solicitudes donde ya ofertó
        # Incluir estados que permiten crear ofertas secundarias: pagada, en_ejecucion
        query |= Q(
            ofertas__proveedor=user,
            ofertas__estado__in=['enviada', 'vista', 'en_chat', 'aceptada', 'pendiente_pago', 'pagada', 'en_ejecucion']
        )
        
        # Excluir la condición imposible y aplicar distinct para evitar duplicados
        queryset = SolicitudServicioPublica.objects.filter(query).exclude(pk=None).distinct()
        
        return queryset.select_related(
            'cliente', 'cliente__usuario', 'vehiculo', 'vehiculo__marca', 'direccion_usuario', 'oferta_seleccionada'
        ).prefetch_related('servicios_solicitados', 'proveedores_dirigidos', 'ofertas', 'rechazos')
    
    def perform_create(self, serializer):
        """Asocia la solicitud con el cliente autenticado"""
        if not hasattr(self.request.user, 'cliente'):
            raise permissions.PermissionDenied("Solo los clientes pueden crear solicitudes")
        
        try:
            # El serializer ya debería tener fecha_expiracion establecida
            # Solo asociamos el cliente
            serializer.save(cliente=self.request.user.cliente)
        except Exception as e:
            logger.error(f"Error creando solicitud pública: {str(e)}", exc_info=True)
            logger.error(f"Datos del serializer: {serializer.validated_data if hasattr(serializer, 'validated_data') else 'No validated_data'}")
            raise
    
    def retrieve(self, request, *args, **kwargs):
        """
        Obtiene el detalle de una solicitud específica
        """
        # ✅ Procesar solicitudes expiradas antes de obtener el detalle
        procesar_solicitudes_expiradas()
        
        return super().retrieve(request, *args, **kwargs)
    
    @action(detail=True, methods=['post'])
    def sugerir_servicios(self, request, pk=None):
        """
        Sugiere servicios basados en el vehículo y descripción del problema
        """
        try:
            solicitud = self.get_object()
            
            # Validar permisos
            if not hasattr(request.user, 'cliente'):
                return Response(
                    {'error': 'Solo los clientes pueden solicitar sugerencias'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            if solicitud.cliente != request.user.cliente:
                return Response(
                    {'error': 'No tienes permiso para esta acción'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Obtener servicios compatibles con el vehículo
            vehiculo = solicitud.vehiculo
            if not vehiculo:
                return Response(
                    {'error': 'La solicitud no tiene un vehículo asociado'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Obtener el modelo del vehículo
            modelo = vehiculo.modelo
            if not modelo:
                return Response(
                    {'error': 'El vehículo no tiene un modelo asociado'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Buscar servicios compatibles con el modelo del vehículo
            # El modelo Servicio tiene modelos_compatibles, no marcas_compatibles
            servicios_compatibles = Servicio.objects.filter(
                modelos_compatibles=modelo
            ).distinct()
            
            # Si no hay servicios compatibles por modelo, obtener todos los servicios disponibles
            if not servicios_compatibles.exists():
                servicios_compatibles = Servicio.objects.all()[:50]
            
            # Filtrar por palabras clave en la descripción (búsqueda simple)
            descripcion_problema = solicitud.descripcion_problema or ''
            descripcion_lower = descripcion_problema.lower()
            palabras_clave = [palabra for palabra in descripcion_lower.split() if len(palabra) > 2]  # Filtrar palabras muy cortas
            
            servicios_sugeridos = []
            
            # Si hay palabras clave, filtrar por ellas
            if palabras_clave:
                for servicio in servicios_compatibles:
                    # Buscar coincidencias en nombre o descripción del servicio
                    nombre_lower = servicio.nombre.lower()
                    descripcion_servicio = (servicio.descripcion or '').lower()
                    
                    # Puntuación simple basada en coincidencias
                    puntuacion = 0
                    for palabra in palabras_clave:
                        if palabra in nombre_lower or palabra in descripcion_servicio:
                            puntuacion += 1
                    
                    if puntuacion > 0:
                        servicios_sugeridos.append({
                            'servicio': ServicioSerializer(servicio, context={'request': request}).data,
                            'relevancia': puntuacion
                        })
            else:
                # Si no hay palabras clave, devolver todos los servicios compatibles
                for servicio in servicios_compatibles[:20]:
                    servicios_sugeridos.append({
                        'servicio': ServicioSerializer(servicio, context={'request': request}).data,
                        'relevancia': 1
                    })
            
            # Ordenar por relevancia
            servicios_sugeridos.sort(key=lambda x: x['relevancia'], reverse=True)
            
            return Response({
                'servicios_sugeridos': [s['servicio'] for s in servicios_sugeridos[:20]],
                'total_encontrados': len(servicios_sugeridos)
            })
        except SolicitudServicioPublica.DoesNotExist:
            return Response(
                {'error': 'Solicitud no encontrada'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error en sugerir_servicios: {str(e)}", exc_info=True)
            return Response(
                {'error': f'Error al sugerir servicios: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def agregar_servicios(self, request, pk=None):
        """
        Agrega servicios seleccionados a la solicitud
        """
        solicitud = self.get_object()
        
        if solicitud.cliente != request.user.cliente:
            return Response(
                {'error': 'No tienes permiso para esta acción'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        servicios_ids = request.data.get('servicios', [])
        if not servicios_ids:
            return Response(
                {'error': 'Debes proporcionar al menos un servicio'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        servicios = Servicio.objects.filter(id__in=servicios_ids)
        if servicios.count() != len(servicios_ids):
            return Response(
                {'error': 'Algunos servicios no existen'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        solicitud.servicios_solicitados.set(servicios)
        # No cambiar el estado, el estado se mantiene como 'creada' hasta que se publique
        solicitud.save()
        
        serializer = self.get_serializer(solicitud)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def publicar(self, request, pk=None):
        """
        Publica la solicitud para que los proveedores puedan ofertar
        """
        solicitud = self.get_object()
        
        if solicitud.cliente != request.user.cliente:
            return Response(
                {'error': 'No tienes permiso para esta acción'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if solicitud.estado not in ['creada', 'seleccionando_servicios']:
            return Response(
                {'error': f'No se puede publicar una solicitud en estado: {solicitud.estado}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not solicitud.servicios_solicitados.exists():
            return Response(
                {'error': 'Debes seleccionar al menos un servicio antes de publicar'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Publicar solicitud
        solicitud.estado = 'publicada'
        solicitud.fecha_publicacion = timezone.now()
        solicitud.save()
        
        # Notificar a proveedores elegibles vía WebSocket
        self._publicar_solicitud(solicitud)
        
        serializer = self.get_serializer(solicitud)
        return Response(serializer.data)
    
    def _obtener_proveedores_para_notificar(self, solicitud):
        """
        Obtiene los proveedores que deben ser notificados sobre una solicitud.
        Solo incluye proveedores que:
        1. Tienen inscrita la marca del vehículo (OBLIGATORIO)
        2. Ofrecen el servicio solicitado (compatibilidad con servicio)
        3. Están verificados y activos
        
        Args:
            solicitud: Instancia de SolicitudServicioPublica
        
        Returns:
            QuerySet: Proveedores que cumplen los criterios
        """
        from mecanimovilapp.apps.servicios.models import OfertaServicio
        
        marca_vehiculo = solicitud.vehiculo.marca
        if not marca_vehiculo:
            logger.warning(f"Solicitud {solicitud.id} no tiene marca de vehículo")
            return Usuario.objects.none()
        
        # Base: Proveedores que tienen la marca en marcas_atendidas (OBLIGATORIO)
        proveedores_base = Usuario.objects.filter(
            Q(taller__marcas_atendidas=marca_vehiculo) |
            Q(mecanico_domicilio__marcas_atendidas=marca_vehiculo)
        ).filter(
            Q(taller__verificado=True, taller__activo=True) |
            Q(mecanico_domicilio__verificado=True, mecanico_domicilio__activo=True)
        ).select_related('taller', 'mecanico_domicilio').distinct()
        
        # Si hay servicios solicitados, filtrar también por compatibilidad de servicio
        servicios_solicitados = solicitud.servicios_solicitados.all()
        
        if servicios_solicitados.exists():
            # Obtener IDs de proveedores que tienen ofertas activas para estos servicios
            # y que atienden la marca del vehículo
            proveedores_con_ofertas = OfertaServicio.objects.filter(
                servicio__in=servicios_solicitados,
                disponible=True
            ).filter(
                # Filtrar por marca específica O sin marca específica (NULL)
                Q(marca_vehiculo_seleccionada=marca_vehiculo) | Q(marca_vehiculo_seleccionada__isnull=True)
            ).filter(
                # Filtrar por tipo de proveedor y que estén verificados
                Q(tipo_proveedor='taller', taller__marcas_atendidas=marca_vehiculo, taller__verificado=True, taller__activo=True) |
                Q(tipo_proveedor='mecanico', mecanico__marcas_atendidas=marca_vehiculo, mecanico__verificado=True, mecanico__activo=True)
            ).values_list('taller__usuario', 'mecanico__usuario').distinct()
            
            # Obtener IDs únicos de proveedores
            proveedor_ids = set()
            for taller_id, mecanico_id in proveedores_con_ofertas:
                if taller_id:
                    proveedor_ids.add(taller_id)
                if mecanico_id:
                    proveedor_ids.add(mecanico_id)
            
            # Filtrar proveedores base que tienen ofertas para los servicios
            if proveedor_ids:
                proveedores_base = proveedores_base.filter(id__in=proveedor_ids)
            else:
                # Si no hay proveedores con ofertas específicas, retornar vacío
                logger.info(f"No se encontraron proveedores con ofertas para servicios solicitados en solicitud {solicitud.id}")
                return Usuario.objects.none()
        
        logger.info(
            f"Proveedores encontrados para notificar solicitud {solicitud.id}: "
            f"{proveedores_base.count()} proveedores (marca: {marca_vehiculo.nombre})"
        )
        
        return proveedores_base
    
    def _publicar_solicitud(self, solicitud):
        """
        Notifica a proveedores elegibles sobre la nueva solicitud.
        Solo notifica a proveedores especialistas en la marca del vehículo.
        """
        try:
            channel_layer = get_channel_layer()
            
            # Determinar proveedores a notificar
            if solicitud.tipo_solicitud == 'dirigida':
                # Solo a proveedores específicos
                proveedores = solicitud.proveedores_dirigidos.all()
            else:
                # ✅ NUEVO: Usar función de filtrado por marca y servicio
                proveedores = self._obtener_proveedores_para_notificar(solicitud)
            
            if not proveedores.exists():
                logger.warning(
                    f"No se encontraron proveedores elegibles para notificar solicitud {solicitud.id}. "
                    f"Marca: {solicitud.vehiculo.marca.nombre if solicitud.vehiculo.marca else 'N/A'}"
                )
                return
            
            # Enviar notificación a cada proveedor
            for proveedor in proveedores:
                async_to_sync(channel_layer.group_send)(
                    f"proveedor_{proveedor.id}",
                    {
                        'type': 'nueva_solicitud',
                        'solicitud_id': str(solicitud.id),
                        'vehiculo': f"{solicitud.vehiculo.marca} {solicitud.vehiculo.modelo}",
                        'descripcion': solicitud.descripcion_problema[:100],
                        'urgencia': solicitud.urgencia,
                        'fecha_expiracion': solicitud.fecha_expiracion.isoformat()
                    }
                )
            
            logger.info(f"Notificaciones enviadas a {proveedores.count()} proveedores para solicitud {solicitud.id}")
        except Exception as e:
            logger.error(f"Error enviando notificación WebSocket: {e}", exc_info=True)
    
    @action(detail=True, methods=['post'])
    def rechazar(self, request, pk=None):
        """
        Permite a un proveedor rechazar una solicitud con un motivo específico
        """
        from .serializers import RechazoSolicitudSerializer
        from .models import RechazoSolicitud
        
        solicitud = self.get_object()
        user = request.user
        
        # Verificar que sea proveedor
        if not (hasattr(user, 'taller') or hasattr(user, 'mecanico_domicilio')):
            return Response(
                {'error': 'Solo los proveedores pueden rechazar solicitudes'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Verificar que la solicitud esté disponible
        if solicitud.estado not in ['publicada', 'con_ofertas']:
            return Response(
                {'error': 'Esta solicitud ya no está disponible para rechazo'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Preparar datos para el serializer
        data = request.data.copy()
        data['solicitud'] = solicitud.id
        
        # Crear el rechazo usando el serializer
        serializer = RechazoSolicitudSerializer(
            data=data,
            context={'request': request}
        )
        
        if serializer.is_valid():
            # Determinar tipo de proveedor
            tipo_proveedor = 'taller' if hasattr(user, 'taller') else 'mecanico'
            
            # Guardar el rechazo
            rechazo = serializer.save(
                solicitud=solicitud,
                proveedor=user,
                tipo_proveedor=tipo_proveedor
            )
            
            solicitud.total_rechazos = solicitud.rechazos.count()
            solicitud.save(update_fields=['total_rechazos'])
            
            # Notificar vía Push al cliente (solo si es una solicitud dirigida)
            if solicitud.tipo_solicitud == 'dirigida':
                try:
                    if solicitud.cliente and solicitud.cliente.usuario:
                        send_expo_push_notification.delay(
                            solicitud.cliente.usuario.id,
                            "Solicitud rechazada",
                            f"Un proveedor ha rechazado tu solicitud dirigida. Revisa tus opciones en la App.",
                            {"type": "solicitud_rechazada", "solicitud_id": str(solicitud.id)}
                        )
                except Exception as e:
                    logger.error(f"Error enviando push en rechazar (SolicitudPublica): {e}")
            
            # Notificar al cliente
            self._notificar_rechazo(solicitud, rechazo)
            
            logger.info(f"Rechazo registrado - Solicitud: {solicitud.id}, Proveedor: {user.id}, Motivo: {rechazo.motivo}")
            
            return Response(
                {
                    'message': 'Solicitud rechazada exitosamente',
                    'rechazo': RechazoSolicitudSerializer(rechazo, context={'request': request}).data
                },
                status=status.HTTP_201_CREATED
            )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def reenviar(self, request, pk=None):
        """
        Permite al cliente reenviar una solicitud que no tiene ofertas pero tiene rechazos
        """
        solicitud = self.get_object()
        user = request.user
        
        # Verificar que sea el cliente dueño
        if not hasattr(user, 'cliente') or solicitud.cliente != user.cliente:
            return Response(
                {'error': 'No tienes permiso para reenviar esta solicitud'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Verificar que pueda reenviar
        if not solicitud.puede_reenviar():
            return Response(
                {
                    'error': 'Esta solicitud no puede ser reenviada',
                    'motivo': 'Solo se pueden reenviar solicitudes sin ofertas que tengan al menos un rechazo'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Resetear la solicitud
        solicitud.estado = 'publicada'
        solicitud.fecha_expiracion = timezone.now() + timedelta(hours=48)
        solicitud.fecha_publicacion = timezone.now()
        solicitud.total_rechazos = 0
        solicitud.save(update_fields=['estado', 'fecha_expiracion', 'fecha_publicacion', 'total_rechazos'])
        
        # Eliminar rechazos anteriores
        solicitud.rechazos.all().delete()
        
        # Publicar nuevamente
        self._publicar_solicitud(solicitud)
        
        logger.info(f"Solicitud reenviada - Solicitud: {solicitud.id}, Cliente: {user.id}")
        
        serializer = self.get_serializer(solicitud)
        return Response({
            'message': 'Solicitud reenviada exitosamente. Expira en 48 horas.',
            'solicitud': serializer.data
        })
    
    def _notificar_rechazo(self, solicitud, rechazo):
        """
        Notifica al cliente sobre el rechazo de un proveedor
        """
        try:
            channel_layer = get_channel_layer()
            
            # Determinar nombre del proveedor
            if rechazo.tipo_proveedor == 'taller' and hasattr(rechazo.proveedor, 'taller'):
                proveedor_nombre = rechazo.proveedor.taller.nombre
            elif rechazo.tipo_proveedor == 'mecanico' and hasattr(rechazo.proveedor, 'mecanico_domicilio'):
                proveedor_nombre = f"{rechazo.proveedor.first_name} {rechazo.proveedor.last_name}"
            else:
                proveedor_nombre = rechazo.proveedor.get_full_name()
            
            # Enviar notificación al cliente
            async_to_sync(channel_layer.group_send)(
                f"cliente_{solicitud.cliente.usuario.id}",
                {
                    'type': 'rechazo_solicitud',
                    'solicitud_id': str(solicitud.id),
                    'proveedor_nombre': proveedor_nombre,
                    'motivo': rechazo.get_motivo_display(),
                    'detalle': rechazo.detalle_motivo
                }
            )
            logger.info(f"Notificación de rechazo enviada - Cliente: {solicitud.cliente.usuario.id}")
        except Exception as e:
            logger.error(f"Error enviando notificación de rechazo: {e}")
    
    @action(detail=True, methods=['post'])
    def seleccionar_oferta(self, request, pk=None):
        """
        Selecciona una oferta y crea una SolicitudServicio tradicional
        """
        try:
            solicitud = self.get_object()
            logger.info(f"Seleccionando oferta - Solicitud: {solicitud.id}, Usuario: {request.user.id}")
            
            if solicitud.cliente != request.user.cliente:
                logger.warning(f"Intento de seleccionar oferta sin permiso - Solicitud: {solicitud.id}, Usuario: {request.user.id}")
                return Response(
                    {'error': 'No tienes permiso para esta acción'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            oferta_id = request.data.get('oferta_id')
            if not oferta_id:
                logger.error("No se proporcionó oferta_id en la solicitud")
                return Response(
                    {'error': 'Debes proporcionar oferta_id'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            logger.info(f"Buscando oferta: {oferta_id} para solicitud: {solicitud.id}")
            try:
                oferta = OfertaProveedor.objects.select_related(
                    'solicitud', 'proveedor', 'solicitud__cliente', 'solicitud__vehiculo',
                    'proveedor__taller', 'proveedor__mecanico_domicilio',
                    'solicitud__direccion_usuario', 'oferta_original'
                ).prefetch_related('detalles_servicios__servicio').get(id=oferta_id, solicitud=solicitud)
                logger.info(f"Oferta encontrada: {oferta.id}, Proveedor: {oferta.proveedor.id}, Tipo: {oferta.tipo_proveedor}, Es Secundaria: {oferta.es_oferta_secundaria}")
            except OfertaProveedor.DoesNotExist:
                logger.error(f"Oferta no encontrada: {oferta_id} para solicitud: {solicitud.id}")
                return Response(
                    {'error': 'Oferta no encontrada'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Si es una oferta secundaria, usar lógica diferente
            if oferta.es_oferta_secundaria:
                logger.info(f"Procesando oferta secundaria: {oferta.id}")
                # Para ofertas secundarias, solo marcamos como aceptada sin cambiar el estado de la solicitud
                # ni rechazar otras ofertas
                if oferta.estado not in ['enviada', 'vista', 'en_chat']:
                    logger.warning(f"Oferta secundaria {oferta.id} ya está en estado: {oferta.estado}")
                    return Response(
                        {'error': f'Esta oferta secundaria ya está en estado: {oferta.estado}'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                # Marcar oferta secundaria como aceptada
                oferta.estado = 'aceptada'
                oferta.fecha_respuesta_cliente = timezone.now()
                oferta.save(update_fields=['estado', 'fecha_respuesta_cliente'])
                
                logger.info(f"Oferta secundaria {oferta.id} marcada como aceptada")
                
                # Notificar al proveedor
                try:
                    channel_layer = get_channel_layer()
                    if channel_layer:
                        async_to_sync(channel_layer.group_send)(
                            f"proveedor_{oferta.proveedor.id}",
                            {
                                'type': 'oferta_secundaria_aceptada',
                                'oferta_id': str(oferta.id),
                                'solicitud_id': str(solicitud.id),
                                'mensaje': '¡Tu oferta secundaria fue aceptada! El cliente procederá con el pago.',
                                'estado_oferta': 'aceptada',
                                'monto_total': float(oferta.precio_total_ofrecido),
                                'timestamp': timezone.now().isoformat()
                            }
                        )
                        logger.info(f"Notificación WebSocket 'oferta_secundaria_aceptada' enviada al proveedor: {oferta.proveedor.id}")
                        
                        # NUEVO: Notificación vía Push al proveedor
                        send_expo_push_notification.delay(
                            oferta.proveedor.id,
                            "¡Oferta secundaria aceptada! ✨",
                            f"El cliente ha aceptado tu oferta adicional por ${oferta.precio_total_ofrecido:,.0f}",
                            {"type": "offer_accepted", "solicitud_id": str(solicitud.id), "oferta_id": str(oferta.id)}
                        )
                except Exception as e:
                    logger.error(f"Error enviando notificación WebSocket: {e}", exc_info=True)
                
                # Retornar respuesta indicando que es una oferta secundaria
                return Response({
                    'message': 'Oferta secundaria aceptada exitosamente',
                    'es_oferta_secundaria': True,
                    'oferta_id': str(oferta.id),
                    'solicitud_id': str(solicitud.id),
                    'mensaje': 'Para pagar esta oferta secundaria, use el endpoint de pago de ofertas secundarias.'
                })
            
            # Lógica para ofertas originales (sin cambios)
            if solicitud.estado in ['adjudicada', 'cancelada', 'expirada']:
                logger.warning(f"No se puede seleccionar oferta - Solicitud en estado: {solicitud.estado}")
                mensaje_error = {
                    'adjudicada': 'Esta solicitud ya tiene una oferta aceptada. No se pueden aceptar más ofertas.',
                    'cancelada': 'Esta solicitud ha sido cancelada. No se pueden aceptar ofertas.',
                    'expirada': 'Esta solicitud ha expirado. No se pueden aceptar ofertas.'
                }.get(solicitud.estado, f'No se puede seleccionar oferta en estado: {solicitud.estado}')
                return Response(
                    {'error': mensaje_error},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validar que el proveedor tenga taller o mecánico asociado
            if oferta.tipo_proveedor == 'taller':
                if not hasattr(oferta.proveedor, 'taller') or not oferta.proveedor.taller:
                    logger.error(f"Proveedor {oferta.proveedor.id} no tiene taller asociado")
                    return Response(
                        {'error': 'El proveedor no tiene un taller asociado'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                taller = oferta.proveedor.taller
                mecanico = None
            else:
                if not hasattr(oferta.proveedor, 'mecanico_domicilio') or not oferta.proveedor.mecanico_domicilio:
                    logger.error(f"Proveedor {oferta.proveedor.id} no tiene mecánico asociado")
                    return Response(
                        {'error': 'El proveedor no tiene un mecánico asociado'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                mecanico = oferta.proveedor.mecanico_domicilio
                taller = None
            
            logger.info(f"Proveedor validado - Taller: {taller.id if taller else None}, Mecánico: {mecanico.id if mecanico else None}")
            
            # Validar que haya detalles de servicios
            detalles_servicios = list(oferta.detalles_servicios.all())
            if not detalles_servicios:
                logger.error(f"Oferta {oferta.id} no tiene detalles de servicios")
                return Response(
                    {'error': 'La oferta no tiene servicios asociados'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            logger.info(f"Oferta tiene {len(detalles_servicios)} servicios")
            
            # ✅ VALIDAR CRÉDITOS ANTES DE ADJUDICAR (solo para ofertas originales)
            if not oferta.es_oferta_secundaria:
                try:
                    from mecanimovilapp.apps.suscripciones.creditos_services import (
                        validar_creditos_suficientes,
                        obtener_creditos_servicio
                    )
                    from mecanimovilapp.apps.suscripciones.creditos_services import puede_adjudicar as puede_adjudicar_creditos
                    
                    # Validar que puede adjudicar (anti-gaming)
                    puede, mensaje_anti_gaming = puede_adjudicar_creditos(oferta.proveedor)
                    if not puede:
                        logger.warning(f"Proveedor {oferta.proveedor.id} no puede adjudicar: {mensaje_anti_gaming}")
                        return Response(
                            {'error': mensaje_anti_gaming},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    
                    # Obtener servicio principal para validar créditos
                    if detalles_servicios:
                        servicio_principal = detalles_servicios[0].servicio
                        puede_adjudicar, mensaje, creditos_necesarios = validar_creditos_suficientes(
                            oferta.proveedor,
                            servicio_principal
                        )
                        
                        if not puede_adjudicar:
                            logger.warning(
                                f"Proveedor {oferta.proveedor.id} no tiene créditos suficientes: {mensaje}"
                            )
                            return Response(
                                {
                                    'error': mensaje,
                                    'creditos_necesarios': creditos_necesarios,
                                    'creditos_disponibles': None  # Se puede obtener del servicio si es necesario
                                },
                                status=status.HTTP_400_BAD_REQUEST
                            )
                        
                        logger.info(
                            f"Validación de créditos OK para proveedor {oferta.proveedor.id}: "
                            f"necesita {creditos_necesarios} créditos"
                        )
                except ImportError:
                    logger.warning("Módulo de créditos no disponible, omitiendo validación")
                except Exception as e:
                    logger.error(f"Error validando créditos: {e}", exc_info=True)
                    # No bloquear adjudicación si hay error en validación de créditos
                    # (por compatibilidad durante transición)
            
            # Variable para almacenar el ID del carrito fuera de la transacción
            carrito_id = None
            
            with transaction.atomic():
                # Marcar oferta como aceptada
                logger.info("Marcando oferta como aceptada")
                oferta.estado = 'aceptada'
                oferta.fecha_respuesta_cliente = timezone.now()
                oferta.save(update_fields=['estado', 'fecha_respuesta_cliente'])
                
                # Actualizar solicitud
                logger.info("Actualizando solicitud")
                solicitud.estado = 'adjudicada'
                solicitud.oferta_seleccionada = oferta
                
                # ✅ Establecer fecha_limite_pago = fecha del servicio (fecha_disponible de la oferta)
                if oferta.fecha_disponible:
                    from datetime import datetime
                    hora_disponible = oferta.hora_disponible or timezone.now().time()
                    fecha_limite = timezone.make_aware(
                        datetime.combine(oferta.fecha_disponible, hora_disponible)
                    )
                    solicitud.fecha_limite_pago = fecha_limite
                    logger.info(f"Fecha límite de pago establecida: {fecha_limite} (fecha del servicio)")
                
                solicitud.save(update_fields=['estado', 'oferta_seleccionada', 'fecha_limite_pago'])
                
                # Rechazar otras ofertas ORIGINALES (no afectar ofertas secundarias)
                logger.info("Rechazando otras ofertas originales")
                ofertas_rechazadas = OfertaProveedor.objects.filter(
                    solicitud=solicitud,
                    estado__in=['enviada', 'vista', 'en_chat'],
                    es_oferta_secundaria=False  # Solo rechazar ofertas originales
                ).exclude(id=oferta.id).update(
                    estado='rechazada',
                    fecha_respuesta_cliente=timezone.now()
                )
                logger.info(f"Rechazadas {ofertas_rechazadas} ofertas originales")
                
                # ✅ CONSUMIR CRÉDITOS AL ADJUDICAR (solo para ofertas originales)
                # Se consumen inmediatamente cuando el cliente acepta la oferta
                # 
                # ✅ POLÍTICA DE CRÉDITOS:
                # - Los créditos se consumen SOLO cuando la oferta es adjudicada (cliente acepta)
                # - Los créditos NO se consumen cuando se envía la oferta
                # - Los créditos NO se devuelven NUNCA una vez adjudicados (previene gaming)
                # - Esto es justo para el proveedor y previene que clientes cancelen después de adjudicar
                if not oferta.es_oferta_secundaria and detalles_servicios:
                    try:
                        from mecanimovilapp.apps.suscripciones.creditos_services import (
                            consumir_creditos_adjudicacion
                        )
                        
                        servicio_principal = detalles_servicios[0].servicio
                        
                        logger.info(
                            f"🔄 Intentando consumir créditos al adjudicar oferta {oferta.id} - "
                            f"Proveedor: {oferta.proveedor.id}, Servicio: {servicio_principal.nombre}"
                        )
                        
                        consumo = consumir_creditos_adjudicacion(
                            proveedor=oferta.proveedor,
                            oferta=oferta,
                            servicio=servicio_principal
                        )
                        
                        logger.info(
                            f"✅ Créditos consumidos exitosamente al adjudicar: {consumo.creditos_consumidos} créditos "
                            f"para oferta {oferta.id}, servicio {servicio_principal.nombre}, "
                            f"proveedor {oferta.proveedor.id} (ID de consumo: {consumo.id})"
                        )
                    except ImportError as e:
                        logger.error(f"❌ Módulo de créditos no disponible: {e}", exc_info=True)
                        # No bloquear adjudicación si el módulo no está disponible
                        # pero loggear el error para debugging
                    except Exception as e:
                        logger.error(
                            f"❌ Error consumiendo créditos al adjudicar oferta {oferta.id}: {e}",
                            exc_info=True
                        )
                        # Rollback de la transacción si falla el consumo de créditos
                        raise
                else:
                    if oferta.es_oferta_secundaria:
                        logger.info(f"ℹ️ Oferta {oferta.id} es secundaria, no se consumen créditos")
                    elif not detalles_servicios:
                        logger.warning(f"⚠️ Oferta {oferta.id} no tiene detalles_servicios, no se pueden consumir créditos")
                
                # Obtener o crear carrito para el cliente y vehículo
                logger.info("Obteniendo o creando carrito para cliente y vehículo")
                try:
                    # Obtener o crear carrito (CarritoAgendamiento ya está importado al inicio del archivo)
                    carrito = obtener_o_crear_carrito(solicitud.cliente, solicitud.vehiculo)
                    logger.info(f"Carrito obtenido/creado: {carrito.id}")
                    
                    # Copiar notas de la solicitud al carrito (si existen y el carrito no tiene notas)
                    if solicitud.descripcion_problema and not carrito.notas:
                        carrito.notas = solicitud.descripcion_problema
                        carrito.fecha_programada = oferta.fecha_disponible
                        carrito.hora_programada = oferta.hora_disponible
                        carrito.save(update_fields=['notas', 'fecha_programada', 'hora_programada'])
                        logger.info(f"Notas copiadas al carrito: {carrito.id}")
                except Exception as e:
                    logger.error(f"Error obteniendo/creando carrito: {e}", exc_info=True)
                    return Response(
                        {'error': f'Error al obtener o crear el carrito: {str(e)}'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )
                
                # Agregar servicios al carrito
                logger.info("Agregando servicios al carrito")
                from mecanimovilapp.apps.servicios.models import OfertaServicio
                
                # Obtener tipo_proveedor correcto para usar en OfertaServicio
                # CRÍTICO: Usar el tipo_proveedor de la oferta directamente, no inferirlo
                tipo_proveedor_servicio = oferta.tipo_proveedor
                logger.info(f"Tipo de proveedor para OfertaServicio: {tipo_proveedor_servicio} (de oferta: {oferta.id})")
                
                # Validar que tipo_proveedor_servicio coincida con taller/mecanico
                if tipo_proveedor_servicio == 'taller' and not taller:
                    logger.error(f"Inconsistencia: tipo_proveedor='taller' pero taller es None")
                    raise ValueError("Inconsistencia: tipo_proveedor es 'taller' pero no hay taller asociado")
                elif tipo_proveedor_servicio == 'mecanico' and not mecanico:
                    logger.error(f"Inconsistencia: tipo_proveedor='mecanico' pero mecanico es None")
                    raise ValueError("Inconsistencia: tipo_proveedor es 'mecanico' pero no hay mecánico asociado")
                elif tipo_proveedor_servicio not in ['taller', 'mecanico']:
                    logger.error(f"Tipo de proveedor inválido: {tipo_proveedor_servicio}")
                    raise ValueError(f"Tipo de proveedor inválido: {tipo_proveedor_servicio}")
                
                for detalle in detalles_servicios:
                    try:
                        logger.info(f"Procesando detalle de servicio: {detalle.servicio.id}, Precio: {detalle.precio_servicio}")
                        
                        # Buscar o crear OfertaServicio correspondiente
                        # CRÍTICO: Incluir tipo_proveedor en la búsqueda para evitar ambigüedades
                        try:
                            oferta_servicio = OfertaServicio.objects.get(
                                servicio=detalle.servicio,
                                tipo_proveedor=tipo_proveedor_servicio,
                                taller=taller,
                                mecanico=mecanico
                            )
                            logger.info(f"OfertaServicio encontrada: {oferta_servicio.id}")
                        except OfertaServicio.DoesNotExist:
                            # Crear OfertaServicio temporal
                            logger.info("Creando OfertaServicio temporal")
                            
                            # IMPORTANTE: El modelo OfertaServicio tiene un método save() que llama a calcular_precios()
                            # calcular_precios() calcula precios basándose en costo_mano_de_obra_sin_iva y costo_repuestos_sin_iva
                            # El precio que viene de detalle.precio_servicio es el precio final que el proveedor ofreció
                            # Necesitamos trabajar hacia atrás para calcular los costos sin IVA
                            
                            from decimal import Decimal
                            precio_ofrecido = Decimal(str(detalle.precio_servicio))
                            
                            # El precio_ofrecido es el precio final que el cliente pagará (con IVA)
                            # Necesitamos calcular los costos sin IVA que resulten en ese precio
                            # Fórmula: precio_final = (costo_mano_de_obra + costo_repuestos) * 1.19
                            # Por lo tanto: costo_total_sin_iva = precio_ofrecido / 1.19
                            IVA_RATE = Decimal('0.19')
                            costo_total_sin_iva = precio_ofrecido / (Decimal('1') + IVA_RATE)
                            
                            # Dividir el costo total entre mano de obra y repuestos
                            if oferta.incluye_repuestos:
                                # Si incluye repuestos, dividir aproximadamente 70% mano de obra, 30% repuestos
                                costo_mano_de_obra = costo_total_sin_iva * Decimal('0.7')
                                costo_repuestos = costo_total_sin_iva * Decimal('0.3')
                                tipo_servicio = 'con_repuestos'
                            else:
                                # Si no incluye repuestos, todo es mano de obra
                                costo_mano_de_obra = costo_total_sin_iva
                                costo_repuestos = Decimal('0')
                                tipo_servicio = 'sin_repuestos'
                            
                            logger.info(f"Creando OfertaServicio: tipo_proveedor={tipo_proveedor_servicio}, taller={taller.id if taller else None}, mecanico={mecanico.id if mecanico else None}")
                            logger.info(f"  Precio ofrecido: {precio_ofrecido}, Costo total sin IVA: {costo_total_sin_iva}")
                            logger.info(f"  Costo mano de obra: {costo_mano_de_obra}, Costo repuestos: {costo_repuestos}, Tipo: {tipo_servicio}")
                            
                            try:
                                # CRÍTICO: Validar que tipo_proveedor coincida con taller/mecanico ANTES de crear
                                if tipo_proveedor_servicio == 'taller':
                                    if not taller:
                                        raise ValueError(f"Inconsistencia: tipo_proveedor='taller' pero taller es None")
                                    if mecanico:
                                        raise ValueError(f"Inconsistencia: tipo_proveedor='taller' pero mecanico no es None")
                                elif tipo_proveedor_servicio == 'mecanico':
                                    if not mecanico:
                                        raise ValueError(f"Inconsistencia: tipo_proveedor='mecanico' pero mecanico es None")
                                    if taller:
                                        raise ValueError(f"Inconsistencia: tipo_proveedor='mecanico' pero taller no es None")
                                else:
                                    raise ValueError(f"Tipo de proveedor inválido: {tipo_proveedor_servicio}")
                                
                                # Crear OfertaServicio con los costos correctos
                                # CRÍTICO: Asegurar que taller y mecanico se establezcan correctamente según tipo_proveedor
                                # El modelo valida que tipo_proveedor=='taller' implica taller!=None y mecanico==None
                                # Y que tipo_proveedor=='mecanico' implica mecanico!=None y taller==None
                                
                                taller_final = taller if tipo_proveedor_servicio == 'taller' else None
                                mecanico_final = mecanico if tipo_proveedor_servicio == 'mecanico' else None
                                
                                logger.info(f"Valores finales para OfertaServicio:")
                                logger.info(f"  tipo_proveedor: '{tipo_proveedor_servicio}' (type: {type(tipo_proveedor_servicio)})")
                                logger.info(f"  taller: {taller_final.id if taller_final else None}")
                                logger.info(f"  mecanico: {mecanico_final.id if mecanico_final else None}")
                                logger.info(f"  servicio: {detalle.servicio.id}")
                                logger.info(f"  costo_mano_de_obra: {costo_mano_de_obra}, costo_repuestos: {costo_repuestos}")
                                
                                # Crear instancia sin guardar primero para validar
                                oferta_servicio = OfertaServicio(
                                    servicio=detalle.servicio,
                                    tipo_proveedor=str(tipo_proveedor_servicio).strip(),  # Asegurar que sea string y sin espacios
                                    taller=taller_final,
                                    mecanico=mecanico_final,
                                    costo_mano_de_obra_sin_iva=costo_mano_de_obra,
                                    costo_repuestos_sin_iva=costo_repuestos,
                                    tipo_servicio=tipo_servicio
                                )
                                
                                # Llamar a clean() manualmente para validar antes de guardar
                                logger.info(f"Validando OfertaServicio antes de guardar...")
                                try:
                                    oferta_servicio.clean()
                                    logger.info(f"Validación exitosa")
                                except ValidationError as ve:
                                    logger.error(f"Error de validación en clean(): {ve}", exc_info=True)
                                    logger.error(f"Estado del objeto: tipo_proveedor='{oferta_servicio.tipo_proveedor}', taller={oferta_servicio.taller}, mecanico={oferta_servicio.mecanico}")
                                    raise
                                
                                # Guardar (calcular_precios() se ejecutará automáticamente en save())
                                logger.info(f"Guardando OfertaServicio...")
                                try:
                                    oferta_servicio.save()
                                except Exception as e:
                                    logger.error(f"Error en save() de OfertaServicio: {e}", exc_info=True)
                                    raise
                                
                                logger.info(f"OfertaServicio creada exitosamente: {oferta_servicio.id}")
                                logger.info(f"  Precios calculados: con_repuestos={oferta_servicio.precio_con_repuestos}, sin_repuestos={oferta_servicio.precio_sin_repuestos}")
                                logger.info(f"  Precio publicado cliente: {oferta_servicio.precio_publicado_cliente}")
                            except ValidationError as ve:
                                logger.error(f"Error de validación creando OfertaServicio: {ve}", exc_info=True)
                                logger.error(f"Datos intentados: tipo_proveedor={tipo_proveedor_servicio}, taller={taller.id if taller else None}, mecanico={mecanico.id if mecanico else None}")
                                logger.error(f"  servicio={detalle.servicio.id}, costo_mano_de_obra={costo_mano_de_obra}, costo_repuestos={costo_repuestos}")
                                raise
                            except Exception as e:
                                logger.error(f"Error creando OfertaServicio: {e}", exc_info=True)
                                logger.error(f"Datos intentados: tipo_proveedor={tipo_proveedor_servicio}, taller={taller}, mecanico={mecanico}")
                                logger.error(f"  servicio={detalle.servicio.id}, costo_mano_de_obra={costo_mano_de_obra}, costo_repuestos={costo_repuestos}")
                                raise
                        
                        # Crear línea de servicio
                        # Usar el precio calculado de oferta_servicio (después de calcular_precios())
                        # Si incluye_repuestos, usar precio_con_repuestos, sino precio_sin_repuestos
                        precio_unitario_linea = oferta_servicio.precio_con_repuestos if oferta.incluye_repuestos else oferta_servicio.precio_sin_repuestos
                        
                        logger.info(f"Agregando servicio al carrito: precio_unitario={precio_unitario_linea}, con_repuestos={oferta.incluye_repuestos}")
                        
                        # Crear o actualizar item del carrito
                        item_carrito, created = ItemCarritoAgendamiento.objects.get_or_create(
                            carrito=carrito,
                            oferta_servicio=oferta_servicio,
                            defaults={
                                'con_repuestos': oferta.incluye_repuestos,
                                'cantidad': 1,
                                'fecha_servicio': oferta.fecha_disponible,
                                'hora_servicio': oferta.hora_disponible,
                            }
                        )
                        
                        if not created:
                            # Si el item ya existe, actualizar información
                            item_carrito.con_repuestos = oferta.incluye_repuestos
                            item_carrito.fecha_servicio = oferta.fecha_disponible
                            item_carrito.hora_servicio = oferta.hora_disponible
                            item_carrito.save(update_fields=['con_repuestos', 'fecha_servicio', 'hora_servicio'])
                            logger.info(f"Item del carrito actualizado: {item_carrito.id}")
                        else:
                            logger.info(f"Item del carrito creado: {item_carrito.id}, precio_estimado={item_carrito.precio_estimado}")
                    except Exception as e:
                        logger.error(f"Error agregando servicio al carrito para {detalle.servicio.id}: {e}", exc_info=True)
                        # Re-lanzar la excepción para que se revierta la transacción
                        raise
                
                logger.info(f"Total de servicios agregados al carrito: {len(detalles_servicios)}")
                
                # Crear mensaje inicial en el chat
                logger.info("Creando mensaje inicial en el chat")
                try:
                    chat_mensaje = crear_chat_inicial_oferta(oferta, solicitud)
                    logger.info(f"Mensaje inicial del chat creado: {chat_mensaje.id}")
                except Exception as e:
                    logger.error(f"Error creando mensaje inicial en el chat: {e}", exc_info=True)
                    # No fallar la operación si falla la creación del chat, pero loguear el error
                
                # Notificar al proveedor vía WebSocket
                try:
                    channel_layer = get_channel_layer()
                    if channel_layer:
                        async_to_sync(channel_layer.group_send)(
                            f"proveedor_{oferta.proveedor.id}",
                            {
                                'type': 'oferta_aceptada',
                                'oferta_id': str(oferta.id),
                                'solicitud_id': str(solicitud.id),
                                'carrito_id': carrito.id,
                                'mensaje': '¡Tu oferta fue aceptada! El cliente procederá con el pago.',
                                'estado_oferta': 'aceptada',
                                'monto_total': float(oferta.precio_total_ofrecido),
                                'timestamp': timezone.now().isoformat()
                            }
                        )
                        logger.info(f"Notificación WebSocket 'oferta_aceptada' enviada al proveedor: {oferta.proveedor.id}")

                        # NUEVO: Notificación vía Push al proveedor
                        send_expo_push_notification.delay(
                            oferta.proveedor.id,
                            "¡Felicidades! Oferta adjudicada 🎉",
                            f"Has ganado la solicitud para un {solicitud.vehiculo.marca} {solicitud.vehiculo.modelo}",
                            {"type": "offer_accepted", "solicitud_id": str(solicitud.id), "oferta_id": str(oferta.id)}
                        )
                except Exception as e:
                    logger.error(f"Error enviando notificación WebSocket: {e}", exc_info=True)
                    # No fallar la operación si falla la notificación
                
                # Guardar el ID del carrito para usar después de la transacción
                carrito_id = carrito.id
                logger.info(f"Carrito ID guardado: {carrito_id}")
            
            # Validar que tenemos un carrito_id antes de continuar
            if not carrito_id:
                logger.error("No se pudo obtener el ID del carrito después de la transacción")
                return Response(
                    {'error': 'Error al obtener el ID del carrito después de agregar los servicios'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # Recargar el carrito con relaciones para serialización (después de la transacción)
            try:
                carrito = CarritoAgendamiento.objects.select_related(
                    'cliente', 'vehiculo'
                ).prefetch_related(
                    'items__oferta_servicio__servicio',
                    'items__oferta_servicio__taller',
                    'items__oferta_servicio__mecanico'
                ).get(id=carrito_id)
                
                logger.info(f"Oferta seleccionada exitosamente - Carrito: {carrito.id}, Total items: {carrito.cantidad_items}, Total: ${carrito.total}")
            except CarritoAgendamiento.DoesNotExist:
                logger.error(f"Carrito {carrito_id} no encontrado después de la transacción")
                return Response(
                    {'error': 'Error al recargar el carrito después de agregar los servicios'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            except Exception as e:
                logger.error(f"Error recargando carrito: {e}", exc_info=True)
                return Response(
                    {'error': f'Error al recargar el carrito: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # Serializar carrito y solicitud
            try:
                carrito_serializer = CarritoAgendamientoSerializer(carrito, context={'request': request})
                solicitud_serializer = SolicitudServicioPublicaSerializer(solicitud, context={'request': request})
                
                return Response({
                    'message': 'Oferta agregada al carrito exitosamente',
                    'carrito': carrito_serializer.data,
                    'solicitud': solicitud_serializer.data
                })
            except Exception as e:
                logger.error(f"Error serializando carrito o solicitud: {e}", exc_info=True)
                return Response(
                    {'error': f'Error al serializar la respuesta: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
        except Exception as e:
            logger.error(f"Error en seleccionar_oferta: {e}", exc_info=True)
            return Response(
                {'error': f'Error al seleccionar la oferta: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def pagar_solicitud_adjudicada(self, request, pk=None):
        """
        Procesa el pago de una solicitud adjudicada sin usar carrito.
        Crea directamente la SolicitudServicio y retorna datos para el pago.
        """
        # ✅ Procesar solicitudes expiradas antes de intentar pagar
        procesar_solicitudes_expiradas()
        
        logger = logging.getLogger(__name__)
        logger.info(f"Iniciando pago directo para solicitud {pk}")
        
        try:
            solicitud = self.get_object()
            # Recargar solicitud para obtener estado actualizado
            solicitud.refresh_from_db()
            
            # Validaciones
            if solicitud.cliente.usuario != request.user:
                logger.warning(f"Usuario no autorizado intenta pagar solicitud {pk}")
                return Response(
                    {'error': 'No está autorizado para pagar esta solicitud'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            if solicitud.estado not in ['adjudicada', 'pendiente_pago']:
                logger.warning(f"Intento de pagar solicitud en estado {solicitud.estado}")
                mensaje_error = {
                    'publicada': 'Debe seleccionar una oferta antes de pagar',
                    'con_ofertas': 'Debe seleccionar una oferta antes de pagar',
                    'cancelada': 'Esta solicitud ha sido cancelada',
                    'expirada': 'Esta solicitud ha expirado',
                    'pagada': 'Esta solicitud ya ha sido pagada'
                }.get(solicitud.estado, f'No se puede pagar una solicitud en estado: {solicitud.estado}')
                
                return Response(
                    {'error': mensaje_error},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # ✅ Validar que se puede pagar (fecha límite no ha pasado)
            if not solicitud.puede_pagar():
                tiempo_restante = solicitud.tiempo_restante_pago()
                if tiempo_restante is None:
                    mensaje = 'El plazo para pagar esta solicitud ha expirado. La fecha límite de pago ya pasó.'
                else:
                    mensaje = f'El plazo para pagar esta solicitud ha expirado. La fecha límite de pago era: {solicitud.fecha_limite_pago.strftime("%d/%m/%Y %H:%M")}'
                
                logger.warning(f"Intento de pagar solicitud {pk} después de fecha límite: {solicitud.fecha_limite_pago}")
                return Response(
                    {
                        'error': mensaje,
                        'fecha_limite_pago': solicitud.fecha_limite_pago.isoformat() if solicitud.fecha_limite_pago else None
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if not solicitud.oferta_seleccionada:
                logger.error(f"Solicitud {pk} adjudicada sin oferta seleccionada")
                return Response(
                    {'error': 'No hay oferta seleccionada'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Obtener datos del request
            metodo_pago = request.data.get('metodo_pago', 'mercadopago')
            notas_cliente = request.data.get('notas_cliente', solicitud.descripcion_problema or '')
            
            logger.info(f"Datos de pago - Método: {metodo_pago}")
            
            # Obtener oferta seleccionada
            oferta = solicitud.oferta_seleccionada
            
            # Determinar proveedor (acceder a través de oferta.proveedor)
            if oferta.tipo_proveedor == 'taller':
                if not hasattr(oferta.proveedor, 'taller') or not oferta.proveedor.taller:
                    logger.error(f"Proveedor {oferta.proveedor.id} no tiene taller asociado")
                    return Response(
                        {'error': 'El proveedor no tiene un taller asociado'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                taller = oferta.proveedor.taller
                mecanico = None
                tipo_servicio = 'taller'
                ubicacion_servicio = taller.direccion if taller else None
            else:
                if not hasattr(oferta.proveedor, 'mecanico_domicilio') or not oferta.proveedor.mecanico_domicilio:
                    logger.error(f"Proveedor {oferta.proveedor.id} no tiene mecánico asociado")
                    return Response(
                        {'error': 'El proveedor no tiene un mecánico asociado'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                taller = None
                mecanico = oferta.proveedor.mecanico_domicilio
                tipo_servicio = 'domicilio'
                ubicacion_servicio = solicitud.direccion_servicio_texto
            
            logger.info(f"Proveedor - Tipo: {tipo_servicio}, Taller: {taller.id if taller else None}, Mecánico: {mecanico.id if mecanico else None}")
            
            # ✅ NOTA: Los créditos ya se consumieron al adjudicar la oferta (en seleccionar_oferta).
            # Si este pago falla, la transacción se revertirá y la solicitud quedará en estado 'adjudicada'.
            # Si el cliente cancela después, se devolverán los créditos (lógica en destroy()).
            
            with transaction.atomic():
                # ✅ PASO 1: Actualizar estados a 'pendiente_pago' (cliente está procesando el pago)
                oferta.estado = 'pendiente_pago'
                oferta.save(update_fields=['estado'])
                
                solicitud.estado = 'pendiente_pago'
                solicitud.save(update_fields=['estado'])
                
                logger.info(f"Estados actualizados: oferta y solicitud → 'pendiente_pago'")
                
                # ✅ Notificar al proveedor que el cliente está pagando
                try:
                    channel_layer = get_channel_layer()
                    if channel_layer:
                        async_to_sync(channel_layer.group_send)(
                            f"proveedor_{oferta.proveedor.id}",
                            {
                                'type': 'pago_en_proceso',
                                'oferta_id': str(oferta.id),
                                'solicitud_id': str(solicitud.id),
                                'mensaje': 'El cliente está procesando el pago de tu oferta.',
                                'estado_oferta': 'pendiente_pago',
                                'monto_total': float(oferta.precio_total_ofrecido),
                                'timestamp': timezone.now().isoformat()
                            }
                        )
                        logger.info(f"Notificación 'pago_en_proceso' enviada al proveedor: {oferta.proveedor.id}")
                except Exception as e:
                    logger.error(f"Error enviando notificación WebSocket: {e}", exc_info=True)
                
                # ✅ PASO 2: Crear SolicitudServicio con estado 'confirmado' (ya no requiere aceptación del proveedor)
                solicitud_servicio = SolicitudServicio.objects.create(
                    cliente=solicitud.cliente,
                    vehiculo=solicitud.vehiculo,
                    tipo_servicio=tipo_servicio,
                    taller=taller,
                    mecanico=mecanico,
                    fecha_servicio=oferta.fecha_disponible or timezone.now().date(),
                    hora_servicio=oferta.hora_disponible or timezone.now().time(),
                    metodo_pago=metodo_pago,
                    total=oferta.precio_total_ofrecido,
                    estado='confirmado',  # ✅ Directamente confirmado (no requiere aceptación del proveedor)
                    notas_cliente=notas_cliente,
                    ubicacion_servicio=ubicacion_servicio,
                    comprobante_validado=False,
                    devolucion_procesada=False,
                    requiere_devolucion=False,
                    oferta_proveedor=oferta  # ✅ Asociar con la oferta que originó esta solicitud
                )
                
                logger.info(f"SolicitudServicio creada: {solicitud_servicio.id} con estado 'confirmado'")
                
                # Obtener detalles de servicios de la oferta
                from mecanimovilapp.apps.servicios.models import OfertaServicio
                detalles_servicios = list(oferta.detalles_servicios.all())
                
                if not detalles_servicios:
                    logger.error(f"Oferta {oferta.id} no tiene detalles de servicios")
                    raise ValueError('La oferta no tiene servicios asociados')
                
                logger.info(f"Procesando {len(detalles_servicios)} servicios")
                
                # Tipo de proveedor para OfertaServicio
                tipo_proveedor_servicio = oferta.tipo_proveedor
                
                # Crear líneas de servicio
                for detalle in detalles_servicios:
                    logger.info(f"Procesando servicio: {detalle.servicio.nombre}, Precio: {detalle.precio_servicio}")
                    
                    # Buscar o crear OfertaServicio
                    try:
                        oferta_servicio = OfertaServicio.objects.get(
                            servicio=detalle.servicio,
                            tipo_proveedor=tipo_proveedor_servicio,
                            taller=taller,
                            mecanico=mecanico
                        )
                        logger.info(f"OfertaServicio encontrada: {oferta_servicio.id}")
                    except OfertaServicio.DoesNotExist:
                        # Crear OfertaServicio temporal
                        logger.info("Creando OfertaServicio temporal para línea de servicio")
                        
                        # Calcular costos desde el precio ofrecido
                        precio_ofrecido = detalle.precio_servicio
                        precio_sin_iva = precio_ofrecido / Decimal('1.19')
                        
                        # Si incluye repuestos, dividir 70/30
                        if oferta.incluye_repuestos:
                            costo_mano_de_obra = precio_sin_iva * Decimal('0.70')
                            costo_repuestos = precio_sin_iva * Decimal('0.30')
                        else:
                            costo_mano_de_obra = precio_sin_iva
                            costo_repuestos = Decimal('0')
                        
                        oferta_servicio = OfertaServicio.objects.create(
                            servicio=detalle.servicio,
                            tipo_proveedor=tipo_proveedor_servicio,
                            taller=taller,
                            mecanico=mecanico,
                            costo_mano_de_obra_sin_iva=costo_mano_de_obra,
                            costo_repuestos_sin_iva=costo_repuestos,
                            disponible=True
                        )
                        logger.info(f"OfertaServicio temporal creada: {oferta_servicio.id}")
                    
                    # Crear línea de servicio
                    precio_unitario = detalle.precio_servicio
                    
                    LineaServicio.objects.create(
                        solicitud=solicitud_servicio,
                        oferta_servicio=oferta_servicio,
                        con_repuestos=oferta.incluye_repuestos,
                        cantidad=1,
                        precio_unitario=precio_unitario,
                        precio_final=precio_unitario
                    )
                    
                    logger.info(f"Línea de servicio creada para {detalle.servicio.nombre}")
                
                # ✅ NOTA: Los créditos ya se consumieron al adjudicar la oferta (en seleccionar_oferta)
                # No es necesario consumirlos nuevamente aquí
                
                # ✅ PASO 2: Actualizar estados a 'pagada' (pago completado exitosamente)
                oferta.estado = 'pagada'
                oferta.save(update_fields=['estado'])
                
                solicitud.estado = 'pagada'
                solicitud.save(update_fields=['estado'])
                
                logger.info(f"Estados actualizados: oferta y solicitud → 'pagada'")
                
                # ✅ Notificar al proveedor que el pago fue completado
                try:
                    channel_layer = get_channel_layer()
                    if channel_layer:
                        async_to_sync(channel_layer.group_send)(
                            f"proveedor_{oferta.proveedor.id}",
                            {
                                'type': 'pago_completado',
                                'solicitud_id': str(solicitud.id),
                                'solicitud_servicio_id': str(solicitud_servicio.id),
                                'oferta_id': str(oferta.id),
                                'mensaje': '¡Pago completado! El servicio ha sido confirmado.',
                                'estado_oferta': 'pagada',
                                'monto_total': float(solicitud_servicio.total),
                                'fecha_servicio': str(solicitud_servicio.fecha_servicio),
                                'hora_servicio': str(solicitud_servicio.hora_servicio),
                                'timestamp': timezone.now().isoformat()
                            }
                        )
                        logger.info(f"Notificación 'pago_completado' enviada al proveedor: {oferta.proveedor.id}")
                except Exception as e:
                    logger.error(f"Error enviando notificación WebSocket: {e}", exc_info=True)
            
            # Retornar datos para el pago
            from .serializers import SolicitudServicioSerializer
            solicitud_servicio_serializer = SolicitudServicioSerializer(solicitud_servicio)
            
            # Datos del resumen para el pago
            resumen_pago = {
                'solicitud_servicio_id': solicitud_servicio.id,
                'solicitud_publica_id': solicitud.id,
                'oferta_id': oferta.id,
                'monto_total': float(solicitud_servicio.total),
                'metodo_pago': metodo_pago,
                'proveedor': {
                    'id': oferta.proveedor.id,
                    'nombre': oferta.nombre_proveedor,
                    'tipo': tipo_servicio
                },
                'servicios': [
                    {
                        'nombre': detalle.servicio.nombre,
                        'precio': float(detalle.precio_servicio),
                        'tiempo_estimado': str(detalle.tiempo_estimado) if detalle.tiempo_estimado else None
                    }
                    for detalle in detalles_servicios
                ],
                'fecha_servicio': str(solicitud_servicio.fecha_servicio),
                'hora_servicio': str(solicitud_servicio.hora_servicio),
                'ubicacion': ubicacion_servicio
            }
            
            logger.info(f"Pago procesado exitosamente - SolicitudServicio: {solicitud_servicio.id}")
            
            return Response({
                'mensaje': 'Solicitud lista para pago',
                'solicitud_servicio': solicitud_servicio_serializer.data,
                'resumen_pago': resumen_pago
            }, status=status.HTTP_200_OK)
            
        except ValueError as e:
            logger.error(f"Error de validación: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Error procesando pago de solicitud {pk}: {e}", exc_info=True)
            return Response(
                {'error': f'Error al procesar el pago: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def activas(self, request):
        """
        Lista solicitudes activas del cliente
        """
        if not hasattr(request.user, 'cliente'):
            return Response(
                {'error': 'Solo los clientes pueden ver sus solicitudes activas'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        solicitudes = SolicitudServicioPublica.objects.filter(
            cliente=request.user.cliente,
            estado__in=['publicada', 'con_ofertas', 'seleccionando_servicios', 'adjudicada', 'pendiente_pago', 'pagada', 'en_ejecucion']
        ).select_related('cliente', 'vehiculo').prefetch_related('ofertas')
        
        serializer = self.get_serializer(solicitudes, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def puede_crear_solicitud(self, request):
        """
        Verifica si el cliente puede crear nuevas solicitudes.
        El cliente NO puede crear solicitudes si tiene:
        - Solicitudes adjudicadas pendientes de pago
        - Ofertas secundarias pendientes de pago
        
        Returns:
            {
                "puede_crear": bool,
                "razon": str (solo si no puede crear),
                "solicitudes_pendientes": int,
                "ofertas_secundarias_pendientes": int
            }
        """
        if not hasattr(request.user, 'cliente'):
            return Response(
                {'error': 'Solo los clientes pueden verificar esta condición'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            cliente = request.user.cliente
            
            # Verificar solicitudes principales adjudicadas pendientes de pago
            solicitudes_pendientes = SolicitudServicioPublica.objects.filter(
                cliente=cliente,
                estado__in=['adjudicada', 'pendiente_pago'],
                oferta_seleccionada__isnull=False
            ).count()
            
            # Verificar ofertas secundarias aceptadas pero no pagadas
            ofertas_secundarias_pendientes = OfertaProveedor.objects.filter(
                solicitud__cliente=cliente,
                es_oferta_secundaria=True,
                estado__in=['aceptada', 'pendiente_pago']
            ).count()
            
            total_pendientes = solicitudes_pendientes + ofertas_secundarias_pendientes
            puede_crear = total_pendientes == 0
            
            response_data = {
                'puede_crear': puede_crear,
                'solicitudes_pendientes': solicitudes_pendientes,
                'ofertas_secundarias_pendientes': ofertas_secundarias_pendientes,
                'total_pendientes': total_pendientes
            }
            
            if not puede_crear:
                razones = []
                if solicitudes_pendientes > 0:
                    razones.append(f'{solicitudes_pendientes} solicitud(es) principal(es) pendiente(s) de pago')
                if ofertas_secundarias_pendientes > 0:
                    razones.append(f'{ofertas_secundarias_pendientes} servicio(s) adicional(es) pendiente(s) de pago')
                
                response_data['razon'] = f'Tienes {" y ".join(razones)}. Por favor, completa el pago de tus servicios antes de crear una nueva solicitud.'
            
            logger.info(f"Cliente {cliente.id} - Verificación crear solicitud: {response_data}")
            return Response(response_data)
            
        except Exception as e:
            logger.error(f"Error verificando si puede crear solicitud: {e}", exc_info=True)
            return Response(
                {'error': f'Error al verificar condición: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def disponibles(self, request):
        """
        Lista solicitudes disponibles para que los proveedores oferten
        Filtradas por marca del vehículo que el proveedor atiende
        Excluye solicitudes donde el proveedor ya tiene una oferta (excepto rechazadas/retiradas)
        Excluye solicitudes que el proveedor ya rechazó
        """
        user = request.user
        
        # IMPORTANTE: Las solicitudes dirigidas SOLO deben aparecer para el proveedor seleccionado
        # Las solicitudes globales aparecen para todos los proveedores que atienden la marca
        
        # Obtener marcas atendidas del proveedor
        marcas_atendidas = []
        if hasattr(user, 'taller') and user.taller:
            marcas_atendidas = list(user.taller.marcas_atendidas.values_list('id', flat=True))
        elif hasattr(user, 'mecanico_domicilio') and user.mecanico_domicilio:
            marcas_atendidas = list(user.mecanico_domicilio.marcas_atendidas.values_list('id', flat=True))
        
        # Separar solicitudes globales y dirigidas
        # Solicitudes GLOBALES: filtradas por marca del vehículo
        solicitudes_globales = SolicitudServicioPublica.objects.filter(
            estado__in=['publicada', 'con_ofertas'],
            fecha_expiracion__gt=timezone.now(),
            tipo_solicitud='global'
        )
        
        # Filtrar solicitudes globales por marca del vehículo
        if marcas_atendidas:
            solicitudes_globales = solicitudes_globales.filter(vehiculo__marca__id__in=marcas_atendidas)
        else:
            # Si el proveedor no tiene marcas configuradas, no mostrar solicitudes globales
            solicitudes_globales = solicitudes_globales.none()
        
        # Solicitudes DIRIGIDAS: SOLO para este proveedor específico
        solicitudes_dirigidas = SolicitudServicioPublica.objects.filter(
            proveedores_dirigidos=user,
            estado__in=['publicada', 'con_ofertas'],
            fecha_expiracion__gt=timezone.now(),
            tipo_solicitud='dirigida'
        )
        
        # Combinar ambas (OR)
        queryset = solicitudes_globales | solicitudes_dirigidas
        
        # Excluir solicitudes donde el proveedor ya tiene una oferta activa
        # (permitir si la oferta está rechazada o retirada, para que pueda volver a ofertar)
        ofertas_proveedor = OfertaProveedor.objects.filter(
            proveedor=user,
            estado__in=['enviada', 'vista', 'en_chat', 'aceptada', 'expirada']
        ).values_list('solicitud_id', flat=True)
        
        if ofertas_proveedor:
            queryset = queryset.exclude(id__in=ofertas_proveedor)
        
        # Excluir solicitudes que el proveedor ya rechazó
        from .models import RechazoSolicitud
        rechazos_proveedor = RechazoSolicitud.objects.filter(
            proveedor=user
        ).values_list('solicitud_id', flat=True)
        
        if rechazos_proveedor:
            queryset = queryset.exclude(id__in=rechazos_proveedor)
        
        queryset = queryset.distinct().select_related(
            'cliente', 'cliente__usuario', 'vehiculo', 'vehiculo__marca', 'direccion_usuario'
        ).prefetch_related('servicios_solicitados', 'proveedores_dirigidos', 'ofertas')
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    def destroy(self, request, *args, **kwargs):
        """
        Cancela una solicitud (soft delete)
        Permite cancelar solicitudes adjudicadas (no pagadas).
        
        ✅ POLÍTICA DE CRÉDITOS:
        - Los créditos NO se devuelven cuando se cancela una solicitud adjudicada
        - Una vez que la oferta es adjudicada, los créditos se consumen permanentemente
        - Esto previene gaming y es más justo para el proveedor
        """
        solicitud = self.get_object()
        
        if solicitud.cliente != request.user.cliente:
            return Response(
                {'error': 'No tienes permiso para esta acción'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # ✅ POLÍTICA: No permitir cancelar solicitudes adjudicadas manualmente
        # Las solicitudes adjudicadas solo se cancelan automáticamente por expiración de pago
        # Esto previene gaming y es más justo para el proveedor
        if solicitud.estado == 'adjudicada':
            return Response(
                {
                    'error': 'No se puede cancelar una solicitud adjudicada manualmente. '
                             'La solicitud se cancelará automáticamente si no se paga antes de la fecha límite. '
                             'Los créditos del proveedor ya fueron consumidos y no se devuelven.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # No permitir cancelar si ya está pagada o completada
        if solicitud.estado in ['pagada', 'completada', 'en_ejecucion']:
            return Response(
                {'error': f'No se puede cancelar una solicitud en estado: {solicitud.estado}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        with transaction.atomic():
            # ✅ Cancelar solicitud (solo para estados no adjudicados)
            # Las solicitudes adjudicadas se bloquean arriba
            
            # Cambiar estado a cancelada
            solicitud.estado = 'cancelada'
            solicitud.save()
            
            # Rechazar todas las ofertas pendientes de esta solicitud
            OfertaProveedor.objects.filter(
                solicitud=solicitud,
                estado__in=['enviada', 'vista', 'en_chat']
            ).update(
                estado='rechazada',
                fecha_respuesta_cliente=timezone.now()
            )
            
            # Notificar a proveedores
            try:
                channel_layer = get_channel_layer()
                # Notificar sobre todas las ofertas afectadas
                ofertas_afectadas = solicitud.ofertas.filter(
                    estado__in=['enviada', 'vista', 'en_chat', 'aceptada']
                )
                for oferta_notif in ofertas_afectadas:
                    async_to_sync(channel_layer.group_send)(
                        f"proveedor_{oferta_notif.proveedor.id}",
                        {
                            'type': 'solicitud_cancelada',
                            'solicitud_id': str(solicitud.id),
                            'oferta_id': str(oferta_notif.id)
                        }
                    )
            except Exception as e:
                logger.error(f"Error enviando notificación WebSocket: {e}")
        
        return Response({'message': 'Solicitud cancelada exitosamente'}, status=status.HTTP_204_NO_CONTENT)
    
    @action(detail=False, methods=['get'], url_path='alertas-pago')
    def alertas_pago(self, request):
        """
        Retorna alertas de pago activas para el usuario actual.
        
        Para clientes: solicitudes adjudicadas con alerta activa (6h antes de expirar)
        
        Para proveedores: 
        - Solo alertas de tipo 'pago_expirado' (solicitudes que expiraron automáticamente)
        - NO se retornan alertas de cancelación manual porque las solicitudes adjudicadas
          NO se pueden cancelar manualmente (solo expiran automáticamente)
        """
        logger = logging.getLogger(__name__)
        logger.info(f"Obteniendo alertas de pago para usuario {request.user.id}")
        
        try:
            # ✅ Procesar solicitudes expiradas antes de obtener alertas
            procesar_solicitudes_expiradas()
            
            # ✅ Obtener IDs de alertas descartadas por el usuario para filtrarlas
            alertas_descartadas = AlertaDescartada.objects.filter(
                usuario=request.user
            ).values_list('solicitud_id', 'tipo_alerta')
            # Convertir a set de tuplas para búsqueda rápida
            alertas_descartadas_set = set(alertas_descartadas)
            
            alertas = []
            
            if hasattr(request.user, 'cliente'):
                # Cliente: buscar solicitudes adjudicadas con alerta activa
                solicitudes = SolicitudServicioPublica.objects.filter(
                    cliente=request.user.cliente,
                    estado__in=['adjudicada', 'pendiente_pago']
                ).select_related('oferta_seleccionada')
                
                for solicitud in solicitudes:
                    # ✅ Filtrar alertas descartadas
                    if (solicitud.id, 'pago_proximo') in alertas_descartadas_set:
                        logger.info(f"Omitiendo alerta descartada: Solicitud {solicitud.id} - tipo pago_proximo")
                        continue
                    
                    if solicitud.debe_mostrar_alerta_cliente():
                        tiempo_restante = solicitud.tiempo_restante_pago()
                        horas_restantes = int(tiempo_restante.total_seconds() // 3600) if tiempo_restante else 0
                        minutos_restantes = int((tiempo_restante.total_seconds() % 3600) // 60) if tiempo_restante else 0
                        
                        alertas.append({
                            'id': str(solicitud.id),
                            'tipo': 'pago_proximo',
                            'solicitud_id': str(solicitud.id),
                            'mensaje': f'Quedan {horas_restantes}h {minutos_restantes}m para pagar esta solicitud',
                            'tiempo_restante_horas': horas_restantes,
                            'tiempo_restante_minutos': minutos_restantes,
                            'fecha_limite_pago': solicitud.fecha_limite_pago.isoformat() if solicitud.fecha_limite_pago else None,
                            'monto': float(solicitud.oferta_seleccionada.precio_total_ofrecido) if solicitud.oferta_seleccionada else None
                        })
            
            elif hasattr(request.user, 'taller') or hasattr(request.user, 'mecanico_domicilio'):
                # Proveedor: buscar ofertas ADJUDICADAS (aceptadas) que luego fueron canceladas
                # ✅ IMPORTANTE: Solo mostrar alertas para ofertas que fueron realmente adjudicadas
                # Una oferta está adjudicada si es la oferta_seleccionada de una solicitud que fue cancelada
                # 
                # ✅ CRÍTICO: Solo retornar alertas para solicitudes que:
                # 1. Están en estado 'cancelada' (no activas como 'publicada', 'con_ofertas', etc.)
                # 2. Tienen una oferta_seleccionada (fueron adjudicadas)
                # 3. La oferta seleccionada pertenece al proveedor actual
                # 4. La oferta está en un estado que indica adjudicación previa (aceptada, rechazada después de adjudicación)
                logger.info(
                    f"Obteniendo alertas para proveedor {request.user.id} "
                    f"(taller: {hasattr(request.user, 'taller')}, "
                    f"mecanico: {hasattr(request.user, 'mecanico_domicilio')})"
                )
                
                solicitudes_canceladas_con_oferta = SolicitudServicioPublica.objects.filter(
                    estado='cancelada',  # ✅ Solo solicitudes canceladas (no activas)
                    oferta_seleccionada__proveedor=request.user,
                    oferta_seleccionada__isnull=False
                ).select_related('oferta_seleccionada')
                
                logger.info(
                    f"Proveedor {request.user.id}: Encontradas {solicitudes_canceladas_con_oferta.count()} "
                    f"solicitudes canceladas con oferta seleccionada del proveedor"
                )
                
                for solicitud in solicitudes_canceladas_con_oferta:
                    oferta = solicitud.oferta_seleccionada
                    
                    # ✅ Validaciones estrictas: asegurar que la oferta fue realmente adjudicada
                    if not oferta or oferta.proveedor != request.user:
                        continue
                    
                    if solicitud.estado != 'cancelada' or solicitud.oferta_seleccionada_id != oferta.id:
                        continue
                    
                    # ✅ CRÍTICO: Solo mostrar alerta si la oferta fue realmente ADJUDICADA.
                    # 
                    # Una oferta está adjudicada si:
                    # 1. Es la oferta_seleccionada de una solicitud (ya verificado arriba)
                    # 2. La solicitud estuvo en estado 'adjudicada' o 'pendiente_pago' antes de cancelarse
                    # 
                    # Estados válidos para alertas (indican que la oferta fue adjudicada antes):
                    # - 'aceptada': Oferta fue aceptada (adjudicada) - puede estar en este estado si cancelación fue reciente
                    # - 'rechazada': Oferta fue adjudicada pero luego rechazada cuando procesar_solicitudes_expiradas() canceló la solicitud
                    # - 'pendiente_pago': Oferta fue aceptada y está pendiente de pago
                    #
                    # Estados que NO deben generar alerta (ofrece nunca adjudicada):
                    # - 'enviada': Oferta enviada pero nunca vista/aceptada
                    # - 'vista': Oferta vista por cliente pero nunca aceptada
                    # - 'en_chat': Oferta en chat pero nunca aceptada (a menos que haya sido adjudicada después)
                    # - 'retirada': Oferta retirada por proveedor
                    # - 'expirada': Oferta expirada antes de adjudicación
                    estados_adjudicacion = ['aceptada', 'rechazada', 'pendiente_pago']
                    estados_no_adjudicados = ['enviada', 'vista', 'retirada', 'expirada']
                    
                    if oferta.estado in estados_no_adjudicados:
                        # Oferta nunca fue adjudicada, omitir alerta
                        logger.info(
                            f"Omitiendo alerta: Oferta {oferta.id} nunca fue adjudicada "
                            f"(estado: {oferta.estado}). La solicitud {solicitud.id} fue cancelada "
                            f"pero la oferta del proveedor {request.user.id} nunca fue aceptada por el cliente. "
                            f"Esto es normal si el proveedor envió una oferta pero el cliente nunca la aceptó."
                        )
                        continue
                    
                    if oferta.estado not in estados_adjudicacion:
                        # Estado desconocido o inesperado, por seguridad no mostrar alerta
                        logger.warning(
                            f"Omitiendo alerta: Oferta {oferta.id} tiene estado inesperado "
                            f"({oferta.estado}) para solicitud cancelada {solicitud.id}. "
                            f"No se mostrará alerta."
                        )
                        continue
                    
                    # ✅ Validación final: Verificar que la solicitud realmente está cancelada
                    # y no está en un estado activo (por si acaso hay inconsistencia en la BD)
                    if solicitud.estado not in ['cancelada', 'expirada']:
                        logger.warning(
                            f"Omitiendo alerta: Solicitud {solicitud.id} no está cancelada "
                            f"(estado: {solicitud.estado}). Esto no debería pasar. "
                            f"No se mostrará alerta."
                        )
                        continue
                    
                    # ✅ CRÍTICO: Verificar que la solicitud está REALMENTE expirada antes de mostrar alerta
                    # Solo mostrar alerta si fecha_limite_pago ya pasó (solicitud expirada)
                    ahora = timezone.now()
                    fue_expirada = (
                        solicitud.fecha_limite_pago and 
                        ahora > solicitud.fecha_limite_pago
                    )
                    
                    # ✅ IMPORTANTE: Solo mostrar alerta si la solicitud fue cancelada por EXPIRACIÓN
                    # No mostrar alerta si fue cancelada explícitamente por el cliente antes de expirar
                    # (a menos que ya haya expirado)
                    if not fue_expirada:
                        # Si la solicitud fue cancelada pero NO ha expirado, no mostrar alerta
                        # Esto puede pasar si el cliente cancela explícitamente antes de la fecha límite
                        logger.info(
                            f"Omitiendo alerta: Solicitud {solicitud.id} fue cancelada pero NO está expirada "
                            f"(fecha_limite_pago: {solicitud.fecha_limite_pago}, ahora: {ahora}). "
                            f"No se mostrará alerta de 'pago expirado'."
                        )
                        continue
                    
                    # ✅ Filtrar alertas descartadas
                    if (solicitud.id, 'pago_expirado') in alertas_descartadas_set:
                        logger.info(
                            f"Omitiendo alerta descartada: Solicitud {solicitud.id} - tipo pago_expirado "
                            f"para proveedor {request.user.id}"
                        )
                        continue
                    
                    # ✅ Solo llegar aquí si la solicitud está realmente expirada
                    logger.info(
                        f"✅ Agregando alerta de EXPIRACIÓN para proveedor {request.user.id}: "
                        f"Oferta {oferta.id} (estado: {oferta.estado}), "
                        f"Solicitud {solicitud.id} (cancelada por EXPIRACIÓN - fecha_limite_pago pasada)"
                    )
                    
                    alertas.append({
                        'id': str(oferta.id),
                        'tipo': 'pago_expirado',  # ✅ Siempre 'pago_expirado' porque solo llegamos aquí si expiró
                        'oferta_id': str(oferta.id),
                        'solicitud_id': str(solicitud.id),
                        'mensaje': 'El cliente no pagó a tiempo. La solicitud ha sido cancelada automáticamente.',
                        'fecha_limite_pago': solicitud.fecha_limite_pago.isoformat() if solicitud.fecha_limite_pago else None,
                        'monto': float(oferta.precio_total_ofrecido),
                        'creditos_devueltos': False  # ✅ Créditos NO se devuelven por expiración
                    })
            
            return Response({
                'alertas': alertas,
                'total': len(alertas)
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error obteniendo alertas de pago: {e}", exc_info=True)
            return Response(
                {'error': f'Error al obtener alertas: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'], url_path='descartar-alerta')
    def descartar_alerta(self, request, pk=None):
        """
        Marca una alerta como descartada por el usuario.
        Por ahora solo retorna éxito, en el futuro se puede almacenar en sesión o modelo.
        """
        try:
            # ✅ Validar que pk existe y es válido ANTES de intentar obtener el objeto
            if not pk:
                logger.warning(f"descartar_alerta: pk no proporcionado")
                return Response(
                    {'error': 'ID de solicitud requerido'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Convertir a string y validar formato
            pk_str = str(pk).strip().lower()
            if pk_str in ['undefined', 'null', 'none', '']:
                logger.warning(f"descartar_alerta: pk inválido recibido: {pk}")
                return Response(
                    {'error': 'ID de solicitud inválido'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # ✅ FIX: Buscar directamente por pk sin usar get_object() que filtra por queryset
            # Esto permite acceder a solicitudes canceladas donde el proveedor tenía ofertas
            try:
                solicitud = SolicitudServicioPublica.objects.get(pk=pk)
            except SolicitudServicioPublica.DoesNotExist:
                logger.warning(f"descartar_alerta: Solicitud con pk={pk} no encontrada")
                return Response(
                    {'error': 'Solicitud no encontrada'},
                    status=status.HTTP_404_NOT_FOUND
                )
            except Exception as e:
                logger.error(f"Error obteniendo solicitud en descartar_alerta: {e}", exc_info=True)
                raise
            
            # Validar que el usuario tiene permiso
            if hasattr(request.user, 'cliente'):
                if solicitud.cliente != request.user.cliente:
                    return Response(
                        {'error': 'No tienes permiso para esta acción'},
                        status=status.HTTP_403_FORBIDDEN
                    )
            elif hasattr(request.user, 'taller') or hasattr(request.user, 'mecanico_domicilio'):
                # Para proveedores, verificar si tienen una oferta relacionada
                # ✅ FIX: Verificar oferta_seleccionada de forma segura para evitar AttributeError
                oferta_seleccionada = solicitud.oferta_seleccionada
                if not oferta_seleccionada or oferta_seleccionada.proveedor != request.user:
                    # Verificar si el proveedor tiene alguna oferta en esta solicitud
                    tiene_oferta = OfertaProveedor.objects.filter(
                        solicitud=solicitud,
                        proveedor=request.user
                    ).exists()
                    
                    if not tiene_oferta:
                        return Response(
                            {'error': 'No tienes permiso para esta acción'},
                            status=status.HTTP_403_FORBIDDEN
                        )
            else:
                return Response(
                    {'error': 'Usuario no válido'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # ✅ Determinar el tipo de alerta basado en el contexto
            
            # Para clientes: alerta de pago próximo
            # Para proveedores: alerta de pago expirado
            if hasattr(request.user, 'cliente'):
                tipo_alerta = 'pago_proximo'
            else:
                tipo_alerta = 'pago_expirado'
            
            # ✅ Guardar la alerta descartada en el modelo
            # Usar get_or_create para evitar duplicados si se intenta descartar dos veces
            alerta_descartada, created = AlertaDescartada.objects.get_or_create(
                usuario=request.user,
                solicitud=solicitud,
                tipo_alerta=tipo_alerta,
                defaults={
                    'fecha_descarte': timezone.now()
                }
            )
            
            if created:
                logger.info(
                    f"✅ Alerta {tipo_alerta} descartada para solicitud {solicitud.id} "
                    f"por usuario {request.user.id} - Guardada en BD"
                )
            else:
                logger.info(
                    f"✅ Alerta {tipo_alerta} ya estaba descartada para solicitud {solicitud.id} "
                    f"por usuario {request.user.id}"
                )
            
            return Response({
                'message': 'Alerta descartada',
                'solicitud_id': str(solicitud.id),
                'tipo_alerta': tipo_alerta
            }, status=status.HTTP_200_OK)
            
        except SolicitudServicioPublica.DoesNotExist:
            logger.warning(f"descartar_alerta: Solicitud {pk} no encontrada")
            return Response(
                {'error': 'Solicitud no encontrada'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error en descartar_alerta para solicitud {pk}: {e}", exc_info=True)
            return Response(
                {'error': f'Error al descartar alerta: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class OfertaProveedorViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar ofertas de proveedores
    """
    queryset = OfertaProveedor.objects.all()
    serializer_class = OfertaProveedorSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['precio_total_ofrecido', 'fecha_envio']
    ordering = ['precio_total_ofrecido']
    
    def get_queryset(self):
        """
        Filtra ofertas según el rol del usuario
        - Cliente: ofertas de sus solicitudes
        - Proveedor: sus propias ofertas
        - Admin: todas
        """
        # ✅ Procesar solicitudes expiradas antes de obtener el queryset
        procesar_solicitudes_expiradas()
        
        user = self.request.user
        
        if user.is_staff or user.is_superuser:
            queryset = OfertaProveedor.objects.select_related(
                'solicitud', 'solicitud__cliente', 'proveedor'
            ).prefetch_related('detalles_servicios__servicio', 'mensajes_chat')
        # Cliente viendo ofertas de sus solicitudes
        elif hasattr(user, 'cliente'):
            queryset = OfertaProveedor.objects.filter(
                solicitud__cliente=user.cliente
            ).select_related(
                'solicitud', 'solicitud__cliente', 'proveedor'
            ).prefetch_related('detalles_servicios__servicio', 'mensajes_chat')
        # Proveedor viendo sus ofertas
        else:
            queryset = OfertaProveedor.objects.filter(
                proveedor=user
            ).select_related(
                'solicitud', 'solicitud__cliente', 'proveedor'
            ).prefetch_related('detalles_servicios__servicio', 'mensajes_chat')
        
        # ✅ FILTRAR POR SOLICITUD si viene en query params
        # Compatible con WSGIRequest (query_params) y ASGIRequest (GET)
        query_params = getattr(self.request, 'query_params', self.request.GET)
        solicitud_id = query_params.get('solicitud')
        if solicitud_id:
            try:
                queryset = queryset.filter(solicitud_id=solicitud_id)
                logger.info(f"🔍 OfertaProveedorViewSet - Filtrando ofertas por solicitud_id: {solicitud_id}")
                logger.info(f"🔍 OfertaProveedorViewSet - Total ofertas encontradas: {queryset.count()}")
                
                # Log de ofertas secundarias
                ofertas_secundarias = queryset.filter(es_oferta_secundaria=True)
                logger.info(f"🔍 OfertaProveedorViewSet - Ofertas secundarias: {ofertas_secundarias.count()}")
                for oferta_sec in ofertas_secundarias:
                    logger.info(f"  - Oferta secundaria ID: {oferta_sec.id}, Estado: {oferta_sec.estado}, es_oferta_secundaria: {oferta_sec.es_oferta_secundaria}")
                
                # Log de ofertas originales
                ofertas_originales = queryset.filter(es_oferta_secundaria=False)
                logger.info(f"🔍 OfertaProveedorViewSet - Ofertas originales: {ofertas_originales.count()}")
            except (ValueError, TypeError):
                logger.warning(f"ID de solicitud inválido en query params: {solicitud_id}")
        
        # Optimizar queryset para incluir ofertas secundarias relacionadas
        queryset = queryset.prefetch_related('ofertas_secundarias')
        
        return queryset
    
    def perform_create(self, serializer):
        """
        Crea una oferta y valida permisos
        """
        try:
            logger.info(f"Creando oferta - Usuario: {self.request.user.id}")
            logger.info(f"Datos recibidos (raw): {self.request.data}")
            logger.info(f"Datos validados: {serializer.validated_data}")
            
            # Solo proveedores pueden crear ofertas
            if hasattr(self.request.user, 'cliente'):
                raise permissions.PermissionDenied("Solo los proveedores pueden crear ofertas")
            
            # Verificar que el usuario es proveedor
            if not (hasattr(self.request.user, 'taller') or hasattr(self.request.user, 'mecanico_domicilio')):
                raise permissions.PermissionDenied("Debes ser un proveedor para crear ofertas")
            
            # Validar que la solicitud esté en validated_data
            if 'solicitud' not in serializer.validated_data:
                logger.error("❌ 'solicitud' no está en validated_data")
                logger.error(f"validated_data keys: {list(serializer.validated_data.keys())}")
                raise serializers.ValidationError({
                    'solicitud': 'La solicitud es requerida'
                })
            
            solicitud = serializer.validated_data['solicitud']
            logger.info(f"Oferta - Solicitud validada: {solicitud.id}")
            
            # Validación para ofertas secundarias
            oferta_original = serializer.validated_data.get('oferta_original')
            motivo_servicio_adicional = serializer.validated_data.get('motivo_servicio_adicional', '')
            
            # Para ofertas secundarias, validar que la oferta original esté en estado válido
            if oferta_original:
                # Validar que la oferta original existe
                try:
                    oferta_original_obj = OfertaProveedor.objects.get(id=oferta_original.id)
                except OfertaProveedor.DoesNotExist:
                    raise serializers.ValidationError({
                        'oferta_original': 'La oferta original no existe'
                    })
                
                # Validar que la oferta original pertenece al mismo proveedor
                if oferta_original_obj.proveedor != self.request.user:
                    raise serializers.ValidationError({
                        'oferta_original': 'Solo puedes crear ofertas secundarias para tus propias ofertas'
                    })
                
                # Validar que la oferta original está en un estado que permite ofertas secundarias
                # Estados permitidos: 'pagada' o 'en_ejecucion' (pero no 'completada')
                if oferta_original_obj.estado not in ['pagada', 'en_ejecucion']:
                    raise serializers.ValidationError({
                        'oferta_original': f'No se pueden crear ofertas secundarias. La oferta original está en estado: {oferta_original_obj.get_estado_display()}'
                    })
                
                # Validar que la oferta secundaria es para la misma solicitud
                if oferta_original_obj.solicitud != solicitud:
                    raise serializers.ValidationError({
                        'oferta_original': 'La oferta secundaria debe ser para la misma solicitud que la oferta original'
                    })
                
                # Validar que el motivo del servicio adicional es proporcionado
                if not motivo_servicio_adicional or motivo_servicio_adicional.strip() == '':
                    raise serializers.ValidationError({
                        'motivo_servicio_adicional': 'El motivo del servicio adicional es obligatorio para ofertas secundarias'
                    })
                
                # Para ofertas secundarias, no validar requiere_repuestos ni puede_recibir_ofertas
                # porque son independientes de la solicitud original
                # Establecer es_oferta_secundaria automáticamente
                serializer.validated_data['es_oferta_secundaria'] = True
                logger.info(f"Creando oferta secundaria - Oferta original: {oferta_original_obj.id}, Estado: {oferta_original_obj.estado}")
            else:
                # Para ofertas originales, validar que la solicitud puede recibir ofertas
                if not solicitud.puede_recibir_ofertas:
                    raise serializers.ValidationError(
                        "Esta solicitud ya no puede recibir ofertas"
                    )
                
                # Validar que si la solicitud no requiere repuestos, no se incluyan repuestos en la oferta
                if not solicitud.requiere_repuestos:
                    detalles_data = self.request.data.get('detalles_servicios', [])
                    for detalle_data in detalles_data:
                        repuestos_data = detalle_data.get('repuestos_seleccionados', [])
                        if repuestos_data and len(repuestos_data) > 0:
                            raise serializers.ValidationError(
                                "Esta solicitud no requiere repuestos. Solo se permite ofertar mano de obra."
                            )
                
                # Asegurar que es_oferta_secundaria sea False para ofertas originales
                serializer.validated_data['es_oferta_secundaria'] = False
                logger.info(f"Creando oferta original para solicitud {solicitud.id}")
            
            # Validar que el proveedor no haya enviado ya una oferta ORIGINAL para esta solicitud
            # (Las ofertas secundarias no cuentan para esta validación)
            oferta_existente = OfertaProveedor.objects.filter(
                solicitud=solicitud,
                proveedor=self.request.user,
                es_oferta_secundaria=False  # Solo verificar ofertas originales
            ).first()
            
            if oferta_existente and not oferta_original:
                # Si la oferta existente fue rechazada o retirada, permitir una nueva oferta
                if oferta_existente.estado in ['rechazada', 'retirada']:
                    logger.info(f"Oferta anterior {oferta_existente.id} está {oferta_existente.estado}, permitiendo nueva oferta")
                else:
                    # Obtener nombre del estado
                    estado_nombres = {
                        'enviada': 'Enviada',
                        'vista': 'Vista por Cliente',
                        'en_chat': 'En Conversación',
                        'aceptada': 'Aceptada',
                        'rechazada': 'Rechazada',
                        'retirada': 'Retirada',
                        'expirada': 'Expirada',
                    }
                    estado_display = estado_nombres.get(oferta_existente.estado, oferta_existente.estado)
                    
                    logger.warning(f"Intento de crear oferta duplicada para solicitud {solicitud.id} por proveedor {self.request.user.id}. Oferta existente: {oferta_existente.id} ({oferta_existente.estado})")
                    raise serializers.ValidationError({
                        'solicitud': [f'Ya has enviado una oferta para esta solicitud. Estado actual: {estado_display}']
                    })
            
            # Validar que el proveedor esté en la lista de proveedores dirigidos (si aplica)
            if solicitud.tipo_solicitud == 'dirigida':
                if self.request.user not in solicitud.proveedores_dirigidos.all():
                    raise permissions.PermissionDenied(
                        "No estás autorizado para ofertar en esta solicitud dirigida"
                    )
            
            # Determinar tipo_proveedor antes de crear la oferta
            tipo_proveedor = None
            if hasattr(self.request.user, 'taller') and self.request.user.taller:
                tipo_proveedor = 'taller'
            elif hasattr(self.request.user, 'mecanico_domicilio') and self.request.user.mecanico_domicilio:
                tipo_proveedor = 'mecanico'
            else:
                raise serializers.ValidationError("El usuario no es un proveedor válido")
            
            # Crear la oferta
            try:
                logger.info(f"🔍 Intentando crear oferta con datos: {serializer.validated_data}")
                oferta = serializer.save(proveedor=self.request.user, tipo_proveedor=tipo_proveedor)
                logger.info(f"✅ Oferta creada exitosamente: {oferta.id}, es_oferta_secundaria: {oferta.es_oferta_secundaria}, estado: {oferta.estado}")
                
                # ✅ NOTA: En el nuevo sistema Pay-per-Win, los créditos NO se consumen al crear ofertas.
                # Los créditos se consumen solo al momento de adjudicación (en pagar_solicitud_adjudicada).
                # Esto permite a los proveedores postular ofertas sin límite de créditos.
            except Exception as e:
                logger.error(f"❌ Error creando oferta: {str(e)}", exc_info=True)
                logger.error(f"❌ Datos del serializer: {serializer.validated_data}")
                logger.error(f"❌ Error completo: {type(e).__name__}: {str(e)}")
                raise
            
            # Crear detalles de servicios
            detalles_data = self.request.data.get('detalles_servicios', [])
            logger.info(f"Detalles de servicios recibidos: {detalles_data}")
            if not detalles_data:
                raise serializers.ValidationError(
                    "Debes incluir al menos un servicio en detalles_servicios"
                )
            
            for detalle_data in detalles_data:
                try:
                    # Validar campos requeridos
                    if 'servicio' not in detalle_data:
                        raise serializers.ValidationError(
                            "Cada detalle de servicio debe incluir el campo 'servicio'"
                        )
                    if 'precio_servicio' not in detalle_data:
                        raise serializers.ValidationError(
                            "Cada detalle de servicio debe incluir el campo 'precio_servicio'"
                        )
                    
                    # Obtener tiempo estimado (puede venir como tiempo_estimado_horas o tiempo_estimado)
                    tiempo_horas = detalle_data.get('tiempo_estimado_horas')
                    if tiempo_horas is None:
                        # Intentar parsear desde tiempo_estimado si viene como string
                        tiempo_estimado_str = detalle_data.get('tiempo_estimado')
                        if tiempo_estimado_str:
                            # Si viene como "HH:MM:SS", parsearlo
                            if isinstance(tiempo_estimado_str, str) and ':' in tiempo_estimado_str:
                                parts = tiempo_estimado_str.split(':')
                                if len(parts) >= 2:
                                    horas = float(parts[0]) + (float(parts[1]) / 60)
                                    tiempo_horas = horas
                                else:
                                    tiempo_horas = float(tiempo_estimado_str)
                            else:
                                tiempo_horas = float(tiempo_estimado_str)
                        else:
                            tiempo_horas = 1  # Default
                    
                    # Convertir a timedelta
                    tiempo_estimado = timedelta(hours=float(tiempo_horas))
                    
                    # Convertir precio_servicio a Decimal
                    try:
                        precio_servicio = Decimal(str(detalle_data['precio_servicio']))
                    except (ValueError, TypeError) as e:
                        raise serializers.ValidationError(
                            f"Precio inválido para servicio {detalle_data.get('servicio', 'desconocido')}: {str(e)}"
                        )
                    
                    repuestos_data = detalle_data.get('repuestos_seleccionados', [])
                    logger.info(f"Creando detalle de servicio: servicio_id={detalle_data['servicio']}, repuestos_seleccionados={repuestos_data}")
                    
                    detalle = DetalleServicioOferta.objects.create(
                        oferta=oferta,
                        servicio_id=detalle_data['servicio'],
                        precio_servicio=precio_servicio,
                        tiempo_estimado=tiempo_estimado,
                        notas=detalle_data.get('notas', ''),
                        repuestos_seleccionados=repuestos_data
                    )
                    logger.info(f"Detalle de servicio creado: id={detalle.id}, servicio_id={detalle.servicio_id}, precio={precio_servicio}, tiempo={tiempo_estimado}, repuestos_count={len(repuestos_data)}")
                except (ValueError, TypeError, KeyError) as e:
                    logger.error(f"Error creando detalle de servicio: {e}")
                    logger.error(f"Datos del detalle: {detalle_data}")
                    raise serializers.ValidationError(
                        f"Error en detalle de servicio: {str(e)}"
                    )
            
            # Actualizar la relación many-to-many servicios_ofertados
            # Esto se hace automáticamente al crear DetalleServicioOferta, pero lo hacemos explícito
            servicios_ids = [detalle_data['servicio'] for detalle_data in detalles_data]
            oferta.servicios_ofertados.set(servicios_ids)
            logger.info(f"Servicios ofertados asignados: {servicios_ids}")
            
            # ✅ INCREMENTAR CONTADOR DE OFERTAS EN LA SOLICITUD (solo para ofertas originales)
            if not oferta.es_oferta_secundaria:
                solicitud.incrementar_ofertas()
                logger.info(f"Contador de ofertas incrementado para solicitud {solicitud.id}. Total: {solicitud.total_ofertas}")
            
            # Notificar al cliente vía WebSocket
            try:
                if solicitud.cliente and solicitud.cliente.usuario:
                    channel_layer = get_channel_layer()
                    if oferta.es_oferta_secundaria:
                        # Notificación para oferta secundaria
                        async_to_sync(channel_layer.group_send)(
                            f"cliente_{solicitud.cliente.usuario.id}",
                            {
                                'type': 'oferta_secundaria_creada',
                                'oferta_id': str(oferta.id),
                                'oferta_original_id': str(oferta.oferta_original.id) if oferta.oferta_original else None,
                                'solicitud_id': str(solicitud.id),
                                'proveedor_nombre': oferta.nombre_proveedor,
                                'precio': str(oferta.precio_total_ofrecido),
                                'motivo': oferta.motivo_servicio_adicional
                            }
                        )
                    else:
                        # Notificación para oferta original
                        async_to_sync(channel_layer.group_send)(
                            f"cliente_{solicitud.cliente.usuario.id}",
                            {
                                'type': 'nueva_oferta',
                                'oferta_id': str(oferta.id),
                                'solicitud_id': str(solicitud.id),
                                'proveedor_nombre': oferta.nombre_proveedor,
                                'precio': str(oferta.precio_total_ofrecido)
                            }
                        )
                        
                        # NUEVO: Notificación vía Push al cliente
                        send_expo_push_notification.delay(
                            solicitud.cliente.usuario.id,
                            "Nueva oferta disponible 🛠️",
                            f"{oferta.nombre_proveedor} te ha enviado una cotización por ${oferta.precio_total_ofrecido:,.0f}",
                            {"type": "new_offer", "solicitud_id": str(solicitud.id), "oferta_id": str(oferta.id)}
                        )
                else:
                    logger.warning(f"No se pudo enviar notificación WebSocket: cliente o usuario no disponible para solicitud {solicitud.id}")
            except Exception as e:
                logger.error(f"Error enviando notificación WebSocket: {e}")
        except Exception as e:
            logger.error(f"Error en perform_create: {str(e)}", exc_info=True)
            raise
    
    @action(detail=False, methods=['get'])
    def mis_ofertas(self, request):
        """
        Lista las ofertas del proveedor autenticado
        """
        if hasattr(request.user, 'cliente'):
            return Response(
                {'error': 'Solo los proveedores pueden ver sus ofertas'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        estado_filter = request.query_params.get('estado')
        queryset = OfertaProveedor.objects.filter(proveedor=request.user)
        
        if estado_filter:
            queryset = queryset.filter(estado=estado_filter)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def estadisticas(self, request):
        """
        Estadísticas de ofertas del proveedor
        """
        if hasattr(request.user, 'cliente'):
            return Response(
                {'error': 'Solo los proveedores pueden ver estadísticas'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        ofertas = OfertaProveedor.objects.filter(proveedor=request.user)
        
        return Response({
            'total_ofertas': ofertas.count(),
            'ofertas_aceptadas': ofertas.filter(estado='aceptada').count(),
            'ofertas_rechazadas': ofertas.filter(estado='rechazada').count(),
            'ofertas_pendientes': ofertas.filter(estado__in=['enviada', 'vista', 'en_chat']).count(),
            'tasa_aceptacion': (
                ofertas.filter(estado='aceptada').count() / ofertas.count() * 100
                if ofertas.count() > 0 else 0
            )
        })
    
    @action(detail=False, methods=['get'], url_path='ofertas-secundarias/(?P<oferta_original_id>[^/.]+)')
    def ofertas_secundarias(self, request, oferta_original_id=None):
        """
        Lista las ofertas secundarias de una oferta original
        """
        try:
            oferta_original = OfertaProveedor.objects.get(id=oferta_original_id)
        except OfertaProveedor.DoesNotExist:
            return Response(
                {'error': 'Oferta original no encontrada'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Validar permisos: solo el proveedor de la oferta original o el cliente de la solicitud
        user = request.user
        puede_ver = False
        
        if hasattr(user, 'cliente'):
            puede_ver = oferta_original.solicitud.cliente == user.cliente
        elif hasattr(user, 'taller') or hasattr(user, 'mecanico_domicilio'):
            puede_ver = oferta_original.proveedor == user
        elif user.is_staff:
            puede_ver = True
        
        if not puede_ver:
            return Response(
                {'error': 'No tienes permiso para ver estas ofertas secundarias'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        ofertas_secundarias = oferta_original.ofertas_secundarias.all()
        serializer = self.get_serializer(ofertas_secundarias, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'], url_path='crear-oferta-secundaria')
    def crear_oferta_secundaria(self, request, pk=None):
        """
        Crea una oferta secundaria desde una oferta original
        """
        oferta_original = self.get_object()
        
        # Validar que el usuario es el proveedor de la oferta original
        if oferta_original.proveedor != request.user:
            return Response(
                {'error': 'Solo puedes crear ofertas secundarias para tus propias ofertas'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Validar que la oferta original está pagada o en ejecución
        if oferta_original.estado not in ['pagada', 'en_ejecucion']:
            return Response(
                {'error': 'Solo se pueden crear ofertas secundarias cuando la oferta original está pagada o en ejecución'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Preparar datos para crear la oferta secundaria
        datos_oferta = request.data.copy()
        datos_oferta['oferta_original'] = str(oferta_original.id)
        datos_oferta['solicitud'] = str(oferta_original.solicitud.id)
        datos_oferta['es_oferta_secundaria'] = True
        
        # Validar que el motivo esté presente
        if 'motivo_servicio_adicional' not in datos_oferta or not datos_oferta.get('motivo_servicio_adicional', '').strip():
            return Response(
                {'error': 'El motivo del servicio adicional es obligatorio'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Usar el serializer para crear la oferta secundaria
        serializer = self.get_serializer(data=datos_oferta)
        if serializer.is_valid():
            try:
                oferta_secundaria = serializer.save(
                    proveedor=request.user,
                    tipo_proveedor=oferta_original.tipo_proveedor,
                    oferta_original=oferta_original,
                    es_oferta_secundaria=True
                )
                
                # Crear detalles de servicios si vienen en el request
                detalles_data = request.data.get('detalles_servicios', [])
                if detalles_data:
                    for detalle_data in detalles_data:
                        # Similar a perform_create
                        tiempo_horas = detalle_data.get('tiempo_estimado_horas', 1)
                        tiempo_estimado = timedelta(hours=float(tiempo_horas))
                        precio_servicio = Decimal(str(detalle_data['precio_servicio']))
                        repuestos_data = detalle_data.get('repuestos_seleccionados', [])
                        
                        DetalleServicioOferta.objects.create(
                            oferta=oferta_secundaria,
                            servicio_id=detalle_data['servicio'],
                            precio_servicio=precio_servicio,
                            tiempo_estimado=tiempo_estimado,
                            notas=detalle_data.get('notas', ''),
                            repuestos_seleccionados=repuestos_data
                        )
                
                return Response(
                    self.get_serializer(oferta_secundaria).data,
                    status=status.HTTP_201_CREATED
                )
            except Exception as e:
                logger.error(f"Error creando oferta secundaria: {str(e)}", exc_info=True)
                return Response(
                    {'error': f'Error al crear la oferta secundaria: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'], url_path='pagar-oferta-secundaria')
    def pagar_oferta_secundaria(self, request, pk=None):
        """
        Prepara el pago de una oferta secundaria.
        Crea la SolicitudServicio y retorna datos para el pago.
        NO cambia el estado a 'pagada' hasta que el pago se complete realmente.
        Similar al flujo de órdenes primarias.
        """
        logger = logging.getLogger(__name__)
        logger.info(f"Preparando pago de oferta secundaria {pk}")
        
        try:
            oferta = self.get_object()
            
            # Validar que es una oferta secundaria
            if not oferta.es_oferta_secundaria:
                return Response(
                    {'error': 'Esta no es una oferta secundaria'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validar que el usuario es el cliente de la solicitud
            if oferta.solicitud.cliente.usuario != request.user:
                return Response(
                    {'error': 'No está autorizado para pagar esta oferta'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Validar que la oferta está en estado 'aceptada' o 'pendiente_pago'
            # Las ofertas secundarias aceptadas pueden pagarse como cualquier orden independiente
            # (igual que las órdenes principales)
            # 'pendiente_pago' permite reintentar el pago si el proceso anterior no se completó
            if oferta.estado not in ['aceptada', 'pendiente_pago']:
                return Response(
                    {'error': f'La oferta secundaria debe estar en estado "aceptada" o "pendiente_pago" para poder pagarse. Estado actual: {oferta.estado}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Obtener datos del request
            metodo_pago = request.data.get('metodo_pago', 'mercadopago')
            notas_cliente = request.data.get('notas_cliente', '')
            
            logger.info(f"Datos de pago - Método: {metodo_pago}")
            
            # Determinar proveedor (acceder a través de oferta.proveedor)
            if oferta.tipo_proveedor == 'taller':
                if not hasattr(oferta.proveedor, 'taller') or not oferta.proveedor.taller:
                    logger.error(f"Proveedor {oferta.proveedor.id} no tiene taller asociado")
                    return Response(
                        {'error': 'El proveedor no tiene un taller asociado'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                taller = oferta.proveedor.taller
                mecanico = None
                tipo_servicio = 'taller'
                ubicacion_servicio = taller.direccion if taller else None
            else:
                if not hasattr(oferta.proveedor, 'mecanico_domicilio') or not oferta.proveedor.mecanico_domicilio:
                    logger.error(f"Proveedor {oferta.proveedor.id} no tiene mecánico asociado")
                    return Response(
                        {'error': 'El proveedor no tiene un mecánico asociado'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                taller = None
                mecanico = oferta.proveedor.mecanico_domicilio
                tipo_servicio = 'domicilio'
                ubicacion_servicio = oferta.solicitud.direccion_servicio_texto
            
            logger.info(f"Proveedor - Tipo: {tipo_servicio}, Taller: {taller.id if taller else None}, Mecánico: {mecanico.id if mecanico else None}")
            
            with transaction.atomic():
                # ✅ PASO 1: Actualizar estado a 'pendiente_pago' (cliente está procesando el pago)
                # NO cambiar a 'pagada' hasta que el pago se complete realmente
                if oferta.estado != 'pendiente_pago':
                    oferta.estado = 'pendiente_pago'
                    oferta.save(update_fields=['estado'])
                    logger.info(f"Estado actualizado: oferta secundaria → 'pendiente_pago'")
                
                # ✅ Notificar al proveedor que el cliente está pagando
                try:
                    channel_layer = get_channel_layer()
                    if channel_layer:
                        async_to_sync(channel_layer.group_send)(
                            f"proveedor_{oferta.proveedor.id}",
                            {
                                'type': 'pago_en_proceso',
                                'oferta_id': str(oferta.id),
                                'solicitud_id': str(oferta.solicitud.id),
                                'mensaje': 'El cliente está procesando el pago de tu oferta secundaria.',
                                'estado_oferta': 'pendiente_pago',
                                'monto_total': float(oferta.precio_total_ofrecido),
                                'es_oferta_secundaria': True,
                                'timestamp': timezone.now().isoformat()
                            }
                        )
                        logger.info(f"Notificación 'pago_en_proceso' enviada al proveedor: {oferta.proveedor.id}")
                except Exception as e:
                    logger.error(f"Error enviando notificación WebSocket: {e}", exc_info=True)
                
                # ✅ PASO 2: Obtener detalles de servicios de la oferta (necesario para ambos casos)
                # Esto debe estar fuera del bloque if/else para estar disponible siempre
                from mecanimovilapp.apps.servicios.models import OfertaServicio
                detalles_servicios = list(oferta.detalles_servicios.all())
                
                if not detalles_servicios:
                    logger.error(f"Oferta secundaria {oferta.id} no tiene detalles de servicios")
                    raise ValueError('La oferta secundaria no tiene servicios asociados')
                
                logger.info(f"Oferta secundaria tiene {len(detalles_servicios)} servicios")
                
                # ✅ PASO 3: Crear SolicitudServicio con estado 'confirmado' (similar a órdenes primarias)
                # Verificar si ya existe una SolicitudServicio para esta oferta
                # SolicitudServicio ya está importado en la línea 8, no es necesario importarlo nuevamente
                solicitud_servicio_existente = SolicitudServicio.objects.filter(
                    oferta_proveedor=oferta
                ).first()
                
                if solicitud_servicio_existente:
                    logger.info(f"Usando SolicitudServicio existente: {solicitud_servicio_existente.id}")
                    solicitud_servicio = solicitud_servicio_existente
                else:
                    solicitud_servicio = SolicitudServicio.objects.create(
                        cliente=oferta.solicitud.cliente,
                        vehiculo=oferta.solicitud.vehiculo,
                        tipo_servicio=tipo_servicio,
                        taller=taller,
                        mecanico=mecanico,
                        fecha_servicio=oferta.fecha_disponible or timezone.now().date(),
                        hora_servicio=oferta.hora_disponible or timezone.now().time(),
                        metodo_pago=metodo_pago,
                        total=oferta.precio_total_ofrecido,
                        estado='confirmado',  # ✅ Directamente confirmado (no requiere aceptación del proveedor)
                        notas_cliente=notas_cliente or f"Servicio adicional: {oferta.motivo_servicio_adicional}",
                        ubicacion_servicio=ubicacion_servicio,
                        comprobante_validado=False,
                        devolucion_procesada=False,
                        requiere_devolucion=False,
                        oferta_proveedor=oferta  # ✅ Asociar con la oferta secundaria que originó esta solicitud
                    )
                    logger.info(f"SolicitudServicio creada para oferta secundaria: {solicitud_servicio.id} con estado 'confirmado'")
                    
                    logger.info(f"Procesando {len(detalles_servicios)} servicios para crear líneas")
                    
                    # Tipo de proveedor para OfertaServicio
                    tipo_proveedor_servicio = oferta.tipo_proveedor
                    
                    # Crear líneas de servicio solo si no existen
                    # LineaServicio ya está importado al inicio del archivo desde .models
                    lineas_existentes = LineaServicio.objects.filter(solicitud=solicitud_servicio).count()
                    
                    if lineas_existentes == 0:
                        for detalle in detalles_servicios:
                            logger.info(f"Procesando servicio: {detalle.servicio.nombre}, Precio: {detalle.precio_servicio}")
                            
                            # Buscar o crear OfertaServicio
                            try:
                                oferta_servicio = OfertaServicio.objects.get(
                                    servicio=detalle.servicio,
                                    tipo_proveedor=tipo_proveedor_servicio,
                                    taller=taller,
                                    mecanico=mecanico
                                )
                                logger.info(f"OfertaServicio encontrada: {oferta_servicio.id}")
                            except OfertaServicio.DoesNotExist:
                                # Crear OfertaServicio temporal
                                logger.info("Creando OfertaServicio temporal para línea de servicio")
                                
                                # Calcular costos desde el precio ofrecido
                                precio_ofrecido = Decimal(str(detalle.precio_servicio))
                                precio_sin_iva = precio_ofrecido / Decimal('1.19')
                                
                                # Si incluye repuestos, dividir 70/30
                                if oferta.incluye_repuestos:
                                    costo_mano_de_obra = precio_sin_iva * Decimal('0.70')
                                    costo_repuestos = precio_sin_iva * Decimal('0.30')
                                    tipo_servicio_linea = 'con_repuestos'
                                else:
                                    costo_mano_de_obra = precio_sin_iva
                                    costo_repuestos = Decimal('0')
                                    tipo_servicio_linea = 'sin_repuestos'
                                
                                # Calcular precios con y sin repuestos (requeridos por el modelo)
                                # El precio_ofrecido es el precio final con IVA
                                precio_con_repuestos = precio_ofrecido
                                precio_sin_repuestos = precio_ofrecido
                                
                                oferta_servicio = OfertaServicio.objects.create(
                                    servicio=detalle.servicio,
                                    tipo_proveedor=tipo_proveedor_servicio,
                                    taller=taller,
                                    mecanico=mecanico,
                                    precio_con_repuestos=precio_con_repuestos,
                                    precio_sin_repuestos=precio_sin_repuestos,
                                    costo_mano_de_obra_sin_iva=costo_mano_de_obra,
                                    costo_repuestos_sin_iva=costo_repuestos,
                                    tipo_servicio=tipo_servicio_linea,
                                    disponible=True
                                )
                                logger.info(f"OfertaServicio temporal creada: {oferta_servicio.id}")
                            
                            # Crear línea de servicio
                            precio_unitario = detalle.precio_servicio
                            
                            LineaServicio.objects.create(
                                solicitud=solicitud_servicio,
                                oferta_servicio=oferta_servicio,
                                con_repuestos=oferta.incluye_repuestos,
                                cantidad=1,
                                precio_unitario=precio_unitario,
                                precio_final=precio_unitario
                            )
                            
                            logger.info(f"Línea de servicio creada para {detalle.servicio.nombre}")
                    else:
                        logger.info(f"Las líneas de servicio ya existen para SolicitudServicio {solicitud_servicio.id}")
            
            # Retornar datos para el pago (NO cambiar estado a 'pagada' hasta que el pago se complete)
            from .serializers import SolicitudServicioSerializer
            solicitud_servicio_serializer = SolicitudServicioSerializer(solicitud_servicio)
            
            # Datos del resumen para el pago
            resumen_pago = {
                'solicitud_servicio_id': solicitud_servicio.id,
                'solicitud_publica_id': oferta.solicitud.id,
                'oferta_id': oferta.id,
                'oferta_original_id': str(oferta.oferta_original.id) if oferta.oferta_original else None,
                'monto_total': float(solicitud_servicio.total),
                'metodo_pago': metodo_pago,
                'es_oferta_secundaria': True,
                'proveedor': {
                    'id': oferta.proveedor.id,
                    'nombre': oferta.nombre_proveedor,
                    'tipo': tipo_servicio
                },
                'servicios': [
                    {
                        'nombre': detalle.servicio.nombre,
                        'precio': float(detalle.precio_servicio),
                        'tiempo_estimado': str(detalle.tiempo_estimado) if detalle.tiempo_estimado else None
                    }
                    for detalle in detalles_servicios
                ],
                'fecha_servicio': str(solicitud_servicio.fecha_servicio),
                'hora_servicio': str(solicitud_servicio.hora_servicio),
                'ubicacion': ubicacion_servicio,
                'motivo_servicio_adicional': oferta.motivo_servicio_adicional
            }
            
            logger.info(f"Oferta secundaria preparada para pago - SolicitudServicio: {solicitud_servicio.id}, Estado: pendiente_pago (NO pagada aún)")
            
            # Recargar la oferta para obtener el estado actualizado
            oferta.refresh_from_db()
            
            return Response({
                'mensaje': 'Oferta secundaria lista para pago',
                'solicitud_servicio': solicitud_servicio_serializer.data,
                'resumen_pago': resumen_pago,
                'oferta_actualizada': {
                    'id': str(oferta.id),
                    'estado': oferta.estado,
                    'solicitud_servicio_id': str(solicitud_servicio.id)
                }
            }, status=status.HTTP_200_OK)
            
        except ValueError as e:
            logger.error(f"Error de validación: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Error procesando pago de oferta secundaria {pk}: {e}", exc_info=True)
            return Response(
                {'error': f'Error al procesar el pago: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'], url_path='iniciar-servicio')
    def iniciar_servicio(self, request, pk=None):
        """
        Permite al proveedor iniciar el servicio desde una oferta pagada.
        Cambia el estado a en_ejecucion y crea/habilita el checklist si existe.
        """
        logger = logging.getLogger(__name__)
        logger.info(f"Iniciando servicio para oferta {pk}")
        
        try:
            oferta = self.get_object()
            
            # Validaciones
            if oferta.proveedor != request.user:
                logger.warning(f"Usuario no autorizado intenta iniciar servicio {pk}")
                return Response(
                    {'error': 'No está autorizado para iniciar este servicio'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # ✅ Permitir iniciar servicio para ofertas secundarias también
            # Las ofertas secundarias son servicios independientes que deben poder iniciarse
            # ✅ Permitir iniciar si está pagada o pagada_parcialmente (si ya se pagó al menos una parte)
            estados_validos_iniciar = ['pagada', 'pagada_parcialmente']
            if oferta.estado not in estados_validos_iniciar:
                return Response(
                    {'error': f'Solo se pueden iniciar servicios desde ofertas pagadas (total o parcialmente). Estado actual: {oferta.estado}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            solicitud = oferta.solicitud
            
            with transaction.atomic():
                # Buscar SolicitudServicio asociada
                solicitud_servicio = SolicitudServicio.objects.filter(oferta_proveedor=oferta).first()
                
                if not solicitud_servicio:
                    # Si no existe, crear una nueva
                    logger.info(f"Creando SolicitudServicio para oferta {oferta.id}")
                    
                    # Determinar proveedor
                    if oferta.tipo_proveedor == 'taller':
                        taller = oferta.proveedor.taller
                        mecanico = None
                        tipo_servicio = 'taller'
                        ubicacion_servicio = taller.direccion if taller else None
                    else:
                        taller = None
                        mecanico = oferta.proveedor.mecanico_domicilio
                        tipo_servicio = 'domicilio'
                        ubicacion_servicio = solicitud.direccion_servicio_texto
                    
                    solicitud_servicio = SolicitudServicio.objects.create(
                        cliente=solicitud.cliente,
                        vehiculo=solicitud.vehiculo,
                        tipo_servicio=tipo_servicio,
                        taller=taller,
                        mecanico=mecanico,
                        fecha_servicio=oferta.fecha_disponible or timezone.now().date(),
                        hora_servicio=oferta.hora_disponible or timezone.now().time(),
                        metodo_pago='transferencia',  # Default, ya fue pagado
                        total=oferta.precio_total_ofrecido,
                        estado='confirmado',
                        notas_cliente=solicitud.descripcion_problema or '',
                        ubicacion_servicio=ubicacion_servicio,
                        comprobante_validado=True,  # Ya fue pagado
                        devolucion_procesada=False,
                        requiere_devolucion=False,
                        oferta_proveedor=oferta
                    )
                    
                    # Crear líneas de servicio
                    from mecanimovilapp.apps.servicios.models import OfertaServicio
                    detalles_servicios = list(oferta.detalles_servicios.all())
                    tipo_proveedor_servicio = oferta.tipo_proveedor
                    
                    for detalle in detalles_servicios:
                        try:
                            oferta_servicio = OfertaServicio.objects.get(
                                servicio=detalle.servicio,
                                tipo_proveedor=tipo_proveedor_servicio,
                                taller=taller,
                                mecanico=mecanico
                            )
                        except OfertaServicio.DoesNotExist:
                            # Crear OfertaServicio temporal
                            from decimal import Decimal
                            precio_ofrecido = Decimal(str(detalle.precio_servicio))
                            precio_sin_iva = precio_ofrecido / Decimal('1.19')
                            
                            if oferta.incluye_repuestos:
                                costo_mano_de_obra = precio_sin_iva * Decimal('0.70')
                                costo_repuestos = precio_sin_iva * Decimal('0.30')
                            else:
                                costo_mano_de_obra = precio_sin_iva
                                costo_repuestos = Decimal('0')
                            
                            oferta_servicio = OfertaServicio.objects.create(
                                servicio=detalle.servicio,
                                tipo_proveedor=tipo_proveedor_servicio,
                                taller=taller,
                                mecanico=mecanico,
                                costo_mano_de_obra_sin_iva=costo_mano_de_obra,
                                costo_repuestos_sin_iva=costo_repuestos,
                                disponible=True
                            )
                        
                        LineaServicio.objects.create(
                            solicitud=solicitud_servicio,
                            oferta_servicio=oferta_servicio,
                            con_repuestos=oferta.incluye_repuestos,
                            cantidad=1,
                            precio_unitario=detalle.precio_servicio,
                            precio_final=detalle.precio_servicio
                        )
                    
                    logger.info(f"SolicitudServicio creada: {solicitud_servicio.id}")
                
                # Cambiar estado de oferta a en_ejecucion
                oferta.estado = 'en_ejecucion'
                oferta.save(update_fields=['estado'])
                
                # Cambiar estado de solicitud pública a en_ejecucion
                solicitud.estado = 'en_ejecucion'
                solicitud.save(update_fields=['estado'])
                
                # Buscar checklist template del servicio configurado
                # Manejar el caso cuando no hay checklist disponible sin fallar
                try:
                    from mecanimovilapp.apps.checklists.models import ChecklistTemplate, ChecklistInstance
                    
                    detalles_servicios = list(oferta.detalles_servicios.all())
                    logger.info(f'🔍 Buscando checklist para oferta {oferta.id} con {len(detalles_servicios)} servicios')
                    checklist_creado = False
                    
                    for detalle in detalles_servicios:
                        servicio = detalle.servicio
                        logger.info(
                            f'🔍 Buscando checklist template para servicio {servicio.id} ({servicio.nombre}) '
                            f'en orden {solicitud_servicio.id}'
                        )
                        
                        try:
                            # Buscar template activo para este servicio
                            # ✅ Usar 'activo' en lugar de 'disponible'
                            template = ChecklistTemplate.objects.filter(
                                servicio=servicio,
                                activo=True
                            ).first()
                            
                            if template:
                                logger.info(
                                    f'✅ Template encontrado: {template.nombre} (ID: {template.id}) '
                                    f'para servicio {servicio.nombre}'
                                )
                                # Verificar que no exista ya una instancia para esta solicitud_servicio
                                existing_instance = ChecklistInstance.objects.filter(orden=solicitud_servicio).first()
                                if not existing_instance:
                                    # Crear automáticamente la instancia de checklist
                                    checklist_instance = ChecklistInstance.objects.create(
                                        orden=solicitud_servicio,
                                        checklist_template=template,
                                        estado='PENDIENTE'
                                    )
                                    logger.info(f'✅ Checklist creado automáticamente: {checklist_instance.id} para orden {solicitud_servicio.id} con template {template.id}')
                                    
                                    # Cambiar estado de solicitud_servicio a checklist_en_progreso
                                    solicitud_servicio.estado = 'checklist_en_progreso'
                                    solicitud_servicio.save(update_fields=['estado'])
                                    checklist_creado = True
                                    break  # Solo crear un checklist (el primero encontrado)
                                else:
                                    logger.info(f'⚠️ Ya existe checklist para orden {solicitud_servicio.id}: {existing_instance.id}')
                                    # Si ya existe checklist, cambiar a checklist_en_progreso si no está en ese estado
                                    if solicitud_servicio.estado != 'checklist_en_progreso':
                                        solicitud_servicio.estado = 'checklist_en_progreso'
                                        solicitud_servicio.save(update_fields=['estado'])
                                    checklist_creado = True
                                    break
                            else:
                                logger.warning(
                                    f'⚠️ No se encontró checklist template activo para servicio {servicio.id} ({servicio.nombre}). '
                                    f'Verificar que existe un ChecklistTemplate con servicio={servicio.id} y activo=True'
                                )
                        except Exception as e:
                            logger.warning(f'⚠️ Error buscando checklist template para servicio {servicio.id}: {e}')
                            # Continuar con el siguiente servicio
                            continue
                    
                    if not checklist_creado:
                        logger.info(f'ℹ️ No se encontró checklist template para los servicios de la oferta {oferta.id}. El servicio continuará sin checklist.')
                        # Si no hay checklist, el servicio puede continuar sin él
                        # El estado de solicitud_servicio permanece en 'confirmado' o 'en_ejecucion'
                        
                except ImportError:
                    logger.warning('⚠️ No se pudo importar modelos de checklist. El servicio continuará sin checklist.')
                except Exception as e:
                    logger.error(f'❌ Error inesperado en proceso de checklist: {e}', exc_info=True)
                    # No fallar la operación si falla la creación del checklist
                    # El servicio puede continuar sin checklist
                
                # Notificar al cliente vía WebSocket
                try:
                    channel_layer = get_channel_layer()
                    if channel_layer and solicitud.cliente and solicitud.cliente.usuario:
                        async_to_sync(channel_layer.group_send)(
                            f"cliente_{solicitud.cliente.usuario.id}",
                            {
                                'type': 'servicio_iniciado',
                                'oferta_id': str(oferta.id),
                                'solicitud_id': str(solicitud.id),
                                'proveedor_nombre': oferta.nombre_proveedor,
                                'mensaje': 'El proveedor ha iniciado el servicio.',
                                'timestamp': timezone.now().isoformat()
                            }
                        )
                        logger.info(f"Notificación WebSocket 'servicio_iniciado' enviada al cliente: {solicitud.cliente.usuario.id}")
                except Exception as e:
                    logger.error(f"Error enviando notificación WebSocket: {e}", exc_info=True)
            
            # Serializar respuesta
            serializer = self.get_serializer(oferta)
            # Actualizar el serializer data con solicitud_servicio_id
            oferta_data = serializer.data
            if solicitud_servicio:
                oferta_data['solicitud_servicio_id'] = solicitud_servicio.id
            
            return Response({
                'mensaje': 'Servicio iniciado exitosamente',
                'oferta': oferta_data,
                'solicitud_servicio_id': solicitud_servicio.id if solicitud_servicio else None,
                'tiene_checklist': checklist_creado if 'checklist_creado' in locals() else False
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error iniciando servicio para oferta {pk}: {e}", exc_info=True)
            return Response(
                {'error': f'Error al iniciar el servicio: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'], url_path='terminar-servicio')
    def terminar_servicio(self, request, pk=None):
        """
        Permite al proveedor terminar el servicio cuando el checklist está completado.
        Cambia el estado a completada y cierra la oferta y solicitud.
        """
        logger = logging.getLogger(__name__)
        logger.info(f"Terminando servicio para oferta {pk}")
        
        try:
            oferta = self.get_object()
            
            # Validaciones
            if oferta.proveedor != request.user:
                logger.warning(f"Usuario no autorizado intenta terminar servicio {pk}")
                return Response(
                    {'error': 'No está autorizado para terminar este servicio'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            if oferta.es_oferta_secundaria:
                return Response(
                    {'error': 'No se puede terminar servicio para ofertas secundarias. Use la oferta original.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if oferta.estado != 'en_ejecucion':
                return Response(
                    {'error': f'Solo se pueden terminar servicios en ejecución. Estado actual: {oferta.estado}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            solicitud = oferta.solicitud
            
            # Buscar SolicitudServicio asociada
            solicitud_servicio = SolicitudServicio.objects.filter(oferta_proveedor=oferta).first()
            
            # Validar checklist si existe
            if solicitud_servicio:
                try:
                    from mecanimovilapp.apps.checklists.models import ChecklistInstance
                    checklist = ChecklistInstance.objects.filter(orden=solicitud_servicio).first()
                    
                    if checklist and checklist.estado != 'COMPLETADO':
                        return Response(
                            {'error': 'No se puede terminar el servicio sin completar el checklist'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                except ImportError:
                    pass  # Si no hay app de checklists, continuar
                except Exception as e:
                    logger.error(f'Error validando checklist: {e}', exc_info=True)
                    # Continuar si hay error validando checklist
            
            with transaction.atomic():
                # Cambiar estado de oferta a completada
                oferta.estado = 'completada'
                oferta.save(update_fields=['estado'])
                
                # Cambiar estado de solicitud pública a completada
                solicitud.estado = 'completada'
                solicitud.save(update_fields=['estado'])
                
                # Cambiar estado de SolicitudServicio a completado si existe
                if solicitud_servicio:
                    solicitud_servicio.estado = 'completado'
                    solicitud_servicio.save(update_fields=['estado'])
                
                # Notificar al cliente vía WebSocket
                try:
                    channel_layer = get_channel_layer()
                    if channel_layer and solicitud.cliente and solicitud.cliente.usuario:
                        async_to_sync(channel_layer.group_send)(
                            f"cliente_{solicitud.cliente.usuario.id}",
                            {
                                'type': 'servicio_completado',
                                'oferta_id': str(oferta.id),
                                'solicitud_id': str(solicitud.id),
                                'proveedor_nombre': oferta.nombre_proveedor,
                                'mensaje': 'El proveedor ha completado el servicio.',
                                'timestamp': timezone.now().isoformat()
                            }
                        )
                        logger.info(f"Notificación WebSocket 'servicio_completado' enviada al cliente: {solicitud.cliente.usuario.id}")
                except Exception as e:
                    logger.error(f"Error enviando notificación WebSocket: {e}", exc_info=True)
            
            # Serializar respuesta
            serializer = self.get_serializer(oferta)
            return Response({
                'mensaje': 'Servicio terminado exitosamente',
                'oferta': serializer.data
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error terminando servicio para oferta {pk}: {e}", exc_info=True)
            return Response(
                {'error': f'Error al terminar el servicio: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'], url_path='rechazar-oferta')
    def rechazar_oferta(self, request, pk=None):
        """
        Permite al cliente rechazar una oferta (especialmente útil para ofertas secundarias)
        """
        try:
            oferta = self.get_object()
            
            # Verificar que el usuario es el cliente de la solicitud
            solicitud = oferta.solicitud
            if not hasattr(request.user, 'cliente') or solicitud.cliente != request.user.cliente:
                return Response(
                    {'error': 'Solo el cliente de la solicitud puede rechazar ofertas'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Validar que la oferta puede ser rechazada
            if oferta.estado in ['rechazada', 'aceptada', 'pagada', 'en_ejecucion', 'completada']:
                return Response(
                    {'error': f'No se puede rechazar una oferta en estado: {oferta.get_estado_display()}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Marcar oferta como rechazada
            oferta.estado = 'rechazada'
            oferta.fecha_respuesta_cliente = timezone.now()
            oferta.save(update_fields=['estado', 'fecha_respuesta_cliente'])
            
            logger.info(f"Oferta {oferta.id} rechazada por cliente {request.user.cliente.id}")
            
            # Notificar al proveedor
            try:
                channel_layer = get_channel_layer()
                if channel_layer:
                    async_to_sync(channel_layer.group_send)(
                        f"proveedor_{oferta.proveedor.id}",
                        {
                            'type': 'oferta_rechazada',
                            'oferta_id': str(oferta.id),
                            'solicitud_id': str(solicitud.id),
                            'mensaje': 'El cliente ha rechazado tu oferta.',
                            'es_oferta_secundaria': oferta.es_oferta_secundaria,
                            'estado_oferta': 'rechazada',
                            'timestamp': timezone.now().isoformat()
                        }
                    )
                    logger.info(f"Notificación WebSocket 'oferta_rechazada' enviada al proveedor: {oferta.proveedor.id}")
            except Exception as e:
                logger.error(f"Error enviando notificación WebSocket: {e}", exc_info=True)
            
            # Serializar respuesta
            serializer = self.get_serializer(oferta)
            return Response({
                'mensaje': 'Oferta rechazada exitosamente',
                'oferta': serializer.data
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error rechazando oferta {pk}: {e}", exc_info=True)
            return Response(
                {'error': f'Error al rechazar la oferta: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def destroy(self, request, *args, **kwargs):
        """
        Retira una oferta (soft delete)
        """
        oferta = self.get_object()
        
        if oferta.proveedor != request.user:
            return Response(
                {'error': 'No tienes permiso para esta acción'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if oferta.estado == 'aceptada':
            return Response(
                {'error': 'No se puede retirar una oferta aceptada'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        oferta.estado = 'retirada'
        oferta.save()
        
        return Response({'message': 'Oferta retirada exitosamente'}, status=status.HTTP_204_NO_CONTENT)

class ChatSolicitudViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar mensajes de chat entre cliente y proveedor
    """
    queryset = ChatSolicitud.objects.all()
    serializer_class = ChatSolicitudSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['fecha_envio']
    ordering = ['fecha_envio']
    
    def get_queryset(self):
        """
        Filtra mensajes donde el usuario es cliente o proveedor
        """
        user = self.request.user
        
        if user.is_staff or user.is_superuser:
            return ChatSolicitud.objects.select_related(
                'oferta', 'oferta__solicitud', 'oferta__proveedor', 'enviado_por'
            )
        
        # Cliente viendo mensajes de sus ofertas
        if hasattr(user, 'cliente'):
            return ChatSolicitud.objects.filter(
                oferta__solicitud__cliente=user.cliente
            ).select_related(
                'oferta', 'oferta__solicitud', 'oferta__proveedor', 'enviado_por'
            )
        
        # Proveedor viendo mensajes de sus ofertas
        return ChatSolicitud.objects.filter(
            oferta__proveedor=user
        ).select_related(
            'oferta', 'oferta__solicitud', 'oferta__proveedor', 'enviado_por'
        )
    
    def perform_create(self, serializer):
        """
        Crea un mensaje y valida permisos
        """
        oferta = serializer.validated_data['oferta']
        user = self.request.user
        
        # ✅ Verificar y procesar solicitudes expiradas antes de permitir chat
        procesar_solicitudes_expiradas()
        
        # Recargar la oferta y su solicitud para obtener el estado actualizado
        oferta.refresh_from_db()
        oferta.solicitud.refresh_from_db()
        
        # ✅ Validar que la solicitud esté activa y vigente
        if oferta.solicitud.estado in ['cancelada', 'expirada']:
            raise permissions.PermissionDenied(
                "No se puede chatear en una solicitud cancelada o expirada"
            )
        
        # ✅ Validar que la oferta esté en un estado válido para chatear
        if oferta.estado in ['rechazada', 'retirada', 'expirada']:
            raise permissions.PermissionDenied(
                "No se puede chatear en una oferta rechazada, retirada o expirada"
            )
        
        # ✅ Validar que si la solicitud está adjudicada, la oferta debe ser la seleccionada o estar en estado válido
        if oferta.solicitud.estado == 'adjudicada':
            # Solo permitir chat si la oferta es la seleccionada o está en estados válidos
            if oferta.solicitud.oferta_seleccionada != oferta:
                if oferta.estado not in ['enviada', 'vista', 'en_chat']:
                    raise permissions.PermissionDenied(
                        "No se puede chatear en una oferta que no está activa"
                    )
        
        # Determinar si es proveedor o cliente
        es_proveedor = not hasattr(user, 'cliente')
        
        # Validar que el usuario puede enviar mensajes en esta oferta
        if hasattr(user, 'cliente'):
            if oferta.solicitud.cliente != user.cliente:
                raise permissions.PermissionDenied(
                    "No tienes permiso para enviar mensajes en esta oferta"
                )
        else:
            if oferta.proveedor != user:
                raise permissions.PermissionDenied(
                    "No tienes permiso para enviar mensajes en esta oferta"
                )
        
        # Guardar el mensaje con los campos automáticos
        mensaje = serializer.save(
            enviado_por=user,
            es_proveedor=es_proveedor
        )
        
        # Marcar mensajes anteriores como leídos (del otro usuario)
        ChatSolicitud.objects.filter(
            oferta=oferta,
            es_proveedor=not mensaje.es_proveedor,
            leido=False
        ).update(
            leido=True,
            fecha_lectura=timezone.now()
        )
        
        # Notificar al destinatario vía WebSocket
        try:
            channel_layer = get_channel_layer()
            
            # Determinar destinatario
            if mensaje.es_proveedor:
                # Mensaje del proveedor, notificar al cliente
                if not oferta.solicitud.cliente or not oferta.solicitud.cliente.usuario:
                    logger.warning(f"No se pudo enviar notificación: cliente o usuario no disponible para oferta {oferta.id}")
                    return Response({'error': 'Cliente o usuario no disponible'}, status=status.HTTP_400_BAD_REQUEST)
                destinatario_id = oferta.solicitud.cliente.usuario.id
                grupo = f"cliente_{destinatario_id}"
            else:
                # Mensaje del cliente, notificar al proveedor
                destinatario_id = oferta.proveedor.id
                grupo = f"proveedor_{destinatario_id}"
            
            async_to_sync(channel_layer.group_send)(
                grupo,
                {
                    'type': 'nuevo_mensaje_chat',
                    'mensaje_id': str(mensaje.id),
                    'oferta_id': str(oferta.id),
                    'solicitud_id': str(oferta.solicitud.id),
                    'enviado_por': mensaje.enviado_por.get_full_name(),
                    'mensaje': mensaje.mensaje[:100],
                    'es_proveedor': mensaje.es_proveedor
                }
            )
        except Exception as e:
            logger.error(f"Error enviando notificación WebSocket: {e}")
    
    @action(detail=True, methods=['post'])
    def marcar_leido(self, request, pk=None):
        """
        Marca un mensaje como leído
        """
        mensaje = self.get_object()
        
        # Validar que el usuario puede marcar este mensaje como leído
        oferta = mensaje.oferta
        user = request.user
        
        if hasattr(user, 'cliente'):
            if oferta.solicitud.cliente != user.cliente:
                return Response(
                    {'error': 'No tienes permiso para esta acción'},
                    status=status.HTTP_403_FORBIDDEN
                )
        else:
            if oferta.proveedor != user:
                return Response(
                    {'error': 'No tienes permiso para esta acción'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        mensaje.marcar_como_leido()
        
        return Response({'message': 'Mensaje marcado como leído'})
    
    @action(detail=False, methods=['get'], url_path='por_oferta/(?P<oferta_id>[^/.]+)')
    def por_oferta(self, request, oferta_id=None):
        """
        Obtiene todos los mensajes de una oferta específica
        """
        try:
            oferta = OfertaProveedor.objects.get(id=oferta_id)
        except OfertaProveedor.DoesNotExist:
            return Response(
                {'error': 'Oferta no encontrada'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Validar permisos
        user = request.user
        if hasattr(user, 'cliente'):
            if oferta.solicitud.cliente != user.cliente:
                return Response(
                    {'error': 'No tienes permiso para ver estos mensajes'},
                    status=status.HTTP_403_FORBIDDEN
                )
        else:
            if oferta.proveedor != user:
                return Response(
                    {'error': 'No tienes permiso para ver estos mensajes'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        # Obtener mensajes ordenados por fecha de envío (más antiguos primero)
        mensajes = ChatSolicitud.objects.filter(oferta=oferta).order_by('fecha_envio')
        
        # Marcar mensajes del otro usuario como leídos
        if hasattr(user, 'cliente'):
            # Cliente viendo: marcar mensajes del proveedor como leídos
            ChatSolicitud.objects.filter(
                oferta=oferta,
                es_proveedor=True,
                leido=False
            ).update(leido=True, fecha_lectura=timezone.now())
        else:
            # Proveedor viendo: marcar mensajes del cliente como leídos
            ChatSolicitud.objects.filter(
                oferta=oferta,
                es_proveedor=False,
                leido=False
            ).update(leido=True, fecha_lectura=timezone.now())
        
        # Asegurar que el contexto del request se pase al serializer
        serializer = self.get_serializer(mensajes, many=True, context={'request': request})
        
        # Log para debug: verificar que proveedor_info y cliente_info están presentes
        if serializer.data and len(serializer.data) > 0:
            primer_mensaje = serializer.data[0]
            logger.info(f"📩 Primer mensaje del chat - Keys: {primer_mensaje.keys()}")
            logger.info(f"📩 proveedor_info presente: {'proveedor_info' in primer_mensaje}")
            logger.info(f"📩 cliente_info presente: {'cliente_info' in primer_mensaje}")
            if 'proveedor_info' in primer_mensaje:
                logger.info(f"📩 proveedor_info data: {primer_mensaje['proveedor_info']}")
        
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='lista-chats')
    def lista_chats(self, request):
        """
        Obtiene lista de todos los chats del usuario con metadata:
        - Último mensaje
        - Contador de mensajes no leídos
        - Información del cliente/proveedor
        - Ordenado por fecha del último mensaje
        """
        from django.db.models import Max, Count, Q, Prefetch
        
        user = request.user
        
        # Obtener ofertas con mensajes del usuario
        if hasattr(user, 'cliente'):
            # Cliente: ofertas de sus solicitudes que tienen mensajes
            ofertas_con_mensajes = OfertaProveedor.objects.filter(
                solicitud__cliente=user.cliente,
                mensajes_chat__isnull=False
            ).distinct().select_related(
                'solicitud', 'solicitud__cliente', 'solicitud__cliente__usuario',
                'solicitud__vehiculo', 'solicitud__vehiculo__marca', 
                'solicitud__vehiculo__modelo', 'proveedor'
            ).prefetch_related(
                Prefetch(
                    'mensajes_chat',
                    queryset=ChatSolicitud.objects.order_by('-fecha_envio')
                )
            ).annotate(
                ultimo_mensaje_fecha=Max('mensajes_chat__fecha_envio'),
                mensajes_no_leidos=Count(
                    'mensajes_chat',
                    filter=Q(mensajes_chat__leido=False, mensajes_chat__es_proveedor=True)
                )
            ).order_by('-ultimo_mensaje_fecha')
        else:
            # Proveedor: sus ofertas que tienen mensajes
            ofertas_con_mensajes = OfertaProveedor.objects.filter(
                proveedor=user,
                mensajes_chat__isnull=False
            ).distinct().select_related(
                'solicitud', 'solicitud__cliente', 'solicitud__cliente__usuario',
                'solicitud__vehiculo', 'solicitud__vehiculo__marca',
                'solicitud__vehiculo__modelo', 'proveedor'
            ).prefetch_related(
                Prefetch(
                    'mensajes_chat',
                    queryset=ChatSolicitud.objects.order_by('-fecha_envio')
                )
            ).annotate(
                ultimo_mensaje_fecha=Max('mensajes_chat__fecha_envio'),
                mensajes_no_leidos=Count(
                    'mensajes_chat',
                    filter=Q(mensajes_chat__leido=False, mensajes_chat__es_proveedor=False)
                )
            ).order_by('-ultimo_mensaje_fecha')
        
        # Construir respuesta con metadata
        chats_list = []
        for oferta in ofertas_con_mensajes:
            ultimo_mensaje = oferta.mensajes_chat.first()
            if not ultimo_mensaje:
                continue
            
            # Obtener info del cliente/proveedor según quien consulte
            if hasattr(user, 'cliente'):
                # Cliente viendo: mostrar info del proveedor
                try:
                    foto_url = None
                    if oferta.proveedor and oferta.proveedor.foto_perfil:
                        if request:
                            foto_url = request.build_absolute_uri(oferta.proveedor.foto_perfil.url)
                        else:
                            import socket
                            hostname = socket.gethostname()
                            ip_address = socket.gethostbyname(hostname)
                            foto_url = f"http://{ip_address}:8000{oferta.proveedor.foto_perfil.url}"
                except (AttributeError, ValueError):
                    foto_url = None
                
                # Obtener estado de conexión del proveedor desde ConnectionStatus
                esta_conectado = False
                if oferta.proveedor:
                    try:
                        if oferta.tipo_proveedor == 'mecanico':
                            # Para mecánicos, verificar en ConnectionStatus
                            try:
                                mecanico = oferta.proveedor.mecanico_domicilio
                                if mecanico:
                                    connection_status = ConnectionStatus.objects.filter(proveedor=mecanico).first()
                                    if connection_status:
                                        esta_conectado = connection_status.esta_conectado or connection_status.is_online
                                    else:
                                        # Fallback: verificar campo en el modelo
                                        esta_conectado = getattr(mecanico, 'esta_conectado', False)
                            except (AttributeError, Exception):
                                esta_conectado = False
                        elif oferta.tipo_proveedor == 'taller':
                            # Para talleres, verificar en ConnectionStatus
                            try:
                                taller = oferta.proveedor.taller
                                if taller:
                                    connection_status = ConnectionStatus.objects.filter(taller=taller).first()
                                    if connection_status:
                                        esta_conectado = connection_status.esta_conectado or connection_status.is_online
                                    else:
                                        # Fallback: verificar campo en el modelo
                                        esta_conectado = getattr(taller, 'esta_conectado', False)
                            except (AttributeError, Exception):
                                esta_conectado = False
                    except Exception:
                        # Si hay algún error, usar fallback a los campos del modelo
                        try:
                            if oferta.tipo_proveedor == 'mecanico':
                                mecanico = oferta.proveedor.mecanico_domicilio
                                esta_conectado = getattr(mecanico, 'esta_conectado', False) if mecanico else False
                            elif oferta.tipo_proveedor == 'taller':
                                taller = oferta.proveedor.taller
                                esta_conectado = getattr(taller, 'esta_conectado', False) if taller else False
                        except:
                            esta_conectado = False
                
                otra_persona = {
                    'id': oferta.proveedor.id if oferta.proveedor else None,
                    'nombre': oferta.nombre_proveedor or 'Proveedor',
                    'foto': foto_url,
                    'tipo': oferta.tipo_proveedor,
                    'esta_conectado': esta_conectado,
                }
            else:
                # Proveedor viendo: mostrar info del cliente
                try:
                    foto_url = None
                    cliente = oferta.solicitud.cliente
                    if cliente and cliente.usuario and cliente.usuario.foto_perfil:
                        if request:
                            foto_url = request.build_absolute_uri(cliente.usuario.foto_perfil.url)
                        else:
                            import socket
                            hostname = socket.gethostname()
                            ip_address = socket.gethostbyname(hostname)
                            foto_url = f"http://{ip_address}:8000{cliente.usuario.foto_perfil.url}"
                except (AttributeError, ValueError):
                    foto_url = None
                
                nombre_cliente = 'Cliente'
                try:
                    if cliente and cliente.usuario:
                        nombre_cliente = cliente.usuario.get_full_name()
                except:
                    pass
                
                otra_persona = {
                    'id': cliente.id if cliente else None,
                    'nombre': nombre_cliente,
                    'foto': foto_url,
                }
            
            # Agregar info del vehículo
            vehiculo_info = None
            try:
                vehiculo = oferta.solicitud.vehiculo
                if vehiculo:
                    vehiculo_info = {
                        'marca': vehiculo.marca.nombre if vehiculo.marca else None,
                        'modelo': vehiculo.modelo.nombre if vehiculo.modelo else None,
                        'year': vehiculo.year,
                        'patente': vehiculo.patente,
                    }
            except:
                pass
            
            chat_data = {
                'oferta_id': str(oferta.id),
                'solicitud_id': str(oferta.solicitud.id),
                'otra_persona': otra_persona,
                'vehiculo': vehiculo_info,
                'ultimo_mensaje': {
                    'id': str(ultimo_mensaje.id),
                    'mensaje': ultimo_mensaje.mensaje,
                    'fecha_envio': ultimo_mensaje.fecha_envio,
                    'es_propio': (
                        (hasattr(user, 'cliente') and not ultimo_mensaje.es_proveedor) or
                        (not hasattr(user, 'cliente') and ultimo_mensaje.es_proveedor)
                    ),
                    'leido': ultimo_mensaje.leido,
                },
                'mensajes_no_leidos': oferta.mensajes_no_leidos,
                'estado_oferta': oferta.estado,
            }
            chats_list.append(chat_data)
        
        return Response(chats_list)