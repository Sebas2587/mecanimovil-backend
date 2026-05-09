from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from .models import (
    ChecklistTemplate, ChecklistInstance, ChecklistItemResponse, 
    ChecklistPhoto
)
from .serializers import (
    ChecklistTemplateSerializer, ChecklistInstanceSerializer,
    ChecklistInstanceCreateSerializer, ChecklistItemResponseSerializer,
    ChecklistPhotoUploadSerializer
)


class ChecklistTemplateViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet para templates de checklist (solo lectura)"""
    serializer_class = ChecklistTemplateSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Filtrar templates por proveedor autenticado"""
        user = self.request.user
        
        # Si es taller - mostrar templates de servicios que el taller puede ofrecer
        if hasattr(user, 'taller'):
            return ChecklistTemplate.objects.filter(
                activo=True
            ).select_related('servicio').prefetch_related('items')
        
        # Si es mecánico a domicilio - mostrar templates de servicios que puede ofrecer
        elif hasattr(user, 'mecanico_domicilio'):
            return ChecklistTemplate.objects.filter(
                activo=True
            ).select_related('servicio').prefetch_related('items')
        
        # Si no es proveedor, no ver nada
        return ChecklistTemplate.objects.none()
    
    def retrieve(self, request, pk=None):
        """Override retrieve para manejar casos especiales del frontend"""
        # Si el frontend envía [object Object], intentar obtener el primer template disponible
        if pk == '[object Object]' or pk == '%5Bobject%20Object%5D':
            queryset = self.get_queryset()
            if queryset.exists():
                # Devolver el primer template disponible como fallback
                template = queryset.first()
                serializer = self.get_serializer(template)
                return Response(serializer.data)
            else:
                return Response(
                    {'error': 'No hay templates disponibles'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
        
        # Caso normal: pk es un ID válido
        try:
            int(pk)  # Verificar que pk es un número
            return super().retrieve(request, pk)
        except ValueError:
            # Si pk no es un número válido, devolver error más descriptivo
            return Response(
                {'error': f'ID de template inválido: {pk}. Debe ser un número.'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['get'])
    def by_service(self, request):
        """Obtener template de checklist por ID de servicio"""
        servicio_id = request.query_params.get('servicio_id')
        if not servicio_id:
            return Response(
                {'error': 'Se requiere el parámetro servicio_id'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            template = self.get_queryset().get(
                servicio_id=servicio_id, 
                activo=True
            )
            serializer = self.get_serializer(template)
            return Response(serializer.data)
        except ChecklistTemplate.DoesNotExist:
            return Response(
                {'error': 'No existe template de checklist para este servicio'}, 
                status=status.HTTP_404_NOT_FOUND
            )


class ChecklistInstanceViewSet(viewsets.ModelViewSet):
    """ViewSet para instancias de checklist"""
    serializer_class = ChecklistInstanceSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Filtrar checklist por proveedor autenticado"""
        user = self.request.user
        
        # Si es taller
        if hasattr(user, 'taller'):
            return ChecklistInstance.objects.filter(
                orden__taller=user.taller
            ).select_related(
                'orden', 'checklist_template'
            ).prefetch_related(
                'respuestas__fotos', 'respuestas__item_template'
            )
        
        # Si es mecánico a domicilio
        elif hasattr(user, 'mecanico_domicilio'):
            return ChecklistInstance.objects.filter(
                orden__mecanico=user.mecanico_domicilio
            ).select_related(
                'orden', 'checklist_template'
            ).prefetch_related(
                'respuestas__fotos', 'respuestas__item_template'
            )
        
        # Si no es proveedor, no ver nada
        return ChecklistInstance.objects.none()
    
    def get_serializer_class(self):
        """Usar serializer simplificado para creación"""
        if hasattr(self, 'action') and self.action == 'create':
            return ChecklistInstanceCreateSerializer
        return ChecklistInstanceSerializer
    
    def create(self, request, *args, **kwargs):
        """
        Crear nueva instancia de checklist y devolver instancia completa
        """
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"🔸 INICIO - Creando nueva instancia de checklist")
        logger.info(f"🔸 Usuario: {request.user.username} (ID: {request.user.id})")
        logger.info(f"🔸 Datos recibidos: {request.data}")
        logger.info(f"🔸 Headers Content-Type: {request.content_type}")
        
        try:
            # Validar datos básicos
            if 'orden' not in request.data:
                logger.error("🔸 ERROR: Falta campo 'orden' en los datos")
                return Response({'error': 'Se requiere el campo orden'}, status=status.HTTP_400_BAD_REQUEST)
            
            if 'checklist_template' not in request.data:
                logger.error("🔸 ERROR: Falta campo 'checklist_template' en los datos")
                return Response({'error': 'Se requiere el campo checklist_template'}, status=status.HTTP_400_BAD_REQUEST)
            
            orden_id = request.data.get('orden')
            template_id = request.data.get('checklist_template')
            
            logger.info(f"🔸 Orden ID: {orden_id}, Template ID: {template_id}")
            
            # Verificar que la orden existe
            try:
                from mecanimovilapp.apps.ordenes.models import SolicitudServicio
                orden = SolicitudServicio.objects.get(id=orden_id)
                logger.info(f"🔸 Orden encontrada: ID {orden.id}, Estado: {orden.estado}")
            except SolicitudServicio.DoesNotExist:
                logger.error(f"🔸 ERROR: No existe orden con ID {orden_id}")
                return Response({'error': f'No existe orden con ID {orden_id}'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Verificar que el template existe
            try:
                template = ChecklistTemplate.objects.get(id=template_id)
                logger.info(f"🔸 Template encontrado: ID {template.id}, Nombre: {template.nombre}")
            except ChecklistTemplate.DoesNotExist:
                logger.error(f"🔸 ERROR: No existe template con ID {template_id}")
                return Response({'error': f'No existe template con ID {template_id}'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Verificar que el usuario tiene acceso a esta orden
            user = request.user
            tiene_acceso = False
            
            if hasattr(user, 'taller') and orden.taller == user.taller:
                tiene_acceso = True
                logger.info(f"🔸 Acceso verificado: Usuario es propietario del taller")
            elif hasattr(user, 'mecanico_domicilio') and orden.mecanico == user.mecanico_domicilio:
                tiene_acceso = True
                logger.info(f"🔸 Acceso verificado: Usuario es el mecánico asignado")
            
            if not tiene_acceso:
                logger.error(f"🔸 ERROR: Usuario {user.username} no tiene acceso a orden {orden_id}")
                return Response({'error': 'No tienes acceso a esta orden'}, status=status.HTTP_403_FORBIDDEN)
            
            # Verificar que no exista ya un checklist para esta orden
            existing = ChecklistInstance.objects.filter(orden=orden).first()
            if existing:
                logger.warning(f"🔸 ADVERTENCIA: Ya existe checklist para orden {orden_id} - ID: {existing.id}")
                # Devolver el existente en lugar de error
                response_serializer = ChecklistInstanceSerializer(
                    existing, context=self.get_serializer_context()
                )
                return Response(response_serializer.data, status=status.HTTP_200_OK)
            
            # Usar el serializer simplificado para validar y crear
            logger.info(f"🔸 Procediendo con la creación...")
            serializer = self.get_serializer(data=request.data)
            
            if not serializer.is_valid():
                logger.error(f"🔸 ERROR: Datos inválidos - {serializer.errors}")
                return Response({'error': 'Datos inválidos', 'details': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
            # Realizar la creación
            instance = serializer.save()
            logger.info(f"🔸 Instancia creada exitosamente: ID {instance.id}")
            
            # 🔧 CORRECCIÓN: Usar el serializer completo para la respuesta
            # Esto asegura que el frontend reciba toda la información necesaria
            response_serializer = ChecklistInstanceSerializer(
                instance, context=self.get_serializer_context()
            )
            
            headers = self.get_success_headers(response_serializer.data)
            logger.info(f"🔸 ÉXITO - Devolviendo instancia completa")
            
            return Response(
                response_serializer.data, 
                status=status.HTTP_201_CREATED, 
                headers=headers
            )
            
        except Exception as e:
            logger.error(f"🔸 ERROR INESPERADO: {str(e)}")
            logger.error(f"🔸 Tipo de error: {type(e).__name__}")
            import traceback
            logger.error(f"🔸 Traceback: {traceback.format_exc()}")
            return Response({'error': f'Error interno: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='by_order/(?P<orden_id>[^/.]+)', permission_classes=[permissions.AllowAny])
    def by_order(self, request, orden_id=None):
        """Obtener checklist por ID de orden - Accesible por proveedores, clientes dueños y PÚBLICO si es marketplace"""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"🔸 by_order llamado para orden: {orden_id}")
        user = request.user
        logger.info(f"🔸 Usuario solicito: {user.username if user.is_authenticated else 'Anonymous'} (ID: {user.id if user.is_authenticated else 'None'})")
        
        if not orden_id:
            logger.error("🔸 ERROR: No se proporcionó orden_id")
            return Response(
                {'error': 'Se requiere el ID de la orden'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Inicializar instance
            instance = None
            
            # Verificar si orden_id es numérico o UUID
            if str(orden_id).isdigit():
                # Búsqueda estándar por ID de SolicitudServicio (Int)
                query = {'orden__id': orden_id}
                try:
                    instance = ChecklistInstance.objects.select_related(
                        'orden__cliente__usuario', 'orden__taller', 'orden__mecanico', 'orden__vehiculo'
                    ).prefetch_related(
                        'respuestas__fotos', 'respuestas__item_template__catalog_item'
                    ).get(**query)
                except ChecklistInstance.DoesNotExist:
                    # Si no existe, lanzará 404
                    raise
            else:
                # Si es UUID, puede ser:
                # 1. ID de la SolicitudServicioPublica (lo que ve el dueño en su panel)
                # 2. ID de la OfertaProveedor (menos probable pero posible)
                
                from django.db.models import Q
                
                # Intentamos encontrar la instancia usando diferentes caminos posibles con UUID
                try:
                    instance = ChecklistInstance.objects.select_related(
                        'orden__cliente__usuario', 'orden__taller', 'orden__mecanico', 'orden__vehiculo'
                    ).prefetch_related(
                        'respuestas__fotos', 'respuestas__item_template__catalog_item'
                    ).filter(
                        Q(orden__oferta_proveedor__solicitud__id=orden_id) |  # Por ID de Solicitud Publica
                        Q(orden__oferta_proveedor__id=orden_id)               # Por ID de Oferta Proveedor
                    ).first()
                    
                    if instance:
                         logger.info(f"🔸 Checklist encontrado por UUID indirecto: ID {instance.id}")
                    else:
                         logger.warning(f"🔸 No se encontró checklist para UUID: {orden_id}")
                         raise ChecklistInstance.DoesNotExist
                except Exception as e:
                     logger.warning(f"🔸 No se pudo resolver UUID {orden_id}: {e}")
                     raise ChecklistInstance.DoesNotExist

            if not instance:
                # Fallback final (seguridad)
                raise ChecklistInstance.DoesNotExist

            logger.info(f"🔸 Checklist encontrado: ID {instance.id}, Estado: {instance.estado}")
            logger.info(f"🔸 Checklist encontrado: ID {instance.id}, Estado: {instance.estado}")
            
            # Verificar que el usuario tenga acceso a esta orden
            tiene_acceso = False
            tipo_usuario = 'ninguno'
            
            # ✅ NUEVO: Permitir acceso PÚBLICO si el vehículo está publicado en Marketplace
            if instance.orden.vehiculo.is_published:
                tiene_acceso = True
                tipo_usuario = 'publico_marketplace'
                logger.info(f"🔸 Acceso verificado: Vehículo publicado en Marketplace")

            if user.is_authenticated:
                # ✅ NUEVO: Verificar si es el cliente dueño de la orden
                try:
                    if hasattr(user, 'cliente') and instance.orden.cliente == user.cliente:
                        tiene_acceso = True
                        tipo_usuario = 'cliente_propietario'
                        logger.info(f"🔸 Acceso verificado: Usuario es el cliente propietario de la orden")
                    elif instance.orden.cliente.usuario == user:
                        tiene_acceso = True
                        tipo_usuario = 'cliente_propietario'
                        logger.info(f"🔸 Acceso verificado: Usuario es el cliente propietario de la orden (por usuario)")
                except Exception as cliente_error:
                    logger.debug(f"🔸 Usuario no es cliente: {cliente_error}")
                
                # Verificar si es el proveedor (lógica existente)
                if hasattr(user, 'taller') and instance.orden.taller == user.taller:
                    tiene_acceso = True
                    tipo_usuario = 'proveedor_taller'
                    logger.info(f"🔸 Acceso verificado: Usuario es propietario del taller")
                elif hasattr(user, 'mecanico_domicilio') and instance.orden.mecanico == user.mecanico_domicilio:
                    tiene_acceso = True
                    tipo_usuario = 'proveedor_mecanico'
                    logger.info(f"🔸 Acceso verificado: Usuario es el mecánico asignado")
                    
            if not tiene_acceso:
                logger.error(f"🔸 ERROR: Usuario {user.username if user.is_authenticated else 'Anonymous'} no tiene acceso a orden {orden_id}")
                return Response(
                    {'error': 'No tienes acceso a este checklist'}, 
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # ✅ VALIDACIÓN: Cliente puede ver checklists COMPLETADOS o PENDIENTE_FIRMA_CLIENTE
            # (firma diferida: necesita revisar y firmar desde su app).
            if tipo_usuario == 'cliente_propietario':
                estados_visibles = ('COMPLETADO', 'PENDIENTE_FIRMA_CLIENTE')
                if instance.estado not in estados_visibles:
                    logger.warning(
                        f"🔸 Cliente intenta ver checklist en estado no visible: {instance.estado}"
                    )
                    return Response(
                        {'error': 'El checklist aún no está disponible para revisión.'},
                        status=status.HTTP_403_FORBIDDEN,
                    )
            
            serializer = self.get_serializer(instance)
            logger.info(f"🔸 ÉXITO - Devolviendo checklist para orden {orden_id} (usuario: {tipo_usuario})")
            return Response(serializer.data)
            
        except ChecklistInstance.DoesNotExist:
            logger.info(f"🔸 INFO - No existe checklist para orden {orden_id}")
            return Response(
                {'error': 'No existe checklist para esta orden'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"🔸 ERROR INESPERADO en by_order: {str(e)}")
            import traceback
            logger.error(f"🔸 Traceback: {traceback.format_exc()}")
            return Response(
                {'error': f'Error interno: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """Iniciar un checklist (solo entonces la orden pasa a 'checklist_en_progreso')."""
        instance = self.get_object()
        
        if instance.estado != 'PENDIENTE':
            return Response(
                {'error': 'El checklist no está en estado pendiente'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        instance.estado = 'EN_PROGRESO'
        instance.fecha_inicio = timezone.now()
        instance.save()
        
        # Pasar la orden a checklist_en_progreso solo cuando el proveedor inicia el checklist
        orden = instance.orden
        if orden.estado == 'confirmado':
            orden.estado = 'checklist_en_progreso'
            orden.save(update_fields=['estado'])
        
        return Response({'message': 'Checklist iniciado correctamente'})
    
    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        """Pausar un checklist"""
        instance = self.get_object()
        
        if instance.estado != 'EN_PROGRESO':
            return Response(
                {'error': 'El checklist no está en progreso'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        instance.estado = 'PAUSADO'
        instance.save()
        
        return Response({'message': 'Checklist pausado correctamente'})
    
    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        """Reanudar un checklist pausado"""
        instance = self.get_object()
        
        if instance.estado != 'PAUSADO':
            return Response(
                {'error': 'El checklist no está pausado'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        instance.estado = 'EN_PROGRESO'
        instance.save()
        
        return Response({'message': 'Checklist reanudado correctamente'})
    
    @action(detail=True, methods=['post'])
    def finalize(self, request, pk=None):
        """
        Finaliza un checklist desde la app del proveedor.

        Firma diferida (change firma-cliente-diferida-checklist):
        - Si solo llega `firma_tecnico`, la instancia queda en
          `PENDIENTE_FIRMA_CLIENTE` y la orden en `pendiente_firma_cliente`.
          El cliente debe firmar después desde su app vía
          `POST .../firmar-cliente/`.
        - Si llegan ambas firmas (compat con clientes presentes), se cierra
          el flujo de inmediato a `COMPLETADO` / `completado`.
        """
        import logging
        logger = logging.getLogger(__name__)

        instance = self.get_object()
        logger.info(
            f"🔸 Finalizando checklist ID: {instance.id} para orden: {instance.orden.id}"
        )

        # ✅ Idempotencia: ya completado, devolver 200 (evita fallos por reintentos).
        if instance.estado == 'COMPLETADO':
            logger.warning(f"🔸 finalize llamado pero checklist ya COMPLETADO: {instance.id}")
            return Response(
                {
                    'message': 'El checklist ya fue finalizado anteriormente',
                    'checklist_id': instance.id,
                    'orden_id': instance.orden.id,
                    'estado': instance.estado,
                    'requiere_firma_cliente': False,
                },
                status=status.HTTP_200_OK,
            )

        # ✅ Idempotencia: ya en pendiente firma cliente, devolver 200 con flag.
        if instance.estado == 'PENDIENTE_FIRMA_CLIENTE':
            logger.warning(
                f"🔸 finalize llamado pero checklist ya PENDIENTE_FIRMA_CLIENTE: {instance.id}"
            )
            return Response(
                {
                    'message': 'El checklist ya fue cerrado por el técnico, esperando firma del cliente.',
                    'checklist_id': instance.id,
                    'orden_id': instance.orden.id,
                    'estado': instance.estado,
                    'requiere_firma_cliente': True,
                },
                status=status.HTTP_200_OK,
            )

        if instance.estado not in ['EN_PROGRESO', 'PAUSADO']:
            logger.warning(f"🔸 Estado inválido para finalizar: {instance.estado}")
            return Response(
                {'error': 'El checklist debe estar en progreso o pausado'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        firma_tecnico = request.data.get('firma_tecnico')
        firma_cliente = request.data.get('firma_cliente') or None
        ubicacion_lat = request.data.get('ubicacion_lat')
        ubicacion_lng = request.data.get('ubicacion_lng')

        if not firma_tecnico:
            return Response(
                {'error': 'Se requiere la firma del técnico para finalizar el checklist.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        firma_cliente_presente = bool(firma_cliente)
        logger.info(
            f"🔸 Firmas recibidas — técnico: ✅, cliente: "
            f"{'✅' if firma_cliente_presente else 'pendiente (firma diferida)'}, "
            f"ubicación: {'✅' if ubicacion_lat and ubicacion_lng else '❌'}"
        )

        instance.firma_tecnico = firma_tecnico

        if firma_cliente_presente:
            # Flujo legacy con cliente presente: cierre inmediato.
            instance.estado = 'COMPLETADO'
            instance.fecha_finalizacion = timezone.now()
            instance.firma_cliente = firma_cliente
            instance.progreso_porcentaje = 100
        else:
            # Flujo nuevo (firma diferida): el cliente firmará desde su app.
            instance.estado = 'PENDIENTE_FIRMA_CLIENTE'
            instance.progreso_porcentaje = 100

        if ubicacion_lat and ubicacion_lng:
            from django.contrib.gis.geos import Point
            try:
                instance.ubicacion_finalizacion = Point(
                    float(ubicacion_lng), float(ubicacion_lat), srid=4326
                )
                logger.info(f"🔸 Ubicación guardada: {ubicacion_lat}, {ubicacion_lng}")
            except (ValueError, TypeError) as e:
                logger.warning(f"🔸 Error guardando ubicación: {e}")

        if instance.fecha_inicio and firma_cliente_presente:
            tiempo_total = timezone.now() - instance.fecha_inicio
            instance.tiempo_total_minutos = int(tiempo_total.total_seconds() / 60)

        instance.save()

        # ✅ ACTUALIZAR ESTADO DE LA ORDEN
        orden = instance.orden
        estado_anterior = orden.estado

        if firma_cliente_presente:
            if orden.estado == 'checklist_en_progreso':
                orden.estado = 'en_proceso'
                orden.save(update_fields=['estado'])
                logger.info(
                    f"🔸 (legacy 2 firmas) Orden actualizada: {estado_anterior} → {orden.estado}"
                )
            else:
                logger.warning(
                    f"🔸 Orden en estado inesperado: {orden.estado}, no se cambió el estado"
                )
        else:
            if orden.estado in ('checklist_en_progreso', 'checklist_completado', 'en_proceso'):
                orden.estado = 'pendiente_firma_cliente'
                orden.save(update_fields=['estado'])
                logger.info(
                    f"🔸 Firma diferida — orden actualizada: {estado_anterior} → {orden.estado}"
                )
            else:
                logger.warning(
                    f"🔸 Firma diferida pero orden en estado inesperado: {orden.estado}"
                )

            # Notificación al cliente para que vaya a firmar.
            try:
                from mecanimovilapp.apps.vehiculos.tasks import (
                    enviar_push_pendiente_firma_cliente,
                )
                enviar_push_pendiente_firma_cliente(orden)
            except Exception as push_err:
                logger.error(
                    f"❌ Error enviando push de firma pendiente para orden {orden.id}: {push_err}",
                    exc_info=True,
                )

        return Response(
            {
                'message': (
                    'Checklist finalizado correctamente'
                    if firma_cliente_presente
                    else 'Firma del técnico registrada. Esperando firma del cliente para cerrar el servicio.'
                ),
                'checklist_id': instance.id,
                'orden_id': orden.id,
                'orden_estado_anterior': estado_anterior,
                'orden_estado_nuevo': orden.estado,
                'estado': instance.estado,
                'requiere_firma_cliente': not firma_cliente_presente,
            }
        )
    
    @action(detail=False, methods=['post'], url_path='finalize_by_order/(?P<orden_id>[^/.]+)')
    def finalize_by_order(self, request, orden_id=None):
        """
        Variante de `finalize` indexada por orden. Misma semántica de firma
        diferida (change firma-cliente-diferida-checklist).
        """
        import logging
        logger = logging.getLogger(__name__)

        logger.info(f"🔸 finalize_by_order llamado para orden: {orden_id}")

        if not orden_id:
            return Response(
                {'error': 'Se requiere el ID de la orden'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            instance = ChecklistInstance.objects.get(orden=orden_id)
            logger.info(
                f"🔸 Instancia encontrada: ID {instance.id}, Estado: {instance.estado}"
            )

            if instance.estado == 'COMPLETADO':
                return Response(
                    {
                        'message': 'El checklist ya fue finalizado anteriormente',
                        'checklist_id': instance.id,
                        'orden_id': instance.orden.id,
                        'estado': instance.estado,
                        'requiere_firma_cliente': False,
                    },
                    status=status.HTTP_200_OK,
                )

            if instance.estado == 'PENDIENTE_FIRMA_CLIENTE':
                return Response(
                    {
                        'message': 'El checklist ya fue cerrado por el técnico, esperando firma del cliente.',
                        'checklist_id': instance.id,
                        'orden_id': instance.orden.id,
                        'estado': instance.estado,
                        'requiere_firma_cliente': True,
                    },
                    status=status.HTTP_200_OK,
                )

            user = self.request.user
            tiene_acceso = False
            if hasattr(user, 'taller') and instance.orden.taller == user.taller:
                tiene_acceso = True
            elif (
                hasattr(user, 'mecanico_domicilio')
                and instance.orden.mecanico == user.mecanico_domicilio
            ):
                tiene_acceso = True

            if not tiene_acceso:
                return Response(
                    {'error': 'No tienes acceso a este checklist'},
                    status=status.HTTP_403_FORBIDDEN,
                )

            if instance.estado not in ['EN_PROGRESO', 'PAUSADO']:
                return Response(
                    {
                        'error': (
                            f'El checklist debe estar en progreso o pausado. '
                            f'Estado actual: {instance.estado}'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            firma_tecnico = (
                request.data.get('firma_tecnico') or request.data.get('firmaTecnico')
            )
            firma_cliente = (
                request.data.get('firma_cliente') or request.data.get('firmaCliente') or None
            )
            ubicacion = request.data.get('ubicacion')

            if not firma_tecnico:
                return Response(
                    {'error': 'Se requiere la firma del técnico para finalizar el checklist.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            firma_cliente_presente = bool(firma_cliente)
            instance.firma_tecnico = firma_tecnico

            if firma_cliente_presente:
                instance.estado = 'COMPLETADO'
                instance.fecha_finalizacion = timezone.now()
                instance.firma_cliente = firma_cliente
                instance.progreso_porcentaje = 100
            else:
                instance.estado = 'PENDIENTE_FIRMA_CLIENTE'
                instance.progreso_porcentaje = 100

            if ubicacion:
                from django.contrib.gis.geos import Point
                lat = ubicacion.get('latitude') or ubicacion.get('lat')
                lng = ubicacion.get('longitude') or ubicacion.get('lng')
                if lat and lng:
                    instance.ubicacion_finalizacion = Point(lng, lat, srid=4326)

            if instance.fecha_inicio and firma_cliente_presente:
                tiempo_total = timezone.now() - instance.fecha_inicio
                instance.tiempo_total_minutos = int(tiempo_total.total_seconds() / 60)

            instance.save()

            orden = instance.orden
            estado_anterior = orden.estado

            if firma_cliente_presente:
                orden.estado = 'completado'
                orden.save(update_fields=['estado'])
            else:
                if orden.estado in (
                    'checklist_en_progreso',
                    'checklist_completado',
                    'en_proceso',
                ):
                    orden.estado = 'pendiente_firma_cliente'
                    orden.save(update_fields=['estado'])

                try:
                    from mecanimovilapp.apps.vehiculos.tasks import (
                        enviar_push_pendiente_firma_cliente,
                    )
                    enviar_push_pendiente_firma_cliente(orden)
                except Exception as push_err:
                    logger.error(
                        f"❌ Error enviando push firma pendiente (by_order) {orden.id}: {push_err}",
                        exc_info=True,
                    )

            return Response(
                {
                    'message': (
                        'Checklist finalizado correctamente'
                        if firma_cliente_presente
                        else 'Firma del técnico registrada. Esperando firma del cliente para cerrar el servicio.'
                    ),
                    'checklist_id': instance.id,
                    'orden_id': instance.orden.id,
                    'orden_estado_anterior': estado_anterior,
                    'orden_estado_nuevo': orden.estado,
                    'estado': instance.estado,
                    'requiere_firma_cliente': not firma_cliente_presente,
                }
            )

        except ChecklistInstance.DoesNotExist:
            logger.error(f"🔸 No se encontró checklist para orden: {orden_id}")
            return Response(
                {'error': f'No existe checklist para la orden {orden_id}'},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            logger.error(f"🔸 Error inesperado: {str(e)}", exc_info=True)
            return Response(
                {'error': f'Error interno: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(
        detail=True,
        methods=['post'],
        url_path='firmar-cliente',
        permission_classes=[permissions.IsAuthenticated],
    )
    def firmar_cliente(self, request, pk=None):
        """
        Firma del cliente desde su app autenticada (firma diferida).

        Permite al cliente dueño de la orden cerrar el servicio aportando
        su firma cuando el checklist está en `PENDIENTE_FIRMA_CLIENTE`.
        Tras firmar, el `post_save` de `ChecklistInstance` dispara la
        actualización de salud del vehículo.
        """
        import logging
        logger = logging.getLogger(__name__)

        try:
            instance = ChecklistInstance.objects.select_related(
                'orden__cliente__usuario'
            ).get(pk=pk)
        except ChecklistInstance.DoesNotExist:
            return Response(
                {'error': 'No existe el checklist'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Validar permisos: cliente dueño de la orden.
        usuario_cliente = getattr(getattr(instance.orden, 'cliente', None), 'usuario', None)
        if usuario_cliente is None or usuario_cliente.id != request.user.id:
            logger.warning(
                f"🔸 firmar_cliente sin permiso (user={request.user.id}, instance={instance.id})"
            )
            return Response(
                {'error': 'No tienes permiso para firmar este checklist.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Idempotencia: ya completado.
        if instance.estado == 'COMPLETADO':
            return Response(
                {
                    'message': 'El checklist ya fue completado anteriormente.',
                    'checklist_id': instance.id,
                    'orden_id': instance.orden.id,
                    'estado': instance.estado,
                },
                status=status.HTTP_200_OK,
            )

        if instance.estado != 'PENDIENTE_FIRMA_CLIENTE':
            return Response(
                {
                    'error': (
                        'El checklist no está en espera de tu firma '
                        f'(estado actual: {instance.estado}).'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not instance.firma_tecnico:
            return Response(
                {'error': 'Falta la firma del técnico, no se puede cerrar todavía.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        firma_cliente = request.data.get('firma_cliente')
        if not firma_cliente:
            return Response(
                {'error': 'Se requiere la firma del cliente para finalizar.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ubicacion_lat = request.data.get('ubicacion_lat')
        ubicacion_lng = request.data.get('ubicacion_lng')

        instance.firma_cliente = firma_cliente
        instance.estado = 'COMPLETADO'
        instance.fecha_finalizacion = timezone.now()
        instance.progreso_porcentaje = 100

        if ubicacion_lat and ubicacion_lng and instance.ubicacion_finalizacion is None:
            from django.contrib.gis.geos import Point
            try:
                instance.ubicacion_finalizacion = Point(
                    float(ubicacion_lng), float(ubicacion_lat), srid=4326
                )
            except (ValueError, TypeError) as geo_err:
                logger.warning(
                    f"🔸 firmar_cliente: ubicación inválida {ubicacion_lat},{ubicacion_lng}: {geo_err}"
                )

        if instance.fecha_inicio:
            tiempo_total = timezone.now() - instance.fecha_inicio
            instance.tiempo_total_minutos = int(tiempo_total.total_seconds() / 60)

        orden = instance.orden
        estado_anterior = orden.estado
        oferta_marketplace = None

        with transaction.atomic():
            instance.save()

            orden.estado = 'completado'
            orden_update_fields = ['estado']
            if orden.fecha_respuesta_proveedor is None:
                orden.fecha_respuesta_proveedor = timezone.now()
                orden_update_fields.append('fecha_respuesta_proveedor')
            orden.save(update_fields=orden_update_fields)

            # Marketplace: alinear oferta y solicitud pública (mismo cierre que terminar-servicio).
            if orden.oferta_proveedor_id:
                from mecanimovilapp.apps.ordenes.models import OfertaProveedor

                oferta_marketplace = (
                    OfertaProveedor.objects.select_for_update()
                    .select_related(
                        'solicitud',
                        'solicitud__cliente__usuario',
                        'proveedor',
                    )
                    .get(pk=orden.oferta_proveedor_id)
                )
                if oferta_marketplace.estado == 'en_ejecucion':
                    oferta_marketplace.estado = 'completada'
                    oferta_marketplace.save(update_fields=['estado'])

                solicitud_pub = oferta_marketplace.solicitud
                if solicitud_pub and solicitud_pub.estado == 'en_ejecucion':
                    solicitud_pub.estado = 'completada'
                    solicitud_pub.save(update_fields=['estado'])

        # WebSocket (fuera del atomic; solo lectura de relaciones ya persistidas).
        try:
            channel_layer = get_channel_layer()
            if channel_layer and oferta_marketplace:
                solicitud = oferta_marketplace.solicitud
                if solicitud.cliente and solicitud.cliente.usuario:
                    async_to_sync(channel_layer.group_send)(
                        f"cliente_{solicitud.cliente.usuario.id}",
                        {
                            'type': 'servicio_completado',
                            'oferta_id': str(oferta_marketplace.id),
                            'solicitud_id': str(solicitud.id),
                            'proveedor_nombre': oferta_marketplace.nombre_proveedor,
                            'mensaje': 'El servicio fue confirmado con tu firma.',
                            'timestamp': timezone.now().isoformat(),
                        },
                    )
                    logger.info(
                        f"Notificación WebSocket 'servicio_completado' (firma cliente) "
                        f"a usuario {solicitud.cliente.usuario.id}"
                    )
                if oferta_marketplace.proveedor_id:
                    async_to_sync(channel_layer.group_send)(
                        f"proveedor_{oferta_marketplace.proveedor_id}",
                        {
                            'type': 'servicio_cerrado_por_cliente',
                            'oferta_id': str(oferta_marketplace.id),
                            'solicitud_publica_id': str(solicitud.id),
                            'solicitud_servicio_id': orden.id,
                            'timestamp': timezone.now().isoformat(),
                        },
                    )
        except Exception as ws_err:
            logger.warning(
                f"🔸 firmar_cliente: WebSocket post-cierre omitido: {ws_err}",
                exc_info=True,
            )

        logger.info(
            f"✅ Cliente {request.user.id} firmó checklist {instance.id} → orden {orden.id} completada"
        )

        return Response(
            {
                'message': 'Servicio confirmado correctamente. ¡Gracias por tu firma!',
                'checklist_id': instance.id,
                'orden_id': orden.id,
                'orden_estado_anterior': estado_anterior,
                'orden_estado_nuevo': orden.estado,
                'estado': instance.estado,
            }
        )

    @action(detail=True, methods=['get'], url_path='salud-snapshot')
    def salud_snapshot(self, request, pk=None):
        """
        Devuelve, por cada ítem del template con `componente_salud_asociado`,
        la salud actual del componente para el vehículo de la orden. Permite
        al frontend del proveedor mostrar el estado actual sobre cada ítem
        antes de que el técnico lo modifique.
        """
        instance = self.get_object()
        vehiculo = getattr(instance.orden, 'vehiculo', None)
        if vehiculo is None:
            return Response(
                {'error': 'La orden no tiene vehículo asociado'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from mecanimovilapp.apps.vehiculos.models_health import (
            ComponenteSaludVehiculo,
        )

        items = list(
            instance.checklist_template.items.select_related(
                'componente_salud_asociado',
                'catalog_item',
            ).filter(componente_salud_asociado__isnull=False)
        )
        componente_ids = {it.componente_salud_asociado_id for it in items}
        estados_map = {
            c.componente_id: c
            for c in ComponenteSaludVehiculo.objects.select_related('componente').filter(
                vehiculo=vehiculo, componente_id__in=componente_ids,
            )
        }

        items_payload = []
        for it in items:
            componente = it.componente_salud_asociado
            estado = estados_map.get(componente.id)
            items_payload.append({
                'item_template_id': it.id,
                'orden_visual': it.orden_visual,
                'tipo_actualizacion': it.tipo_actualizacion_efectivo,
                'componente': {
                    'id': componente.id,
                    'nombre': componente.nombre,
                    'slug': componente.slug,
                    'icono': componente.icono,
                },
                'salud_actual': (
                    round(estado.salud_porcentaje, 1) if estado else None
                ),
                'nivel_alerta_actual': estado.nivel_alerta if estado else None,
                'fuente_actual': estado.historial_fuente if estado else None,
                'salud_anclada_pct': estado.salud_anclada_pct if estado else None,
                'fecha_ultimo_servicio': (
                    estado.fecha_ultimo_servicio.isoformat()
                    if estado and estado.fecha_ultimo_servicio else None
                ),
                'km_ultimo_servicio': estado.km_ultimo_servicio if estado else None,
            })

        return Response({
            'vehiculo_id': vehiculo.id,
            'kilometraje_actual': int(getattr(vehiculo, 'kilometraje', 0) or 0),
            'tipo_intencion_default': instance.checklist_template.tipo_intencion_default,
            'items': items_payload,
        })

    @action(detail=True, methods=['post'], url_path='preview-impacto')
    def preview_impacto(self, request, pk=None):
        """
        Calcula sin persistir el diff entre la salud actual y la proyectada
        por las respuestas guardadas hasta el momento. Se usa antes de
        finalizar el checklist para mostrarle al técnico el impacto.
        """
        from mecanimovilapp.apps.vehiculos.tasks import (
            _porcentaje_inspeccion_desde_respuesta,
            _nivel_alerta_desde_pct,
        )
        from mecanimovilapp.apps.vehiculos.models_health import (
            ComponenteSaludVehiculo,
            EstadoSaludVehiculo,
        )

        instance = self.get_object()
        vehiculo = getattr(instance.orden, 'vehiculo', None)
        if vehiculo is None:
            return Response(
                {'error': 'La orden no tiene vehículo asociado'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        respuestas = instance.respuestas.select_related(
            'item_template__componente_salud_asociado',
            'item_template__catalog_item',
            'item_template__checklist_template',
        ).all()

        componente_ids = set()
        for r in respuestas:
            comp = getattr(r.item_template, 'componente_salud_asociado', None)
            if comp is not None:
                componente_ids.add(comp.id)

        estados_map = {
            c.componente_id: c
            for c in ComponenteSaludVehiculo.objects.select_related('componente').filter(
                vehiculo=vehiculo, componente_id__in=componente_ids,
            )
        }
        # Snapshot global existente para "antes"
        estado_general = EstadoSaludVehiculo.objects.filter(vehiculo=vehiculo).first()
        salud_general_actual = (
            round(estado_general.salud_general_porcentaje, 1)
            if estado_general else None
        )

        diff = []
        ya_visto = set()
        for r in respuestas:
            item_template = r.item_template
            componente = getattr(item_template, 'componente_salud_asociado', None)
            if componente is None:
                continue
            tipo_act = item_template.tipo_actualizacion_efectivo
            if tipo_act == 'INFORMATIVO':
                continue
            if componente.id in ya_visto:
                continue
            ya_visto.add(componente.id)

            estado = estados_map.get(componente.id)
            salud_actual = (
                round(estado.salud_porcentaje, 1) if estado else None
            )

            if tipo_act == 'REEMPLAZA':
                salud_nueva = 100.0
                nivel_nuevo = 'OPTIMO'
            else:
                pct = _porcentaje_inspeccion_desde_respuesta(r)
                if pct is None:
                    continue
                salud_nueva = round(pct, 1)
                nivel_nuevo = _nivel_alerta_desde_pct(pct)

            delta = round(salud_nueva - (salud_actual or 0.0), 1)
            diff.append({
                'componente': {
                    'id': componente.id,
                    'nombre': componente.nombre,
                    'slug': componente.slug,
                },
                'tipo_actualizacion': tipo_act,
                'salud_actual': salud_actual,
                'salud_nueva': salud_nueva,
                'nivel_alerta_actual': estado.nivel_alerta if estado else None,
                'nivel_alerta_nuevo': nivel_nuevo,
                'delta': delta,
            })

        # Estimación grosera de salud_general nueva: promedio simple sobre los
        # componentes evaluados aquí + los componentes existentes no tocados.
        salud_general_estimada = None
        if estado_general and estado_general.total_componentes_evaluados > 0:
            tocados = {d['componente']['id']: d['salud_nueva'] for d in diff}
            salud_existentes = ComponenteSaludVehiculo.objects.filter(
                vehiculo=vehiculo,
            ).exclude(componente_id__in=tocados.keys()).values_list(
                'salud_porcentaje', flat=True,
            )
            valores = list(tocados.values()) + [float(s) for s in salud_existentes]
            if valores:
                salud_general_estimada = round(sum(valores) / len(valores), 1)

        return Response({
            'vehiculo_id': vehiculo.id,
            'salud_general_actual': salud_general_actual,
            'salud_general_estimada': salud_general_estimada,
            'diff': diff,
        })


class ChecklistResponseViewSet(viewsets.ModelViewSet):
    """ViewSet para respuestas de checklist"""
    serializer_class = ChecklistItemResponseSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Filtrar respuestas por checklist del proveedor"""
        user = self.request.user
        
        # Filtrar por proveedor
        if hasattr(user, 'taller'):
            return ChecklistItemResponse.objects.filter(
                checklist_instance__orden__taller=user.taller
            ).select_related(
                'checklist_instance', 'item_template'
            ).prefetch_related('fotos')
        elif hasattr(user, 'mecanico_domicilio'):
            return ChecklistItemResponse.objects.filter(
                checklist_instance__orden__mecanico=user.mecanico_domicilio
            ).select_related(
                'checklist_instance', 'item_template'
            ).prefetch_related('fotos')
        
        return ChecklistItemResponse.objects.none()
    
    def create(self, request, *args, **kwargs):
        """Override create para agregar logging y mejor manejo de errores"""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"🔸 Creando respuesta de checklist")
        logger.info(f"🔸 Datos recibidos: {request.data}")
        
        # Verificar que se incluyan los campos requeridos
        if 'checklist_instance' not in request.data:
            logger.error("🔸 Error: falta checklist_instance en la petición")
            return Response(
                {'error': 'Se requiere checklist_instance'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if 'item_template' not in request.data:
            logger.error("🔸 Error: falta item_template en la petición")
            return Response(
                {'error': 'Se requiere item_template'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Verificar que la instancia del checklist existe y el usuario tiene acceso
            checklist_instance_id = request.data.get('checklist_instance')
            instance = ChecklistInstance.objects.get(id=checklist_instance_id)
            
            # Verificar acceso del usuario
            user = self.request.user
            tiene_acceso = False
            
            if hasattr(user, 'taller') and instance.orden.taller == user.taller:
                tiene_acceso = True
            elif hasattr(user, 'mecanico_domicilio') and instance.orden.mecanico == user.mecanico_domicilio:
                tiene_acceso = True
                
            if not tiene_acceso:
                logger.warning(f"🔸 Usuario {user.username} no tiene acceso a checklist {checklist_instance_id}")
                return Response(
                    {'error': 'No tienes acceso a este checklist'}, 
                    status=status.HTTP_403_FORBIDDEN
                )
            
            logger.info(f"🔸 Creando respuesta para checklist {checklist_instance_id}, item {request.data.get('item_template')}")
            
            return super().create(request, *args, **kwargs)
            
        except ChecklistInstance.DoesNotExist:
            logger.error(f"🔸 No se encontró checklist instance: {request.data.get('checklist_instance')}")
            return Response(
                {'error': f'No existe checklist instance {request.data.get("checklist_instance")}'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"🔸 Error inesperado al crear respuesta: {str(e)}")
            return Response(
                {'error': f'Error interno: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def perform_create(self, serializer):
        """Al crear una respuesta, actualizar el progreso del checklist"""
        import logging
        logger = logging.getLogger(__name__)
        
        response = serializer.save()
        logger.info(f"🔸 Respuesta guardada: ID {response.id}, Completado: {response.completado}")
        
        # Actualizar progreso del checklist
        instance = response.checklist_instance
        total_items = instance.checklist_template.items.count()
        items_completados = instance.respuestas.filter(completado=True).count()
        
        if total_items > 0:
            progreso = int((items_completados / total_items) * 100)
            instance.progreso_porcentaje = progreso
            
            # 🔧 NUEVA LÓGICA: Verificar si puede finalizar
            puede_finalizar = self._can_finalize_checklist(instance)
            logger.info(f"🔸 Progreso actualizado: {progreso}% ({items_completados}/{total_items}), Puede finalizar: {puede_finalizar}")
            
            instance.save(update_fields=['progreso_porcentaje'])
        
        return response
    
    def _can_finalize_checklist(self, instance):
        """
        Método auxiliar para determinar si el checklist puede finalizarse
        """
        # Solo se puede finalizar si está en progreso
        if instance.estado != 'EN_PROGRESO':
            return False
            
        # Verificar que todos los items obligatorios estén completados
        items_obligatorios = instance.checklist_template.items.filter(
            catalog_item__es_obligatorio_por_defecto=True
        )
        
        for item in items_obligatorios:
            respuesta = instance.respuestas.filter(item_template=item, completado=True).first()
            if not respuesta:
                return False
        
        # Verificar que haya al menos una respuesta completada y progreso > 80%
        # (flexibilizamos un poco para casos donde no todos los items son obligatorios)
        return instance.progreso_porcentaje >= 80 and instance.respuestas.filter(completado=True).exists()


class ChecklistPhotoViewSet(viewsets.ModelViewSet):
    """ViewSet para fotos de checklist"""
    serializer_class = ChecklistPhotoUploadSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Filtrar fotos por checklist del proveedor"""
        user = self.request.user
        
        if hasattr(user, 'taller'):
            return ChecklistPhoto.objects.filter(
                response__checklist_instance__orden__taller=user.taller
            ).select_related('response', 'response__checklist_instance')
        elif hasattr(user, 'mecanico_domicilio'):
            return ChecklistPhoto.objects.filter(
                response__checklist_instance__orden__mecanico=user.mecanico_domicilio
            ).select_related('response', 'response__checklist_instance')
        
        return ChecklistPhoto.objects.none()
    
    def create(self, request, *args, **kwargs):
        """Override create para logging detallado y respuesta con imagen_url"""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"📸 ChecklistPhoto.create — usuario: {request.user.username}")
        logger.info(f"📸 Content-Type: {request.content_type}")
        logger.info(f"📸 FILES recibidos: {list(request.FILES.keys())}")
        logger.info(f"📸 DATA recibido: { {k: v for k, v in request.data.items() if k != 'imagen'} }")
        
        if 'imagen' not in request.FILES and 'imagen' not in request.data:
            logger.error("📸 ERROR: campo 'imagen' no encontrado en la petición")
            return Response(
                {'error': "Se requiere el campo 'imagen' (archivo de imagen)"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            logger.error(f"📸 ERROR de validación: {serializer.errors}")
            return Response(
                {'error': 'Datos inválidos', 'details': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            foto = serializer.save()
            logger.info(f"📸 Foto guardada: ID {foto.id}, archivo: {foto.imagen.name}")
            
            # Construir URL completa usando el mismo mecanismo que otros serializadores
            from mecanimovilapp.storage.utils import get_image_url
            imagen_url = get_image_url(foto.imagen, request)
            logger.info(f"📸 imagen_url generada: {imagen_url}")
            
            return Response(
                {
                    'id': foto.id,
                    'imagen_url': imagen_url,
                    'descripcion': foto.descripcion,
                    'orden_en_respuesta': foto.orden_en_respuesta,
                    'fecha_captura': foto.fecha_captura,
                },
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            logger.error(f"📸 ERROR guardando foto: {type(e).__name__}: {e}")
            import traceback
            logger.error(f"📸 Traceback: {traceback.format_exc()}")
            return Response(
                {'error': f'Error al guardar la imagen: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            ) 