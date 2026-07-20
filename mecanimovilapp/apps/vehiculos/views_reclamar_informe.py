"""Endpoint autenticado para reclamar informe de servicio."""

from rest_framework import permissions, status, views
from rest_framework.response import Response

from mecanimovilapp.apps.vehiculos.services.reclamar_informe import reclamar_informe_por_token


class ReclamarInformeView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, token=None):
        if not hasattr(request.user, 'cliente'):
            return Response(
                {'error': 'Solo clientes pueden reclamar un informe de servicio'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            result = reclamar_informe_por_token(token, request.user.cliente)
            return Response(result, status=status.HTTP_200_OK)
        except ValueError as exc:
            msg = str(exc)
            code = status.HTTP_400_BAD_REQUEST
            if 'otro usuario' in msg.lower() or 'ya está registrada' in msg.lower():
                code = status.HTTP_409_CONFLICT
            return Response({'error': msg}, status=code)
