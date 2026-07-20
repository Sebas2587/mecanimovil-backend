"""API pipeline comercial unificado para proveedores."""
from __future__ import annotations

from rest_framework import permissions, viewsets
from rest_framework.response import Response

from mecanimovilapp.apps.ordenes.permissions import IsProveedor
from mecanimovilapp.apps.ordenes.services.pipeline_comercial import construir_pipeline_comercial
from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller


class PipelineComercialViewSet(viewsets.ViewSet):
    """Vista agregada de seguimiento comercial multi-origen."""

    permission_classes = [permissions.IsAuthenticated, IsProveedor]

    def list(self, request):
        taller_ctx, miembro_ctx, rol_ctx = resolver_contexto_taller(request.user)
        estado = request.query_params.get('estado_normalizado')
        origen = request.query_params.get('origen')
        solo_24h = request.query_params.get('esperando_24h', '').lower() in ('1', 'true', 'yes')
        limite_raw = request.query_params.get('limite', '100')
        try:
            limite = min(int(limite_raw), 200)
        except (TypeError, ValueError):
            limite = 100

        miembro_param = request.query_params.get('miembro_taller')
        miembro_id = None
        if rol_ctx == 'mecanico' and miembro_ctx is not None:
            miembro_id = miembro_ctx.id
        elif miembro_param:
            try:
                miembro_id = int(miembro_param)
            except (TypeError, ValueError):
                miembro_id = None

        payload = construir_pipeline_comercial(
            user=request.user,
            taller=taller_ctx,
            estado_normalizado=estado or None,
            origen=origen or None,
            solo_esperando_24h=solo_24h,
            miembro_taller_id=miembro_id,
            limite=limite,
        )
        return Response(payload)
