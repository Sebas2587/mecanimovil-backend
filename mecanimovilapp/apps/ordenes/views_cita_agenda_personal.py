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
        from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller

        taller_ctx, miembro_ctx, rol_ctx = resolver_contexto_taller(request.user)
        taller, mecanico = resolver_proveedor_usuario(request.user)
        if taller_ctx is not None:
            taller = taller_ctx

        if rol_ctx == 'mecanico' and miembro_ctx is not None:
            return obj.miembro_taller_id == miembro_ctx.id
        if taller and obj.taller_id == taller.id:
            return True
        if mecanico and obj.mecanico_id == mecanico.id:
            return True
        return False


class CitaAgendaPersonalViewSet(viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated, IsProveedor, IsCitaAgendaPersonalOwner]
    serializer_class = CitaAgendaPersonalSerializer

    def get_queryset(self):
        from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller

        taller_ctx, miembro_ctx, rol_ctx = resolver_contexto_taller(self.request.user)
        taller, mecanico = resolver_proveedor_usuario(self.request.user)
        if taller_ctx is not None:
            taller = taller_ctx

        base_qs = (
            CitaAgendaPersonal.objects
            .select_related('detalle', 'detalle__oferta_servicio__servicio', 'miembro_taller')
            .prefetch_related('miembro_taller__especialidades')
            .order_by('-fecha_servicio', '-hora_servicio')
        )

        if rol_ctx == 'mecanico' and miembro_ctx is not None:
            return base_qs.filter(taller=taller, miembro_taller=miembro_ctx)
        if taller:
            return base_qs.filter(taller=taller)
        if mecanico:
            return base_qs.filter(mecanico=mecanico)
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
        from mecanimovilapp.apps.usuarios.services.taller_contexto import exigir_no_mecanico_equipo

        exigir_no_mecanico_equipo(request.user, 'crear citas personales')
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
                    'conversation_id': data.get('conversation_id'),
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
        from mecanimovilapp.apps.usuarios.services.taller_contexto import exigir_no_mecanico_equipo

        exigir_no_mecanico_equipo(request.user, 'editar citas personales')
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
        from mecanimovilapp.apps.usuarios.services.taller_contexto import exigir_no_mecanico_equipo

        exigir_no_mecanico_equipo(request.user, 'eliminar citas personales')
        cita = self.get_object()
        if cita.estado != 'cancelada':
            return Response(
                {
                    'error': 'Solo se pueden eliminar citas canceladas.',
                    'codigo': 'cita_no_eliminable',
                },
                status=status.HTTP_409_CONFLICT,
            )
        from mecanimovilapp.apps.ordenes.services.cita_cotizacion_sync import (
            marcar_cotizacion_origen_cancelada,
        )
        # Antes del delete: sincronizar cotización origen → Perdidos.
        marcar_cotizacion_origen_cancelada(cita)
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
        if cita.horario_por_confirmar:
            return Response(
                {
                    'error': 'Confirma día, hora y técnico antes de completar la cita.',
                    'codigo': 'horario_por_confirmar',
                },
                status=status.HTTP_409_CONFLICT,
            )
        try:
            cita.cerrar()
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_409_CONFLICT)
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
        from mecanimovilapp.apps.checklists.models import ChecklistInstance

        checklist = ChecklistInstance.objects.filter(cita_personal=cita).only('estado').first()
        if checklist is not None and checklist.estado not in ('PENDIENTE',):
            return Response(
                {
                    'error': (
                        'No se puede cancelar: el servicio ya fue iniciado. '
                        'El técnico debe completar el checklist operativo.'
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )
        cita.cancelar()
        cita.save(update_fields=['estado', 'cancelada_en', 'fecha_actualizacion'])
        from mecanimovilapp.apps.ordenes.services.cita_cotizacion_sync import (
            marcar_cotizacion_origen_cancelada,
        )
        marcar_cotizacion_origen_cancelada(cita)
        return Response(CitaAgendaPersonalSerializer(cita).data)

    def _puede_usar_asistente_ia_cita(self, request, cita: CitaAgendaPersonal) -> bool:
        from mecanimovilapp.apps.ordenes.services.asistente_diagnostico.permisos import (
            usuario_puede_usar_asistente_ia,
        )

        if not self.get_queryset().filter(pk=cita.pk).exists():
            return False
        return usuario_puede_usar_asistente_ia(request.user, cita=cita)

    def _respuesta_asistente_ia_cita(self, diagnostico=None, resultado=None):
        if diagnostico is not None:
            contenido = diagnostico.contenido or None
            disponible = diagnostico.estado == 'completado' and bool(contenido)
            return Response({
                'disponible': disponible,
                'contenido': contenido,
                'error': diagnostico.error or None,
                'latencia_ms': diagnostico.latencia_ms,
                'generado_en': diagnostico.creado_en,
                'diagnostico_id': diagnostico.id,
            })
        return Response({
            'disponible': bool(resultado and resultado.get('disponible')),
            'contenido': (resultado or {}).get('contenido'),
            'error': (resultado or {}).get('error'),
            'latencia_ms': (resultado or {}).get('latencia_ms', 0),
        })

    @action(detail=True, methods=['get', 'post'], url_path='asistente-ia')
    def asistente_ia(self, request, pk=None):
        """Genera o consulta la guía de reparación asistida por IA para una cita personal."""
        from mecanimovilapp.apps.ordenes.models import DiagnosticoAsistidoCitaPersonal
        from mecanimovilapp.apps.ordenes.services.asistente_diagnostico import (
            asistente_habilitado,
            generar_guia_reparacion_cita_personal,
        )
        from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller

        cita = (
            self.get_queryset()
            .select_related('detalle', 'detalle__oferta_servicio__servicio')
            .get(pk=self.kwargs['pk'])
        )
        if not self._puede_usar_asistente_ia_cita(request, cita):
            return Response(
                {'error': 'No tienes permiso para usar el asistente en esta cita.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if request.method == 'GET':
            from mecanimovilapp.apps.ordenes.services.asistente_diagnostico.permisos import (
                filtrar_diagnosticos_asistente_visibles,
            )
            ultimo = (
                filtrar_diagnosticos_asistente_visibles(
                    request.user,
                    DiagnosticoAsistidoCitaPersonal.objects.filter(cita=cita),
                )
                .order_by('-creado_en')
                .first()
            )
            if ultimo is None:
                return Response({
                    'disponible': False,
                    'contenido': None,
                    'error': None,
                    'latencia_ms': 0,
                })
            if ultimo.estado == 'completado':
                return self._respuesta_asistente_ia_cita(diagnostico=ultimo)
            return Response({
                'disponible': False,
                'contenido': None,
                'error': ultimo.error or None,
                'latencia_ms': ultimo.latencia_ms,
                'generado_en': ultimo.creado_en,
                'diagnostico_id': ultimo.id,
            })

        if not asistente_habilitado():
            return self._respuesta_asistente_ia_cita(resultado={
                'disponible': False,
                'contenido': None,
                'error': 'El asistente de diagnóstico IA no está habilitado.',
                'latencia_ms': 0,
            })

        regenerar = str(request.query_params.get('regenerar', '')).lower() in ('1', 'true', 'yes')
        if not regenerar:
            from mecanimovilapp.apps.ordenes.services.asistente_diagnostico.permisos import (
                filtrar_diagnosticos_asistente_visibles,
            )
            ultimo = (
                filtrar_diagnosticos_asistente_visibles(
                    request.user,
                    DiagnosticoAsistidoCitaPersonal.objects.filter(cita=cita, estado='completado'),
                )
                .order_by('-creado_en')
                .first()
            )
            if ultimo is not None:
                return self._respuesta_asistente_ia_cita(diagnostico=ultimo)

        _taller, miembro, rol = resolver_contexto_taller(request.user)
        generado_por = miembro if rol == 'mecanico' else None
        resultado = generar_guia_reparacion_cita_personal(cita)
        estado = 'completado' if resultado.get('disponible') else 'error'
        diagnostico = DiagnosticoAsistidoCitaPersonal.objects.create(
            cita=cita,
            generado_por=generado_por,
            contenido=resultado.get('contenido') or {},
            estado=estado,
            error=(resultado.get('error') or '')[:500],
            latencia_ms=resultado.get('latencia_ms') or 0,
            tokens_entrada=resultado.get('tokens_entrada') or 0,
            tokens_salida=resultado.get('tokens_salida') or 0,
            tokens_total=resultado.get('tokens_total') or 0,
            modelo=(resultado.get('modelo') or '')[:80],
        )
        return self._respuesta_asistente_ia_cita(diagnostico=diagnostico)

    @action(detail=True, methods=['post'], url_path='iniciar-servicio')
    def iniciar_servicio(self, request, pk=None):
        """Inicia el servicio operativo: crea checklist (con IA si hace falta) para la cita."""
        from mecanimovilapp.apps.usuarios.services.taller_contexto import exigir_puede_ejecutar_servicio
        from mecanimovilapp.apps.checklists.services import crear_checklist_para_cita_personal

        cita = self.get_object()
        if cita.estado != 'activa':
            return Response(
                {'error': 'Solo se puede iniciar servicio en citas activas.'},
                status=status.HTTP_409_CONFLICT,
            )
        if cita.horario_por_confirmar:
            return Response(
                {
                    'error': 'Confirma día, hora y técnico antes de iniciar el servicio.',
                    'codigo': 'horario_por_confirmar',
                },
                status=status.HTTP_409_CONFLICT,
            )
        # Taller/supervisor o el mecánico asignado pueden iniciar el servicio.
        exigir_puede_ejecutar_servicio(
            request.user,
            miembro_asignado_id=cita.miembro_taller_id,
            accion='iniciar este servicio',
        )

        checklist_instance = crear_checklist_para_cita_personal(
            cita,
            generar_template_si_ausente=True,
        )
        if checklist_instance is None:
            return Response(
                {
                    'message': 'Servicio iniciado sin checklist (servicio no resuelto)',
                    'tiene_checklist': False,
                    'cita': CitaAgendaPersonalSerializer(cita).data,
                }
            )

        # Dejar el checklist en EN_PROGRESO para que el técnico vea los ítems al abrir.
        if checklist_instance.estado == 'PENDIENTE':
            checklist_instance.estado = 'EN_PROGRESO'
            checklist_instance.fecha_inicio = timezone.now()
            checklist_instance.save(update_fields=['estado', 'fecha_inicio'])

        return Response({
            'message': 'Servicio iniciado. Checklist listo para completar.',
            'tiene_checklist': True,
            'checklist_id': checklist_instance.id,
            'checklist_estado': checklist_instance.estado,
            'template_generado_por_ia': bool(
                checklist_instance.checklist_template.generado_por_ia
                and checklist_instance.checklist_template.revisado_en is None
            ),
            'cita': CitaAgendaPersonalSerializer(cita).data,
        })

    @action(detail=True, methods=['post'], url_path='asignar-mecanico')
    def asignar_mecanico(self, request, pk=None):
        """Asigna o reasigna el técnico de una cita personal."""
        from django.core.exceptions import ValidationError as DjangoValidationError
        from mecanimovilapp.apps.usuarios.services.taller_contexto import exigir_no_mecanico_equipo

        exigir_no_mecanico_equipo(request.user, 'asignar técnicos')
        cita = self.get_object()
        miembro_id = request.data.get('miembro_taller_id')
        if miembro_id is not None and miembro_id != '':
            try:
                miembro_id = int(miembro_id)
            except (TypeError, ValueError):
                return Response({'error': 'miembro_taller_id inválido'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            miembro_id = None

        from mecanimovilapp.apps.ordenes.services.reasignacion_mecanico import reasignar_mecanico_cita_personal

        try:
            miembro = reasignar_mecanico_cita_personal(cita, miembro_id)
        except DjangoValidationError as exc:
            msg = exc.message if hasattr(exc, 'message') and isinstance(exc.message, str) else str(exc)
            return Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)

        cita.refresh_from_db()
        return Response({
            'message': 'Técnico asignado correctamente',
            'miembro_taller_id': miembro.id if miembro else None,
            'miembro_taller_nombre': miembro.nombre if miembro else None,
            'cita': CitaAgendaPersonalSerializer(cita).data,
        })

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
        """
        Historial de citas personales cerradas del taller.
        Sin ventana de 30 días: deben aparecer en Servicios → Completadas
        igual que en la agenda (antes solo se veían al elegir el día).
        Query opcional ?dias=N limita a los últimos N días si se necesita.
        """
        from django.db.models import F

        qs = self.get_queryset().filter(estado='cerrada')
        dias_raw = request.query_params.get('dias')
        if dias_raw is not None:
            try:
                dias = int(dias_raw)
            except (TypeError, ValueError):
                dias = None
            if dias is not None and dias > 0:
                fecha_limite = timezone.now() - timedelta(days=dias)
                qs = qs.filter(cerrada_en__gte=fecha_limite)
        qs = qs.order_by(F('cerrada_en').desc(nulls_last=True), '-fecha_servicio', '-id')
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
        'tiene_checklist': CitaAgendaPersonalSerializer(cita).data.get('tiene_checklist', False),
        'cliente_nombre': det.cliente_nombre,
        'cliente_telefono': det.cliente_telefono,
        'vehiculo_marca': det.vehiculo_marca,
        'vehiculo_modelo': det.vehiculo_modelo,
        'vehiculo_anio': det.vehiculo_anio,
        'vehiculo_patente': det.vehiculo_patente,
        'vehiculo_vin': det.vehiculo_vin,
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
        from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller

        taller_ctx, miembro_ctx, rol_ctx = resolver_contexto_taller(request.user)
        taller, mecanico = resolver_proveedor_usuario(request.user)
        if taller_ctx is not None:
            taller = taller_ctx
        if not taller and not mecanico:
            return Response([])

        fecha_desde = request.query_params.get('fecha_desde')
        fecha_hasta = request.query_params.get('fecha_hasta')
        incluir = request.query_params.get('incluir', 'activas,cerradas')
        miembro_taller_id = request.query_params.get('miembro_taller')
        if rol_ctx == 'mecanico' and miembro_ctx is not None:
            miembro_taller_id = str(miembro_ctx.id)

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
