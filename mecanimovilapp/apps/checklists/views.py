from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404

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
                response_serializer = ChecklistInstanceSerializer(existing)
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
            response_serializer = ChecklistInstanceSerializer(instance)
            
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
            # Buscar el checklist asociado a esta orden
            logger.info(f"🔸 Buscando checklist para orden: {orden_id}")
            
            # Verificar si orden_id es numérico o UUID
            if str(orden_id).isdigit():
                query = {'orden__id': orden_id}
            else:
                # Asumir que es UUID si no es dígito
                query = {'orden__uuid': orden_id}

            instance = ChecklistInstance.objects.select_related(
                'orden__cliente__usuario', 'orden__taller', 'orden__mecanico', 'orden__vehiculo'
            ).get(**query)
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
            
            # ✅ VALIDACIÓN ADICIONAL: Para clientes, solo permitir ver checklists completados
            if tipo_usuario == 'cliente_propietario':
                if instance.estado != 'COMPLETADO':
                    logger.warning(f"🔸 Cliente intenta ver checklist no completado: {instance.estado}")
                    return Response(
                        {'error': 'El checklist aún no está disponible. Solo puedes ver checklists de servicios completados.'}, 
                        status=status.HTTP_403_FORBIDDEN
                    )
                
                # Verificar que la orden esté completada
                if instance.orden.estado != 'completado':
                    logger.warning(f"🔸 Cliente intenta ver checklist de orden no completada: {instance.orden.estado}")
                    return Response(
                        {'error': 'Este checklist solo está disponible para servicios completados.'}, 
                        status=status.HTTP_403_FORBIDDEN
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
        """Iniciar un checklist"""
        instance = self.get_object()
        
        if instance.estado != 'PENDIENTE':
            return Response(
                {'error': 'El checklist no está en estado pendiente'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        instance.estado = 'EN_PROGRESO'
        instance.fecha_inicio = timezone.now()
        instance.save()
        
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
        """Finalizar un checklist con firmas"""
        import logging
        logger = logging.getLogger(__name__)
        
        instance = self.get_object()
        logger.info(f"🔸 Finalizando checklist ID: {instance.id} para orden: {instance.orden.id}")
        
        if instance.estado not in ['EN_PROGRESO', 'PAUSADO']:
            logger.warning(f"🔸 Estado inválido para finalizar: {instance.estado}")
            return Response(
                {'error': 'El checklist debe estar en progreso o pausado'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verificar que se proporcionaron las firmas
        firma_tecnico = request.data.get('firma_tecnico')
        firma_cliente = request.data.get('firma_cliente')
        ubicacion_lat = request.data.get('ubicacion_lat')
        ubicacion_lng = request.data.get('ubicacion_lng')
        
        logger.info(f"🔸 Datos recibidos - Firmas: {'✅' if firma_tecnico and firma_cliente else '❌'}, Ubicación: {'✅' if ubicacion_lat and ubicacion_lng else '❌'}")
        
        if not firma_tecnico or not firma_cliente:
            return Response(
                {'error': 'Se requieren ambas firmas para finalizar'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Actualizar la instancia del checklist
        instance.estado = 'COMPLETADO'
        instance.fecha_finalizacion = timezone.now()
        instance.firma_tecnico = firma_tecnico
        instance.firma_cliente = firma_cliente
        instance.progreso_porcentaje = 100
        
        # Guardar ubicación si se proporcionó
        if ubicacion_lat and ubicacion_lng:
            from django.contrib.gis.geos import Point
            try:
                instance.ubicacion_finalizacion = Point(float(ubicacion_lng), float(ubicacion_lat), srid=4326)
                logger.info(f"🔸 Ubicación guardada: {ubicacion_lat}, {ubicacion_lng}")
            except (ValueError, TypeError) as e:
                logger.warning(f"🔸 Error guardando ubicación: {e}")
        
        # Calcular tiempo total
        if instance.fecha_inicio:
            tiempo_total = timezone.now() - instance.fecha_inicio
            instance.tiempo_total_minutos = int(tiempo_total.total_seconds() / 60)
        
        instance.save()
        logger.info(f"🔸 Checklist finalizado: ID {instance.id}")
        
        # ✅ ACTUALIZAR ESTADO DE LA ORDEN
        orden = instance.orden
        estado_anterior = orden.estado
        
        # Cambiar estado de la orden según el flujo correcto
        if orden.estado == 'checklist_en_progreso':
            orden.estado = 'en_proceso'  # Próximo paso: realizar el servicio
            orden.save()
            logger.info(f"🔸 Orden actualizada: {estado_anterior} → {orden.estado}")
        else:
            logger.warning(f"🔸 Orden en estado inesperado: {orden.estado}, no se cambió el estado")
        
        return Response({
            'message': 'Checklist finalizado correctamente',
            'checklist_id': instance.id,
            'orden_id': orden.id,
            'orden_estado_anterior': estado_anterior,
            'orden_estado_nuevo': orden.estado
        })
    
    @action(detail=False, methods=['post'], url_path='finalize_by_order/(?P<orden_id>[^/.]+)')
    def finalize_by_order(self, request, orden_id=None):
        """Finalizar un checklist por ID de orden - Endpoint robusto para el frontend"""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"🔸 finalize_by_order llamado para orden: {orden_id}")
        logger.info(f"🔸 Datos recibidos: {request.data}")
        
        if not orden_id:
            return Response(
                {'error': 'Se requiere el ID de la orden'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Buscar el checklist asociado a esta orden
            instance = ChecklistInstance.objects.get(orden=orden_id)
            logger.info(f"🔸 Instancia encontrada: ID {instance.id}, Estado: {instance.estado}")
            
            # Verificar que el usuario tenga acceso a esta orden
            user = self.request.user
            tiene_acceso = False
            
            if hasattr(user, 'taller') and instance.orden.taller == user.taller:
                tiene_acceso = True
            elif hasattr(user, 'mecanico_domicilio') and instance.orden.mecanico == user.mecanico_domicilio:
                tiene_acceso = True
                
            if not tiene_acceso:
                logger.warning(f"🔸 Usuario {user.username} no tiene acceso a orden {orden_id}")
                return Response(
                    {'error': 'No tienes acceso a este checklist'}, 
                    status=status.HTTP_403_FORBIDDEN
                )
            
            if instance.estado not in ['EN_PROGRESO', 'PAUSADO']:
                return Response(
                    {'error': f'El checklist debe estar en progreso o pausado. Estado actual: {instance.estado}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Verificar que se proporcionaron las firmas
            firma_tecnico = request.data.get('firma_tecnico') or request.data.get('firmaTecnico')
            firma_cliente = request.data.get('firma_cliente') or request.data.get('firmaCliente')
            ubicacion = request.data.get('ubicacion')
            
            logger.info(f"🔸 Firmas recibidas - Técnico: {'✅' if firma_tecnico else '❌'}, Cliente: {'✅' if firma_cliente else '❌'}")
            
            if not firma_tecnico or not firma_cliente:
                return Response(
                    {'error': 'Se requieren ambas firmas para finalizar'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Actualizar la instancia
            instance.estado = 'COMPLETADO'
            instance.fecha_finalizacion = timezone.now()
            instance.firma_tecnico = firma_tecnico
            instance.firma_cliente = firma_cliente
            instance.progreso_porcentaje = 100
            
            if ubicacion:
                from django.contrib.gis.geos import Point
                lat = ubicacion.get('latitude') or ubicacion.get('lat')
                lng = ubicacion.get('longitude') or ubicacion.get('lng')
                if lat and lng:
                    instance.ubicacion_finalizacion = Point(lng, lat, srid=4326)
                    logger.info(f"🔸 Ubicación guardada: {lat}, {lng}")
            
            # Calcular tiempo total
            if instance.fecha_inicio:
                tiempo_total = timezone.now() - instance.fecha_inicio
                instance.tiempo_total_minutos = int(tiempo_total.total_seconds() / 60)
            
            instance.save()
            logger.info(f"🔸 Checklist finalizado exitosamente: ID {instance.id}")
            
            # Actualizar estado de la orden
            instance.orden.estado = 'completado'
            instance.orden.save()
            logger.info(f"🔸 Orden actualizada a estado: completado")
            
            return Response({
                'message': 'Checklist finalizado correctamente',
                'checklist_id': instance.id,
                'orden_id': instance.orden.id,
                'siguiente_paso': 'El proceso ha sido completado exitosamente'
            })
            
        except ChecklistInstance.DoesNotExist:
            logger.error(f"🔸 No se encontró checklist para orden: {orden_id}")
            return Response(
                {'error': f'No existe checklist para la orden {orden_id}'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"🔸 Error inesperado: {str(e)}")
            return Response(
                {'error': f'Error interno: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


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