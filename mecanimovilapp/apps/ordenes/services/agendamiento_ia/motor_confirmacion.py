"""
Creación de solicitud dirigida + oferta catálogo y acciones del proveedor (fase 2).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time

from mecanimovilapp.apps.ordenes.models import (
    DetalleServicioOferta,
    OfertaProveedor,
    SolicitudServicioPublica,
)
from mecanimovilapp.apps.ordenes.services import adjudicacion_publica
from mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_match import (
    _oferta_ofrece_repuestos,
)
from mecanimovilapp.apps.ordenes.ubicacion_servicio_proveedor import (
    punto_ubicacion_taller,
    texto_direccion_taller,
)
from mecanimovilapp.apps.servicios.models import OfertaServicio, Servicio
from mecanimovilapp.apps.usuarios.models import Cliente, Usuario
from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification
from mecanimovilapp.apps.vehiculos.models import Vehiculo

logger = logging.getLogger(__name__)


class ConfirmacionCatalogoError(Exception):
    """Error de negocio en confirmación catálogo."""

    def __init__(self, message: str, code: str = 'error', status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _parse_fecha(value) -> date | None:
    if value is None or value == '':
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    parsed = parse_date(str(value))
    return parsed


def _parse_hora(value) -> time | None:
    if value is None or value == '':
        return None
    if isinstance(value, time):
        return value
    return parse_time(str(value))


def _proveedor_de_oferta_servicio(oferta_servicio: OfertaServicio) -> tuple[Usuario | None, str | None]:
    if oferta_servicio.tipo_proveedor == 'taller' and oferta_servicio.taller_id:
        return oferta_servicio.taller.usuario, 'taller'
    if oferta_servicio.tipo_proveedor == 'mecanico' and oferta_servicio.mecanico_id:
        return oferta_servicio.mecanico.usuario, 'mecanico'
    return None, None


def _tiempo_estimado_desde_servicio(servicio: Servicio) -> timedelta:
    dur = getattr(servicio, 'duracion_estimada_base', None)
    if dur:
        return dur
    return timedelta(hours=2)


def _tiempo_estimado_desde_oferta_servicio(oferta_servicio: OfertaServicio) -> timedelta:
    """Usa duración min/max del catálogo del proveedor; fallback al servicio base."""
    min_m = getattr(oferta_servicio, 'duracion_minima_minutos', None)
    max_m = getattr(oferta_servicio, 'duracion_maxima_minutos', None)
    if min_m is not None and max_m is not None:
        promedio = max(15, (int(min_m) + int(max_m)) // 2)
        return timedelta(minutes=promedio)
    if min_m is not None:
        return timedelta(minutes=max(15, int(min_m)))
    if max_m is not None:
        return timedelta(minutes=max(15, int(max_m)))
    legado = getattr(oferta_servicio, 'duracion_estimada', None)
    if legado:
        return timedelta(
            hours=legado.hour,
            minutes=legado.minute,
            seconds=legado.second,
        )
    return _tiempo_estimado_desde_servicio(oferta_servicio.servicio)


def _incluye_repuestos_catalogo(
    ofertas_servicio: list[OfertaServicio],
    requiere_repuestos_solicitud: bool,
) -> bool:
    """True solo si el cliente pidió repuestos y al menos una línea los publica."""
    if not requiere_repuestos_solicitud:
        return False
    return any(_oferta_ofrece_repuestos(os) for os in ofertas_servicio)


def _linea_usa_repuestos(
    oferta_servicio: OfertaServicio,
    requiere_repuestos_solicitud: bool,
) -> bool:
    return bool(
        requiere_repuestos_solicitud and _oferta_ofrece_repuestos(oferta_servicio)
    )


def _notificar_proveedor_asignacion_catalogo(solicitud: SolicitudServicioPublica, proveedor: Usuario):
    try:
        channel_layer = get_channel_layer()
        v = solicitud.vehiculo
        if v:
            vehiculo_label = f"{getattr(v.marca, 'nombre', v.marca)} {getattr(v.modelo, 'nombre', v.modelo)}"
        else:
            vehiculo_label = 'Sin vehículo'
        async_to_sync(channel_layer.group_send)(
            f"proveedor_{proveedor.id}",
            {
                'type': 'nueva_solicitud',
                'solicitud_id': str(solicitud.id),
                'vehiculo': vehiculo_label,
                'descripcion': (solicitud.descripcion_problema or '')[:100],
                'urgencia': solicitud.urgencia,
                'fecha_expiracion': solicitud.fecha_expiracion.isoformat(),
                'es_asignacion_catalogo': True,
            },
        )
        send_expo_push_notification.delay(
            proveedor.id,
            'Nueva solicitud para confirmar',
            'Un cliente eligió tu servicio del catálogo. Revisa y confirma la asignación.',
            {
                'type': 'catalog_assignment',
                'solicitud_id': str(solicitud.id),
            },
        )
    except Exception:
        logger.exception('Error notificando proveedor asignación catálogo solicitud %s', solicitud.id)


def _notificar_cliente_catalogo(usuario_id: int, titulo: str, cuerpo: str, extra: dict | None = None):
    try:
        send_expo_push_notification.delay(usuario_id, titulo, cuerpo, extra or {})
    except Exception:
        logger.warning('No se pudo encolar push al cliente %s', usuario_id)


def _precio_linea_oferta_servicio(
    oferta_servicio: OfertaServicio,
    requiere_repuestos_solicitud: bool,
) -> Decimal:
    usa_repuestos = _linea_usa_repuestos(oferta_servicio, requiere_repuestos_solicitud)
    total = Decimal(str(oferta_servicio.precio_publicado_cliente or 0))
    if total <= 0:
        total = Decimal(
            str(
                oferta_servicio.precio_con_repuestos
                if usa_repuestos
                else oferta_servicio.precio_sin_repuestos
            )
        )
    return total


def _crear_oferta_catalogo_con_lineas(
    *,
    ofertas_servicio: list[OfertaServicio],
    solicitud: SolicitudServicioPublica,
    proveedor: Usuario,
    tipo_proveedor: str,
    requiere_repuestos: bool,
    metadata_ia: dict | None,
    fecha_disponible: date,
    hora_disponible: time | None,
) -> OfertaProveedor:
    """Una OfertaProveedor con un DetalleServicioOferta por cada OfertaServicio del proveedor."""
    if not ofertas_servicio:
        raise ConfirmacionCatalogoError('Sin ofertas de catálogo', 'sin_ofertas')

    principal = ofertas_servicio[0]
    incluye_repuestos = _incluye_repuestos_catalogo(
        ofertas_servicio, requiere_repuestos
    )
    mo_total = Decimal('0')
    rep_total = Decimal('0')
    gest_total = Decimal('0')
    precio_total = Decimal('0')
    tiempo_total = timedelta(0)
    nombres: list[str] = []

    for oferta_servicio in ofertas_servicio:
        mo_total += Decimal(str(oferta_servicio.costo_mano_de_obra_sin_iva or 0))
        if _linea_usa_repuestos(oferta_servicio, requiere_repuestos):
            rep_total += Decimal(str(oferta_servicio.costo_repuestos_sin_iva or 0))
            gest_total += Decimal(
                str(getattr(oferta_servicio, 'costo_gestion_compra_sin_iva', None) or 0)
            )
        precio_total += _precio_linea_oferta_servicio(oferta_servicio, requiere_repuestos)
        tiempo_total += _tiempo_estimado_desde_oferta_servicio(oferta_servicio)
        nombres.append(oferta_servicio.servicio.nombre)

    descripcion = (
        f"Propuesta desde catálogo: {', '.join(nombres)}"
        if len(nombres) > 1
        else f"Propuesta desde catálogo: {nombres[0]}"
    )

    oferta = OfertaProveedor.objects.create(
        solicitud=solicitud,
        proveedor=proveedor,
        tipo_proveedor=tipo_proveedor,
        origen='catalogo',
        oferta_servicio=principal,
        metadata_ia=metadata_ia,
        precio_total_ofrecido=precio_total,
        incluye_repuestos=incluye_repuestos,
        costo_mano_obra=mo_total,
        costo_repuestos=rep_total,
        costo_gestion_compra=gest_total,
        tiempo_estimado_total=tiempo_total,
        descripcion_oferta=descripcion,
        garantia_ofrecida='',
        fecha_disponible=fecha_disponible,
        hora_disponible=hora_disponible,
        es_fecha_alternativa=False,
        estado='pendiente_confirmacion',
        es_oferta_secundaria=False,
    )

    servicio_ids: list[int] = []
    for oferta_servicio in ofertas_servicio:
        servicio = oferta_servicio.servicio
        precio_detalle = _precio_linea_oferta_servicio(oferta_servicio, requiere_repuestos)
        repuestos_linea: list = []
        if _linea_usa_repuestos(oferta_servicio, requiere_repuestos):
            raw_rep = getattr(oferta_servicio, 'repuestos_seleccionados', None)
            if isinstance(raw_rep, list):
                repuestos_linea = list(raw_rep)
        DetalleServicioOferta.objects.create(
            oferta=oferta,
            servicio=servicio,
            precio_servicio=precio_detalle,
            tiempo_estimado=_tiempo_estimado_desde_oferta_servicio(oferta_servicio),
            notas='',
            repuestos_seleccionados=repuestos_linea,
        )
        servicio_ids.append(servicio.id)

    oferta.servicios_ofertados.set(servicio_ids)
    return oferta


def _parse_oferta_servicio_ids(payload: dict[str, Any]) -> list[int]:
    raw_list = payload.get('oferta_servicio_ids')
    ids: list[int] = []
    if isinstance(raw_list, (list, tuple)):
        for x in raw_list:
            try:
                ids.append(int(x))
            except (TypeError, ValueError):
                continue
    if not ids and payload.get('oferta_servicio_id') is not None:
        try:
            ids.append(int(payload['oferta_servicio_id']))
        except (TypeError, ValueError):
            pass
    # dedupe preserving order
    seen: set[int] = set()
    out: list[int] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


@transaction.atomic
def confirmar_candidato(cliente: Cliente, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Cliente confirma un candidato del catálogo: crea solicitud dirigida + oferta prellenada.
    """
    oferta_servicio_ids = _parse_oferta_servicio_ids(payload)
    if not oferta_servicio_ids:
        raise ConfirmacionCatalogoError(
            'oferta_servicio_id u oferta_servicio_ids es obligatorio',
            'oferta_servicio_requerida',
        )
    oferta_servicio_id = oferta_servicio_ids[0]

    vehiculo_id = payload.get('vehiculo_id')
    if not vehiculo_id:
        raise ConfirmacionCatalogoError('vehiculo_id es obligatorio', 'vehiculo_requerido')

    vehiculo = (
        Vehiculo.objects.select_related('marca', 'modelo')
        .filter(pk=vehiculo_id, cliente=cliente)
        .first()
    )
    if not vehiculo:
        raise ConfirmacionCatalogoError('Vehículo no encontrado', 'vehiculo_no_encontrado', 404)

    ofertas_servicio = list(
        OfertaServicio.objects.select_related(
            'servicio',
            'taller',
            'taller__usuario',
            'taller__direccion_fisica',
            'mecanico',
            'mecanico__usuario',
        )
        .filter(pk__in=oferta_servicio_ids, disponible=True)
        .order_by('servicio_id', 'id')
    )
    if len(ofertas_servicio) != len(oferta_servicio_ids):
        raise ConfirmacionCatalogoError(
            'Una o más ofertas de catálogo no están disponibles',
            'catalogo_no_disponible',
            404,
        )

    proveedor, tipo_proveedor = _proveedor_de_oferta_servicio(ofertas_servicio[0])
    if not proveedor or not tipo_proveedor:
        raise ConfirmacionCatalogoError('Proveedor de catálogo inválido', 'proveedor_invalido')

    for os in ofertas_servicio[1:]:
        prov_o, tipo_o = _proveedor_de_oferta_servicio(os)
        if prov_o != proveedor or tipo_o != tipo_proveedor:
            raise ConfirmacionCatalogoError(
                'Todas las ofertas deben ser del mismo proveedor',
                'proveedor_mixto',
            )

    servicio_ids = payload.get('servicio_ids') or [
        os.servicio_id for os in ofertas_servicio
    ]
    for os in ofertas_servicio:
        if os.servicio_id not in [int(s) for s in servicio_ids if s is not None]:
            servicio_ids = list(servicio_ids) + [os.servicio_id]

    descripcion = (payload.get('descripcion_problema') or '').strip()
    if not descripcion:
        raise ConfirmacionCatalogoError('descripcion_problema es obligatoria', 'descripcion_requerida')

    fecha_preferida = _parse_fecha(payload.get('fecha_preferida'))
    if not fecha_preferida:
        raise ConfirmacionCatalogoError('fecha_preferida es obligatoria', 'fecha_requerida')

    hora_preferida = _parse_hora(payload.get('hora_preferida'))
    requiere_repuestos = payload.get('requiere_repuestos', True)
    if isinstance(requiere_repuestos, str):
        requiere_repuestos = requiere_repuestos.lower() in ('1', 'true', 'yes', 'si')

    lat = payload.get('lat')
    lng = payload.get('lng')
    if lat is None or lng is None:
        ubicacion = payload.get('ubicacion_servicio') or {}
        coords = ubicacion.get('coordinates') if isinstance(ubicacion, dict) else None
        if coords and len(coords) >= 2:
            lng, lat = float(coords[0]), float(coords[1])

    direccion_texto = (payload.get('direccion_servicio_texto') or '').strip()

    if tipo_proveedor == 'taller':
        taller = ofertas_servicio[0].taller
        if not taller:
            raise ConfirmacionCatalogoError('Taller de catálogo inválido', 'proveedor_invalido')
        punto_taller = punto_ubicacion_taller(taller)
        if punto_taller is None:
            raise ConfirmacionCatalogoError(
                'El taller no tiene ubicación configurada',
                'taller_sin_ubicacion',
            )
        lng, lat = float(punto_taller.x), float(punto_taller.y)
        direccion_texto = texto_direccion_taller(taller) or direccion_texto
        if not direccion_texto:
            raise ConfirmacionCatalogoError(
                'El taller no tiene dirección configurada',
                'taller_sin_direccion',
            )
    else:
        if lat is None or lng is None:
            raise ConfirmacionCatalogoError('Ubicación (lat/lng) es obligatoria', 'ubicacion_requerida')
        if not direccion_texto:
            raise ConfirmacionCatalogoError(
                'direccion_servicio_texto es obligatoria',
                'direccion_requerida',
            )

    ahora = timezone.now()
    fecha_expiracion = SolicitudServicioPublica.compute_default_fecha_expiracion(
        now=ahora,
        fecha_preferida=fecha_preferida,
    )

    metadata_entrada = payload.get('metadata_ia_entrada')
    if metadata_entrada is not None and not isinstance(metadata_entrada, dict):
        metadata_entrada = None

    metadata_ia_oferta = {
        'oferta_servicio_id': oferta_servicio_id,
        'oferta_servicio_ids': oferta_servicio_ids,
        'score_match': payload.get('score_match'),
    }

    solicitud = SolicitudServicioPublica.objects.create(
        cliente=cliente,
        vehiculo=vehiculo,
        descripcion_problema=descripcion,
        urgencia=payload.get('urgencia') or 'normal',
        requiere_repuestos=requiere_repuestos,
        tipo_solicitud='dirigida',
        direccion_usuario_id=payload.get('direccion_usuario') or None,
        ubicacion_servicio=Point(float(lng), float(lat), srid=4326),
        direccion_servicio_texto=direccion_texto,
        detalles_ubicacion=(payload.get('detalles_ubicacion') or '')[:255],
        fecha_preferida=fecha_preferida,
        hora_preferida=hora_preferida,
        estado='pendiente_confirmacion',
        fecha_publicacion=ahora,
        fecha_expiracion=fecha_expiracion,
        metadata_ia_entrada=metadata_entrada,
        total_ofertas=1,
    )
    solicitud.servicios_solicitados.set(
        Servicio.objects.filter(id__in=servicio_ids)
    )
    solicitud.proveedores_dirigidos.set([proveedor])

    oferta = _crear_oferta_catalogo_con_lineas(
        ofertas_servicio=ofertas_servicio,
        solicitud=solicitud,
        proveedor=proveedor,
        tipo_proveedor=tipo_proveedor,
        requiere_repuestos=requiere_repuestos,
        metadata_ia=metadata_ia_oferta,
        fecha_disponible=fecha_preferida,
        hora_disponible=hora_preferida,
    )
    solicitud.oferta_seleccionada = oferta
    solicitud.save(update_fields=['oferta_seleccionada', 'fecha_actualizacion'])

    transaction.on_commit(
        lambda: _notificar_proveedor_asignacion_catalogo(solicitud, proveedor)
    )

    return {
        'solicitud_id': str(solicitud.id),
        'oferta_id': str(oferta.id),
        'estado': solicitud.estado,
        'proveedor_usuario_id': str(proveedor.id),
    }


