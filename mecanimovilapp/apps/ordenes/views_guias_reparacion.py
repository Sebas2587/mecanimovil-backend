"""API de guías de reparación guardadas por mecánico."""
from __future__ import annotations

from django.db.models import Count
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from mecanimovilapp.apps.ordenes.models import (
    CitaAgendaPersonal,
    DiagnosticoAsistidoCitaPersonal,
    DiagnosticoAsistidoOrden,
    GuiaReparacionGuardada,
    SolicitudServicio,
)
from mecanimovilapp.apps.ordenes.permissions import IsProveedor
from mecanimovilapp.apps.ordenes.serializers_guias_reparacion import (
    GuiaReparacionGuardadaSerializer,
    GuardarGuiaReparacionSerializer,
)
from mecanimovilapp.apps.ordenes.services.asistente_diagnostico.permisos import (
    usuario_puede_usar_asistente_ia,
)


class GuiaReparacionGuardadaViewSet(viewsets.ModelViewSet):
    """Biblioteca personal de guías IA del mecánico autenticado."""

    serializer_class = GuiaReparacionGuardadaSerializer
    permission_classes = [permissions.IsAuthenticated, IsProveedor]
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def _miembro_mecanico(self):
        from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller

        taller, miembro, rol = resolver_contexto_taller(self.request.user)
        if rol != 'mecanico' or miembro is None:
            raise PermissionDenied('Solo los mecánicos pueden acceder a sus guías guardadas.')
        if taller is None:
            raise PermissionDenied('No se encontró el taller del mecánico.')
        return taller, miembro

    def get_queryset(self):
        try:
            _taller, miembro = self._miembro_mecanico()
        except PermissionDenied:
            return GuiaReparacionGuardada.objects.none()

        qs = GuiaReparacionGuardada.objects.filter(miembro_taller=miembro)
        marca = (self.request.query_params.get('marca') or '').strip()
        modelo = (self.request.query_params.get('modelo') or '').strip()
        if marca:
            qs = qs.filter(vehiculo_marca__iexact=marca)
        if modelo:
            qs = qs.filter(vehiculo_modelo__iexact=modelo)
        return qs

    def create(self, request, *args, **kwargs):
        taller, miembro = self._miembro_mecanico()
        ser = GuardarGuiaReparacionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        origen = data['origen']
        origen_id = data['origen_id']
        diagnostico_id = data['diagnostico_id']

        if origen == 'orden':
            orden = SolicitudServicio.objects.select_related('vehiculo__marca', 'vehiculo__modelo').filter(
                pk=origen_id,
            ).first()
            if orden is None or not usuario_puede_usar_asistente_ia(request.user, orden=orden):
                raise PermissionDenied('No puedes guardar guías de esta orden.')
            diagnostico = DiagnosticoAsistidoOrden.objects.filter(
                pk=diagnostico_id,
                orden=orden,
                estado='completado',
            ).first()
            if diagnostico is None:
                raise ValidationError({'diagnostico_id': 'Diagnóstico no encontrado o incompleto.'})
            if GuiaReparacionGuardada.objects.filter(
                miembro_taller=miembro,
                diagnostico_orden=diagnostico,
            ).exists():
                existente = GuiaReparacionGuardada.objects.get(miembro_taller=miembro, diagnostico_orden=diagnostico)
                return Response(GuiaReparacionGuardadaSerializer(existente).data, status=status.HTTP_200_OK)

            vehiculo = orden.vehiculo
            marca = getattr(getattr(vehiculo, 'marca', None), 'nombre', '') or ''
            modelo = getattr(getattr(vehiculo, 'modelo', None), 'nombre', '') or ''
            anio = getattr(vehiculo, 'year', None)
            patente = getattr(vehiculo, 'patente', '') or ''
            titulo = (diagnostico.contenido or {}).get('problema_reportado') or f'Orden #{orden.id}'
            guia = GuiaReparacionGuardada.objects.create(
                miembro_taller=miembro,
                taller=taller,
                vehiculo_marca=marca,
                vehiculo_modelo=modelo,
                vehiculo_anio=anio,
                vehiculo_patente=patente,
                titulo=str(titulo)[:255],
                contenido=diagnostico.contenido or {},
                origen='orden',
                origen_id=orden.id,
                diagnostico_orden=diagnostico,
            )
        else:
            cita = CitaAgendaPersonal.objects.select_related('detalle').filter(pk=origen_id).first()
            if cita is None or not usuario_puede_usar_asistente_ia(request.user, cita=cita):
                raise PermissionDenied('No puedes guardar guías de esta cita.')
            diagnostico = DiagnosticoAsistidoCitaPersonal.objects.filter(
                pk=diagnostico_id,
                cita=cita,
                estado='completado',
            ).first()
            if diagnostico is None:
                raise ValidationError({'diagnostico_id': 'Diagnóstico no encontrado o incompleto.'})
            if GuiaReparacionGuardada.objects.filter(
                miembro_taller=miembro,
                diagnostico_cita=diagnostico,
            ).exists():
                existente = GuiaReparacionGuardada.objects.get(miembro_taller=miembro, diagnostico_cita=diagnostico)
                return Response(GuiaReparacionGuardadaSerializer(existente).data, status=status.HTTP_200_OK)

            det = cita.detalle
            titulo = (diagnostico.contenido or {}).get('problema_reportado') or (det.servicio_nombre if det else f'Cita #{cita.id}')
            guia = GuiaReparacionGuardada.objects.create(
                miembro_taller=miembro,
                taller=taller,
                vehiculo_marca=(det.vehiculo_marca if det else '') or '',
                vehiculo_modelo=(det.vehiculo_modelo if det else '') or '',
                vehiculo_anio=det.vehiculo_anio if det else None,
                vehiculo_patente=(det.vehiculo_patente if det else '') or '',
                titulo=str(titulo)[:255],
                contenido=diagnostico.contenido or {},
                origen='cita',
                origen_id=cita.id,
                diagnostico_cita=diagnostico,
            )

        return Response(GuiaReparacionGuardadaSerializer(guia).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path='agrupadas')
    def agrupadas(self, request):
        """Lista marcas/modelos con conteo de guías del mecánico."""
        _taller, miembro = self._miembro_mecanico()
        filas = (
            GuiaReparacionGuardada.objects.filter(miembro_taller=miembro)
            .values('vehiculo_marca', 'vehiculo_modelo')
            .annotate(total=Count('id'))
            .order_by('vehiculo_marca', 'vehiculo_modelo')
        )
        grupos: dict[str, list[dict]] = {}
        for fila in filas:
            marca = (fila['vehiculo_marca'] or 'Sin marca').strip()
            modelos = grupos.setdefault(marca, [])
            modelos.append({
                'modelo': (fila['vehiculo_modelo'] or 'Sin modelo').strip(),
                'total': fila['total'],
            })
        resultado = [
            {'marca': marca, 'modelos': modelos}
            for marca, modelos in sorted(grupos.items(), key=lambda x: x[0].lower())
        ]
        return Response(resultado, status=status.HTTP_200_OK)
