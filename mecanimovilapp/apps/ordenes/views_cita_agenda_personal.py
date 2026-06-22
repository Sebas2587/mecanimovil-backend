"""
API de citas de agenda personal del proveedor.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, SolicitudServicio
from mecanimovilapp.apps.ordenes.permissions import IsProveedor
from mecanimovilapp.apps.ordenes.serializers_cita_agenda_personal import (
    CitaAgendaPersonalCreateSerializer,
    CitaAgendaPersonalSerializer,
    CitaAgendaPersonalUpdateSerializer,
    EventoAgendaUnificadoSerializer,
)
from mecanimovilapp.apps.ordenes.services.cita_agenda_personal import (
    actualizar_cita_personal,
    crear_cita_personal,
    resolver_proveedor_usuario,
    validar_cita_personal_slot,
    _categorias_de_oferta,
)


class IsCitaAgendaPersonalOwner(permissions.BasePermission):
    def has_object_permission(self, request, view, obj: CitaAgendaPersonal) -> bool:
        taller, mecanico = resolver_proveedor_usuario(request.user)
        if taller and obj.taller_id == taller.id:
            return True
        if mecanico and obj.mecanico_id == mecanico.id:
            return True
        return False


class CitaAgendaPersonalViewSet(viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated, IsProveedor, IsCitaAgendaPersonalOwner]
    serializer_class = CitaAgendaPersonalSerializer

    def get_queryset(self):
        taller, mecanico = resolver_proveedor_usuario(self.request.user)
        if taller:
            return (
                CitaAgendaPersonal.objects.filter(taller=taller)
                .select_related('detalle', 'detalle__oferta_servicio__servicio', 'miembro_taller')
                .prefetch_related('miembro_taller__especialidades')
                .order_by('-fecha_servicio', '-hora_servicio')
            )
        if mecanico:
            return (
                CitaAgendaPersonal.objects.filter(mecanico=mecanico)
                .select_related('detalle', 'detalle__oferta_servicio__servicio', 'miembro_taller')
                .prefetch_related('miembro_taller__especialidades')
                .order_by('-fecha_servicio', '-hora_servicio')
            )
        return CitaAgendaPersonal.objects.none()

    def get_permissions(self):
        if self.action in ('create', 'list', 'validar_slot', 'cerradas', 'canceladas'):
            return [permissions.IsAuthenticated(), IsProveedor()]
        return super().get_permissions()

    def get_object(self):
        return get_object_or_404(self.get_queryset(), pk=self.kwargs['pk'])

    def list(self, request):
        qs = self.get_queryset()
        estado = request.query_params.get('estado')
        if estado:
            qs = qs.filter(estado=estado)
        fecha_desde = request.query_params.get('fecha_desde')
        fecha_hasta = request.query_params.get('fecha_hasta')
        if fecha_desde:
            qs = qs.filter(fecha_servicio__gte=fecha_desde)
        if fecha_hasta:
            qs = qs.filter(fecha_servicio__lte=fecha_hasta)
        serializer = CitaAgendaPersonalSerializer(qs, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        cita = self.get_object()
        return Response(CitaAgendaPersonalSerializer(cita).data)

    def create(self, request):
        ser = CitaAgendaPersonalCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        try:
            cita = crear_cita_personal(
                user=request.user,
                cabecera={
                    'fecha_servicio': data['fecha_servicio'],
                    'hora_servicio': data['hora_servicio'],
                    'duracion_minutos': data.get('duracion_minutos'),
                    'tipo_servicio': data['tipo_servicio'],
                    'miembro_taller': data.get('miembro_taller'),
                },
                detalle=data['detalle'],
            )
        except DjangoValidationError as e:
            raise ValidationError(e.message_dict if hasattr(e, 'message_dict') else str(e))
        return Response(
            CitaAgendaPersonalSerializer(cita).data,
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, pk=None):
        cita = self.get_object()
        ser = CitaAgendaPersonalUpdateSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        try:
            cita = actualizar_cita_personal(
                cita,
                cabecera={k: v for k, v in data.items() if k != 'detalle'},
                detalle=data.get('detalle'),
            )
        except DjangoValidationError as e:
            raise ValidationError(e.message_dict if hasattr(e, 'message_dict') else str(e))
        return Response(CitaAgendaPersonalSerializer(cita).data)

    def destroy(self, request, pk=None):
        cita = self.get_object()
        if cita.estado != 'cancelada':
            return Response(
                {
                    'error': 'Solo se pueden eliminar citas canceladas.',
                    'codigo': 'cita_no_eliminable',
                },
                status=status.HTTP_409_CONFLICT,
            )
        try:
            cita.delete()
        except ProtectedError:
            return Response(
                {'error': 'No se pudo eliminar la cita.', 'codigo': 'cita_no_eliminable'},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def cerrar(self, request, pk=None):
        cita = self.get_object()
        if cita.estado != 'activa':
            return Response(
                {'error': 'Solo se pueden cerrar citas activas.'},
                status=status.HTTP_409_CONFLICT,
            )
        cita.cerrar()
        cita.save(update_fields=['estado', 'cerrada_en', 'fecha_actualizacion'])
        return Response(CitaAgendaPersonalSerializer(cita).data)

    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        cita = self.get_object()
        if cita.estado != 'activa':
            return Response(
                {'error': 'Solo se pueden cancelar citas activas.'},
                status=status.HTTP_409_CONFLICT,
            )
        cita.cancelar()
        cita.save(update_fields=['estado', 'cancelada_en', 'fecha_actualizacion'])
        return Response(CitaAgendaPersonalSerializer(cita).data)

    @action(detail=False, methods=['post'], url_path='validar-slot')
    def validar_slot(self, request):
        ser = CitaAgendaPersonalCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        taller, mecanico = resolver_proveedor_usuario(request.user)
        excluir = request.data.get('excluir_cita_id')
        detalle = data.get('detalle') or {}
        oferta = detalle.get('oferta_servicio')
        try:
            validar_cita_personal_slot(
                taller=taller,
                mecanico=mecanico,
                tipo_servicio=data['tipo_servicio'],
                fecha=data['fecha_servicio'],
                hora=data['hora_servicio'],
                duracion_minutos=data.get('duracion_minutos') or 60,
                miembro_id=data.get('miembro_taller'),
                categorias_requeridas=_categorias_de_oferta(oferta),
                excluir_cita_id=int(excluir) if excluir else None,
            )
        except DjangoValidationError as e:
            msg = e.message if hasattr(e, 'message') and isinstance(e.message, str) else str(e)
            if hasattr(e, 'message_dict'):
                parts = []
                for val in e.message_dict.values():
                    if isinstance(val, list):
                        parts.extend(str(v) for v in val)
                    else:
                        parts.append(str(val))
                if parts:
                    msg = ' '.join(parts)
            return Response(
                {'valido': False, 'error': msg},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({'valido': True})

    @action(detail=False, methods=['get'])
    def cerradas(self, request):
        fecha_limite = timezone.now() - timedelta(days=30)
        qs = self.get_queryset().filter(
            estado='cerrada',
            cerrada_en__gte=fecha_limite,
        )
        return Response(CitaAgendaPersonalSerializer(qs, many=True).data)

    @action(detail=False, methods=['get'])
    def canceladas(self, request):
        qs = self.get_queryset().filter(estado='cancelada')
        return Response(CitaAgendaPersonalSerializer(qs, many=True).data)


def _serializar_cita_personal_evento(cita: CitaAgendaPersonal) -> dict:
    det = cita.detalle
    nombre_servicio = (det.servicio_nombre or '').strip()
    if det.oferta_servicio_id and det.oferta_servicio:
        servicio = getattr(det.oferta_servicio, 'servicio', None)
        if servicio is not None:
            nombre_servicio = servicio.nombre

    return {
        'id': str(cita.id),
        'origen': 'personal',
        'etiqueta': 'Personal',
        'fecha_servicio': cita.fecha_servicio,
        'hora_servicio': cita.hora_servicio,
        'duracion_minutos': cita.duracion_minutos,
        'estado': cita.estado,
        'editable': cita.estado == 'activa',
        'tiene_checklist': False,
        'cliente_nombre': det.cliente_nombre,
        'cliente_telefono': det.cliente_telefono,
        'vehiculo_marca': det.vehiculo_marca,
        'vehiculo_modelo': det.vehiculo_modelo,
        'vehiculo_anio': det.vehiculo_anio,
        'vehiculo_patente': det.vehiculo_patente,
        'servicio_nombre': nombre_servicio,
        'descripcion': det.descripcion,
        'precio_referencia': det.precio_referencia,
        'tipo_servicio': cita.tipo_servicio,
        'oferta_proveedor_id': None,
        'orden_id': None,
        'miembro_taller_id': cita.miembro_taller_id,
        'mecanico_nombre': cita.miembro_taller.nombre if cita.miembro_taller_id else None,
    }


def _serializar_orden_mecanimovil_evento(orden: SolicitudServicio) -> dict:
    linea = orden.lineas.select_related('oferta_servicio__servicio').first()
    nombre_servicio = 'Servicio'
    if linea and linea.oferta_servicio and linea.oferta_servicio.servicio:
        nombre_servicio = linea.oferta_servicio.servicio.nombre

    cliente_nombre = ''
    if orden.cliente:
        cliente_nombre = f'{orden.cliente.nombre} {getattr(orden.cliente, "apellido", "") or ""}'.strip()

    vehiculo = orden.vehiculo
    return {
        'id': str(orden.id),
        'origen': 'mecanimovil',
        'etiqueta': 'Mecanimovil',
        'fecha_servicio': orden.fecha_servicio,
        'hora_servicio': orden.hora_servicio,
        'duracion_minutos': None,
        'estado': orden.estado,
        'editable': False,
        'tiene_checklist': True,
        'cliente_nombre': cliente_nombre,
        'cliente_telefono': getattr(orden.cliente, 'telefono', '') if orden.cliente else '',
        'vehiculo_marca': vehiculo.marca.nombre if vehiculo and vehiculo.marca else '',
        'vehiculo_modelo': vehiculo.modelo.nombre if vehiculo and vehiculo.modelo else '',
        'vehiculo_anio': vehiculo.year if vehiculo else None,
        'vehiculo_patente': vehiculo.patente if vehiculo else '',
        'servicio_nombre': nombre_servicio,
        'descripcion': orden.notas_cliente or '',
        'precio_referencia': orden.total,
        'tipo_servicio': orden.tipo_servicio,
        'oferta_proveedor_id': str(orden.oferta_proveedor_id) if orden.oferta_proveedor_id else None,
        'orden_id': orden.id,
        'miembro_taller_id': orden.mecanico_asignado_id,
        'mecanico_nombre': orden.mecanico_asignado.nombre if orden.mecanico_asignado_id else None,
    }


class ProveedorAgendaViewSet(viewsets.ViewSet):
    """Feed unificado de calendario: órdenes Mecanimovil + citas personales."""

    permission_classes = [permissions.IsAuthenticated, IsProveedor]

    def list(self, request):
        taller, mecanico = resolver_proveedor_usuario(request.user)
        if not taller and not mecanico:
            return Response([])

        fecha_desde = request.query_params.get('fecha_desde')
        fecha_hasta = request.query_params.get('fecha_hasta')
        incluir = request.query_params.get('incluir', 'activas,cerradas')
        miembro_taller_id = request.query_params.get('miembro_taller')

        estados_cita_map = {
            'activas': ['activa'],
            'cerradas': ['cerrada'],
            'canceladas': ['cancelada'],
        }
        estados_cita: list[str] = []
        for key in incluir.split(','):
            key = key.strip()
            estados_cita.extend(estados_cita_map.get(key, []))
        if not estados_cita:
            estados_cita = ['activa']

        citas_qs = CitaAgendaPersonal.objects.select_related(
            'detalle', 'detalle__oferta_servicio__servicio', 'miembro_taller',
        )
        if taller:
            citas_qs = citas_qs.filter(taller=taller)
        else:
            citas_qs = citas_qs.filter(mecanico=mecanico)
        citas_qs = citas_qs.filter(estado__in=estados_cita)
        if miembro_taller_id:
            citas_qs = citas_qs.filter(miembro_taller_id=miembro_taller_id)
        if fecha_desde:
            citas_qs = citas_qs.filter(fecha_servicio__gte=fecha_desde)
        if fecha_hasta:
            citas_qs = citas_qs.filter(fecha_servicio__lte=fecha_hasta)

        eventos = [_serializar_cita_personal_evento(c) for c in citas_qs]

        if 'mecanimovil' in incluir or 'activas' in incluir or 'cerradas' in incluir:
            ordenes_qs = SolicitudServicio.objects.prefetch_related(
                'lineas__oferta_servicio__servicio',
            ).select_related('cliente', 'vehiculo', 'vehiculo__marca', 'vehiculo__modelo', 'mecanico_asignado')
            if taller:
                ordenes_qs = ordenes_qs.filter(taller=taller)
            else:
                ordenes_qs = ordenes_qs.filter(mecanico=mecanico)
            if miembro_taller_id:
                ordenes_qs = ordenes_qs.filter(mecanico_asignado_id=miembro_taller_id)
            if fecha_desde:
                ordenes_qs = ordenes_qs.filter(fecha_servicio__gte=fecha_desde)
            if fecha_hasta:
                ordenes_qs = ordenes_qs.filter(fecha_servicio__lte=fecha_hasta)

            estados_finalizados = {'completado', 'cancelado', 'rechazada_por_proveedor', 'devuelto'}
            if 'activas' in incluir and 'cerradas' not in incluir:
                ordenes_qs = ordenes_qs.exclude(estado__in=estados_finalizados)
            elif 'cerradas' in incluir and 'activas' not in incluir:
                ordenes_qs = ordenes_qs.filter(estado='completado')

            eventos.extend(_serializar_orden_mecanimovil_evento(o) for o in ordenes_qs)

        eventos.sort(
            key=lambda e: (e['fecha_servicio'], e['hora_servicio']),
        )
        ser = EventoAgendaUnificadoSerializer(eventos, many=True)
        return Response(ser.data)
