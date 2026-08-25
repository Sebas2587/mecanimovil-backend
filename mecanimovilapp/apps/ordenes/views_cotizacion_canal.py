"""API cotizaciones canal con IA."""
from __future__ import annotations

from django.db.models import F
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class CotizacionCanalPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200

from mecanimovilapp.apps.chat.models import Conversation
from mecanimovilapp.apps.ordenes.models import CotizacionCanal, CotizacionCanalPlantilla
from mecanimovilapp.apps.ordenes.permissions import IsProveedor
from mecanimovilapp.apps.ordenes.serializers_cotizacion_canal import (
    CotizacionCanalPlantillaSerializer,
    CotizacionCanalSerializer,
    CotizarItemsIaSerializer,
    CrearCotizacionAdicionalSerializer,
    GenerarCotizacionIaSerializer,
    GuardarPlantillaCotizacionSerializer,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador import generar_cotizacion_ia
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.permisos import usuario_puede_cotizar_canal
from mecanimovilapp.apps.ordenes.services.cotizacion_canal import (
    aplicar_edicion_cotizacion,
    aplicar_plan_entrega_cotizacion,
    enviar_cotizacion_canal,
    payload_plantilla_whatsapp_cotizacion,
    snapshot_desde_cotizacion,
)
from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
    enviar_cotizacion_libre,
    resolver_politicas_cotizacion,
)
from mecanimovilapp.apps.ordenes.services.plantilla_vehiculo import filtrar_plantillas_por_vehiculo
from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller
from mecanimovilapp.apps.vehiculos.cilindraje_texto import cilindraje_efectivo


