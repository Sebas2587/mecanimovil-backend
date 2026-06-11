"""
Adjudicación de solicitudes públicas con reserva cuando el proveedor no tiene créditos al ser elegido.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from mecanimovilapp.apps.ordenes import adjudicacion_helpers
from mecanimovilapp.apps.ordenes.models import (
    CarritoAgendamiento,
    ItemCarritoAgendamiento,
    OfertaProveedor,
    SolicitudServicioPublica,
)
from mecanimovilapp.apps.servicios.models import OfertaServicio
from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification

logger = logging.getLogger(__name__)


class AdjudicacionCarritoError(Exception):
    """Error al armar carrito durante adjudicación (revierte transacción)."""

    pass


def _parse_oferta_servicio_ids_from_metadata(oferta: OfertaProveedor) -> list[int]:
    meta = oferta.metadata_ia if isinstance(oferta.metadata_ia, dict) else {}
    ids: list[int] = []
    raw_list = meta.get('oferta_servicio_ids')
    if isinstance(raw_list, (list, tuple)):
        for value in raw_list:
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue
    if not ids and meta.get('oferta_servicio_id') is not None:
        try:
            ids.append(int(meta['oferta_servicio_id']))
        except (TypeError, ValueError):
            pass
    if oferta.oferta_servicio_id and oferta.oferta_servicio_id not in ids:
        ids.insert(0, oferta.oferta_servicio_id)
    return ids


def _map_servicio_id_a_oferta_servicio_catalogo(oferta: OfertaProveedor) -> dict[int, int]:
    """Mapea servicio_id -> OfertaServicio.pk usando metadata de ofertas catálogo."""
    ids = _parse_oferta_servicio_ids_from_metadata(oferta)
    if not ids:
        return {}
    mapping: dict[int, int] = {}
    for row in OfertaServicio.objects.filter(pk__in=ids).only('id', 'servicio_id'):
        mapping[row.servicio_id] = row.id
    return mapping


def resolver_oferta_servicio_para_detalle(
    *,
    oferta: OfertaProveedor,
    detalle,
    tipo_proveedor: str,
    taller,
    mecanico,
    solicitud: SolicitudServicioPublica | None = None,
) -> OfertaServicio:
    """
    Resuelve la fila de catálogo (OfertaServicio) para un detalle de oferta.
    Prioriza ids explícitos de catálogo; evita MultipleObjectsReturned en multimarca/motor.
    """
    servicio_id = detalle.servicio_id

    if oferta.origen == 'catalogo':
        catalog_map = _map_servicio_id_a_oferta_servicio_catalogo(oferta)
        catalog_id = catalog_map.get(servicio_id)
        if catalog_id:
            return OfertaServicio.objects.get(pk=catalog_id)
        if oferta.oferta_servicio_id and oferta.oferta_servicio.servicio_id == servicio_id:
            return oferta.oferta_servicio

    qs = OfertaServicio.objects.filter(
        servicio_id=servicio_id,
        tipo_proveedor=tipo_proveedor,
        taller=taller,
        mecanico=mecanico,
    )

    vehiculo = getattr(solicitud, 'vehiculo', None) if solicitud else None
    if vehiculo is not None:
        if getattr(vehiculo, 'marca_id', None):
            por_marca = qs.filter(marca_vehiculo_seleccionada_id=vehiculo.marca_id)
            if por_marca.exists():
                qs = por_marca
        tipo_motor = getattr(vehiculo, 'tipo_motor', None)
        if tipo_motor and str(tipo_motor).strip():
            from mecanimovilapp.apps.vehiculos.catalogo_resolver import normalizar_tipo_motor_vehiculo

            motor = normalizar_tipo_motor_vehiculo(tipo_motor)
            por_motor = qs.filter(tipo_motor__in=['', motor])
            if por_motor.exists():
                qs = por_motor

    count = qs.count()
    if count == 1:
        return qs.get()
    if count > 1:
        picked = qs.filter(disponible=True).order_by('-id').first() or qs.order_by('-id').first()
        if picked:
            logger.warning(
                'Múltiples OfertaServicio para servicio %s (proveedor %s); usando id=%s',
                servicio_id,
                oferta.proveedor_id,
                picked.id,
            )
            return picked

    raise OfertaServicio.DoesNotExist(
        f'Sin OfertaServicio para servicio {servicio_id} y proveedor de oferta {oferta.id}'
    )


def _horas_reserva_creditos() -> int:
    return int(getattr(settings, 'ADJUDICACION_CREDITOS_RESERVA_HORAS', 48))


@transaction.atomic
def aplicar_reserva_por_falta_creditos(
    solicitud_id,
    oferta_id,
    creditos_necesarios: int,
):
    """
    Cliente eligió oferta; proveedor sin saldo suficiente.
    Reserva la solicitud y marca plazo para que el proveedor compre créditos.
    """
    solicitud = SolicitudServicioPublica.objects.select_for_update().get(pk=solicitud_id)
    oferta = OfertaProveedor.objects.select_for_update().get(pk=oferta_id, solicitud_id=solicitud_id)
    ahora = timezone.now()
    limite = ahora + timedelta(hours=_horas_reserva_creditos())

    oferta.estado = 'pendiente_creditos'
    oferta.fecha_respuesta_cliente = ahora
    oferta.save(update_fields=['estado', 'fecha_respuesta_cliente'])

    solicitud.oferta_seleccionada = oferta
    solicitud.estado = 'esperando_creditos_proveedor'
    solicitud.fecha_limite_confirmacion_creditos = limite
    solicitud.save(
        update_fields=[
            'oferta_seleccionada',
            'estado',
            'fecha_limite_confirmacion_creditos',
            'fecha_actualizacion',
        ]
    )

    rech = OfertaProveedor.objects.filter(
        solicitud=solicitud,
        estado__in=['enviada', 'vista', 'en_chat'],
        es_oferta_secundaria=False,
    ).exclude(pk=oferta.pk).update(
        estado='rechazada',
        fecha_respuesta_cliente=ahora,
    )
    logger.info(
        f"Reserva créditos: solicitud {solicitud_id}, oferta {oferta_id}, "
        f"rechazadas_otras_originales={rech}, límite={limite}"
    )

    try:
        send_expo_push_notification.delay(
            oferta.proveedor.id,
            'Te eligieron: confirma con créditos',
            f'Compra {creditos_necesarios} crédito(s) antes del plazo para confirmar la adjudicación.',
            {
                'type': 'offer_pending_credits',
                'solicitud_id': str(solicitud.id),
                'oferta_id': str(oferta.id),
                'creditos_necesarios': creditos_necesarios,
            },
        )
    except Exception as e:
        logger.warning(f"No se pudo encolar push pendiente_creditos: {e}")

    return {
        'fecha_limite_confirmacion_creditos': limite,
        'creditos_necesarios': creditos_necesarios,
    }


def ejecutar_finalizacion_adjudicacion(solicitud, oferta, taller, mecanico, detalles_servicios):
    """
    Tramo interno post-validación de créditos: acepta oferta, adjudica solicitud, consume créditos,
    arma carrito, chat inicial, notificaciones.
    Debe ejecutarse dentro de transaction.atomic del llamador.
    Retorna carrito_id (int|None).
    """
    logger.info("Marcando oferta como aceptada")
    oferta.estado = 'aceptada'
    oferta.fecha_respuesta_cliente = timezone.now()
    oferta.save(update_fields=['estado', 'fecha_respuesta_cliente'])

    logger.info("Actualizando solicitud a adjudicada")
    solicitud.estado = 'adjudicada'
    solicitud.oferta_seleccionada = oferta
    solicitud.fecha_limite_confirmacion_creditos = None
    if oferta.fecha_disponible:
        hora_disponible = oferta.hora_disponible or timezone.now().time()
        fecha_limite = timezone.make_aware(
            datetime.combine(oferta.fecha_disponible, hora_disponible)
        )
        solicitud.fecha_limite_pago = fecha_limite
        logger.info(f"Fecha límite de pago establecida: {fecha_limite}")

    solicitud.save(
        update_fields=[
            'estado',
            'oferta_seleccionada',
            'fecha_limite_pago',
            'fecha_limite_confirmacion_creditos',
            'fecha_actualizacion',
        ]
    )

    ofertas_rechazadas = OfertaProveedor.objects.filter(
        solicitud=solicitud,
        estado__in=['enviada', 'vista', 'en_chat'],
        es_oferta_secundaria=False,
    ).exclude(id=oferta.id).update(
        estado='rechazada',
        fecha_respuesta_cliente=timezone.now(),
    )
    logger.info(f"Rechazadas {ofertas_rechazadas} ofertas originales")

    if not oferta.es_oferta_secundaria and detalles_servicios:
        try:
            from mecanimovilapp.apps.suscripciones.creditos_services import consumir_creditos_adjudicacion

            servicio_principal = detalles_servicios[0].servicio
            logger.info(
                f"Consumir créditos oferta {oferta.id} proveedor {oferta.proveedor.id} "
                f"servicio {servicio_principal.nombre}"
            )
            consumir_creditos_adjudicacion(
                proveedor=oferta.proveedor,
                oferta=oferta,
                servicio=servicio_principal,
            )
        except ImportError as e:
            logger.error(f"Módulo de créditos no disponible: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Error consumiendo créditos oferta {oferta.id}: {e}", exc_info=True)
            raise
    elif oferta.es_oferta_secundaria:
        logger.info(f"Oferta {oferta.id} secundaria, no se consumen créditos")
    elif not detalles_servicios:
        logger.warning(f"Oferta {oferta.id} sin detalles_servicios")

    carrito = None
    if solicitud.vehiculo_id is not None:
        logger.info("Obteniendo o creando carrito")
        try:
            carrito = adjudicacion_helpers.obtener_o_crear_carrito(solicitud.cliente, solicitud.vehiculo)
            if solicitud.descripcion_problema and not carrito.notas:
                carrito.notas = solicitud.descripcion_problema
                carrito.fecha_programada = oferta.fecha_disponible
                carrito.hora_programada = oferta.hora_disponible
                carrito.save(update_fields=['notas', 'fecha_programada', 'hora_programada'])
        except Exception as e:
            logger.error(f"Error obteniendo/creando carrito: {e}", exc_info=True)
            raise AdjudicacionCarritoError(f'Error al obtener o crear el carrito: {str(e)}') from e

        tipo_proveedor_servicio = oferta.tipo_proveedor
        if tipo_proveedor_servicio == 'taller' and not taller:
            raise ValueError("Inconsistencia: tipo_proveedor es 'taller' pero no hay taller asociado")
        if tipo_proveedor_servicio == 'mecanico' and not mecanico:
            raise ValueError("Inconsistencia: tipo_proveedor es 'mecanico' pero no hay mecánico asociado")
        if tipo_proveedor_servicio not in ['taller', 'mecanico']:
            raise ValueError(f"Tipo de proveedor inválido: {tipo_proveedor_servicio}")

        for detalle in detalles_servicios:
            try:
                try:
                    oferta_servicio = resolver_oferta_servicio_para_detalle(
                        oferta=oferta,
                        detalle=detalle,
                        tipo_proveedor=tipo_proveedor_servicio,
                        taller=taller,
                        mecanico=mecanico,
                        solicitud=solicitud,
                    )
                except OfertaServicio.DoesNotExist:
                    precio_ofrecido = Decimal(str(detalle.precio_servicio))
                    IVA_RATE = Decimal('0.19')
                    costo_total_sin_iva = precio_ofrecido / (Decimal('1') + IVA_RATE)
                    if oferta.incluye_repuestos:
                        costo_mano_de_obra = costo_total_sin_iva * Decimal('0.7')
                        costo_repuestos = costo_total_sin_iva * Decimal('0.3')
                        tipo_servicio = 'con_repuestos'
                    else:
                        costo_mano_de_obra = costo_total_sin_iva
                        costo_repuestos = Decimal('0')
                        tipo_servicio = 'sin_repuestos'

                    taller_final = taller if tipo_proveedor_servicio == 'taller' else None
                    mecanico_final = mecanico if tipo_proveedor_servicio == 'mecanico' else None

                    oferta_servicio = OfertaServicio(
                        servicio=detalle.servicio,
                        tipo_proveedor=str(tipo_proveedor_servicio).strip(),
                        taller=taller_final,
                        mecanico=mecanico_final,
                        costo_mano_de_obra_sin_iva=costo_mano_de_obra,
                        costo_repuestos_sin_iva=costo_repuestos,
                        tipo_servicio=tipo_servicio,
                    )
                    oferta_servicio.clean()
                    oferta_servicio.save()

                precio_unitario_linea = (
                    oferta_servicio.precio_con_repuestos
                    if oferta.incluye_repuestos
                    else oferta_servicio.precio_sin_repuestos
                )
                item_carrito, created = ItemCarritoAgendamiento.objects.get_or_create(
                    carrito=carrito,
                    oferta_servicio=oferta_servicio,
                    defaults={
                        'con_repuestos': oferta.incluye_repuestos,
                        'cantidad': 1,
                        'fecha_servicio': oferta.fecha_disponible,
                        'hora_servicio': oferta.hora_disponible,
                    },
                )
                if not created:
                    item_carrito.con_repuestos = oferta.incluye_repuestos
                    item_carrito.fecha_servicio = oferta.fecha_disponible
                    item_carrito.hora_servicio = oferta.hora_disponible
                    item_carrito.save(update_fields=['con_repuestos', 'fecha_servicio', 'hora_servicio'])
            except Exception as e:
                logger.error(f"Error agregando servicio al carrito {detalle.servicio.id}: {e}", exc_info=True)
                raise

        logger.info(f"Total servicios en carrito: {len(detalles_servicios)}")
    else:
        logger.info("Solicitud sin vehículo: sin carrito")

    try:
        adjudicacion_helpers.crear_chat_inicial_oferta(oferta, solicitud)
    except Exception as e:
        logger.error(f"Error creando mensaje inicial chat: {e}", exc_info=True)

    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"proveedor_{oferta.proveedor.id}",
                {
                    'type': 'oferta_aceptada',
                    'oferta_id': str(oferta.id),
                    'solicitud_id': str(solicitud.id),
                    'carrito_id': carrito.id if carrito else None,
                    'mensaje': '¡Tu oferta fue aceptada! El cliente procederá con el pago.',
                    'estado_oferta': 'aceptada',
                    'monto_total': float(oferta.precio_total_ofrecido),
                    'timestamp': timezone.now().isoformat(),
                },
            )
            push_body = (
                f"Has ganado la solicitud para un {solicitud.vehiculo.marca} {solicitud.vehiculo.modelo}"
                if solicitud.vehiculo_id
                else "Has ganado una solicitud de servicio (sin vehículo registrado)"
            )
            send_expo_push_notification.delay(
                oferta.proveedor.id,
                "¡Felicidades! Oferta adjudicada 🎉",
                push_body,
                {"type": "offer_accepted", "solicitud_id": str(solicitud.id), "oferta_id": str(oferta.id)},
            )
    except Exception as e:
        logger.error(f"Error notificación adjudicación: {e}", exc_info=True)

    return carrito.id if carrito is not None else None


@transaction.atomic
def completar_adjudicacion_si_listo(oferta_id) -> dict:
    """
    Idempotente: si la oferta está en pendiente_creditos y hay saldo, ejecuta adjudicación final.
    """
    oferta = (
        OfertaProveedor.objects.select_for_update()
        .select_related('solicitud', 'proveedor', 'proveedor__taller', 'proveedor__mecanico_domicilio')
        .filter(pk=oferta_id)
        .first()
    )
    if not oferta:
        return {'ok': False, 'reason': 'oferta_not_found'}

    if oferta.consumos_credito.exists():
        return {'ok': True, 'reason': 'already_has_consumo'}

    solicitud = SolicitudServicioPublica.objects.select_for_update().get(pk=oferta.solicitud_id)

    if solicitud.estado == 'adjudicada' and oferta.estado == 'aceptada':
        return {'ok': True, 'reason': 'already_adjudicada'}

    if oferta.estado != 'pendiente_creditos':
        return {'ok': False, 'reason': f'oferta_estado_{oferta.estado}'}

    if solicitud.estado != 'esperando_creditos_proveedor':
        return {'ok': False, 'reason': f'solicitud_estado_{solicitud.estado}'}

    detalles_servicios = list(oferta.detalles_servicios.all())
    if not detalles_servicios:
        return {'ok': False, 'reason': 'sin_detalles_servicios'}

    try:
        from mecanimovilapp.apps.suscripciones.creditos_services import (
            puede_adjudicar as puede_adjudicar_creditos,
            validar_creditos_suficientes,
        )

        puede_ag, _msg_ag = puede_adjudicar_creditos(oferta.proveedor)
        if not puede_ag:
            return {'ok': False, 'reason': 'anti_gaming'}

        servicio_principal = detalles_servicios[0].servicio
        puede, _mensaje, _cn = validar_creditos_suficientes(oferta.proveedor, servicio_principal)
        if not puede:
            return {'ok': False, 'reason': 'insufficient_credits'}
    except ImportError:
        logger.warning("Módulo créditos no disponible en completar_adjudicacion_si_listo")
        return {'ok': False, 'reason': 'creditos_module_missing'}

    if oferta.tipo_proveedor == 'taller':
        if not hasattr(oferta.proveedor, 'taller') or not oferta.proveedor.taller:
            return {'ok': False, 'reason': 'sin_taller'}
        taller = oferta.proveedor.taller
        mecanico = None
    else:
        if not hasattr(oferta.proveedor, 'mecanico_domicilio') or not oferta.proveedor.mecanico_domicilio:
            return {'ok': False, 'reason': 'sin_mecanico'}
        mecanico = oferta.proveedor.mecanico_domicilio
        taller = None

    try:
        carrito_id = ejecutar_finalizacion_adjudicacion(
            solicitud, oferta, taller, mecanico, detalles_servicios
        )
    except AdjudicacionCarritoError as e:
        logger.error(f"AdjudicacionCarritoError completando oferta {oferta_id}: {e}")
        raise

    return {'ok': True, 'reason': 'completed', 'carrito_id': carrito_id}


def reintentar_adjudicaciones_pendientes_tras_acreditacion(proveedor):
    """
    Tras acreditar saldo (compra MP, suscripción, admin), intenta cerrar ofertas pendiente_creditos.
    """
    ids = OfertaProveedor.objects.filter(
        proveedor=proveedor,
        estado='pendiente_creditos',
    ).values_list('id', flat=True)
    resultados = []
    for oid in ids:
        try:
            resultados.append((str(oid), completar_adjudicacion_si_listo(oid)))
        except Exception as e:
            logger.error(f"Error completando adjudicación oferta {oid}: {e}", exc_info=True)
            resultados.append((str(oid), {'ok': False, 'reason': str(e)}))
    return resultados
