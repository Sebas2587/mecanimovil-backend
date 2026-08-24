"""API pipeline comercial unificado para proveedores."""
from __future__ import annotations

from urllib.parse import unquote

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from mecanimovilapp.apps.ordenes.permissions import IsProveedor
from mecanimovilapp.apps.ordenes.services.pipeline_comercial import (
    construir_pipeline_cliente_detalle,
    construir_pipeline_clientes,
    construir_pipeline_comercial,
)
from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller


class PipelineComercialViewSet(viewsets.ViewSet):
    """Vista agregada de seguimiento comercial multi-origen."""

    permission_classes = [permissions.IsAuthenticated, IsProveedor]

    def _contexto(self, request):
        taller_ctx, miembro_ctx, rol_ctx = resolver_contexto_taller(request.user)
        miembro_param = request.query_params.get('miembro_taller')
        miembro_id = None
        if rol_ctx == 'mecanico' and miembro_ctx is not None:
            miembro_id = miembro_ctx.id
        elif miembro_param:
            try:
                miembro_id = int(miembro_param)
            except (TypeError, ValueError):
                miembro_id = None
        return taller_ctx, miembro_id

    def _limite(self, request, default: int = 100) -> int:
        limite_raw = request.query_params.get('limite', str(default))
        try:
            return min(int(limite_raw), 500)
        except (TypeError, ValueError):
            return default

    def list(self, request):
        taller_ctx, miembro_id = self._contexto(request)
        estado = request.query_params.get('estado_normalizado')
        origen = request.query_params.get('origen')
        solo_24h = request.query_params.get('esperando_24h', '').lower() in ('1', 'true', 'yes')
        incluir_borradores = request.query_params.get('incluir_borradores', '').lower() in (
            '1',
            'true',
            'yes',
        )
        q = (request.query_params.get('q') or '').strip() or None

        payload = construir_pipeline_comercial(
            user=request.user,
            taller=taller_ctx,
            estado_normalizado=estado or None,
            origen=origen or None,
            solo_esperando_24h=solo_24h,
            miembro_taller_id=miembro_id,
            limite=self._limite(request),
            incluir_borradores=incluir_borradores,
            q=q,
        )
        return Response(payload)

    @action(detail=False, methods=['get'], url_path='clientes')
    def clientes(self, request):
        taller_ctx, miembro_id = self._contexto(request)
        origen = request.query_params.get('origen')
        prioridad = (request.query_params.get('prioridad') or 'todos').strip().lower()
        q = (request.query_params.get('q') or '').strip() or None
        payload = construir_pipeline_clientes(
            user=request.user,
            taller=taller_ctx,
            origen=origen or None,
            prioridad=prioridad,
            miembro_taller_id=miembro_id,
            limite=self._limite(request),
            q=q,
        )
        return Response(payload)

    @action(detail=False, methods=['get'], url_path=r'clientes/(?P<cliente_key>[^/]+)')
    def cliente_detalle(self, request, cliente_key=None):
        taller_ctx, miembro_id = self._contexto(request)
        key = unquote(cliente_key or '').strip()
        payload = construir_pipeline_cliente_detalle(
            user=request.user,
            taller=taller_ctx,
            cliente_key=key,
            miembro_taller_id=miembro_id,
        )
        if payload is None:
            return Response({'detail': 'Cliente no encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(payload)