class CotizacionCanalViewSet(viewsets.ModelViewSet):
    serializer_class = CotizacionCanalSerializer
    permission_classes = [permissions.IsAuthenticated, IsProveedor]
    pagination_class = CotizacionCanalPagination
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def _taller_contexto(self):
        taller, _miembro, rol = resolver_contexto_taller(self.request.user)
        if taller is None or rol == 'mecanico':
            raise PermissionDenied('Solo mandante o supervisor pueden gestionar cotizaciones.')
        return taller, rol

    def _get_conversation(self, conversation_id: int) -> Conversation:
        conversation = Conversation.objects.filter(pk=conversation_id).first()
        if conversation is None:
            raise ValidationError({'conversation_id': 'Conversación no encontrada.'})
        if not usuario_puede_cotizar_canal(self.request.user, conversation=conversation):
            raise PermissionDenied('No tienes acceso a esta conversación.')
        return conversation

    def get_queryset(self):
        try:
            taller, _rol = self._taller_contexto()
        except PermissionDenied:
            return CotizacionCanal.objects.none()
        return CotizacionCanal.objects.filter(taller=taller).select_related(
            'taller',
            'conversation',
            'conversation__external_contact',
            'conversation__external_contact__connection',
            'cotizacion_original',
            'cita_origen',
            'cita_origen__detalle',
        )

    def retrieve(self, request, *args, **kwargs):
        """Detalle; reintenta búsqueda web si el borrador quedó pendiente/sin marca."""
        instance = self.get_object()
        instance = self._reintentar_busqueda_web_si_corresponde(instance)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def _reintentar_busqueda_web_si_corresponde(self, cotizacion: CotizacionCanal) -> CotizacionCanal:
        """Reintenta búsqueda web en borradores trabados (worker muerto / validación).

        - `pendiente` o `error`: reintenta con debounce 45s.
        - `sin_resultados`: un solo reintento (útil tras deploy de validación más permisiva).
        """
        if cotizacion.estado != 'borrador':
            return cotizacion
        meta = dict(cotizacion.metadata or {})
        estado = str(meta.get('busqueda_web_estado') or '')
        retries = int(meta.get('busqueda_web_retry_count') or 0)
        if estado in ('pendiente', 'error'):
            pass
        elif estado in ('sin_resultados', '') and retries < 1:
            # '' = borrador viejo sin disparo; un reintento tras deploy.
            pass
        else:
            return cotizacion

        from django.core.cache import cache

        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.disparar_busqueda_web import (
            disparar_y_refrescar_cotizacion,
            marcar_busqueda_web_pendiente,
        )

        lock_key = f'busqueda_web_retry:{cotizacion.id}'
        if not cache.add(lock_key, '1', timeout=45):
            return cotizacion

        meta['busqueda_web_retry_count'] = retries + 1
        cotizacion.metadata = marcar_busqueda_web_pendiente(meta)
        if cotizacion.metadata.get('busqueda_web_estado') == 'pendiente':
            cotizacion.save(update_fields=['metadata', 'actualizado_en'])
            cotizacion = disparar_y_refrescar_cotizacion(cotizacion)
        return cotizacion

    @action(detail=False, methods=['post'], url_path='generar-ia')
    def generar_ia(self, request):
        taller, _rol = self._taller_contexto()
        ser = GenerarCotizacionIaSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        conversation_id = data.get('conversation_id')
        conversation = None
        es_libre = conversation_id is None
        if conversation_id is not None:
            conversation = self._get_conversation(conversation_id)

        cliente_nombre = (data.get('cliente_nombre') or '').strip()
        cliente_telefono = (data.get('cliente_telefono') or '').strip()

        plantilla_id = data.get('plantilla_id')
        if plantilla_id:
            plantilla = CotizacionCanalPlantilla.objects.filter(pk=plantilla_id, taller=taller).first()
            if plantilla is None:
                raise ValidationError({'plantilla_id': 'Plantilla no encontrada.'})
            snap = plantilla.snapshot or {}
            CotizacionCanalPlantilla.objects.filter(pk=plantilla.pk).update(
                uso_count=F('uso_count') + 1,
            )
            veh_plant = data.get('vehiculo') or {}
            marca_p = snap.get('vehiculo_marca') or veh_plant.get('marca', '')
            modelo_p = snap.get('vehiculo_modelo') or veh_plant.get('modelo', '')
            cotizacion = CotizacionCanal.objects.create(
                conversation=conversation,
                es_libre=es_libre,
                cliente_nombre=cliente_nombre,
                cliente_telefono=cliente_telefono,
                taller=taller,
                creado_por=request.user,
                estado='borrador',
                modalidad=snap.get('modalidad') or data.get('modalidad') or 'taller',
                direccion_servicio=(
                    data.get('direccion_servicio')
                    or snap.get('direccion_servicio')
                    or ''
                )[:500],
                vehiculo_marca=marca_p,
                vehiculo_modelo=modelo_p,
                vehiculo_anio=snap.get('vehiculo_anio') or veh_plant.get('anio'),
                vehiculo_patente=snap.get('vehiculo_patente') or veh_plant.get('patente', ''),
                vehiculo_cilindraje=cilindraje_efectivo(
                    snap.get('vehiculo_cilindraje') or veh_plant.get('cilindraje', ''),
                    marca_p,
                    modelo_p,
                ),
                tipo_motor=snap.get('tipo_motor', ''),
                tipo_motor_label=snap.get('tipo_motor_label', ''),
                servicio_nombre=snap.get('servicio_nombre') or data.get('servicio_nombre', ''),
                descripcion_problema=snap.get('descripcion_problema') or data.get('descripcion_problema', ''),
                repuestos=snap.get('repuestos') or [],
                mano_obra_clp=snap.get('mano_obra_clp') or 0,
                costo_repuestos_clp=snap.get('costo_repuestos_clp') or 0,
                total_clp=snap.get('total_clp') or 0,
                duracion_minutos_estimada=snap.get('duracion_minutos_estimada'),
                advertencias=snap.get('advertencias') or [],
                notas_internas=snap.get('notas_internas') or '',
                politicas_cotizacion=resolver_politicas_cotizacion(
                    taller=taller,
                    texto=snap.get('politicas_cotizacion'),
                ),
                metadata={'origen': 'plantilla', 'plantilla_id': plantilla_id},
            )
            return Response({
                'disponible': True,
                'cotizacion': CotizacionCanalSerializer(cotizacion).data,
                'desde_plantilla': True,
            }, status=status.HTTP_201_CREATED)

        from mecanimovilapp.apps.suscripciones.cuotas_services import (
            CuotaAgotadaError,
            SinSuscripcionError,
            verificar_y_consumir_cuota,
        )
        from mecanimovilapp.apps.suscripciones.models import ConsumoFeatureMensual

        resultado = generar_cotizacion_ia(
            conversation=conversation,
            servicio_nombre=data.get('servicio_nombre', ''),
            descripcion_problema=data.get('descripcion_problema', ''),
            modalidad=data.get('modalidad', 'taller'),
            vehiculo=data.get('vehiculo') or {},
            taller=taller,
            enriquecer_ml=False,
        )
        if not resultado.get('disponible'):
            return Response(resultado, status=status.HTTP_200_OK)

        try:
            verificar_y_consumir_cuota(
                request.user,
                ConsumoFeatureMensual.FEATURE_COTIZACION_IA,
            )
        except (CuotaAgotadaError, SinSuscripcionError) as exc:
            return Response(exc.to_dict(), status=status.HTTP_403_FORBIDDEN)

        contenido = resultado['contenido'] or {}
        ctx = resultado.get('contexto') or {}
        veh = data.get('vehiculo') or {}
        anio_raw = veh.get('anio') or ctx.get('vehiculo_anio')
        try:
            anio_int = int(anio_raw) if anio_raw else None
        except (TypeError, ValueError):
            anio_int = None

        marca = ctx.get('vehiculo_marca') or veh.get('marca', '')
        modelo = ctx.get('vehiculo_modelo') or veh.get('modelo', '')
        cilindraje = cilindraje_efectivo(
            ctx.get('vehiculo_cilindraje') or veh.get('cilindraje', ''),
            marca,
            modelo,
        )

        cotizacion = CotizacionCanal.objects.create(
            conversation=conversation,
            es_libre=es_libre,
            cliente_nombre=cliente_nombre,
            cliente_telefono=cliente_telefono,
            taller=taller,
            creado_por=request.user,
            estado='borrador',
            modalidad=data.get('modalidad', 'taller'),
            direccion_servicio=str(data.get('direccion_servicio') or '')[:500],
            vehiculo_marca=marca,
            vehiculo_modelo=modelo,
            vehiculo_anio=anio_int,
            vehiculo_patente=ctx.get('vehiculo_patente') or veh.get('patente', ''),
            vehiculo_cilindraje=cilindraje,
            vehiculo_vin=str(veh.get('vin') or '')[:50],
            tipo_motor=contenido.get('tipo_motor') or ctx.get('tipo_motor', ''),
            tipo_motor_label=contenido.get('tipo_motor_label') or ctx.get('tipo_motor_label', ''),
            aviso_motor=contenido.get('aviso_motor') or ctx.get('aviso_motor', ''),
            servicio_nombre=(
                (data.get('servicio_nombre') or '').strip()
                or contenido.get('servicio_nombre', '')
            ),
            descripcion_problema=(
                (data.get('descripcion_problema') or '').strip()
                or contenido.get('descripcion_problema', '')
            ),
            repuestos=contenido.get('repuestos') or [],
            mano_obra_clp=contenido.get('mano_obra_clp') or 0,
            costo_repuestos_clp=contenido.get('costo_repuestos_clp') or 0,
            total_clp=contenido.get('total_clp') or 0,
            duracion_minutos_estimada=contenido.get('duracion_minutos_estimada'),
            advertencias=contenido.get('advertencias') or [],
            politicas_cotizacion=resolver_politicas_cotizacion(taller=taller),
            contenido_ia=resultado.get('contenido_ia') or {},
            tokens_entrada=resultado.get('tokens_entrada') or 0,
            tokens_salida=resultado.get('tokens_salida') or 0,
            modelo_ia=resultado.get('modelo') or '',
            metadata={
                'origen': 'ia',
                'valores_estimativos': bool(
                    resultado.get('valores_estimativos')
                    or contenido.get('valores_estimativos', True)
                ) and not bool(contenido.get('precio_desde_catalogo')),
                'precio_desde_catalogo': bool(contenido.get('precio_desde_catalogo')),
            },
        )
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.disparar_busqueda_web import (
            disparar_busqueda_web_cotizacion,
            marcar_busqueda_web_pendiente,
        )

        cotizacion.metadata = marcar_busqueda_web_pendiente(cotizacion.metadata)
        if cotizacion.metadata.get('busqueda_web_estado') == 'pendiente':
            cotizacion.save(update_fields=['metadata', 'actualizado_en'])
            disparar_busqueda_web_cotizacion(cotizacion.id, sync=False)
        return Response({
            **resultado,
            'cotizacion': CotizacionCanalSerializer(cotizacion).data,
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='crear-adicional')
    def crear_adicional(self, request):
        """Cotización adicional sobre un trabajo de canal agendado o en ejecución."""
        from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal
        from mecanimovilapp.apps.ordenes.services.cotizacion_adicional import (
            crear_cotizacion_adicional_con_ia,
            crear_cotizacion_adicional_desde_catalogo,
        )

        taller, _rol = self._taller_contexto()
        ser = CrearCotizacionAdicionalSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        cita = (
            CitaAgendaPersonal.objects.select_related(
                'cotizacion_canal_origen',
                'checklist_instance',
            )
            .filter(pk=data['cita_id'], taller=taller)
            .first()
        )
        if cita is None:
            raise ValidationError({'cita_id': 'Cita no encontrada.'})

        cot_original = (
            CotizacionCanal.objects.filter(
                pk=data['cotizacion_original_id'],
                taller=taller,
            )
            .select_related('conversation')
            .first()
        )
        if cot_original is None:
            raise ValidationError({'cotizacion_original_id': 'Cotización original no encontrada.'})
        if cita.cotizacion_canal_origen_id and cita.cotizacion_canal_origen_id != cot_original.id:
            raise ValidationError({
                'cotizacion_original_id': 'No coincide con la cotización de origen de la cita.',
            })

        try:
            if data.get('modo') == 'ia':
                cotizacion = crear_cotizacion_adicional_con_ia(
                    cotizacion_original=cot_original,
                    cita=cita,
                    taller=taller,
                    creado_por=request.user,
                    motivo_servicio_adicional=data['motivo_servicio_adicional'],
                    servicio_nombre=data.get('servicio_nombre') or '',
                    descripcion_problema=data.get('descripcion_problema') or '',
                    ejecucion_adicional=data.get('ejecucion_adicional') or 'misma_visita',
                    fecha_propuesta=data.get('fecha_propuesta'),
                    hora_propuesta=data.get('hora_propuesta'),
                )
            else:
                cotizacion = crear_cotizacion_adicional_desde_catalogo(
                    cotizacion_original=cot_original,
                    cita=cita,
                    taller=taller,
                    creado_por=request.user,
                    motivo_servicio_adicional=data['motivo_servicio_adicional'],
                    servicios_catalogo=data.get('servicios_catalogo') or [],
                    ejecucion_adicional=data.get('ejecucion_adicional') or 'misma_visita',
                    fecha_propuesta=data.get('fecha_propuesta'),
                    hora_propuesta=data.get('hora_propuesta'),
                )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        return Response(
            {'cotizacion': CotizacionCanalSerializer(cotizacion).data},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'], url_path='cotizar-items')
    def cotizar_items(self, request, pk=None):
        """Agrega ítems (IA o líneas vacías) si la cotización aún se puede editar."""
        from mecanimovilapp.apps.ordenes.services.cotizacion_canal import (
            aplicar_efecto_edicion_aceptada,
            asegurar_cotizacion_editable_para_items,
            cita_activa_de_cotizacion,
        )

        cotizacion = self.get_object()
        try:
            cotizacion = asegurar_cotizacion_editable_para_items(cotizacion)
        except ValueError as exc:
            raise ValidationError({'estado': str(exc)}) from exc
        ser = CotizarItemsIaSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.cotizar_items_faltantes import (
            cotizar_items_faltantes,
        )

        estado_previo = cotizacion.estado
        total_previo = int(cotizacion.total_clp or 0)
        try:
            resultado = cotizar_items_faltantes(
                cotizacion,
                nombres=data.get('nombres') or [],
                repuestos_locales=data.get('repuestos'),
            )
        except ValueError as exc:
            raise ValidationError({'nombres': str(exc)}) from exc

        cotizacion = resultado['cotizacion']
        modo = None
        if estado_previo == 'aceptada':
            modo = aplicar_efecto_edicion_aceptada(
                cotizacion,
                total_previo=total_previo,
                cita=cita_activa_de_cotizacion(cotizacion),
            )
        payload = {
            'cotizacion': CotizacionCanalSerializer(cotizacion).data,
            'agregados': resultado.get('agregados') or [],
            'busqueda_web': bool(resultado.get('busqueda_web')),
        }
        if modo:
            payload['modo_actualizacion'] = modo
        return Response(payload)

    def partial_update(self, request, *args, **kwargs):
        from mecanimovilapp.apps.ordenes.services.cotizacion_canal import (
            actualizar_cotizacion_aceptada_sin_iniciar,
            asegurar_cotizacion_editable_para_items,
        )

        cotizacion = self.get_object()
        try:
            cotizacion = asegurar_cotizacion_editable_para_items(cotizacion)
        except ValueError as exc:
            raise ValidationError({'estado': str(exc)}) from exc
        if cotizacion.estado == 'aceptada':
            try:
                cotizacion, modo = actualizar_cotizacion_aceptada_sin_iniciar(
                    cotizacion, request.data,
                )
            except ValueError as exc:
                raise ValidationError({'estado': str(exc)}) from exc
            data = CotizacionCanalSerializer(cotizacion).data
            data['modo_actualizacion'] = modo
            return Response(data)
        aplicar_edicion_cotizacion(cotizacion, request.data)
        cotizacion.save()
        return Response(CotizacionCanalSerializer(cotizacion).data)

    @action(detail=True, methods=['post'], url_path='reabrir')
    def reabrir(self, request, pk=None):
        """enviada → borrador (mismo token) para que el taller actualice y reenvíe."""
        from mecanimovilapp.apps.ordenes.services.cotizacion_canal import (
            reabrir_cotizacion_enviada,
        )

        cotizacion = self.get_object()
        try:
            cotizacion = reabrir_cotizacion_enviada(cotizacion)
        except ValueError as exc:
            raise ValidationError({'estado': str(exc)}) from exc
        return Response(CotizacionCanalSerializer(cotizacion).data)

    @action(detail=True, methods=['post'])
    def enviar(self, request, pk=None):
        cotizacion = self.get_object()
        if cotizacion.estado != 'borrador':
            raise ValidationError({'estado': 'La cotización ya fue enviada o cerrada.'})
        if not cotizacion.servicio_nombre.strip():
            raise ValidationError({'servicio_nombre': 'Indica el nombre del servicio.'})

        if cotizacion.es_libre or cotizacion.conversation_id is None:
            try:
                cotizacion = enviar_cotizacion_libre(cotizacion)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            if cotizacion.conversation_id:
                from mecanimovilapp.apps.agente_ia.services.lead_scoring import (
                    actualizar_calificacion_desde_cotizacion,
                )
                actualizar_calificacion_desde_cotizacion(cotizacion, evento='enviada')
            return Response({
                'cotizacion': CotizacionCanalSerializer(cotizacion).data,
                'message_id': None,
                'share_url': cotizacion.url_publica,
            })

        try:
            message = enviar_cotizacion_canal(cotizacion, request.user)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        from mecanimovilapp.apps.omnichannel.services.outbound_guard import (
            plan_entrega_cotizacion,
        )

        plan = plan_entrega_cotizacion(cotizacion.conversation)
        aplicar_plan_entrega_cotizacion(cotizacion, plan)
        cotizacion.refresh_from_db()

        if plan.use_template:
            tpl = payload_plantilla_whatsapp_cotizacion(cotizacion)
            meta_msg = dict(message.channel_metadata or {})
            meta_msg['whatsapp_template'] = True
            meta_msg['cotizacion_id'] = cotizacion.id
            meta_msg['template_kind'] = tpl.get('kind') or 'cotizacion'
            meta_msg['template_name'] = tpl.get('name') or ''
            meta_msg['template_language'] = tpl.get('language') or 'es'
            meta_msg['template_components'] = tpl.get('components') or []
            message.channel_metadata = meta_msg
            message.save(update_fields=['channel_metadata'])

        from mecanimovilapp.apps.omnichannel.tasks import send_meta_message

        if cotizacion.conversation.source_channel != 'APP' and plan.should_send_meta:
            send_meta_message.delay(message.id)

        from mecanimovilapp.apps.agente_ia.services.lead_scoring import (
            actualizar_calificacion_desde_cotizacion,
        )
        actualizar_calificacion_desde_cotizacion(cotizacion, evento='enviada')

        serialized = CotizacionCanalSerializer(cotizacion).data
        return Response({
            'cotizacion': serialized,
            'message_id': message.id,
            'share_url': serialized.get('share_url') or cotizacion.url_publica,
            'entrega_via': plan.via,
            'entrega_mensaje': plan.message,
        })

    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        cotizacion = self.get_object()
        if cotizacion.estado in ('aceptada', 'cancelada'):
            raise ValidationError({'estado': 'No se puede cancelar esta cotización.'})
        cotizacion.estado = 'cancelada'
        cotizacion.save(update_fields=['estado', 'actualizado_en'])
        from mecanimovilapp.apps.agente_ia.services.lead_scoring import (
            actualizar_calificacion_desde_cotizacion,
        )
        from mecanimovilapp.apps.agente_ia.services.sesion_cotizacion import (
            liberar_sesiones_tras_cerrar_borrador,
        )

        liberar_sesiones_tras_cerrar_borrador(cotizacion)
        # Un borrador nunca enviado no es un lead perdido: no baja el score.
        if cotizacion.enviada_en:
            actualizar_calificacion_desde_cotizacion(cotizacion, evento='cancelada')
        return Response(CotizacionCanalSerializer(cotizacion).data)

    @action(detail=True, methods=['post'], url_path='marcar-aceptada')
    def marcar_aceptada(self, request, pk=None):
        """Fallback mandante cuando cliente acepta por teléfono (Messenger/IG)."""
        from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
            aceptar_cotizacion_publica,
            on_cotizacion_respondida,
        )

        cotizacion = self.get_object()
        if cotizacion.estado != 'enviada':
            raise ValidationError({'estado': 'Solo cotizaciones enviadas pueden marcarse como aceptadas.'})
        try:
            cotizacion, cita = aceptar_cotizacion_publica(cotizacion)
        except ValueError as exc:
            raise ValidationError({'estado': str(exc)}) from exc
        on_cotizacion_respondida(
            cotizacion,
            'aceptar',
            conversation=cotizacion.conversation,
            cita_id=cita.id if cita else None,
        )

        data = CotizacionCanalSerializer(cotizacion).data
        if cita is not None:
            data['cita_id'] = cita.id
        data['horario_por_confirmar'] = bool(
            cita and not cotizacion.es_cotizacion_adicional and getattr(cita, 'horario_por_confirmar', False)
        )
        return Response(data)

    @action(detail=True, methods=['post'], url_path='marcar-perdida')
    def marcar_perdida(self, request, pk=None):
        """Cierra el lead comercial desde la bandeja (taller)."""
        cotizacion = self.get_object()
        if cotizacion.estado in ('cancelada', 'rechazada', 'expirada'):
            raise ValidationError({'estado': 'Esta cotización ya está cerrada.'})
        # Aceptada sin cita activa (o cita cancelada) también puede ir a Perdidos.
        if cotizacion.estado == 'aceptada':
            from mecanimovilapp.apps.ordenes.services.cita_cotizacion_sync import (
                cotizacion_aceptada_tiene_cita_activa,
            )
            if cotizacion_aceptada_tiene_cita_activa(cotizacion):
                raise ValidationError({
                    'estado': 'Hay una cita activa. Cancélala o elimínala antes de cerrar el caso.',
                })
        cotizacion.estado = 'cancelada'
        cotizacion.save(update_fields=['estado', 'actualizado_en'])
        if cotizacion.es_cotizacion_adicional and cotizacion.cita_origen_id:
            from mecanimovilapp.apps.ordenes.services.cotizacion_adicional import (
                actualizar_precio_referencia_visita,
            )
            cita = cotizacion.cita_origen
            if cita is not None:
                actualizar_precio_referencia_visita(cita)
        from mecanimovilapp.apps.agente_ia.services.lead_scoring import (
            actualizar_calificacion_desde_cotizacion,
        )
        actualizar_calificacion_desde_cotizacion(cotizacion, evento='cancelada')
        return Response(CotizacionCanalSerializer(cotizacion).data)

    @action(detail=False, methods=['get'], url_path=r'por-conversacion/(?P<conversation_id>[^/.]+)')
    def por_conversacion(self, request, conversation_id=None):
        taller, _rol = self._taller_contexto()
        conversation = self._get_conversation(int(conversation_id))
        qs = CotizacionCanal.objects.filter(
            taller=taller,
            conversation=conversation,
        ).order_by('-creado_en')[:20]
        return Response(CotizacionCanalSerializer(qs, many=True).data)


class CotizacionCanalPlantillaViewSet(viewsets.ModelViewSet):
    serializer_class = CotizacionCanalPlantillaSerializer
    permission_classes = [permissions.IsAuthenticated, IsProveedor]
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def _taller(self):
        taller, _miembro, rol = resolver_contexto_taller(self.request.user)
        if taller is None or rol == 'mecanico':
            raise PermissionDenied('Solo mandante o supervisor pueden gestionar plantillas.')
        return taller

    def get_queryset(self):
        try:
            taller = self._taller()
        except PermissionDenied:
            return CotizacionCanalPlantilla.objects.none()
        return CotizacionCanalPlantilla.objects.filter(taller=taller)

    def list(self, request, *args, **kwargs):
        queryset = list(self.filter_queryset(self.get_queryset()))
        marca = (request.query_params.get('marca') or '').strip()
        modelo = (request.query_params.get('modelo') or '').strip()
        cilindraje = (request.query_params.get('cilindraje') or '').strip()
        if marca and modelo:
            queryset = filtrar_plantillas_por_vehiculo(
                queryset,
                marca=marca,
                modelo=modelo,
                cilindraje=cilindraje,
            )
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        taller = self._taller()
        ser = GuardarPlantillaCotizacionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        snapshot = data.get('snapshot')
        cotizacion_id = data.get('cotizacion_id')
        if snapshot is None and cotizacion_id:
            cot = CotizacionCanal.objects.filter(pk=cotizacion_id, taller=taller).first()
            if cot is None:
                raise ValidationError({'cotizacion_id': 'Cotización no encontrada.'})
            snapshot = snapshot_desde_cotizacion(cot)
        if not snapshot:
            raise ValidationError({'snapshot': 'Debes indicar snapshot o cotizacion_id.'})
        plantilla = CotizacionCanalPlantilla.objects.create(
            taller=taller,
            creado_por=request.user,
            titulo=data['titulo'][:255],
            snapshot=snapshot,
        )
        return Response(
            CotizacionCanalPlantillaSerializer(plantilla).data,
            status=status.HTTP_201_CREATED,
        )
