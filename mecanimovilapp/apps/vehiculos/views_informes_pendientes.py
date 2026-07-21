"""Endpoints autenticados: listar y reclamar informes pendientes por patente."""

from rest_framework import permissions, status, views
from rest_framework.response import Response

from mecanimovilapp.apps.vehiculos.services.informes_por_patente import (
    listar_informes_pendientes_por_patente,
)
from mecanimovilapp.apps.vehiculos.services.reclamar_informe import reclamar_informe_por_token


class InformesPendientesPorPatenteView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not hasattr(request.user, 'cliente'):
            return Response(
                {'error': 'Solo clientes pueden consultar informes pendientes'},
                status=status.HTTP_403_FORBIDDEN,
            )

        patente = request.query_params.get('patente', '').strip()
        if not patente:
            return Response(
                {'error': 'Debe proporcionar una patente'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        informes = listar_informes_pendientes_por_patente(patente)
        return Response({'informes': informes, 'count': len(informes)}, status=status.HTTP_200_OK)


class ReclamarInformesBatchView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not hasattr(request.user, 'cliente'):
            return Response(
                {'error': 'Solo clientes pueden reclamar informes de servicio'},
                status=status.HTTP_403_FORBIDDEN,
            )

        tokens = request.data.get('tokens') or []
        if not isinstance(tokens, list) or not tokens:
            return Response(
                {'error': 'Debe proporcionar una lista de tokens'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        resultados = []
        exitosos = 0
        for raw in tokens:
            token = str(raw or '').strip()
            if not token:
                continue
            try:
                result = reclamar_informe_por_token(token, request.user.cliente)
                resultados.append({
                    'token': token,
                    'success': True,
                    'message': result.get('message') or 'Servicio vinculado correctamente.',
                    'already_claimed': bool(result.get('already_claimed')),
                    'vehiculo_id': result.get('vehiculo_id'),
                    'componentes_oficiales': result.get('componentes_oficiales') or [],
                })
                exitosos += 1
            except ValueError as exc:
                resultados.append({
                    'token': token,
                    'success': False,
                    'message': str(exc),
                })

        return Response(
            {
                'resultados': resultados,
                'exitosos': exitosos,
                'total': len(resultados),
            },
            status=status.HTTP_200_OK,
        )