def _validar_oferta_catalogo_proveedor(oferta: OfertaProveedor, proveedor: Usuario):
    if oferta.origen != 'catalogo':
        raise ConfirmacionCatalogoError('No es una oferta de catálogo', 'no_es_catalogo')
    if oferta.proveedor_id != proveedor.id:
        raise ConfirmacionCatalogoError('No autorizado', 'no_autorizado', 403)
    if oferta.estado != 'pendiente_confirmacion':
        raise ConfirmacionCatalogoError(
            f'La oferta no está pendiente de confirmación (estado: {oferta.estado})',
            'estado_invalido',
        )
    if oferta.solicitud.estado != 'pendiente_confirmacion':
        raise ConfirmacionCatalogoError(
            'La solicitud no está pendiente de confirmación',
            'solicitud_estado_invalido',
        )


@transaction.atomic
def proveedor_rechazar_catalogo(oferta: OfertaProveedor, proveedor: Usuario, motivo: str = '') -> dict:
    _validar_oferta_catalogo_proveedor(oferta, proveedor)
    ahora = timezone.now()
    oferta.estado = 'rechazada'
    oferta.save(update_fields=['estado'])
    solicitud = oferta.solicitud
    solicitud.estado = 'cancelada'
    solicitud.oferta_seleccionada = None
    solicitud.save(update_fields=['estado', 'oferta_seleccionada', 'fecha_actualizacion'])

    cliente_user = solicitud.cliente.usuario_id
    transaction.on_commit(
        lambda: _notificar_cliente_catalogo(
            cliente_user,
            'Proveedor no disponible',
            'El proveedor no pudo confirmar tu solicitud. Puedes elegir otro candidato.',
            {'type': 'catalog_rejected', 'solicitud_id': str(solicitud.id)},
        )
    )
    return {'estado': 'cancelada', 'oferta_estado': 'rechazada', 'motivo': motivo}


