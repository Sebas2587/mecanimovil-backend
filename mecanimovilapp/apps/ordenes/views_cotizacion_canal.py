"""API cotizaciones canal con IA."""
from __future__ import annotations

import logging
from django.db.models import F

logger = logging.getLogger(__name__)
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
    crear_mensaje_actualizacion_cotizacion,
    entregar_mensaje_cotizacion_meta,
    enviar_cotizacion_canal,
    snapshot_desde_cotizacion,
)
from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
    enviar_cotizacion_libre,
    resolver_politicas_cotizacion,
    snapshot_dias_validez,
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
                dias_validez=snapshot_dias_validez(taller, snap.get('dias_validez')),
                descuento_tipo=(
                    snap.get('descuento_tipo')
                    if snap.get('descuento_tipo') in ('monto', 'porcentaje')
                    else ''
                ),
                descuento_alcance=(
                    snap.get('descuento_alcance')
                    if snap.get('descuento_alcance') in ('mano_obra', 'total')
                    else 'mano_obra'
                ),
                descuento_valor=snap.get('descuento_valor') or 0,
                metadata={'origen': 'plantilla', 'plantilla_id': plantilla_id},
            )
            from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
                aplicar_totales_cotizacion,
            )

            aplicar_totales_cotizacion(cotizacion)
            cotizacion.save()
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
            dias_validez=snapshot_dias_validez(taller),
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

    @action(detail=False, methods=['post'], url_path='crear-borrador')
    def crear_borrador(self, request):
        """Borrador vacío sin IA ni cuota: el taller carga precios a mano."""
        taller, _rol = self._taller_contexto()
        ser = GenerarCotizacionIaSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        if data.get('plantilla_id'):
            raise ValidationError({'plantilla_id': 'Usa generar-ia para aplicar una plantilla.'})

        conversation_id = data.get('conversation_id')
        conversation = None
        es_libre = conversation_id is None
        if conversation_id is not None:
            conversation = self._get_conversation(conversation_id)

        veh = data.get('vehiculo') or {}
        marca = str(veh.get('marca') or '').strip()
        modelo = str(veh.get('modelo') or '').strip()
        anio_raw = veh.get('anio')
        try:
            anio_int = int(anio_raw) if anio_raw else None
        except (TypeError, ValueError):
            anio_int = None

        cotizacion = CotizacionCanal.objects.create(
            conversation=conversation,
            es_libre=es_libre,
            cliente_nombre=(data.get('cliente_nombre') or '').strip(),
            cliente_telefono=(data.get('cliente_telefono') or '').strip(),
            taller=taller,
            creado_por=request.user,
            estado='borrador',
            modalidad=data.get('modalidad') or 'taller',
            direccion_servicio=str(data.get('direccion_servicio') or '')[:500],
            vehiculo_marca=marca,
            vehiculo_modelo=modelo,
            vehiculo_anio=anio_int,
            vehiculo_patente=str(veh.get('patente') or '')[:20],
            vehiculo_cilindraje=cilindraje_efectivo(
                str(veh.get('cilindraje') or ''),
                marca,
                modelo,
            ),
            vehiculo_vin=str(veh.get('vin') or '')[:50],
            tipo_motor=str(veh.get('tipo_motor') or ''),
            tipo_motor_label=str(veh.get('tipo_motor_label') or ''),
            servicio_nombre=(data.get('servicio_nombre') or '').strip(),
            descripcion_problema=(data.get('descripcion_problema') or '').strip(),
            repuestos=[],
            mano_obra_clp=0,
            costo_repuestos_clp=0,
            total_clp=0,
            politicas_cotizacion=resolver_politicas_cotizacion(taller=taller),
            dias_validez=snapshot_dias_validez(taller),
            metadata={'origen': 'manual', 'valores_estimativos': False},
        )
        return Response(
            {'cotizacion': CotizacionCanalSerializer(cotizacion).data},
            status=status.HTTP_201_CREATED,
        )

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

    def _persistir_repuestos_y_totales(self, cotizacion):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
            aplicar_totales_cotizacion,
        )

        aplicar_totales_cotizacion(cotizacion)
        cotizacion.save(update_fields=[
            'repuestos',
            'costo_repuestos_clp',
            'descuento_clp',
            'total_clp',
            'actualizado_en',
        ])

    @action(detail=True, methods=['post'], url_path='confirmar-precio-repuesto')
    def confirmar_precio_repuesto(self, request, pk=None):
        from mecanimovilapp.apps.ordenes.serializers_proveedor_repuestos import (
            ConfirmarPrecioRepuestoSerializer,
        )
        from mecanimovilapp.apps.ordenes.services.precios_proveedor import (
            aplicar_confirmacion_linea,
        )

        cotizacion = self.get_object()
        ser = ConfirmarPrecioRepuestoSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        try:
            aplicar_confirmacion_linea(
                cotizacion,
                repuesto_id=data['repuesto_id'],
                precio_clp=data['precio_clp'],
                proveedor_id=data.get('proveedor_id'),
                proveedor_nombre=data.get('proveedor_nombre') or '',
                especificacion=data.get('especificacion') or '',
                guardar_en_mis_precios=data.get('guardar_en_mis_precios', True),
                usuario=request.user,
            )
        except ValueError as exc:
            raise ValidationError({'repuesto_id': str(exc)}) from exc
        self._persistir_repuestos_y_totales(cotizacion)
        return Response({'cotizacion': CotizacionCanalSerializer(cotizacion).data})

    @action(detail=True, methods=['post'], url_path='asumir-precio-repuesto')
    def asumir_precio_repuesto(self, request, pk=None):
        from mecanimovilapp.apps.ordenes.serializers_proveedor_repuestos import (
            AsumirPrecioRepuestoSerializer,
        )
        from mecanimovilapp.apps.ordenes.services.precios_proveedor import aplicar_asumir_lineas

        cotizacion = self.get_object()
        ser = AsumirPrecioRepuestoSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ids = ser.validated_data.get('repuesto_id') or []
        aplicar_asumir_lineas(cotizacion, ids)
        self._persistir_repuestos_y_totales(cotizacion)
        return Response({'cotizacion': CotizacionCanalSerializer(cotizacion).data})

    @action(detail=True, methods=['post'], url_path='definir-especificacion')
    def definir_especificacion(self, request, pk=None):
        from mecanimovilapp.apps.ordenes.serializers_proveedor_repuestos import (
            DefinirEspecificacionSerializer,
        )
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.disparar_busqueda_web import (
            disparar_busqueda_web_cotizacion,
            marcar_busqueda_web_pendiente,
        )
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.familias_sensibles import (
            anotar_familia_en_linea,
        )

        cotizacion = self.get_object()
        ser = DefinirEspecificacionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        rid = ser.validated_data['repuesto_id']
        spec = ser.validated_data['especificacion']
        reps = list(cotizacion.repuestos or [])
        found = False
        for i, r in enumerate(reps):
            if not isinstance(r, dict) or str(r.get('id') or '') != str(rid):
                continue
            linea = dict(r)
            linea['especificacion'] = spec
            linea['especificacion_pendiente'] = False
            linea['precio_unitario_clp'] = 0
            linea['certeza'] = 'sin_precio'
            linea['motivo_sin_precio'] = 'sin_referencia'
            linea.pop('precio_referencia_mercado', None)
            linea.pop('fuente_marketplace', None)
            linea.pop('fuentes_detalle', None)
            linea.pop('fuentes_n', None)
            reps[i] = anotar_familia_en_linea(linea)
            found = True
            break
        if not found:
            raise ValidationError({'repuesto_id': 'No se encontró el repuesto en la cotización.'})
        cotizacion.repuestos = reps
        meta = dict(cotizacion.metadata or {})
        meta = marcar_busqueda_web_pendiente(meta)
        cotizacion.metadata = meta
        self._persistir_repuestos_y_totales(cotizacion)
        cotizacion.save(update_fields=['metadata', 'actualizado_en'])
        if meta.get('busqueda_web_estado') == 'pendiente':
            disparar_busqueda_web_cotizacion(cotizacion.id, sync=False)
        return Response({'cotizacion': CotizacionCanalSerializer(cotizacion).data})

    @action(detail=True, methods=['get'], url_path='opciones-repuesto')
    def opciones_repuesto(self, request, pk=None):
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.opciones_repuesto import (
            MAX_OPCIONES_TALLER,
            construir_opciones_linea,
        )

        cotizacion = self.get_object()
        rid = str(request.query_params.get('repuesto_id') or '').strip()
        if not rid:
            raise ValidationError({'repuesto_id': 'Indica el repuesto.'})
        linea = next(
            (
                r for r in (cotizacion.repuestos or [])
                if isinstance(r, dict) and str(r.get('id') or '') == rid
            ),
            None,
        )
        if linea is None:
            raise ValidationError({'repuesto_id': 'No se encontró el repuesto en la cotización.'})
        opciones = construir_opciones_linea(
            linea,
            vehiculo={
                'marca': cotizacion.vehiculo_marca or '',
                'modelo': cotizacion.vehiculo_modelo or '',
                'anio': cotizacion.vehiculo_anio or '',
            },
            taller=cotizacion.taller,
            calidad=str(linea.get('calidad') or '') or None,
            max_opciones=MAX_OPCIONES_TALLER,
        )
        return Response({
            'opciones': opciones,
            'calidad_cliente': str(linea.get('calidad') or ''),
            'actualizado_en': cotizacion.actualizado_en,
        })

    @action(detail=True, methods=['post'], url_path='usar-opcion-repuesto')
    def usar_opcion_repuesto(self, request, pk=None):
        from mecanimovilapp.apps.ordenes.serializers_proveedor_repuestos import (
            UsarOpcionRepuestoSerializer,
        )
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.opciones_repuesto import (
            aplicar_usar_opcion,
        )

        cotizacion = self.get_object()
        ser = UsarOpcionRepuestoSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        try:
            aplicar_usar_opcion(
                cotizacion,
                repuesto_id=data['repuesto_id'],
                opcion_id=data['opcion_id'],
                guardar_en_mis_precios=data.get('guardar_en_mis_precios', False),
                usuario=request.user,
            )
        except ValueError as exc:
            raise ValidationError({'opcion_id': str(exc)}) from exc
        self._persistir_repuestos_y_totales(cotizacion)
        return Response({'cotizacion': CotizacionCanalSerializer(cotizacion).data})

    @action(detail=True, methods=['post'], url_path='definir-calidad')
    def definir_calidad(self, request, pk=None):
        from mecanimovilapp.apps.ordenes.serializers_proveedor_repuestos import (
            DefinirCalidadSerializer,
        )
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.calidad_repuesto import (
            anotar_calidad_en_linea,
        )
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.disparar_busqueda_web import (
            disparar_busqueda_web_cotizacion,
            marcar_busqueda_web_pendiente,
        )

        cotizacion = self.get_object()
        ser = DefinirCalidadSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        rid = ser.validated_data['repuesto_id']
        calidad = ser.validated_data['calidad']
        reps = list(cotizacion.repuestos or [])
        found = False
        for i, r in enumerate(reps):
            if not isinstance(r, dict) or str(r.get('id') or '') != str(rid):
                continue
            linea = dict(r)
            linea['calidad'] = calidad
            linea['calidad_pendiente'] = False
            linea['precio_unitario_clp'] = 0
            linea['certeza'] = 'sin_precio'
            linea['motivo_sin_precio'] = 'sin_referencia'
            linea.pop('precio_referencia_mercado', None)
            linea.pop('fuente_marketplace', None)
            linea.pop('fuentes_detalle', None)
            linea.pop('fuentes_n', None)
            linea.pop('opciones', None)
            reps[i] = anotar_calidad_en_linea(linea)
            found = True
            break
        if not found:
            raise ValidationError({'repuesto_id': 'No se encontró el repuesto en la cotización.'})
        cotizacion.repuestos = reps
        meta = dict(cotizacion.metadata or {})
        meta = marcar_busqueda_web_pendiente(meta)
        cotizacion.metadata = meta
        self._persistir_repuestos_y_totales(cotizacion)
        cotizacion.save(update_fields=['metadata', 'actualizado_en'])
        if meta.get('busqueda_web_estado') == 'pendiente':
            disparar_busqueda_web_cotizacion(cotizacion.id, sync=False)
        return Response({'cotizacion': CotizacionCanalSerializer(cotizacion).data})

    @action(detail=True, methods=['post'], url_path='enviar-vitrina')
    def enviar_vitrina(self, request, pk=None):
        from mecanimovilapp.apps.agente_ia.models import AgenteConversacionSesion, TallerAgenteConfig
        from mecanimovilapp.apps.agente_ia.services.orquestador import enviar_respuesta_agente
        from mecanimovilapp.apps.ordenes.services.vitrina_repuestos import (
            crear_vitrina,
            texto_mensaje_vitrina,
            vitrina_habilitada,
        )

        cotizacion = self.get_object()
        config = TallerAgenteConfig.objects.filter(taller=cotizacion.taller).first()
        if not vitrina_habilitada(config):
            raise ValidationError({'vitrina': 'La vitrina no está habilitada para este taller.'})
        ids = request.data.get('repuesto_ids') if isinstance(request.data, dict) else None
        if ids is not None and not isinstance(ids, list):
            raise ValidationError({'repuesto_ids': 'Debe ser una lista.'})
        vit = crear_vitrina(
            taller=cotizacion.taller,
            cotizacion=cotizacion,
            conversation=cotizacion.conversation,
            muestra_bandas=bool(getattr(config, 'vitrina_muestra_bandas', True)),
            repuesto_ids=[str(x) for x in ids] if ids else None,
        )
        if vit is None:
            raise ValidationError({'vitrina': 'No hay suficientes opciones para enviar.'})
        if cotizacion.conversation_id and cotizacion.creado_por_id:
            enviar_respuesta_agente(
                conversation=cotizacion.conversation,
                proveedor_user_id=cotizacion.creado_por_id,
                texto=texto_mensaje_vitrina(vit),
            )
        ses = AgenteConversacionSesion.objects.filter(conversation_id=cotizacion.conversation_id).first()
        if ses is not None:
            ses.vitrina_activa = vit
            ses.estado = AgenteConversacionSesion.ESTADO_ELIGIENDO_REPUESTOS
            ses.save(update_fields=['vitrina_activa', 'estado', 'actualizado_en'])
        return Response({
            'ok': True,
            'token': vit.token,
            'url': f'/repuestos/{vit.token}',
        })

    @action(detail=True, methods=['post'], url_path='registrar-compra-repuestos')
    def registrar_compra_repuestos(self, request, pk=None):
        from mecanimovilapp.apps.ordenes.serializers_proveedor_repuestos import (
            RegistrarCompraRepuestosSerializer,
        )
        from mecanimovilapp.apps.ordenes.services.precios_proveedor import (
            get_or_create_proveedor,
            upsert_precio_proveedor,
        )

        cotizacion = self.get_object()
        ser = RegistrarCompraRepuestosSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        creados = 0
        for item in ser.validated_data.get('items') or []:
            linea = next(
                (
                    r for r in (cotizacion.repuestos or [])
                    if isinstance(r, dict) and str(r.get('id') or '') == str(item['repuesto_id'])
                ),
                None,
            )
            if linea is None:
                continue
            proveedor = None
            if item.get('proveedor_id'):
                from mecanimovilapp.apps.ordenes.models import ProveedorRepuestos

                proveedor = ProveedorRepuestos.objects.filter(
                    pk=item['proveedor_id'], taller=cotizacion.taller,
                ).first()
            elif item.get('proveedor_nombre'):
                proveedor = get_or_create_proveedor(cotizacion.taller, item['proveedor_nombre'])
            upsert_precio_proveedor(
                taller=cotizacion.taller,
                nombre_repuesto=str(linea.get('nombre') or ''),
                precio_clp=item['precio_clp'],
                proveedor=proveedor,
                especificacion=str(linea.get('especificacion') or ''),
                marca_repuesto=str(linea.get('marca_repuesto') or ''),
                codigo_parte=str(linea.get('codigo_parte') or ''),
                categoria=str(linea.get('categoria') or ''),
                origen='compra',
                cotizacion=cotizacion,
                precio_referencia_web_clp=int(linea.get('precio_marketplace_clp') or 0),
                usuario=request.user,
            )
            creados += 1
        meta = dict(cotizacion.metadata or {})
        meta['compra_repuestos_registrada'] = True
        cotizacion.metadata = meta
        cotizacion.save(update_fields=['metadata', 'actualizado_en'])
        return Response({'ok': True, 'creados': creados})

    def partial_update(self, request, *args, **kwargs):
        from mecanimovilapp.apps.ordenes.services.cotizacion_canal import (
            actualizar_cotizacion_aceptada_sin_iniciar,
            asegurar_cotizacion_editable_para_items,
        )

        cotizacion = self.get_object()
        from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
            asegurar_documento_emitido_antes_de_editar,
            marcar_emision_pendiente,
        )

        # Congelar el documento público ANTES de reabrir enviada → borrador.
        asegurar_documento_emitido_antes_de_editar(cotizacion)
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
            marcar_emision_pendiente(cotizacion)
            cotizacion.save(update_fields=['metadata', 'actualizado_en'])
            data = CotizacionCanalSerializer(cotizacion).data
            data['modo_actualizacion'] = modo
            return Response(data)
        aplicar_edicion_cotizacion(cotizacion, request.data)
        marcar_emision_pendiente(cotizacion)
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

    @action(detail=True, methods=['get'], url_path='vista-previa')
    def vista_previa(self, request, pk=None):
        """Documento tal como quedará para el cliente (borrador actual, no el snapshot viejo)."""
        from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
            serializar_cotizacion_publica,
        )

        cotizacion = self.get_object()
        return Response(serializar_cotizacion_publica(cotizacion, request, live=True))

    @action(detail=True, methods=['post'])
    def enviar(self, request, pk=None):
        cotizacion = self.get_object()
        from django.conf import settings
        from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
            emision_pendiente,
            persistir_documento_emitido,
        )
        from mecanimovilapp.apps.ordenes.services.precios_proveedor import (
            lineas_pendientes_precio,
        )

        tipo_doc = str(request.data.get('tipo_documento') or '').strip()
        if tipo_doc not in ('estimacion', 'cotizacion'):
            tipo_doc = 'cotizacion' if not lineas_pendientes_precio(cotizacion) else 'estimacion'
        if (
            tipo_doc == 'cotizacion'
            and bool(getattr(settings, 'DOCUMENTO_FIRME_GATE_ENABLED', False))
        ):
            pendientes = lineas_pendientes_precio(cotizacion)
            if pendientes:
                raise ValidationError({
                    'error': 'Faltan precios por confirmar',
                    'lineas_pendientes': pendientes,
                })
        cotizacion.tipo_documento = tipo_doc
        if not cotizacion.tipo_documento_emitido:
            cotizacion.tipo_documento_emitido = tipo_doc
        cotizacion.save(update_fields=['tipo_documento', 'tipo_documento_emitido', 'actualizado_en'])

        if cotizacion.estado != 'borrador' and not emision_pendiente(cotizacion):
            raise ValidationError({'estado': 'La cotización ya fue enviada o cerrada.'})
        if cotizacion.estado != 'borrador' and emision_pendiente(cotizacion):
            persistir_documento_emitido(cotizacion)
            cotizacion.save(update_fields=['metadata', 'actualizado_en'])
            message = None
            plan = None
            if cotizacion.conversation_id:
                message = crear_mensaje_actualizacion_cotizacion(cotizacion, request.user)
                plan = entregar_mensaje_cotizacion_meta(cotizacion, message)
            serialized = CotizacionCanalSerializer(cotizacion).data
            return Response({
                'cotizacion': serialized,
                'message_id': message.id if message else None,
                'share_url': serialized.get('share_url') or cotizacion.url_publica,
                'entrega_via': getattr(plan, 'via', None),
                'entrega_mensaje': getattr(plan, 'message', None),
            })
        if not cotizacion.servicio_nombre.strip():
            raise ValidationError({'servicio_nombre': 'Indica el nombre del servicio.'})
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.mano_obra_lineas import (
            validar_nombres_mano_obra_para_enviar,
        )
        mo_err = validar_nombres_mano_obra_para_enviar(cotizacion)
        if mo_err:
            raise ValidationError({'mano_obra_lineas': mo_err})

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

        plan = entregar_mensaje_cotizacion_meta(cotizacion, message)

        from mecanimovilapp.apps.agente_ia.services.lead_scoring import (
            actualizar_calificacion_desde_cotizacion,
        )
        actualizar_calificacion_desde_cotizacion(cotizacion, evento='enviada')

        serialized = CotizacionCanalSerializer(cotizacion).data
        return Response({
            'cotizacion': serialized,
            'message_id': message.id,
            'share_url': serialized.get('share_url') or cotizacion.url_publica,
            'entrega_via': getattr(plan, 'via', None),
            'entrega_mensaje': getattr(plan, 'message', None),
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
