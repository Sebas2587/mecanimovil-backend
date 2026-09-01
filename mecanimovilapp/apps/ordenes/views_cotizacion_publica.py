"""Vistas públicas de cotización (link compartido, sin autenticación)."""
from __future__ import annotations

from django.http import HttpResponse
from rest_framework import permissions, status, views
from rest_framework.response import Response

from mecanimovilapp.apps.ordenes.models import CotizacionCanal
from mecanimovilapp.apps.ordenes.services.cotizacion_pdf import generar_pdf_cotizacion_publica
from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
    aceptar_cotizacion_publica,
    cotizacion_publica_expirada,
    emision_pendiente,
    marcar_cotizacion_expirada_si_corresponde,
    marcar_visto,
    on_cotizacion_respondida,
    rechazar_cotizacion_publica,
    serializar_cotizacion_publica,
)
from mecanimovilapp.apps.ordenes.throttling import CotizacionPublicaThrottle

_CACHE_PUBLICA = 'private, no-store, no-cache, must-revalidate'
_MSG_EMISION_PENDIENTE = (
    'El taller está actualizando esta cotización. '
    'En breve recibirás la versión nueva.'
)


def _respuesta_publica(payload, status_code=status.HTTP_200_OK):
    resp = Response(payload, status=status_code)
    resp['Cache-Control'] = _CACHE_PUBLICA
    return resp


_TALLER_RELATED = (
    'taller',
    'taller__usuario',
    'taller__direccion_fisica',
    'cotizacion_original',
    'cita_origen',
    'cita_origen__detalle',
    'conversation',
    'conversation__external_contact',
)


class CotizacionPublicaDetailView(views.APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [CotizacionPublicaThrottle]

    def get(self, request, token=None):
        cotizacion = (
            CotizacionCanal.objects.select_related(*_TALLER_RELATED)
            .filter(token=token)
            .first()
        )
        if cotizacion is None:
            return Response({'error': 'Cotización no encontrada'}, status=status.HTTP_404_NOT_FOUND)
        marcar_cotizacion_expirada_si_corresponde(cotizacion)
        if cotizacion_publica_expirada(cotizacion):
            return _respuesta_publica(
                {
                    'error': 'Este enlace de cotización ha expirado',
                    'codigo': 'enlace_expirado',
                    'expirado': True,
                    'cotizacion': serializar_cotizacion_publica(cotizacion, request),
                },
                status.HTTP_410_GONE,
            )
        marcar_visto(cotizacion)
        return _respuesta_publica(serializar_cotizacion_publica(cotizacion, request))


class CotizacionPublicaAceptarView(views.APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [CotizacionPublicaThrottle]

    def post(self, request, token=None):
        cotizacion = (
            CotizacionCanal.objects.select_related(
                'taller',
                'taller__usuario',
                'taller__direccion_fisica',
                'creado_por',
                'cotizacion_original',
                'cita_origen',
                'cita_origen__detalle',
            )
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
        if emision_pendiente(cotizacion):
            return Response(
                {
                    'error': _MSG_EMISION_PENDIENTE,
                    'codigo': 'emision_pendiente',
                    'cotizacion': serializar_cotizacion_publica(cotizacion, request),
                },
                status=status.HTTP_409_CONFLICT,
            )
        if cotizacion.estado != 'enviada':
            return Response(
                {
                    'message': 'Esta cotización ya fue respondida',
                    'estado': cotizacion.estado,
                    'cotizacion': serializar_cotizacion_publica(cotizacion, request),
                },
                status=status.HTTP_200_OK,
            )
        try:
            cotizacion, cita = aceptar_cotizacion_publica(cotizacion)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        on_cotizacion_respondida(cotizacion, 'aceptar', cita_id=cita.id if cita else None)
        data = serializar_cotizacion_publica(cotizacion, request)
        if cita is not None and not cotizacion.es_cotizacion_adicional:
            data['cita_id'] = cita.id
            data['horario_por_confirmar'] = True
        elif cotizacion.es_cotizacion_adicional:
            data['horario_por_confirmar'] = False
        return Response(data)


class CotizacionPublicaRechazarView(views.APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [CotizacionPublicaThrottle]

    def post(self, request, token=None):
        cotizacion = (
            CotizacionCanal.objects.select_related(
                'taller',
                'taller__usuario',
                'taller__direccion_fisica',
            )
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
        if emision_pendiente(cotizacion):
            return Response(
                {
                    'error': _MSG_EMISION_PENDIENTE,
                    'codigo': 'emision_pendiente',
                    'cotizacion': serializar_cotizacion_publica(cotizacion, request),
                },
                status=status.HTTP_409_CONFLICT,
            )
        if cotizacion.estado != 'enviada':
            return Response(
                {
                    'message': 'Esta cotización ya fue respondida',
                    'estado': cotizacion.estado,
                    'cotizacion': serializar_cotizacion_publica(cotizacion, request),
                },
                status=status.HTTP_200_OK,
            )
        try:
            cotizacion = rechazar_cotizacion_publica(cotizacion)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        on_cotizacion_respondida(cotizacion, 'rechazar')
        return Response(serializar_cotizacion_publica(cotizacion, request))


class CotizacionPublicaPdfView(views.APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [CotizacionPublicaThrottle]

    def get(self, request, token=None):
        cotizacion = (
            CotizacionCanal.objects.select_related(*_TALLER_RELATED)
            .filter(token=token)
            .first()
        )
        if cotizacion is None:
            return Response({'error': 'Cotización no encontrada'}, status=status.HTTP_404_NOT_FOUND)
        marcar_cotizacion_expirada_si_corresponde(cotizacion)
        pdf_bytes = generar_pdf_cotizacion_publica(cotizacion, request)
        folio = (cotizacion.numero_publico or f'MM-{cotizacion.pk:06d}').strip()
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="Cotizacion-{folio}.pdf"'
        response['Cache-Control'] = _CACHE_PUBLICA
        return response
