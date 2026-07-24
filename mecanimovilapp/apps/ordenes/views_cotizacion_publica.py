"""Vistas públicas de cotización (link compartido, sin autenticación)."""
from __future__ import annotations

from rest_framework import permissions, status, views
from rest_framework.response import Response

from mecanimovilapp.apps.ordenes.models import CotizacionCanal
from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
    aceptar_cotizacion_publica,
    cotizacion_publica_expirada,
    marcar_cotizacion_expirada_si_corresponde,
    marcar_visto,
    on_cotizacion_respondida,
    rechazar_cotizacion_publica,
    serializar_cotizacion_publica,
)
from mecanimovilapp.apps.ordenes.throttling import CotizacionPublicaThrottle


class CotizacionPublicaDetailView(views.APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [CotizacionPublicaThrottle]

    def get(self, request, token=None):
        cotizacion = (
            CotizacionCanal.objects.select_related('taller', 'taller__direccion_fisica')
            .filter(token=token)
            .first()
        )
        if cotizacion is None:
            return Response({'error': 'Cotización no encontrada'}, status=status.HTTP_404_NOT_FOUND)
        marcar_cotizacion_expirada_si_corresponde(cotizacion)
        if cotizacion_publica_expirada(cotizacion):
            return Response(
                {
                    'error': 'Este enlace de cotización ha expirado',
                    'codigo': 'enlace_expirado',
                    'expirado': True,
                    'cotizacion': serializar_cotizacion_publica(cotizacion),
                },
                status=status.HTTP_410_GONE,
            )
        marcar_visto(cotizacion)
        return Response(serializar_cotizacion_publica(cotizacion))


class CotizacionPublicaAceptarView(views.APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [CotizacionPublicaThrottle]

    def post(self, request, token=None):
        cotizacion = (
            CotizacionCanal.objects.select_related('taller', 'taller__direccion_fisica', 'creado_por')
            .filter(token=token)
            .first()
        )
        if cotizacion is None:
            return Response({'error': 'Cotización no encontrada'}, status=status.HTTP_404_NOT_FOUND)
        marcar_cotizacion_expirada_si_corresponde(cotizacion)
        if cotizacion_publica_expirada(cotizacion):
            return Response(
                {'error': 'Este enlace de cotización ha expirado', 'codigo': 'enlace_expirado'},
                status=status.HTTP_410_GONE,
            )
        if cotizacion.estado != 'enviada':
            return Response(
                {
                    'message': 'Esta cotización ya fue respondida',
                    'estado': cotizacion.estado,
                    'cotizacion': serializar_cotizacion_publica(cotizacion),
                },
                status=status.HTTP_200_OK,
            )
        try:
            cotizacion, cita = aceptar_cotizacion_publica(cotizacion)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        on_cotizacion_respondida(cotizacion, 'aceptar', cita_id=cita.id)
        data = serializar_cotizacion_publica(cotizacion)
        data['cita_id'] = cita.id
        data['horario_por_confirmar'] = True
        return Response(data)


class CotizacionPublicaRechazarView(views.APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [CotizacionPublicaThrottle]

    def post(self, request, token=None):
        cotizacion = (
            CotizacionCanal.objects.select_related('taller', 'taller__direccion_fisica')
            .filter(token=token)
            .first()
        )
        if cotizacion is None:
            return Response({'error': 'Cotización no encontrada'}, status=status.HTTP_404_NOT_FOUND)
        marcar_cotizacion_expirada_si_corresponde(cotizacion)
        if cotizacion_publica_expirada(cotizacion):
            return Response(
                {'error': 'Este enlace de cotización ha expirado', 'codigo': 'enlace_expirado'},
                status=status.HTTP_410_GONE,
            )
        if cotizacion.estado != 'enviada':
            return Response(
                {
                    'message': 'Esta cotización ya fue respondida',
                    'estado': cotizacion.estado,
                    'cotizacion': serializar_cotizacion_publica(cotizacion),
                },
                status=status.HTTP_200_OK,
            )
        try:
            cotizacion = rechazar_cotizacion_publica(cotizacion)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        on_cotizacion_respondida(cotizacion, 'rechazar')
        return Response(serializar_cotizacion_publica(cotizacion))
