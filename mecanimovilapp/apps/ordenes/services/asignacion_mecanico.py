"""
Asignación automática de un mecánico (MiembroTaller) a una SolicitudServicio de taller.

Selecciona un mecánico activo y apto (especialidad + modalidad) que esté libre en el
slot solicitado, balanceando la carga del equipo. No afecta el consumo de créditos
(que sigue siendo a nivel del usuario mandante del taller).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from mecanimovilapp.apps.usuarios.models import MiembroTaller, Taller
from mecanimovilapp.apps.usuarios.services.disponibilidad_proveedor import (
    DURACION_DEFAULT_MINUTOS,
    _duracion_solicitud_minutos,
    _horario_config_miembro,
    _intervalos_ocupados_miembro,
    _time_to_minutes,
    mecanicos_aptos_taller,
)

logger = logging.getLogger(__name__)


def _modalidad_desde_tipo_servicio(tipo_servicio: str | None) -> str | None:
    """Mapea tipo_servicio de la orden a la modalidad del técnico."""
    if tipo_servicio == 'domicilio':
        return 'a_domicilio'
    if tipo_servicio == 'taller':
        return 'en_taller'
    return None


def _categorias_de_solicitud(solicitud) -> list[int]:
    """Especialidades requeridas según las ofertas de la solicitud."""
    categorias: set[int] = set()
    for linea in solicitud.lineas.select_related('oferta_servicio__servicio').all():
        oferta = linea.oferta_servicio
        servicio = getattr(oferta, 'servicio', None) if oferta else None
        if servicio is not None:
            categorias.update(servicio.categorias.values_list('id', flat=True))
    oferta_prov = getattr(solicitud, 'oferta_proveedor', None)
    if oferta_prov is not None:
        oferta_cat = getattr(oferta_prov, 'oferta_servicio', None)
        servicio = getattr(oferta_cat, 'servicio', None) if oferta_cat else None
        if servicio is not None:
            categorias.update(servicio.categorias.values_list('id', flat=True))
    return list(categorias)


def _miembro_libre_en_slot(
    *,
    miembro: MiembroTaller,
    taller: Taller,
    fecha: date,
    hora: time,
    duracion_minutos: int,
    excluir_cita_personal_id: int | None = None,
) -> bool:
    """True si el mecánico atiende ese día y no tiene solapamiento en el slot."""
    horario = _horario_config_miembro(miembro, taller, fecha.weekday())
    if horario is None:
        return False

    inicio = datetime.combine(fecha, hora)
    fin = inicio + timedelta(minutes=duracion_minutos)

    # Dentro de la jornada del mecánico.
    h_ini = _time_to_minutes(horario.hora_inicio)
    h_fin = _time_to_minutes(horario.hora_fin)
    slot_ini = _time_to_minutes(hora)
    slot_fin = slot_ini + duracion_minutos if slot_ini is not None else None
    if None in (h_ini, h_fin, slot_ini, slot_fin):
        return False
    if slot_ini < h_ini or slot_fin > h_fin:
        return False

    ocupados = _intervalos_ocupados_miembro(
        miembro=miembro,
        fecha=fecha,
        tiempo_descanso=horario.tiempo_descanso,
        duracion_fallback=duracion_minutos,
        excluir_cita_personal_id=excluir_cita_personal_id,
    )
    for occ_ini, occ_fin in ocupados:
        if inicio < occ_fin and occ_ini < fin:
            return False
    return True


def _carga_mecanico(miembro: MiembroTaller, fecha: date) -> int:
    """Número de órdenes asignadas al mecánico en la semana de `fecha` (balanceo)."""
    inicio_semana = fecha - timedelta(days=fecha.weekday())
    fin_semana = inicio_semana + timedelta(days=6)
    return miembro.solicitudes_asignadas.filter(
        fecha_servicio__gte=inicio_semana,
        fecha_servicio__lte=fin_semana,
    ).count()


def seleccionar_mecanico(
    *,
    taller: Taller,
    fecha: date,
    hora: time,
    duracion_minutos: int = DURACION_DEFAULT_MINUTOS,
    categorias_requeridas: list[int] | None = None,
    modalidad: str | None = None,
    excluir_cita_personal_id: int | None = None,
) -> MiembroTaller | None:
    """
    Devuelve el mejor mecánico apto, libre en el slot y con menor carga; o None.
    """
    aptos = mecanicos_aptos_taller(
        taller,
        categorias_requeridas=categorias_requeridas,
        modalidad=modalidad,
    )
    libres = [
        m for m in aptos
        if _miembro_libre_en_slot(
            miembro=m, taller=taller, fecha=fecha, hora=hora,
            duracion_minutos=duracion_minutos,
            excluir_cita_personal_id=excluir_cita_personal_id,
        )
    ]
    if not libres:
        return None
    # Desempate por balanceo de carga (menos órdenes en la semana).
    libres.sort(key=lambda m: (_carga_mecanico(m, fecha), m.id))
    return libres[0]


def asignar_mecanico_a_solicitud(solicitud, *, guardar: bool = True) -> MiembroTaller | None:
    """
    Asigna automáticamente un mecánico a una SolicitudServicio de taller.

    No-op seguro si la orden no es de un taller, si el taller no tiene equipo, o si no
    hay técnico disponible (en cuyo caso queda `mecanico_asignado=None` para reasignación
    manual del supervisor). Nunca lanza: la creación de la orden no debe fallar por esto.
    """
    try:
        taller = getattr(solicitud, 'taller', None)
        if taller is None:
            return None
        if not solicitud.fecha_servicio or not solicitud.hora_servicio:
            return None

        anterior_asignado_id = getattr(solicitud, 'mecanico_asignado_id', None)

        def _notificar_si_asignado(miembro_asignado: MiembroTaller | None) -> None:
            if (
                miembro_asignado is None
                or not guardar
                or miembro_asignado.id == anterior_asignado_id
            ):
                return
            try:
                from mecanimovilapp.apps.ordenes.services.notificaciones_proveedor import (
                    notificar_orden_asignada_mecanico,
                )
                notificar_orden_asignada_mecanico(solicitud, miembro_asignado)
            except Exception:
                logger.exception(
                    'Error notificando asignación mecánico solicitud=%s',
                    getattr(solicitud, 'id', None),
                )

        # Si el taller no tiene mecánicos activos, no se asigna (fallback a nivel taller).
        if not MiembroTaller.objects.filter(
            taller=taller, rol='mecanico', activo=True
        ).exists():
            return None

        duracion = _duracion_solicitud_minutos(solicitud, DURACION_DEFAULT_MINUTOS)
        categorias = _categorias_de_solicitud(solicitud)
        modalidad = _modalidad_desde_tipo_servicio(getattr(solicitud, 'tipo_servicio', None))

        miembro_pref = None
        oferta = getattr(solicitud, 'oferta_proveedor', None)
        if oferta is not None:
            if oferta.miembro_taller_asignado_id:
                miembro_pref = oferta.miembro_taller_asignado
            elif oferta.solicitud.miembro_taller_preferido_id:
                miembro_pref = oferta.solicitud.miembro_taller_preferido

        if miembro_pref is not None:
            aptos = mecanicos_aptos_taller(
                taller,
                categorias_requeridas=categorias,
                modalidad=modalidad,
            )
            if any(m.id == miembro_pref.id for m in aptos) and _miembro_libre_en_slot(
                miembro=miembro_pref,
                taller=taller,
                fecha=solicitud.fecha_servicio,
                hora=solicitud.hora_servicio,
                duracion_minutos=duracion,
            ):
                if guardar:
                    solicitud.mecanico_asignado = miembro_pref
                    solicitud.save(update_fields=['mecanico_asignado'])
                else:
                    solicitud.mecanico_asignado = miembro_pref
                _notificar_si_asignado(miembro_pref)
                return miembro_pref

        miembro = seleccionar_mecanico(
            taller=taller,
            fecha=solicitud.fecha_servicio,
            hora=solicitud.hora_servicio,
            duracion_minutos=duracion,
            categorias_requeridas=categorias,
            modalidad=modalidad,
        )

        if miembro is not None and guardar:
            solicitud.mecanico_asignado = miembro
            solicitud.save(update_fields=['mecanico_asignado'])
        elif miembro is not None:
            solicitud.mecanico_asignado = miembro

        if miembro is None:
            logger.info(
                'Sin mecánico disponible para solicitud=%s taller=%s fecha=%s hora=%s; queda sin asignar',
                getattr(solicitud, 'id', None), taller.id,
                solicitud.fecha_servicio, solicitud.hora_servicio,
            )
        else:
            _notificar_si_asignado(miembro)
        return miembro
    except Exception:
        logger.exception(
            'Error asignando mecánico a solicitud=%s (no bloquea la creación)',
            getattr(solicitud, 'id', None),
        )
        return None
