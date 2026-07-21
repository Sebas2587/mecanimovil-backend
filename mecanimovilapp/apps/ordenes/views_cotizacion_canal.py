"""API cotizaciones canal con IA."""
from __future__ import annotations

from django.db.models import F
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class CotizacionCanalPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200

from mecanimovilapp.apps.chat.models import Conversation
from mecanimovilapp.apps.ordenes.models import CotizacionCanal, CotizacionCanalPlantilla
from mecanimovilapp.apps.ordenes.permissions import IsProveedor
from mecanimovilapp.apps.ordenes.serializers_cotizacion_canal import (
    CotizacionCanalPlantillaSerializer,
    CotizacionCanalSerializer,
    GenerarCotizacionIaSerializer,
    GuardarPlantillaCotizacionSerializer,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador import generar_cotizacion_ia
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.permisos import usuario_puede_cotizar_canal
from mecanimovilapp.apps.ordenes.services.cotizacion_canal import (
    aplicar_edicion_cotizacion,
    enviar_cotizacion_canal,
    snapshot_desde_cotizacion,
)
from mecanimovilapp.apps.ordenes.services.cotizacion_publica import enviar_cotizacion_libre
from mecanimovilapp.apps.ordenes.services.plantilla_vehiculo import filtrar_plantillas_por_vehiculo
from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller


class CotizacionCanalViewSet(viewsets.ModelViewSet):
    serializer_class = CotizacionCanalSerializer
    permission_classes = [permissions.IsAuthenticated, IsProveedor]
    pagination_class = CotizacionCanalPagination
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def _taller_contexto(self):
        taller, _miembro, rol = resolver_contexto_taller(self.request.user)
        if taller is None or rol == 'mecanico':
            raise PermissionDenied('Solo mandante o supervisor pueden gestionar cotizaciones.')
        return taller, rol

    def _get_conversation(self, conversation_id: int) -> Conversation:
        conversation = Conversation.objects.filter(pk=conversation_id).first()
        if conversation is None:
            raise ValidationError({'conversation_id': 'Conversación no encontrada.'})
        if not usuario_puede_cotizar_canal(self.request.user, conversation=conversation):
            raise PermissionDenied('No tienes acceso a esta conversación.')
        return conversation

    def get_queryset(self):
        try:
            taller, _rol = self._taller_contexto()
        except PermissionDenied:
            return CotizacionCanal.objects.none()
        return CotizacionCanal.objects.filter(taller=taller).select_related(
            'conversation',
            'conversation__external_contact',
        )

    @action(detail=False, methods=['post'], url_path='generar-ia')
    def generar_ia(self, request):
        taller, _rol = self._taller_contexto()
        ser = GenerarCotizacionIaSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        conversation_id = data.get('conversation_id')
        conversation = None
        es_libre = conversation_id is None
        if conversation_id is not None:
            conversation = self._get_conversation(conversation_id)

        cliente_nombre = (data.get('cliente_nombre') or '').strip()
        cliente_telefono = (data.get('cliente_telefono') or '').strip()

        plantilla_id = data.get('plantilla_id')
        if plantilla_id:
            plantilla = CotizacionCanalPlantilla.objects.filter(pk=plantilla_id, taller=taller).first()
            if plantilla is None:
                raise ValidationError({'plantilla_id': 'Plantilla no encontrada.'})
            snap = plantilla.snapshot or {}
            CotizacionCanalPlantilla.objects.filter(pk=plantilla.pk).update(
                uso_count=F('uso_count') + 1,
            )
            cotizacion = CotizacionCanal.objects.create(
                conversation=conversation,
                es_libre=es_libre,
                cliente_nombre=cliente_nombre,
                cliente_telefono=cliente_telefono,
                taller=taller,
                creado_por=request.user,
                estado='borrador',
                modalidad=snap.get('modalidad') or data.get('modalidad') or 'taller',
                vehiculo_marca=snap.get('vehiculo_marca') or data.get('vehiculo', {}).get('marca', ''),
                vehiculo_modelo=snap.get('vehiculo_modelo') or data.get('vehiculo', {}).get('modelo', ''),
                vehiculo_anio=snap.get('vehiculo_anio') or data.get('vehiculo', {}).get('anio'),
                vehiculo_patente=snap.get('vehiculo_patente') or data.get('vehiculo', {}).get('patente', ''),
                vehiculo_cilindraje=snap.get('vehiculo_cilindraje') or data.get('vehiculo', {}).get('cilindraje', ''),
                tipo_motor=snap.get('tipo_motor', ''),
                tipo_motor_label=snap.get('tipo_motor_label', ''),
                servicio_nombre=snap.get('servicio_nombre') or data.get('servicio_nombre', ''),
                descripcion_problema=snap.get('descripcion_problema') or data.get('descripcion_problema', ''),
                repuestos=snap.get('repuestos') or [],
                mano_obra_clp=snap.get('mano_obra_clp') or 0,
                costo_repuestos_clp=snap.get('costo_repuestos_clp') or 0,
                total_clp=snap.get('total_clp') or 0,
                duracion_minutos_estimada=snap.get('duracion_minutos_estimada'),
                advertencias=snap.get('advertencias') or [],
                metadata={'origen': 'plantilla', 'plantilla_id': plantilla_id},
            )
            return Response({
                'disponible': True,
                'cotizacion': CotizacionCanalSerializer(cotizacion).data,
                'desde_plantilla': True,
            }, status=status.HTTP_201_CREATED)

        resultado = generar_cotizacion_ia(
            conversation=conversation,
            servicio_nombre=data.get('servicio_nombre', ''),
            descripcion_problema=data.get('descripcion_problema', ''),
            modalidad=data.get('modalidad', 'taller'),
            vehiculo=data.get('vehiculo') or {},
        )
        if not resultado.get('disponible'):
            return Response(resultado, status=status.HTTP_200_OK)

        contenido = resultado['contenido'] or {}
        ctx = resultado.get('contexto') or {}
        veh = data.get('vehiculo') or {}
        anio_raw = veh.get('anio') or ctx.get('vehiculo_anio')
        try:
            anio_int = int(anio_raw) if anio_raw else None
        except (TypeError, ValueError):
            anio_int = None

        cotizacion = CotizacionCanal.objects.create(
            conversation=conversation,
            es_libre=es_libre,
            cliente_nombre=cliente_nombre,
            cliente_telefono=cliente_telefono,
            taller=taller,
            creado_por=request.user,
            estado='borrador',
            modalidad=data.get('modalidad', 'taller'),
            vehiculo_marca=ctx.get('vehiculo_marca') or veh.get('marca', ''),
            vehiculo_modelo=ctx.get('vehiculo_modelo') or veh.get('modelo', ''),
            vehiculo_anio=anio_int,
            vehiculo_patente=ctx.get('vehiculo_patente') or veh.get('patente', ''),
            vehiculo_cilindraje=ctx.get('vehiculo_cilindraje') or veh.get('cilindraje', ''),
            vehiculo_vin=str(veh.get('vin') or '')[:50],
            tipo_motor=contenido.get('tipo_motor') or ctx.get('tipo_motor', ''),
            tipo_motor_label=contenido.get('tipo_motor_label') or ctx.get('tipo_motor_label', ''),
            aviso_motor=contenido.get('aviso_motor') or ctx.get('aviso_motor', ''),
            servicio_nombre=contenido.get('servicio_nombre', ''),
            descripcion_problema=contenido.get('descripcion_problema', ''),
            repuestos=contenido.get('repuestos') or [],
            mano_obra_clp=contenido.get('mano_obra_clp') or 0,
            costo_repuestos_clp=contenido.get('costo_repuestos_clp') or 0,
            total_clp=contenido.get('total_clp') or 0,
            duracion_minutos_estimada=contenido.get('duracion_minutos_estimada'),
            advertencias=contenido.get('advertencias') or [],
            contenido_ia=resultado.get('contenido_ia') or {},
            tokens_entrada=resultado.get('tokens_entrada') or 0,
            tokens_salida=resultado.get('tokens_salida') or 0,
            modelo_ia=resultado.get('modelo') or '',
        )
        return Response({
            **resultado,
            'cotizacion': CotizacionCanalSerializer(cotizacion).data,
        }, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        cotizacion = self.get_object()
        if cotizacion.estado != 'borrador':
            raise ValidationError({'estado': 'Solo se puede editar una cotización en borrador.'})
        aplicar_edicion_cotizacion(cotizacion, request.data)
        cotizacion.save()
        return Response(CotizacionCanalSerializer(cotizacion).data)

    @action(detail=True, methods=['post'])
    def enviar(self, request, pk=None):
        cotizacion = self.get_object()
        if cotizacion.estado != 'borrador':
            raise ValidationError({'estado': 'La cotización ya fue enviada o cerrada.'})
        if not cotizacion.servicio_nombre.strip():
            raise ValidationError({'servicio_nombre': 'Indica el nombre del servicio.'})

        if cotizacion.es_libre or cotizacion.conversation_id is None:
            try:
                cotizacion = enviar_cotizacion_libre(cotizacion)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            return Response({
                'cotizacion': CotizacionCanalSerializer(cotizacion).data,
                'message_id': None,
                'share_url': cotizacion.url_publica,
            })

        try:
            message = enviar_cotizacion_canal(cotizacion, request.user)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        from mecanimovilapp.apps.omnichannel.tasks import send_meta_message

        if cotizacion.conversation.source_channel != 'APP':
            send_meta_message.delay(message.id)

        return Response({
            'cotizacion': CotizacionCanalSerializer(cotizacion).data,
            'message_id': message.id,
            'share_url': None,
        })

    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        cotizacion = self.get_object()
        if cotizacion.estado in ('aceptada', 'cancelada'):
            raise ValidationError({'estado': 'No se puede cancelar esta cotización.'})
        cotizacion.estado = 'cancelada'
        cotizacion.save(update_fields=['estado', 'actualizado_en'])
        return Response(CotizacionCanalSerializer(cotizacion).data)

    @action(detail=True, methods=['post'], url_path='marcar-aceptada')
    def marcar_aceptada(self, request, pk=None):
        """Fallback mandante cuando cliente acepta por teléfono (Messenger/IG)."""
        cotizacion = self.get_object()
        if cotizacion.estado != 'enviada':
            raise ValidationError({'estado': 'Solo cotizaciones enviadas pueden marcarse como aceptadas.'})
        cotizacion.estado = 'aceptada'
        cotizacion.aceptada_en = timezone.now()
        cotizacion.save(update_fields=['estado', 'aceptada_en', 'actualizado_en'])
        return Response(CotizacionCanalSerializer(cotizacion).data)

    @action(detail=True, methods=['post'], url_path='marcar-perdida')
    def marcar_perdida(self, request, pk=None):
        """Cierra el lead comercial desde la bandeja (taller)."""
        cotizacion = self.get_object()
        if cotizacion.estado in ('aceptada', 'cancelada', 'rechazada'):
            raise ValidationError({'estado': 'Esta cotización ya está cerrada.'})
        cotizacion.estado = 'cancelada'
        cotizacion.save(update_fields=['estado', 'actualizado_en'])
        return Response(CotizacionCanalSerializer(cotizacion).data)

    @action(detail=False, methods=['get'], url_path=r'por-conversacion/(?P<conversation_id>[^/.]+)')
    def por_conversacion(self, request, conversation_id=None):
        taller, _rol = self._taller_contexto()
        conversation = self._get_conversation(int(conversation_id))
        qs = CotizacionCanal.objects.filter(
            taller=taller,
            conversation=conversation,
        ).order_by('-creado_en')[:20]
        return Response(CotizacionCanalSerializer(qs, many=True).data)


class CotizacionCanalPlantillaViewSet(viewsets.ModelViewSet):
    serializer_class = CotizacionCanalPlantillaSerializer
    permission_classes = [permissions.IsAuthenticated, IsProveedor]
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def _taller(self):
        taller, _miembro, rol = resolver_contexto_taller(self.request.user)
        if taller is None or rol == 'mecanico':
            raise PermissionDenied('Solo mandante o supervisor pueden gestionar plantillas.')
        return taller

    def get_queryset(self):
        try:
            taller = self._taller()
        except PermissionDenied:
            return CotizacionCanalPlantilla.objects.none()
        return CotizacionCanalPlantilla.objects.filter(taller=taller)

    def list(self, request, *args, **kwargs):
        queryset = list(self.filter_queryset(self.get_queryset()))
        marca = (request.query_params.get('marca') or '').strip()
        modelo = (request.query_params.get('modelo') or '').strip()
        cilindraje = (request.query_params.get('cilindraje') or '').strip()
        if marca and modelo:
            queryset = filtrar_plantillas_por_vehiculo(
                queryset,
                marca=marca,
                modelo=modelo,
                cilindraje=cilindraje,
            )
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        taller = self._taller()
        ser = GuardarPlantillaCotizacionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        snapshot = data.get('snapshot')
        cotizacion_id = data.get('cotizacion_id')
        if snapshot is None and cotizacion_id:
            cot = CotizacionCanal.objects.filter(pk=cotizacion_id, taller=taller).first()
            if cot is None:
                raise ValidationError({'cotizacion_id': 'Cotización no encontrada.'})
            snapshot = snapshot_desde_cotizacion(cot)
        if not snapshot:
            raise ValidationError({'snapshot': 'Debes indicar snapshot o cotizacion_id.'})
        plantilla = CotizacionCanalPlantilla.objects.create(
            taller=taller,
            creado_por=request.user,
            titulo=data['titulo'][:255],
            snapshot=snapshot,
        )
        return Response(
            CotizacionCanalPlantillaSerializer(plantilla).data,
            status=status.HTTP_201_CREATED,
        )