@transaction.atomic
def proveedor_proponer_fecha_catalogo(
    oferta: OfertaProveedor,
    proveedor: Usuario,
    *,
    fecha_disponible,
    hora_disponible=None,
    motivo: str = '',
) -> dict:
    _validar_oferta_catalogo_proveedor(oferta, proveedor)
    fd = _parse_fecha(fecha_disponible)
    if not fd:
        raise ConfirmacionCatalogoError('fecha_disponible inválida', 'fecha_invalida')
    hd = _parse_hora(hora_disponible)

    oferta.fecha_disponible = fd
    oferta.hora_disponible = hd
    oferta.es_fecha_alternativa = True
    oferta.motivo_fecha_alternativa = (motivo or '')[:500]
    oferta.estado = 'en_chat'
    oferta.save(
        update_fields=[
            'fecha_disponible',
            'hora_disponible',
            'es_fecha_alternativa',
            'motivo_fecha_alternativa',
            'estado',
        ]
    )

    cliente_user = oferta.solicitud.cliente.usuario_id
    transaction.on_commit(
        lambda: _notificar_cliente_catalogo(
            cliente_user,
            'Nueva fecha propuesta',
            'El proveedor propuso otra fecha para tu servicio. Revísala en la solicitud.',
            {
                'type': 'catalog_date_proposed',
                'solicitud_id': str(oferta.solicitud_id),
                'oferta_id': str(oferta.id),
            },
        )
    )
    return {
        'oferta_id': str(oferta.id),
        'fecha_disponible': fd.isoformat(),
        'hora_disponible': hd.isoformat() if hd else None,
        'es_fecha_alternativa': True,
    }


