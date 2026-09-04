"""CRUD de casas de repuestos y precios propios del taller."""
from __future__ import annotations

from rest_framework import permissions, viewsets
from rest_framework.exceptions import PermissionDenied

from mecanimovilapp.apps.ordenes.models import PrecioProveedorTaller, ProveedorRepuestos
from mecanimovilapp.apps.ordenes.permissions import IsProveedor
from mecanimovilapp.apps.ordenes.serializers_proveedor_repuestos import (
    PrecioProveedorTallerSerializer,
    ProveedorRepuestosSerializer,
)
from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller


def _taller_mandante(request):
    taller, _miembro, rol = resolver_contexto_taller(request.user)
    if taller is None or rol == 'mecanico':
        raise PermissionDenied('Solo mandante o supervisor pueden gestionar casas de repuestos.')
    return taller


class ProveedorRepuestosViewSet(viewsets.ModelViewSet):
    serializer_class = ProveedorRepuestosSerializer
    permission_classes = [permissions.IsAuthenticated, IsProveedor]

    def get_queryset(self):
        try:
            taller = _taller_mandante(self.request)
        except PermissionDenied:
            return ProveedorRepuestos.objects.none()
        qs = ProveedorRepuestos.objects.filter(taller=taller)
        if self.request.query_params.get('activos') == '1':
            qs = qs.filter(activo=True)
        return qs.order_by('-es_preferido', 'nombre')

    def perform_create(self, serializer):
        serializer.save(taller=_taller_mandante(self.request))

    def perform_destroy(self, instance):
        if instance.precios.exists():
            instance.activo = False
            instance.save(update_fields=['activo', 'actualizado_en'])
            return
        instance.delete()


class PrecioProveedorTallerViewSet(viewsets.ModelViewSet):
    serializer_class = PrecioProveedorTallerSerializer
    permission_classes = [permissions.IsAuthenticated, IsProveedor]
    http_method_names = ['get', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        try:
            taller = _taller_mandante(self.request)
        except PermissionDenied:
            return PrecioProveedorTaller.objects.none()
        qs = PrecioProveedorTaller.objects.filter(taller=taller).select_related('proveedor')
        q = (self.request.query_params.get('q') or '').strip()
        if q:
            qs = qs.filter(nombre_repuesto__icontains=q)
        vigente = (self.request.query_params.get('vigente') or '').strip()
        if vigente == '1':
            from django.utils import timezone
            from datetime import timedelta
            from mecanimovilapp.apps.ordenes.services.precios_proveedor import vigencia_dias

            since = timezone.now() - timedelta(days=vigencia_dias())
            qs = qs.filter(registrado_en__gte=since)
        return qs.order_by('-registrado_en')
