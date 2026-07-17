"""
Cálculo de ventanas libres y slots según duración del servicio solicitado
y citas ya agendadas del proveedor.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Any

from django.utils import timezone

logger = logging.getLogger(__name__)

from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, SolicitudServicio
from mecanimovilapp.apps.servicios.models import OfertaServicio
from mecanimovilapp.apps.usuarios.models import (
    HorarioProveedor,
    MecanicoDomicilio,
    MiembroTaller,
    Taller,
)

ESTADOS_OCUPAN_AGENDA = (
    'pendiente',
    'confirmado',
    'en_proceso',
    'aceptada_por_proveedor',
)

ESTADOS_CITA_PERSONAL_OCUPAN = ('activa',)

PASO_SLOT_MINUTOS = 15
DURACION_DEFAULT_MINUTOS = 60


def _time_to_minutes(t: time | None) -> int | None:
    if t is None:
        return None
    if isinstance(t, timedelta):
        total = int(t.total_seconds())
        if total <= 0:
            return None
        return total // 60
    if not isinstance(t, time):
        return None
    return t.hour * 60 + t.minute


def _minutos_ventana_jornada(hora_inicio: time, hora_fin: time) -> int:
    ini = _time_to_minutes(hora_inicio)
    fin = _time_to_minutes(hora_fin)
    if ini is None or fin is None or fin <= ini:
        return 0
    return fin - ini


def duracion_rango_oferta(oferta: OfertaServicio | None) -> tuple[int, int]:
    """Retorna (minutos_min, minutos_max) para bloqueo de agenda y etiqueta UI."""
    if oferta is None:
        return DURACION_DEFAULT_MINUTOS, DURACION_DEFAULT_MINUTOS

    max_m = oferta.duracion_maxima_minutos
    min_m = oferta.duracion_minima_minutos
    if max_m:
        min_m = min_m or max_m
        return int(min_m), int(max_m)

    legacy = _time_to_minutes(oferta.duracion_estimada)
    if legacy and legacy > 0:
        return legacy, legacy

    base = _time_to_minutes(getattr(oferta.servicio, 'duracion_estimada_base', None))
    if base and base > 0:
        return base, base

    return DURACION_DEFAULT_MINUTOS, DURACION_DEFAULT_MINUTOS


def etiqueta_duracion(min_m: int, max_m: int) -> str:
    def fmt(m: int) -> str:
        if m < 60:
            return f'{m} min'
        h, r = divmod(m, 60)
        return f'{h}h' if r == 0 else f'{h}h {r}min'

    if min_m == max_m:
        return fmt(min_m)
    return f'{fmt(min_m)} – {fmt(max_m)}'


def _duracion_solicitud_minutos(solicitud: SolicitudServicio, fallback: int) -> int:
    """Duración máxima en minutos para una cita existente."""
    max_dur = fallback
    for linea in solicitud.lineas.select_related('oferta_servicio').all():
        _, mx = duracion_rango_oferta(linea.oferta_servicio)
        max_dur = max(max_dur, mx)
    if solicitud.oferta_proveedor_id and solicitud.oferta_proveedor:
        oferta_cat = getattr(solicitud.oferta_proveedor, 'oferta_servicio', None)
        if oferta_cat:
            _, mx = duracion_rango_oferta(oferta_cat)
            max_dur = max(max_dur, mx)
    return max_dur


def _merge_intervals(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    if not intervals:
        return []
    sorted_iv = sorted(intervals, key=lambda x: x[0])
    merged = [sorted_iv[0]]
    for start, end in sorted_iv[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _intervalos_citas_personales_dia(
    *,
    taller: Taller | None = None,
    mecanico: MecanicoDomicilio | None = None,
    fecha: date,
    tiempo_descanso: int = 0,
    excluir_cita_personal_id: int | None = None,
) -> list[tuple[datetime, datetime]]:
    filtros = {
        'fecha_servicio': fecha,
        'estado__in': ESTADOS_CITA_PERSONAL_OCUPAN,
    }
    if taller:
        filtros['taller'] = taller
    else:
        filtros['mecanico'] = mecanico

    qs = CitaAgendaPersonal.objects.filter(**filtros)
    if excluir_cita_personal_id:
        qs = qs.exclude(pk=excluir_cita_personal_id)

    intervalos: list[tuple[datetime, datetime]] = []
    for cita in qs:
        inicio = datetime.combine(fecha, cita.hora_servicio)
        fin = inicio + timedelta(minutes=cita.duracion_minutos + tiempo_descanso)
        intervalos.append((inicio, fin))
    return intervalos


def intervalos_ocupados_dia(
    *,
    taller: Taller | None = None,
    mecanico: MecanicoDomicilio | None = None,
    fecha: date,
    tiempo_descanso: int = 0,
    duracion_fallback: int = DURACION_DEFAULT_MINUTOS,
    excluir_cita_personal_id: int | None = None,
) -> list[tuple[datetime, datetime]]:
    filtros = {
        'fecha_servicio': fecha,
        'estado__in': ESTADOS_OCUPAN_AGENDA,
    }
    if taller:
        filtros['taller'] = taller
    else:
        filtros['mecanico'] = mecanico

    solicitudes = (
        SolicitudServicio.objects.filter(**filtros)
        .prefetch_related('lineas__oferta_servicio', 'oferta_proveedor__oferta_servicio')
    )

    intervalos: list[tuple[datetime, datetime]] = []
    for sol in solicitudes:
        if not sol.hora_servicio:
            continue
        inicio = datetime.combine(fecha, sol.hora_servicio)
        dur = _duracion_solicitud_minutos(sol, duracion_fallback)
        fin = inicio + timedelta(minutes=dur + tiempo_descanso)
        intervalos.append((inicio, fin))

    intervalos_citas = _intervalos_citas_personales_dia(
        taller=taller,
        mecanico=mecanico,
        fecha=fecha,
        tiempo_descanso=tiempo_descanso,
        excluir_cita_personal_id=excluir_cita_personal_id,
    )

    return _merge_intervals(intervalos + intervalos_citas)


# ---------------------------------------------------------------------------
# Disponibilidad por mecánico (equipo de taller)
# ---------------------------------------------------------------------------

def _categorias_requeridas(oferta: OfertaServicio | None) -> list[int]:
    """IDs de CategoriaServicio del servicio ofertado (especialidad requerida)."""
    if oferta is None:
        return []
    servicio = getattr(oferta, 'servicio', None)
    if servicio is None:
        return []
    return list(servicio.categorias.values_list('id', flat=True))


def mecanicos_aptos_taller(
    taller: Taller,
    *,
    categorias_requeridas: list[int] | None = None,
    modalidad: str | None = None,
) -> list[MiembroTaller]:
    """
    Mecánicos activos del taller que cubren la especialidad requerida y la modalidad.
    Un taller sin mecánicos activos retorna lista vacía (el caller hace fallback).
    """
    qs = (
        MiembroTaller.objects
        .filter(taller=taller, rol='mecanico', activo=True)
        .prefetch_related('especialidades')
    )
    aptos: list[MiembroTaller] = []
    for miembro in qs:
        if categorias_requeridas and not miembro.especialidades.filter(
            id__in=categorias_requeridas
        ).exists():
            continue
        if modalidad and not miembro.modalidad_compatible(modalidad):
            continue
        aptos.append(miembro)
    return aptos


def _horario_config_miembro(
    miembro: MiembroTaller,
    taller: Taller,
    dia_semana: int,
) -> HorarioProveedor | None:
    """
    Horario del mecánico para el día.

    Si el mecánico tiene configuración propia para ese día (activa o inactiva),
    se respeta tal cual: un día inactivo NO hereda el horario general del taller.
    Solo hereda el taller cuando el mecánico no tiene ningún registro para ese día.
    """
    propio = (
        HorarioProveedor.objects
        .filter(miembro_taller=miembro, dia_semana=dia_semana)
        .order_by('id')
        .first()
    )
    if propio is not None:
        return propio if propio.activo else None
    return (
        HorarioProveedor.objects
        .filter(taller=taller, miembro_taller__isnull=True, dia_semana=dia_semana, activo=True)
        .order_by('id')
        .first()
    )


def _intervalos_ocupados_miembro(
    *,
    miembro: MiembroTaller,
    fecha: date,
    tiempo_descanso: int = 0,
    duracion_fallback: int = DURACION_DEFAULT_MINUTOS,
    excluir_cita_personal_id: int | None = None,
) -> list[tuple[datetime, datetime]]:
    """Intervalos ocupados de un mecánico: sus órdenes asignadas + sus citas personales."""
    solicitudes = (
        SolicitudServicio.objects
        .filter(
            mecanico_asignado=miembro,
            fecha_servicio=fecha,
            estado__in=ESTADOS_OCUPAN_AGENDA,
        )
        .prefetch_related('lineas__oferta_servicio', 'oferta_proveedor__oferta_servicio')
    )

    intervalos: list[tuple[datetime, datetime]] = []
    for sol in solicitudes:
        if not sol.hora_servicio:
            continue
        inicio = datetime.combine(fecha, sol.hora_servicio)
        dur = _duracion_solicitud_minutos(sol, duracion_fallback)
        fin = inicio + timedelta(minutes=dur + tiempo_descanso)
        intervalos.append((inicio, fin))

    citas = CitaAgendaPersonal.objects.filter(
        miembro_taller=miembro,
        fecha_servicio=fecha,
        estado__in=ESTADOS_CITA_PERSONAL_OCUPAN,
    )
    if excluir_cita_personal_id:
        citas = citas.exclude(pk=excluir_cita_personal_id)
    for cita in citas:
        inicio = datetime.combine(fecha, cita.hora_servicio)
        fin = inicio + timedelta(minutes=cita.duracion_minutos + tiempo_descanso)
        intervalos.append((inicio, fin))

    return _merge_intervals(intervalos)


def _slots_libres_miembro(
    *,
    miembro: MiembroTaller,
    taller: Taller,
    fecha: date,
    dia_semana: int,
    max_dur: int,
) -> list[dict[str, Any]]:
    """Genera los slots donde el mecánico está libre en el día (vacío si no atiende)."""
    horario = _horario_config_miembro(miembro, taller, dia_semana)
    if horario is None:
        return []
    ocupados = _intervalos_ocupados_miembro(
        miembro=miembro,
        fecha=fecha,
        tiempo_descanso=horario.tiempo_descanso,
        duracion_fallback=max_dur,
    )
    libres = ventanas_libres(horario.hora_inicio, horario.hora_fin, fecha, ocupados)
    ventana_jornada = _minutos_ventana_jornada(horario.hora_inicio, horario.hora_fin)
    duracion_slot = int(max_dur)
    if ventana_jornada > 0:
        duracion_slot = min(duracion_slot, ventana_jornada)
    return slots_en_ventanas(libres, duracion_slot)


def ventanas_libres(
    hora_inicio: time,
    hora_fin: time,
    fecha: date,
    intervalos_ocupados: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """Intervalos libres dentro del horario laboral del día."""
    dia_inicio = datetime.combine(fecha, hora_inicio)
    dia_fin = datetime.combine(fecha, hora_fin)
    libres: list[tuple[datetime, datetime]] = []
    cursor = dia_inicio

    for occ_start, occ_end in intervalos_ocupados:
        if occ_start > cursor and occ_start < dia_fin:
            libres.append((cursor, min(occ_start, dia_fin)))
        cursor = max(cursor, occ_end)

    if cursor < dia_fin:
        libres.append((cursor, dia_fin))
    return [(a, b) for a, b in libres if b > a]


def slots_en_ventanas(
    ventanas: list[tuple[datetime, datetime]],
    duracion_max_minutos: int,
    paso_minutos: int = PASO_SLOT_MINUTOS,
) -> list[dict[str, Any]]:
    """Genera horarios de inicio donde cabe el servicio (usa duración máxima)."""
    slots: list[dict[str, Any]] = []
    delta = timedelta(minutes=duracion_max_minutos)
    paso = timedelta(minutes=paso_minutos)

    for ventana_inicio, ventana_fin in ventanas:
        hora_actual = ventana_inicio
        while hora_actual + delta <= ventana_fin:
            hora_fin_slot = hora_actual + delta
            slots.append({
                'hora': hora_actual.time().strftime('%H:%M'),
                'hora_fin_estimada': hora_fin_slot.time().strftime('%H:%M'),
                'hora_inicio_24h': hora_actual.time(),
                'hora_fin_24h': hora_fin_slot.time(),
                'disponible': True,
            })
            hora_actual += paso

    return slots


def _slots_json_safe(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Quita objetos time no serializables; la API solo expone hora en string."""
    safe: list[dict[str, Any]] = []
    for slot in slots:
        safe.append({
            'hora': slot.get('hora'),
            'hora_fin_estimada': slot.get('hora_fin_estimada'),
            'disponible': slot.get('disponible', True),
        })
    return safe


