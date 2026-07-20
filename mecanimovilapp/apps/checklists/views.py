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
from mecanimovilapp.apps.ordenes.services.cierre_servicio_marketplace import (
    sincronizar_cierre_marketplace,
)
from mecanimovilapp.apps.checklists.services import resolver_o_generar_template
from mecanimovilapp.apps.servicios.models import Servicio
from .firma_utils import firma_a_payload_base64


def _notificar_websocket_cierre_marketplace(oferta_marketplace, orden_id, logger):
    """Cliente + proveedor (misma carga que firmar_cliente / terminar-servicio)."""
    try:
        channel_layer = get_channel_layer()
        if not channel_layer or not oferta_marketplace:
            return
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
                f"WS servicio_completado → cliente_{solicitud.cliente.usuario.id} "
                f"(orden={orden_id})"
            )
        if oferta_marketplace.proveedor_id:
            async_to_sync(channel_layer.group_send)(
                f"proveedor_{oferta_marketplace.proveedor_id}",
                {
                    'type': 'servicio_cerrado_por_cliente',
                    'oferta_id': str(oferta_marketplace.id),
                    'solicitud_publica_id': str(solicitud.id),
                    'solicitud_servicio_id': orden_id,
                    'timestamp': timezone.now().isoformat(),
                },
            )
    except Exception as ws_err:
        logger.warning(
            f"🔸 WebSocket cierre marketplace omitido (orden={orden_id}): {ws_err}",
            exc_info=True,
        )


class ChecklistTemplateViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet para templates de checklist (solo lectura)"""
    serializer_class = ChecklistTemplateSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Templates activos visibles para cualquier miembro del taller o proveedor."""
        from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller

        user = self.request.user
        taller_ctx, _miembro, rol = resolver_contexto_taller(user)
        base = (
            ChecklistTemplate.objects
            .filter(activo=True)
            .select_related('servicio')
            .prefetch_related('items__catalog_item')
        )

        # Mandante, supervisor o mecánico de equipo del taller.
        if taller_ctx is not None and rol in ('mandante', 'supervisor', 'mecanico'):
            return base

        # Dueño legacy / mecánico a domicilio (hasattr evita DoesNotExist del reverse FK).
        if hasattr(user, 'taller') and user.taller is not None:
            return base
        if hasattr(user, 'mecanico_domicilio') and user.mecanico_domicilio is not None:
            return base

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
            servicio = Servicio.objects.get(id=servicio_id)
            template = resolver_o_generar_template(servicio, generar_si_ausente=True)
            if template is None:
                return Response(
                    {'error': 'No existe template de checklist para este servicio'},
                    status=status.HTTP_404_NOT_FOUND,
                )
            serializer = self.get_serializer(template)
            return Response(serializer.data)
        except Servicio.DoesNotExist:
            return Response(
                {'error': 'Servicio no encontrado'},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception:
            return Response(
                {'error': 'No existe template de checklist para este servicio'},
                status=status.HTTP_404_NOT_FOUND,
            )

    @action(detail=True, methods=['post'], url_path='bulk-add-items', permission_classes=[permissions.IsAdminUser])
    def bulk_add_items(self, request, pk=None):
        """
        Agrega ChecklistItemTemplate en bulk a este template a partir de
        categoria + componente_ids + tipo_evaluacion.

        Solo accesible por usuarios admin (IsAdminUser).

        tipo_evaluacion:
          - rapida    → 1 item SELECT INSPECCIONA por componente
          - completa  → 1 SELECT + 1 COMPONENT_HEALTH INSPECCIONA por componente
          - reemplazo → 1 BOOLEAN REEMPLAZA por componente
        """
        import logging
        logger = logging.getLogger(__name__)

        template = self.get_object()
        serializer_class = self._get_bulk_add_items_serializer()
        ser = serializer_class(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        categoria = ser.validated_data['categoria']
        componente_ids = ser.validated_data['componente_ids']
        tipo_evaluacion = ser.validated_data['tipo_evaluacion']

        from mecanimovilapp.apps.vehiculos.models_health import ComponenteSalud
        from .models import ChecklistItemTemplate, ChecklistItemCatalog
        from .admin import _build_bulk_items_for_componente

        componentes = ComponenteSalud.objects.filter(id__in=componente_ids)
        if not componentes.exists():
            return Response(
                {'error': 'No se encontraron componentes con los IDs proporcionados'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        items_creados = 0
        items_existentes = 0
        items_resultado = []
        orden_base = template.items.count()

        for componente in componentes:
            pares = _build_bulk_items_for_componente(
                template, componente, categoria, tipo_evaluacion, orden_base
            )
            for catalog_item, tipo_act, orden in pares:
                item_template, created = ChecklistItemTemplate.objects.get_or_create(
                    checklist_template=template,
                    catalog_item=catalog_item,
                    defaults={
                        'orden_visual': orden,
                        'tipo_actualizacion': tipo_act,
                        'componente_salud_asociado': componente,
                    },
                )
                if created:
                    items_creados += 1
                    orden_base += 1
                else:
                    items_existentes += 1
                items_resultado.append({
                    'id': item_template.id,
                    'orden_visual': item_template.orden_visual,
                    'catalog_item_nombre': catalog_item.nombre,
                    'tipo_actualizacion': tipo_act,
                    'componente_nombre': componente.nombre,
                    'created': created,
                })

        logger.info(
            'bulk_add_items: template=%s categoria=%s tipo=%s → creados=%d existentes=%d',
            template.id, categoria, tipo_evaluacion, items_creados, items_existentes,
        )

        return Response(
            {
                'items_creados': items_creados,
                'items_existentes': items_existentes,
                'items': items_resultado,
            },
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _get_bulk_add_items_serializer():
        from rest_framework import serializers as drf_serializers

        class _BulkAddItemsSerializer(drf_serializers.Serializer):
            TIPO_EVALUACION_CHOICES = ['rapida', 'completa', 'reemplazo']

            categoria = drf_serializers.ChoiceField(
                choices=[c[0] for c in __import__(
                    'mecanimovilapp.apps.checklists.models',
                    fromlist=['ChecklistItemCatalog']
                ).ChecklistItemCatalog.CATEGORIA_CHOICES],
            )
            componente_ids = drf_serializers.ListField(
                child=drf_serializers.IntegerField(min_value=1),
                min_length=1,
            )
            tipo_evaluacion = drf_serializers.ChoiceField(choices=TIPO_EVALUACION_CHOICES)

        return _BulkAddItemsSerializer


class ChecklistInstanceViewSet(viewsets.ModelViewSet):
    """ViewSet para instancias de checklist"""
    serializer_class = ChecklistInstanceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _contexto_proveedor(self):
        from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller
        return resolver_contexto_taller(self.request.user)

    def _usuario_tiene_acceso_orden(self, user, orden) -> bool:
        taller, miembro, rol = self._contexto_proveedor()
        if rol == 'mecanico' and miembro is not None:
            return orden.mecanico_asignado_id == miembro.id
        if taller is not None and orden.taller_id == taller.id:
            return True
        if hasattr(user, 'mecanico_domicilio') and orden.mecanico_id == user.mecanico_domicilio.id:
            return True
        return False

    def _usuario_tiene_acceso_cita(self, user, cita) -> bool:
        taller, miembro, rol = self._contexto_proveedor()
        if rol == 'mecanico' and miembro is not None:
            return cita.miembro_taller_id == miembro.id
        if taller is not None and cita.taller_id == taller.id:
            return True
        if hasattr(user, 'mecanico_domicilio') and cita.mecanico_id == user.mecanico_domicilio.id:
            return True
        return False

    def _usuario_tiene_acceso_instance(self, user, instance) -> bool:
        if instance.orden_id:
            return self._usuario_tiene_acceso_orden(user, instance.orden)
        if instance.cita_personal_id:
            return self._usuario_tiene_acceso_cita(user, instance.cita_personal)
        return False
    
    def get_queryset(self):
        """Filtrar checklist por proveedor autenticado"""
        from django.db.models import Q

        user = self.request.user
        taller, miembro, rol = self._contexto_proveedor()

        base_qs = ChecklistInstance.objects.select_related(
            'orden', 'cita_personal', 'checklist_template'
        ).prefetch_related(
            'respuestas__fotos', 'respuestas__item_template'
        )

        if rol == 'mecanico' and miembro is not None:
            return base_qs.filter(
                Q(orden__mecanico_asignado=miembro) | Q(cita_personal__miembro_taller=miembro)
            )

        if taller is not None:
            return base_qs.filter(
                Q(orden__taller=taller) | Q(cita_personal__taller=taller)
            )

        if hasattr(user, 'mecanico_domicilio'):
            return base_qs.filter(
                Q(orden__mecanico=user.mecanico_domicilio)
                | Q(cita_personal__mecanico=user.mecanico_domicilio)
            )

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
            orden_id = request.data.get('orden')
            cita_id = request.data.get('cita_personal')
            template_id = request.data.get('checklist_template')

            if not orden_id and not cita_id:
                logger.error("🔸 ERROR: Falta campo 'orden' o 'cita_personal' en los datos")
                return Response(
                    {'error': 'Se requiere el campo orden o cita_personal'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if orden_id and cita_id:
                return Response(
                    {'error': 'Indique solo uno: orden o cita_personal'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if 'checklist_template' not in request.data:
                logger.error("🔸 ERROR: Falta campo 'checklist_template' en los datos")
                return Response({'error': 'Se requiere el campo checklist_template'}, status=status.HTTP_400_BAD_REQUEST)
            
            logger.info(f"🔸 Orden ID: {orden_id}, Cita ID: {cita_id}, Template ID: {template_id}")
            
            orden = None
            cita = None
            if orden_id:
                try:
                    from mecanimovilapp.apps.ordenes.models import SolicitudServicio
                    orden = SolicitudServicio.objects.get(id=orden_id)
                    logger.info(f"🔸 Orden encontrada: ID {orden.id}, Estado: {orden.estado}")
                except SolicitudServicio.DoesNotExist:
                    logger.error(f"🔸 ERROR: No existe orden con ID {orden_id}")
                    return Response({'error': f'No existe orden con ID {orden_id}'}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal
                    cita = CitaAgendaPersonal.objects.get(id=cita_id)
                    logger.info(f"🔸 Cita personal encontrada: ID {cita.id}, Estado: {cita.estado}")
                except CitaAgendaPersonal.DoesNotExist:
                    logger.error(f"🔸 ERROR: No existe cita con ID {cita_id}")
                    return Response({'error': f'No existe cita con ID {cita_id}'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Verificar que el template existe
            try:
                template = ChecklistTemplate.objects.get(id=template_id)
                logger.info(f"🔸 Template encontrado: ID {template.id}, Nombre: {template.nombre}")
            except ChecklistTemplate.DoesNotExist:
                logger.error(f"🔸 ERROR: No existe template con ID {template_id}")
                return Response({'error': f'No existe template con ID {template_id}'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Verificar acceso
            user = request.user
            tiene_acceso = (
                self._usuario_tiene_acceso_orden(user, orden)
                if orden is not None
                else self._usuario_tiene_acceso_cita(user, cita)
            )
            
            if tiene_acceso:
                parent_id = orden.id if orden else cita.id
                logger.info(f"🔸 Acceso verificado para {'orden' if orden else 'cita'} {parent_id}")
            
            if not tiene_acceso:
                logger.error(f"🔸 ERROR: Usuario {user.username} sin acceso")
                return Response({'error': 'No tienes acceso a este checklist'}, status=status.HTTP_403_FORBIDDEN)
            
            # Verificar instancia existente
            if orden is not None:
                existing = ChecklistInstance.objects.filter(orden=orden).first()
            else:
                existing = ChecklistInstance.objects.filter(cita_personal=cita).first()
            if existing:
                parent_label = orden.id if orden else cita.id
                logger.warning(f"🔸 ADVERTENCIA: Ya existe checklist para {parent_label} - ID: {existing.id}")
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
                        'orden__cliente__usuario',
                        'orden__taller',
                        'orden__mecanico',
                        'orden__vehiculo',
                        'orden__mecanico_asignado',
                    ).prefetch_related(
                        'respuestas__fotos',
                        'respuestas__item_template__catalog_item',
                        'orden__mecanico_asignado__especialidades',
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
                        'orden__cliente__usuario',
                        'orden__taller',
                        'orden__mecanico',
                        'orden__vehiculo',
                        'orden__mecanico_asignado',
                    ).prefetch_related(
                        'respuestas__fotos',
                        'respuestas__item_template__catalog_item',
                        'orden__mecanico_asignado__especialidades',
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

    @action(detail=False, methods=['get'], url_path='by_cita_personal/(?P<cita_id>[^/.]+)')
    def by_cita_personal(self, request, cita_id=None):
        """Obtener checklist por ID de cita personal del taller."""
        import logging
        logger = logging.getLogger(__name__)

        if not cita_id:
            return Response(
                {'error': 'Se requiere el ID de la cita personal'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            instance = ChecklistInstance.objects.select_related(
                'cita_personal__detalle',
                'cita_personal__miembro_taller',
                'checklist_template',
                'checklist_template__servicio',
            ).prefetch_related(
                'checklist_template__items__catalog_item',
                'respuestas__fotos',
                'respuestas__item_template__catalog_item',
                'cita_personal__miembro_taller__especialidades',
            ).get(cita_personal_id=cita_id)
        except ChecklistInstance.DoesNotExist:
            return Response(
                {'error': 'No existe checklist para esta cita personal'},
                status=status.HTTP_404_NOT_FOUND,
            )

        user = request.user
        if not self._usuario_tiene_acceso_cita(user, instance.cita_personal):
            return Response(
                {'error': 'No tienes acceso a este checklist'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = self.get_serializer(instance)
        logger.info('Checklist devuelto para cita personal %s', cita_id)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """Iniciar un checklist (solo entonces la orden pasa a 'checklist_en_progreso')."""
        instance = self.get_object()

        # Idempotente: si ya está en progreso, devolver la instancia (evita error al reintentar).
        if instance.estado == 'EN_PROGRESO':
            serializer = self.get_serializer(instance)
            return Response(serializer.data)

        if instance.estado == 'PAUSADO':
            return Response(
                {'error': 'El checklist está pausado. Usa reanudar para continuar.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if instance.estado != 'PENDIENTE':
            return Response(
                {'error': f'El checklist no se puede iniciar desde el estado {instance.estado}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        instance.estado = 'EN_PROGRESO'
        instance.fecha_inicio = timezone.now()
        instance.save(update_fields=['estado', 'fecha_inicio'])

        # Pasar la orden a checklist_en_progreso solo cuando el proveedor inicia el checklist
        if instance.orden_id and instance.orden.estado == 'confirmado':
            orden = instance.orden
            orden.estado = 'checklist_en_progreso'
            orden.save(update_fields=['estado'])

        serializer = self.get_serializer(instance)
        return Response(serializer.data)
    
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
        parent_ref = (
            f'orden {instance.orden_id}'
            if instance.orden_id
            else f'cita {instance.cita_personal_id}'
        )
        logger.info(
            f"🔸 Finalizando checklist ID: {instance.id} para {parent_ref}"
        )

        # ✅ Idempotencia: ya completado, devolver 200 (evita fallos por reintentos).
        if instance.estado == 'COMPLETADO':
            logger.warning(f"🔸 finalize llamado pero checklist ya COMPLETADO: {instance.id}")
            if instance.cita_personal_id:
                cita = instance.cita_personal
                return Response(
                    {
                        'message': 'El checklist ya fue finalizado anteriormente',
                        'checklist_id': instance.id,
                        'cita_personal_id': cita.id,
                        'cita_estado_nuevo': cita.estado,
                        'estado': instance.estado,
                        'requiere_firma_cliente': False,
                    },
                    status=status.HTTP_200_OK,
                )
            orden = instance.orden
            if orden and orden.estado == 'completado':
                hubo, oferta_ref = sincronizar_cierre_marketplace(orden.id)
                if hubo and oferta_ref:
                    _notificar_websocket_cierre_marketplace(oferta_ref, orden.id, logger)
            return Response(
                {
                    'message': 'El checklist ya fue finalizado anteriormente',
                    'checklist_id': instance.id,
                    'orden_id': instance.orden_id,
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
                    'orden_id': instance.orden_id,
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

        instance.firma_tecnico = firma_a_payload_base64(firma_tecnico)

        # Registrar el momento exacto en que el proveedor completa su parte.
        # Se usa para KPIs de tiempo real (excluye espera de firma del cliente).
        ahora = timezone.now()
        if not instance.fecha_completado_proveedor:
            instance.fecha_completado_proveedor = ahora

        if firma_cliente_presente:
            # Flujo legacy con cliente presente: cierre inmediato.
            instance.estado = 'COMPLETADO'
            instance.fecha_finalizacion = ahora
            instance.firma_cliente = firma_a_payload_base64(firma_cliente)
            instance.progreso_porcentaje = 100
        elif instance.cita_personal_id:
            # Cita personal: no hay firma de cliente en app; cierra con firma del técnico.
            instance.estado = 'COMPLETADO'
            instance.fecha_finalizacion = ahora
            instance.progreso_porcentaje = 100
        else:
            # Flujo marketplace (firma diferida): el cliente firmará desde su app.
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

        # tiempo_total_minutos: solo el trabajo del proveedor (inicio → firma técnico).
        # Esto excluye la espera de firma del cliente, que puede ser horas o días.
        if instance.fecha_inicio and instance.fecha_completado_proveedor:
            tiempo_proveedor = instance.fecha_completado_proveedor - instance.fecha_inicio
            instance.tiempo_total_minutos = max(0, int(tiempo_proveedor.total_seconds() / 60))

        instance.save()

        # Actualizar estado de la orden o cita personal
        if instance.cita_personal_id:
            cita = instance.cita_personal
            if instance.estado == 'COMPLETADO' and cita.estado == 'activa':
                cita.cerrar()
                cita.save(update_fields=['estado', 'cerrada_en', 'fecha_actualizacion'])
                logger.info('Cita personal %s cerrada tras checklist completado', cita.id)
            return Response(
                {
                    'message': 'Checklist finalizado correctamente',
                    'checklist_id': instance.id,
                    'cita_personal_id': cita.id,
                    'cita_estado_nuevo': cita.estado,
                    'estado': instance.estado,
                    'requiere_firma_cliente': False,
                    'template_generado_por_ia': bool(
                        getattr(instance.checklist_template, 'generado_por_ia', False)
                        and instance.checklist_template.revisado_en is None
                    ),
                }
            )

        orden = instance.orden
        estado_anterior = orden.estado

        if firma_cliente_presente:
            # Cierre con ambas firmas: orden debe quedar completada y marketplace alineado.
            if orden.estado != 'completado':
                orden.estado = 'completado'
                orden.save(update_fields=['estado'])
                logger.info(
                    f"🔸 (legacy 2 firmas) Orden actualizada: {estado_anterior} → {orden.estado}"
                )
            hubo_sync, oferta_ref = sincronizar_cierre_marketplace(orden.id)
            if hubo_sync and oferta_ref:
                _notificar_websocket_cierre_marketplace(oferta_ref, orden.id, logger)
            if orden.estado == 'completado':
                try:
                    from mecanimovilapp.apps.usuarios.review_notification_utils import (
                        notificar_resena_pendiente_si_aplica,
                    )
                    notificar_resena_pendiente_si_aplica(orden.id)
                except Exception as exc:
                    logger.warning('review_reminder no enviado (orden %s): %s', orden.id, exc)
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
                orden = instance.orden
                if orden.estado == 'completado':
                    hubo, oferta_ref = sincronizar_cierre_marketplace(orden.id)
                    if hubo and oferta_ref:
                        _notificar_websocket_cierre_marketplace(oferta_ref, orden.id, logger)
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
            instance.firma_tecnico = firma_a_payload_base64(firma_tecnico)

            ahora = timezone.now()
            if not instance.fecha_completado_proveedor:
                instance.fecha_completado_proveedor = ahora

            if firma_cliente_presente:
                instance.estado = 'COMPLETADO'
                instance.fecha_finalizacion = ahora
                instance.firma_cliente = firma_a_payload_base64(firma_cliente)
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

            if instance.fecha_inicio and instance.fecha_completado_proveedor:
                tiempo_proveedor = instance.fecha_completado_proveedor - instance.fecha_inicio
                instance.tiempo_total_minutos = max(0, int(tiempo_proveedor.total_seconds() / 60))

            instance.save()

            orden = instance.orden
            estado_anterior = orden.estado

            if firma_cliente_presente:
                orden.estado = 'completado'
                orden.save(update_fields=['estado'])
                hubo_sync, oferta_ref = sincronizar_cierre_marketplace(orden.id)
                if hubo_sync and oferta_ref:
                    _notificar_websocket_cierre_marketplace(oferta_ref, orden.id, logger)
                try:
                    from mecanimovilapp.apps.usuarios.review_notification_utils import (
                        notificar_resena_pendiente_si_aplica,
                    )
                    notificar_resena_pendiente_si_aplica(orden.id)
                except Exception as exc:
                    logger.warning('review_reminder no enviado (orden %s): %s', orden.id, exc)
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

        # Idempotencia: ya completado (repara oferta/solicitud si quedaron desfasadas).
        if instance.estado == 'COMPLETADO':
            orden = instance.orden
            if orden.estado == 'completado':
                hubo, oferta_ref = sincronizar_cierre_marketplace(orden.id)
                if hubo and oferta_ref:
                    _notificar_websocket_cierre_marketplace(
                        oferta_ref, orden.id, logger
                    )
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

        instance.firma_cliente = firma_a_payload_base64(firma_cliente)
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

        with transaction.atomic():
            instance.save()

            orden.estado = 'completado'
            orden.save(update_fields=['estado'])

        hubo_sync, oferta_marketplace = sincronizar_cierre_marketplace(orden.id)
        if hubo_sync and oferta_marketplace:
            _notificar_websocket_cierre_marketplace(oferta_marketplace, orden.id, logger)

        try:
            from mecanimovilapp.apps.usuarios.review_notification_utils import (
                notificar_resena_pendiente_si_aplica,
            )
            notificar_resena_pendiente_si_aplica(orden.id)
        except Exception as exc:
            logger.warning('review_reminder no enviado (orden %s): %s', orden.id, exc)

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
        por las respuestas guardadas hasta el momento. Usa la misma política
        de prioridad que actualizar_salud_desde_checklist para resultados
        coherentes.
        """
        from mecanimovilapp.apps.vehiculos.tasks import (
            _porcentaje_inspeccion_desde_respuesta,
            _nivel_alerta_desde_pct,
            _candidatos_por_componente,
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

        respuestas = list(instance.respuestas.select_related(
            'item_template__componente_salud_asociado',
            'item_template__catalog_item',
            'item_template__checklist_template',
        ).all())

        candidatos = _candidatos_por_componente(respuestas)
        componente_ids = set(candidatos.keys())

        estados_map = {
            c.componente_id: c
            for c in ComponenteSaludVehiculo.objects.select_related('componente').filter(
                vehiculo=vehiculo, componente_id__in=componente_ids,
            )
        }
        estado_general = EstadoSaludVehiculo.objects.filter(vehiculo=vehiculo).first()
        salud_general_actual = (
            round(estado_general.salud_general_porcentaje, 1)
            if estado_general else None
        )

        diff = []
        for comp_id, r in candidatos.items():
            item_template = r.item_template
            componente = item_template.componente_salud_asociado
            tipo_act = item_template.tipo_actualizacion_efectivo

            estado = estados_map.get(comp_id)
            salud_actual = round(estado.salud_porcentaje, 1) if estado else None

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

    @action(detail=True, methods=['get'], url_path='recomendaciones')
    def recomendaciones(self, request, pk=None):
        """
        Retorna las recomendaciones ML generadas post-checklist.

        Accesible para:
          - El proveedor (taller o mecánico) de la orden.
          - El cliente dueño de la orden.

        Solo disponible cuando la instancia está en estado COMPLETADO.
        Los resultados se cachean en Redis 24h y se generan via Celery al completarse.
        Si el cache no está listo aún, los genera en el momento (respuesta más lenta).
        """
        import logging
        rec_logger = logging.getLogger(__name__)

        instance = self.get_object()

        # Verificar que es COMPLETADO
        if instance.estado != 'COMPLETADO':
            return Response(
                {
                    'error': (
                        f'Las recomendaciones solo están disponibles cuando el checklist '
                        f'está completado (estado actual: {instance.estado}).'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Verificar permisos: proveedor de la orden OR cliente dueño
        user = request.user
        orden = instance.orden
        es_proveedor = (
            (hasattr(user, 'taller') and getattr(orden, 'taller', None) == user.taller)
            or (hasattr(user, 'mecanico_domicilio') and getattr(orden, 'mecanico', None) == user.mecanico_domicilio)
        )
        usuario_cliente = getattr(getattr(orden, 'cliente', None), 'usuario', None)
        es_cliente = usuario_cliente is not None and usuario_cliente.id == user.id

        if not es_proveedor and not es_cliente:
            # Intento de acceso anónimo o de usuario no relacionado a la orden
            rec_logger.warning(
                'recomendaciones: usuario %s no tiene permiso para checklist %s',
                user.id, instance.id,
            )
            return Response(
                {'error': 'No tienes permiso para ver las recomendaciones de este checklist.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            from mecanimovilapp.apps.vehiculos.services.checklist_recommender import (
                generar_recomendaciones,
            )
            resultado = generar_recomendaciones(instance.id)
            if resultado is None:
                return Response(
                    {'recomendaciones': [], 'componentes_actualizados': [], 'checklist_id': instance.id},
                    status=status.HTTP_200_OK,
                )
            return Response(resultado, status=status.HTTP_200_OK)
        except Exception as e:
            rec_logger.error(
                'recomendaciones: error generando para checklist %s: %s',
                instance.id, e, exc_info=True,
            )
            return Response(
                {'error': 'No se pudieron generar las recomendaciones.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


def _usuario_tiene_acceso_checklist_instance(user, instance) -> bool:
    """Acceso a checklist de orden marketplace o cita personal (incluye mecánico de equipo)."""
    from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller

    taller, miembro, rol = resolver_contexto_taller(user)
    if instance.orden_id:
        orden = instance.orden
        if rol == 'mecanico' and miembro is not None:
            return orden.mecanico_asignado_id == miembro.id
        if taller is not None and orden.taller_id == taller.id:
            return True
        if hasattr(user, 'mecanico_domicilio') and orden.mecanico_id == user.mecanico_domicilio.id:
            return True
        return False

    if instance.cita_personal_id:
        cita = instance.cita_personal
        if rol == 'mecanico' and miembro is not None:
            return cita.miembro_taller_id == miembro.id
        if taller is not None and cita.taller_id == taller.id:
            return True
        if hasattr(user, 'mecanico_domicilio') and cita.mecanico_id == user.mecanico_domicilio.id:
            return True
        return False

    return False


def _queryset_respuestas_proveedor(user):
    from django.db.models import Q
    from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller

    taller, miembro, rol = resolver_contexto_taller(user)
    base = ChecklistItemResponse.objects.select_related(
        'checklist_instance',
        'checklist_instance__orden',
        'checklist_instance__cita_personal',
        'item_template',
    ).prefetch_related('fotos')

    if rol == 'mecanico' and miembro is not None:
        return base.filter(
            Q(checklist_instance__orden__mecanico_asignado=miembro)
            | Q(checklist_instance__cita_personal__miembro_taller=miembro)
        )
    if taller is not None:
        return base.filter(
            Q(checklist_instance__orden__taller=taller)
            | Q(checklist_instance__cita_personal__taller=taller)
        )
    if hasattr(user, 'mecanico_domicilio'):
        return base.filter(
            Q(checklist_instance__orden__mecanico=user.mecanico_domicilio)
            | Q(checklist_instance__cita_personal__mecanico=user.mecanico_domicilio)
        )
    return ChecklistItemResponse.objects.none()


class ChecklistResponseViewSet(viewsets.ModelViewSet):
    """ViewSet para respuestas de checklist"""
    serializer_class = ChecklistItemResponseSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Filtrar respuestas por checklist del proveedor (orden o cita personal)."""
        return _queryset_respuestas_proveedor(self.request.user)
    
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
            instance = ChecklistInstance.objects.select_related(
                'orden', 'cita_personal',
            ).get(id=checklist_instance_id)

            if not _usuario_tiene_acceso_checklist_instance(request.user, instance):
                logger.warning(
                    'Usuario %s no tiene acceso a checklist %s',
                    request.user.username,
                    checklist_instance_id,
                )
                return Response(
                    {'error': 'No tienes acceso a este checklist'},
                    status=status.HTTP_403_FORBIDDEN,
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
        """Filtrar fotos por checklist del proveedor (orden o cita personal)."""
        from django.db.models import Q
        from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller

        user = self.request.user
        taller, miembro, rol = resolver_contexto_taller(user)
        base = ChecklistPhoto.objects.select_related(
            'response',
            'response__checklist_instance',
            'response__checklist_instance__orden',
            'response__checklist_instance__cita_personal',
        )

        if rol == 'mecanico' and miembro is not None:
            return base.filter(
                Q(response__checklist_instance__orden__mecanico_asignado=miembro)
                | Q(response__checklist_instance__cita_personal__miembro_taller=miembro)
            )
        if taller is not None:
            return base.filter(
                Q(response__checklist_instance__orden__taller=taller)
                | Q(response__checklist_instance__cita_personal__taller=taller)
            )
        if hasattr(user, 'mecanico_domicilio'):
            return base.filter(
                Q(response__checklist_instance__orden__mecanico=user.mecanico_domicilio)
                | Q(response__checklist_instance__cita_personal__mecanico=user.mecanico_domicilio)
            )
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