@transaction.atomic
def cliente_aceptar_fecha_catalogo(oferta: OfertaProveedor, cliente) -> dict:
    """Cliente acepta la fecha alternativa propuesta por el proveedor."""
    if oferta.solicitud.cliente_id != cliente.id:
        raise ConfirmacionCatalogoError('No autorizado', 'no_autorizado', 403)
    if oferta.origen != 'catalogo':
        raise ConfirmacionCatalogoError('No es una oferta de catálogo', 'no_es_catalogo')
    if not oferta.es_fecha_alternativa:
        raise ConfirmacionCatalogoError(
            'No hay fecha alternativa pendiente de aceptar',
            'sin_fecha_alternativa',
        )
    if oferta.solicitud.oferta_seleccionada_id != oferta.id:
        raise ConfirmacionCatalogoError(
            'La oferta no corresponde a la solicitud activa',
            'oferta_no_seleccionada',
        )

    solicitud = oferta.solicitud
    solicitud.fecha_preferida = oferta.fecha_disponible
    solicitud.hora_preferida = oferta.hora_disponible
    solicitud.save(update_fields=['fecha_preferida', 'hora_preferida', 'fecha_actualizacion'])

    oferta.es_fecha_alternativa = False
    oferta.estado = 'pendiente_confirmacion'
    oferta.save(update_fields=['es_fecha_alternativa', 'estado'])

    proveedor_id = oferta.proveedor_id
    transaction.on_commit(
        lambda: send_expo_push_notification.delay(
            proveedor_id,
            'Fecha aceptada',
            'El cliente aceptó tu propuesta de fecha. Confirma la asignación cuando puedas.',
            {
                'type': 'catalog_date_accepted',
                'solicitud_id': str(solicitud.id),
                'oferta_id': str(oferta.id),
            },
        )
    )
    return {
        'solicitud_id': str(solicitud.id),
        'oferta_id': str(oferta.id),
        'fecha_preferida': solicitud.fecha_preferida.isoformat(),
        'hora_preferida': (
            solicitud.hora_preferida.isoformat() if solicitud.hora_preferida else None
        ),
    }