def estado_actual_proveedor(
    *,
    taller: Taller | None = None,
    mecanico: MecanicoDomicilio | None = None,
    duracion_fallback: int = DURACION_DEFAULT_MINUTOS,
) -> dict[str, Any]:
    """Si hay un servicio en curso hoy, estima cuándo queda libre."""
    hoy = timezone.localdate()
    ahora = timezone.localtime().replace(tzinfo=None)

    filtros = {
        'fecha_servicio': hoy,
        'estado__in': ('en_proceso', 'confirmado', 'aceptada_por_proveedor'),
    }
    if taller:
        filtros['taller'] = taller
    else:
        filtros['mecanico'] = mecanico

    en_curso = (
        SolicitudServicio.objects.filter(**filtros)
        .prefetch_related('lineas__oferta_servicio')
        .order_by('hora_servicio')
    )

    for sol in en_curso:
        if not sol.hora_servicio:
            continue
        inicio = datetime.combine(hoy, sol.hora_servicio)
        dur = _duracion_solicitud_minutos(sol, duracion_fallback)
        fin_estimado = inicio + timedelta(minutes=dur)
        if inicio <= ahora < fin_estimado:
            minutos_restantes = max(0, int((fin_estimado - ahora).total_seconds() // 60))
            nombre_servicio = 'Servicio'
            linea = sol.lineas.select_related('oferta_servicio__servicio').first()
            if linea and linea.oferta_servicio:
                servicio = getattr(linea.oferta_servicio, 'servicio', None)
                if servicio is not None:
                    nombre_servicio = servicio.nombre
            return {
                'ocupado': True,
                'servicio_en_curso': nombre_servicio,
                'hora_estimada_libre': fin_estimado.time().strftime('%H:%M'),
                'minutos_restantes': minutos_restantes,
            }

    return {
        'ocupado': False,
        'servicio_en_curso': None,
        'hora_estimada_libre': None,
        'minutos_restantes': 0,
    }


def _servicio_meta_from_oferta(oferta: OfertaServicio | None) -> dict[str, Any]:
    servicio = getattr(oferta, 'servicio', None) if oferta else None
    return {
        'servicio_id': getattr(servicio, 'id', None) if servicio else None,
        'servicio_nombre': (getattr(servicio, 'nombre', None) or None) if servicio else None,
    }


def _with_servicio_meta(payload: dict[str, Any], oferta: OfertaServicio | None) -> dict[str, Any]:
    payload.update(_servicio_meta_from_oferta(oferta))
    return payload


def _disponibilidad_union_equipo(
    *,
    taller: Taller,
    fecha: date,
    dia_semana: int,
    oferta: OfertaServicio | None,
    aptos: list[MiembroTaller],
) -> dict[str, Any]:
    """
    Disponibilidad pública del taller = UNIÓN de los slots libres de cada mecánico apto.
    Un slot se ofrece si al menos un mecánico apto cabe el servicio completo en ese inicio.
    """
    min_dur, max_dur = duracion_rango_oferta(oferta)

    estado_actual = estado_actual_proveedor(taller=taller, duracion_fallback=max_dur)

    if not aptos:
        return _with_servicio_meta({
            'fecha': fecha.isoformat(),
            'proveedor_disponible': False,
            'mensaje': 'No hay mecánicos disponibles para este servicio',
            'duracion_servicio_solicitado': {
                'minimo': min_dur,
                'maximo': max_dur,
                'etiqueta': etiqueta_duracion(min_dur, max_dur),
            },
            'estado_actual': estado_actual,
            'slots_disponibles': [],
            'total_slots': 0,
        }, oferta)

    # Unión de slots por hora de inicio (dedupe). Un mecánico aporta solo si cabe el servicio.
    slots_por_hora: dict[str, dict[str, Any]] = {}
    for miembro in aptos:
        for slot in _slots_libres_miembro(
            miembro=miembro,
            taller=taller,
            fecha=fecha,
            dia_semana=dia_semana,
            max_dur=max_dur,
        ):
            slots_por_hora[slot['hora']] = slot

    slots = sorted(slots_por_hora.values(), key=lambda s: s['hora_inicio_24h'])

    if fecha == timezone.localdate():
        ahora_t = timezone.localtime().time()
        slots = [s for s in slots if s['hora_inicio_24h'] > ahora_t]

    if not slots:
        return _with_servicio_meta({
            'fecha': fecha.isoformat(),
            'proveedor_disponible': False,
            'mensaje': 'El proveedor no atiende este día',
            'duracion_servicio_solicitado': {
                'minimo': min_dur,
                'maximo': max_dur,
                'etiqueta': etiqueta_duracion(min_dur, max_dur),
            },
            'estado_actual': estado_actual,
            'slots_disponibles': [],
            'total_slots': 0,
        }, oferta)

    slots_safe = _slots_json_safe(slots)
    return _with_servicio_meta({
        'fecha': fecha.isoformat(),
        'proveedor_disponible': True,
        'duracion_servicio_solicitado': {
            'minimo': min_dur,
            'maximo': max_dur,
            'etiqueta': etiqueta_duracion(min_dur, max_dur),
        },
        'estado_actual': estado_actual,
        'slots_disponibles': slots_safe,
        'total_slots': len(slots_safe),
    }, oferta)


def disponibilidad_con_duracion(
    *,
    taller: Taller | None = None,
    mecanico: MecanicoDomicilio | None = None,
    fecha: date,
    oferta_servicio_id: int | None = None,
    modalidad: str | None = None,
    miembro_taller_id: int | None = None,
    requiere_especialidad: bool = True,
) -> dict[str, Any]:
    dia_semana = fecha.weekday()

    # Resolver oferta (para duración y especialidad requerida) — común a ambos caminos.
    oferta = None
    if oferta_servicio_id:
        oferta_qs = OfertaServicio.objects.filter(pk=oferta_servicio_id).select_related('servicio')
        if taller:
            oferta_qs = oferta_qs.filter(taller=taller)
        elif mecanico:
            oferta_qs = oferta_qs.filter(mecanico=mecanico)
        oferta = oferta_qs.first()
        if oferta is None:
            logger.warning(
                'oferta_servicio_id=%s no pertenece al proveedor taller=%s mecanico=%s',
                oferta_servicio_id,
                getattr(taller, 'id', None),
                getattr(mecanico, 'id', None),
            )

    # Camino equipo de taller: disponibilidad = UNIÓN por mecánico apto (o uno solo si miembro_taller_id).
    if taller is not None:
        categorias_req = _categorias_requeridas(oferta) if requiere_especialidad else []
        aptos = mecanicos_aptos_taller(
            taller,
            categorias_requeridas=categorias_req,
            modalidad=modalidad,
        )
        if miembro_taller_id:
            miembro = MiembroTaller.objects.filter(
                pk=miembro_taller_id,
                taller=taller,
                rol='mecanico',
                activo=True,
            ).first()
            if not miembro:
                min_dur, max_dur = duracion_rango_oferta(oferta)
                return _with_servicio_meta({
                    'fecha': fecha.isoformat(),
                    'proveedor_disponible': False,
                    'mensaje': 'El técnico seleccionado no pertenece a este taller',
                    'duracion_servicio_solicitado': {
                        'minimo': min_dur,
                        'maximo': max_dur,
                        'etiqueta': etiqueta_duracion(min_dur, max_dur),
                    },
                    'estado_actual': estado_actual_proveedor(taller=taller),
                    'slots_disponibles': [],
                    'total_slots': 0,
                }, oferta)
            if modalidad and not miembro.modalidad_compatible(modalidad):
                min_dur, max_dur = duracion_rango_oferta(oferta)
                return _with_servicio_meta({
                    'fecha': fecha.isoformat(),
                    'proveedor_disponible': False,
                    'mensaje': 'El técnico seleccionado no atiende este tipo de servicio',
                    'duracion_servicio_solicitado': {
                        'minimo': min_dur,
                        'maximo': max_dur,
                        'etiqueta': etiqueta_duracion(min_dur, max_dur),
                    },
                    'estado_actual': estado_actual_proveedor(taller=taller),
                    'slots_disponibles': [],
                    'total_slots': 0,
                }, oferta)
            return _disponibilidad_union_equipo(
                taller=taller,
                fecha=fecha,
                dia_semana=dia_semana,
                oferta=oferta,
                aptos=[miembro],
            )
        tiene_equipo = MiembroTaller.objects.filter(
            taller=taller, rol='mecanico', activo=True
        ).exists()
        if tiene_equipo:
            return _disponibilidad_union_equipo(
                taller=taller,
                fecha=fecha,
                dia_semana=dia_semana,
                oferta=oferta,
                aptos=aptos,
            )

    horario_qs = HorarioProveedor.objects.filter(dia_semana=dia_semana, activo=True)
    if taller:
        horario_qs = horario_qs.filter(taller=taller, miembro_taller__isnull=True)
    else:
        horario_qs = horario_qs.filter(mecanico=mecanico)

    horario_config = horario_qs.order_by('id').first()
    if horario_config is None:
        return _with_servicio_meta({
            'fecha': fecha.isoformat(),
            'proveedor_disponible': False,
            'mensaje': 'El proveedor no atiende este día',
            'slots_disponibles': [],
            'estado_actual': estado_actual_proveedor(
                taller=taller, mecanico=mecanico,
            ),
        }, oferta)
    if horario_qs.count() > 1:
        logger.warning(
            'HorarioProveedor duplicado activo: taller=%s mecanico=%s dia=%s',
            getattr(taller, 'id', None),
            getattr(mecanico, 'id', None),
            dia_semana,
        )

    min_dur, max_dur = duracion_rango_oferta(oferta)
    ocupados = intervalos_ocupados_dia(
        taller=taller,
        mecanico=mecanico,
        fecha=fecha,
        tiempo_descanso=horario_config.tiempo_descanso,
        duracion_fallback=max_dur,
    )
    libres = ventanas_libres(
        horario_config.hora_inicio,
        horario_config.hora_fin,
        fecha,
        ocupados,
    )
    ventana_jornada = _minutos_ventana_jornada(
        horario_config.hora_inicio,
        horario_config.hora_fin,
    )
    duracion_slot = int(max_dur)
    if ventana_jornada > 0:
        duracion_slot = min(duracion_slot, ventana_jornada)
    slots = slots_en_ventanas(libres, duracion_slot)

    # Filtrar slots en el pasado si es hoy
    if fecha == timezone.localdate():
        ahora_t = timezone.localtime().time()
        slots = [s for s in slots if s['hora_inicio_24h'] > ahora_t]

    slots_safe = _slots_json_safe(slots)

    return _with_servicio_meta({
        'fecha': fecha.isoformat(),
        'proveedor_disponible': True,
        'duracion_servicio_solicitado': {
            'minimo': min_dur,
            'maximo': max_dur,
            'etiqueta': etiqueta_duracion(min_dur, max_dur),
        },
        'estado_actual': estado_actual_proveedor(
            taller=taller,
            mecanico=mecanico,
            duracion_fallback=max_dur,
        ),
        'slots_disponibles': slots_safe,
        'total_slots': len(slots_safe),
    }, oferta)


def dias_con_slots(
    *,
    taller: Taller | None = None,
    mecanico: MecanicoDomicilio | None = None,
    oferta_servicio_id: int | None = None,
    dias_adelante: int = 14,
    modalidad: str | None = None,
    miembro_taller_id: int | None = None,
    requiere_especialidad: bool = True,
) -> list[str]:
    """Fechas YYYY-MM-DD con al menos un slot en los próximos N días."""
    hoy = timezone.localdate()
    fechas_ok: list[str] = []
    for offset in range(dias_adelante):
        f = hoy + timedelta(days=offset)
        try:
            data = disponibilidad_con_duracion(
                taller=taller,
                mecanico=mecanico,
                fecha=f,
                oferta_servicio_id=oferta_servicio_id,
                modalidad=modalidad,
                miembro_taller_id=miembro_taller_id,
                requiere_especialidad=requiere_especialidad,
            )
        except Exception:
            logger.exception(
                'dias_con_slots falló para fecha=%s taller=%s mecanico=%s oferta=%s',
                f,
                getattr(taller, 'id', None),
                getattr(mecanico, 'id', None),
                oferta_servicio_id,
            )
            continue
        if data.get('proveedor_disponible') and data.get('slots_disponibles'):
            fechas_ok.append(f.isoformat())
    return fechas_ok
