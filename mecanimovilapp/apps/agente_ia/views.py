"""API REST del agente IA conversacional."""
from __future__ import annotations

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from mecanimovilapp.apps.agente_ia.models import (
    AgenteConversacionSesion,
    TallerAgenteConfig,
    TallerConocimientoDocumento,
)
from mecanimovilapp.apps.agente_ia.serializers import (
    AgenteSesionSerializer,
    TallerAgenteConfigSerializer,
    TallerConocimientoDocumentoSerializer,
)
from mecanimovilapp.apps.agente_ia.services.orquestador import pausar_sesion_por_mensaje_taller
from mecanimovilapp.apps.agente_ia.tasks import procesar_documento_conocimiento_task
from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller


class AgenteIaViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def _taller(self, request):
        taller, _, _ = resolver_contexto_taller(request.user)
        if not taller:
            raise ValidationError({'error': 'No se encontró contexto de taller.'})
        return taller

    @action(detail=False, methods=['get', 'patch'], url_path='config')
    def config(self, request):
        taller = self._taller(request)
        config, _ = TallerAgenteConfig.objects.get_or_create(taller=taller)
        if request.method == 'GET':
            return Response(TallerAgenteConfigSerializer(config).data)
        ser = TallerAgenteConfigSerializer(config, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(TallerAgenteConfigSerializer(config).data)

    @action(detail=False, methods=['get', 'post'], url_path='documentos')
    def documentos(self, request):
        taller = self._taller(request)
        if request.method == 'GET':
            docs = TallerConocimientoDocumento.objects.filter(taller=taller).order_by('-creado_en')
            return Response(TallerConocimientoDocumentoSerializer(docs, many=True).data)

        ser = TallerConocimientoDocumentoSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if not ser.validated_data.get('archivo') and not (ser.validated_data.get('texto_pegado') or '').strip():
            raise ValidationError({'detail': 'Sube un archivo o pega texto.'})
        doc = ser.save(taller=taller, creado_por=request.user)
        procesar_documento_conocimiento_task.delay(doc.id)
        return Response(
            TallerConocimientoDocumentoSerializer(doc).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=['delete'], url_path=r'documentos/(?P<doc_id>[^/.]+)')
    def eliminar_documento(self, request, doc_id=None):
        taller = self._taller(request)
        doc = TallerConocimientoDocumento.objects.filter(pk=doc_id, taller=taller).first()
        if not doc:
            return Response({'error': 'Documento no encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        doc.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['get'], url_path='sesion')
    def sesion(self, request):
        """Estado de sesión IA para una conversación. Nunca 400 por falta de contexto."""
        raw_id = (request.query_params.get('conversation_id') or '').strip()
        if not raw_id.isdigit():
            return Response({'activa': False})

        taller, _, _ = resolver_contexto_taller(request.user)
        if not taller:
            return Response({'activa': False})

        sesion = AgenteConversacionSesion.objects.filter(
            conversation_id=int(raw_id),
            taller=taller,
        ).first()
        if not sesion:
            return Response({'activa': False})
        data = AgenteSesionSerializer(sesion).data
        data['activa'] = (
            not sesion.pausado_por_taller
            and sesion.estado not in (
                AgenteConversacionSesion.ESTADO_PAUSADO,
                AgenteConversacionSesion.ESTADO_CERRADO,
            )
        )
        return Response(data)

    @action(detail=False, methods=['post'], url_path='pausar')
    def pausar(self, request):
        conversation_id = request.data.get('conversation_id')
        if not conversation_id:
            raise ValidationError({'conversation_id': 'Requerido.'})
        taller = self._taller(request)
        updated = AgenteConversacionSesion.objects.filter(
            conversation_id=conversation_id,
            taller=taller,
        ).update(
            pausado_por_taller=True,
            estado=AgenteConversacionSesion.ESTADO_PAUSADO,
        )
        if not updated:
            pausar_sesion_por_mensaje_taller(int(conversation_id))
        return Response({'pausado': True})

    @action(detail=False, methods=['post'], url_path='reanudar')
    def reanudar(self, request):
        conversation_id = request.data.get('conversation_id')
        if not conversation_id:
            raise ValidationError({'conversation_id': 'Requerido.'})
        taller = self._taller(request)
        AgenteConversacionSesion.objects.filter(
            conversation_id=conversation_id,
            taller=taller,
        ).update(
            pausado_por_taller=False,
            estado=AgenteConversacionSesion.ESTADO_CAPTURANDO,
        )
        return Response({'reanudado': True})

    @action(detail=False, methods=['get'], url_path='borradores-pendientes')
    def borradores_pendientes(self, request):
        """Sesiones con cotización IA esperando revisión del taller."""
        taller = self._taller(request)
        sesiones = (
            AgenteConversacionSesion.objects.filter(
                taller=taller,
                estado=AgenteConversacionSesion.ESTADO_ESPERANDO_REVISION,
                cotizacion_borrador__isnull=False,
            )
            .select_related('cotizacion_borrador')
            .order_by('-actualizado_en')[:20]
        )
        items = [
            {
                'sesion_id': s.id,
                'conversation_id': s.conversation_id,
                'cotizacion_id': s.cotizacion_borrador_id,
                'servicio_nombre': (
                    s.cotizacion_borrador.servicio_nombre if s.cotizacion_borrador else ''
                ),
            }
            for s in sesiones
        ]
        return Response({'count': len(items), 'results': items})