def adjudicar_oferta_catalogo_confirmada(oferta: OfertaProveedor) -> dict[str, Any]:
    """
    Ejecuta adjudicación tras confirmación del proveedor (créditos + carrito).
    Debe llamarse dentro de transaction.atomic del view.
    Retorna dict con estado_resultado, carrito_id, etc.
    """
    solicitud = oferta.solicitud
    if oferta.tipo_proveedor == 'taller':
        taller = oferta.proveedor.taller
        mecanico = None
    else:
        taller = None
        mecanico = oferta.proveedor.mecanico_domicilio

    detalles = list(oferta.detalles_servicios.all())
    if not detalles:
        raise ConfirmacionCatalogoError('La oferta no tiene servicios', 'sin_detalles', 400)

    use_reserve = False
    creditos_necesarios_reserva = 0
    try:
        from mecanimovilapp.apps.suscripciones.creditos_services import (
            puede_adjudicar as puede_adjudicar_creditos,
            validar_creditos_suficientes,
        )

        puede_ag, mensaje_anti = puede_adjudicar_creditos(oferta.proveedor)
        if not puede_ag:
            raise ConfirmacionCatalogoError(mensaje_anti, 'anti_gaming', 400)

        servicio_principal = detalles[0].servicio
        puede_adjudicar, mensaje, creditos_necesarios = validar_creditos_suficientes(
            oferta.proveedor,
            servicio_principal,
        )
        if not puede_adjudicar:
            use_reserve = True
            creditos_necesarios_reserva = creditos_necesarios
    except ImportError:
        pass

    if use_reserve:
        reserva = adjudicacion_publica.aplicar_reserva_por_falta_creditos(
            solicitud.id,
            oferta.id,
            creditos_necesarios_reserva,
        )
        return {
            'estado_resultado': 'esperando_creditos_proveedor',
            'creditos_necesarios': creditos_necesarios_reserva,
            'fecha_limite_confirmacion_creditos': reserva['fecha_limite_confirmacion_creditos'].isoformat(),
            'oferta_id': str(oferta.id),
            'solicitud_id': str(solicitud.id),
        }

    carrito_id = adjudicacion_publica.ejecutar_finalizacion_adjudicacion(
        solicitud,
        oferta,
        taller,
        mecanico,
        detalles,
    )
    return {
        'estado_resultado': 'adjudicada',
        'carrito_id': carrito_id,
        'oferta_id': str(oferta.id),
        'solicitud_id': str(solicitud.id),
    }
