"""Vistas públicas de vitrina de repuestos."""
from __future__ import annotations

from rest_framework import permissions, status, views
from rest_framework.response import Response

from mecanimovilapp.apps.ordenes.models import VitrinaRepuestos
from mecanimovilapp.apps.ordenes.services.vitrina_repuestos import (
    marcar_abierta,
    registrar_seleccion,
    serializar_vitrina_publica,
)
from mecanimovilapp.apps.ordenes.throttling import VitrinaRepuestosThrottle

_CACHE = 'private, no-store, no-cache, must-revalidate'


def _resp(payload, status_code=status.HTTP_200_OK):
    r = Response(payload, status=status_code)
    r['Cache-Control'] = _CACHE
    return r


class VitrinaRepuestosDetailView(views.APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [VitrinaRepuestosThrottle]

    def get(self, request, token=None):
        vit = (
            VitrinaRepuestos.objects.select_related('taller', 'cotizacion')
            .filter(token=token)
            .first()
        )
        if vit is None:
            return Response({'error': 'No encontrada'}, status=status.HTTP_404_NOT_FOUND)
        if vit.estado == VitrinaRepuestos.ESTADO_EXPIRADA:
            return _resp(
                {
                    'error': 'Este link ya venció. Escríbenos y te mandamos las opciones de nuevo.',
                    'codigo': 'enlace_expirado',
                    'expirado': True,
                },
                status.HTTP_410_GONE,
            )
        marcar_abierta(vit)
        return _resp(serializar_vitrina_publica(vit))


class VitrinaRepuestosSeleccionarView(views.APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [VitrinaRepuestosThrottle]

    def post(self, request, token=None):
        vit = VitrinaRepuestos.objects.filter(token=token).first()
        if vit is None:
            return Response({'error': 'No encontrada'}, status=status.HTTP_404_NOT_FOUND)
        if vit.estado == VitrinaRepuestos.ESTADO_EXPIRADA:
            return _resp(
                {
                    'error': 'Este link ya venció. Escríbenos y te mandamos las opciones de nuevo.',
                    'codigo': 'enlace_expirado',
                    'expirado': True,
                },
                status.HTTP_410_GONE,
            )
        out = registrar_seleccion(vit, request.data or {})
        if not out.get('ok'):
            code = out.get('error')
            if code == 'expirada':
                return _resp({'error': 'Este link ya venció.'}, status.HTTP_410_GONE)
            return Response({'error': 'Selección inválida'}, status=status.HTTP_400_BAD_REQUEST)
        return _resp({
            'ok': True,
            'mensaje': out.get('mensaje')
            or 'Listo. Se lo pasamos al taller para que te confirme el valor.',
        })
