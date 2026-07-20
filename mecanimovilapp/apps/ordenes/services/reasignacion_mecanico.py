"""
Reasignación manual de mecánico en órdenes marketplace y citas personales.
"""
from __future__ import annotations

import logging

from django.core.exceptions import ValidationError

from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, OfertaProveedor, SolicitudServicio
from mecanimovilapp.apps.ordenes.services.asignacion_mecanico import (
    _categorias_de_solicitud,
    _duracion_solicitud_minutos,
    _miembro_libre_en_slot,
    _modalidad_desde_tipo_servicio,
    asignar_mecanico_a_solicitud,
)
from mecanimovilapp.apps.ordenes.services.cita_agenda_personal import (
    _categorias_de_oferta,
    resolver_miembro_cita_personal,
)
from mecanimovilapp.apps.usuarios.models import MiembroTaller

logger = logging.getLogger(__name__)

DURACION_DEFAULT_MINUTOS = 60


def reasignar_mecanico_solicitud(
    solicitud: SolicitudServicio,
    miembro_id: int | None,
    *,
    user=None,
) -> MiembroTaller | None:
    """
    Asigna o reasigna el técnico de una SolicitudServicio.
    Si miembro_id es None, usa asignación automática.
    """
    if miembro_id is None:
        solicitud.mecanico_asignado = None
        solicitud.save(update_fields=['mecanico_asignado'])
        return asignar_mecanico_a_solicitud(solicitud)

    taller = getattr(solicitud, 'taller', None)
    if taller is None:
        raise ValidationError('La orden no pertenece a un taller.')

    try:
        miembro = MiembroTaller.objects.get(
            id=miembro_id,
            taller=taller,
            rol='mecanico',
            activo=True,
        )
    except MiembroTaller.DoesNotExist as exc:
        raise ValidationError('Mecánico no encontrado o inactivo.') from exc

    duracion = _duracion_solicitud_minutos(solicitud, DURACION_DEFAULT_MINUTOS)
    categorias = _categorias_de_solicitud(solicitud)
    modalidad = _modalidad_desde_tipo_servicio(getattr(solicitud, 'tipo_servicio', None))

    from mecanimovilapp.apps.usuarios.services.disponibilidad_proveedor import mecanicos_aptos_taller

    aptos = mecanicos_aptos_taller(
        taller,
        categorias_requeridas=categorias,
        modalidad=modalidad,
    )
    if not any(m.id == miembro.id for m in aptos):
        raise ValidationError('El mecánico no cumple especialidad o modalidad para este servicio.')

    if solicitud.fecha_servicio and solicitud.hora_servicio:
        if not _miembro_libre_en_slot(
            miembro=miembro,
            taller=taller,
            fecha=solicitud.fecha_servicio,
            hora=solicitud.hora_servicio,
            duracion_minutos=duracion,
        ):
            raise ValidationError('El mecánico no está disponible en ese horario.')

    solicitud.mecanico_asignado = miembro
    solicitud.save(update_fields=['mecanico_asignado'])

    oferta = getattr(solicitud, 'oferta_proveedor', None)
    if oferta is not None:
        oferta.miembro_taller_asignado = miembro
        oferta.save(update_fields=['miembro_taller_asignado'])

    try:
        from mecanimovilapp.apps.ordenes.services.notificaciones_proveedor import (
            notificar_orden_asignada_mecanico,
        )
        notificar_orden_asignada_mecanico(solicitud, miembro)
    except Exception:
        logger.exception('Error notificando reasignación solicitud=%s', solicitud.id)

    return miembro


def reasignar_mecanico_cita_personal(
    cita: CitaAgendaPersonal,
    miembro_id: int | None,
) -> MiembroTaller | None:
    """Asigna o reasigna el técnico de una cita personal."""
    if cita.estado != 'activa':
        raise ValidationError('Solo se puede reasignar en citas activas.')

    det = getattr(cita, 'detalle', None)
    oferta = getattr(det, 'oferta_servicio', None) if det else None
    categorias = _categorias_de_oferta(oferta)

    miembro = resolver_miembro_cita_personal(
        taller=cita.taller,
        miembro_id=miembro_id,
        tipo_servicio=cita.tipo_servicio,
        fecha=cita.fecha_servicio,
        hora=cita.hora_servicio,
        duracion_minutos=cita.duracion_minutos or DURACION_DEFAULT_MINUTOS,
        categorias_requeridas=categorias,
        excluir_cita_id=cita.id,
    )

    cita.miembro_taller = miembro
    cita.save(update_fields=['miembro_taller', 'fecha_actualizacion'])

    if miembro is not None:
        try:
            from mecanimovilapp.apps.ordenes.services.notificaciones_proveedor import (
                notificar_cita_asignada_mecanico,
            )
            notificar_cita_asignada_mecanico(cita, miembro)
        except Exception:
            logger.exception('Error notificando reasignación cita=%s', cita.id)

    return miembro


def reasignar_mecanico_oferta(
    oferta: OfertaProveedor,
    miembro_id: int | None,
) -> MiembroTaller | None:
    """Asigna técnico preferido en la oferta y en la SolicitudServicio si existe."""
    solicitud_servicio = (
        SolicitudServicio.objects
        .filter(oferta_proveedor=oferta)
        .order_by('-id')
        .first()
    )
    if solicitud_servicio is not None:
        return reasignar_mecanico_solicitud(solicitud_servicio, miembro_id)

    if miembro_id is None:
        oferta.miembro_taller_asignado = None
        oferta.save(update_fields=['miembro_taller_asignado'])
        return None

    taller = getattr(oferta, 'taller', None)
    if taller is None and hasattr(oferta, 'proveedor') and hasattr(oferta.proveedor, 'taller'):
        taller = oferta.proveedor.taller

    try:
        miembro = MiembroTaller.objects.get(
            id=miembro_id,
            taller=taller,
            rol='mecanico',
            activo=True,
        )
    except MiembroTaller.DoesNotExist as exc:
        raise ValidationError('Mecánico no encontrado o inactivo.') from exc

    oferta.miembro_taller_asignado = miembro
    oferta.es_cambio_tecnico = True
    oferta.save(update_fields=['miembro_taller_asignado', 'es_cambio_tecnico'])
    return miembro
