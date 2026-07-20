"""Vistas de liquidación a proveedores."""
from __future__ import annotations

from django.db.models import Sum
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from mecanimovilapp.apps.pagos.models import LiquidacionProveedor
from mecanimovilapp.apps.pagos.serializers import LiquidacionProveedorSerializer


class LiquidacionProveedorViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LiquidacionProveedorSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = LiquidacionProveedor.objects.filter(usuario=self.request.user).order_by('-creado_en')
        estado = self.request.query_params.get('estado')
        if estado:
            qs = qs.filter(estado=estado)
        return qs

    @action(detail=False, methods=['get'], url_path='resumen')
    def resumen(self, request):
        qs = self.get_queryset()
        pendiente = qs.filter(estado='pendiente').aggregate(
            total=Sum('monto_neto_proveedor'),
        )
        pagada = qs.filter(estado='pagada').aggregate(total=Sum('monto_neto_proveedor'))
        return Response({
            'saldo_pendiente_clp': float(pendiente['total'] or 0),
            'cantidad_pendiente': qs.filter(estado='pendiente').count(),
            'total_liquidado_clp': float(pagada['total'] or 0),
        })
