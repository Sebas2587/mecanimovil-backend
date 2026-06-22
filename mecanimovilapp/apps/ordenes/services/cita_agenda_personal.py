"""
Dominio: citas de agenda personal del proveedor (fuera de marketplace).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, CitaAgendaPersonalDetalle
from mecanimovilapp.apps.servicios.models import OfertaServicio
from mecanimovilapp.apps.usuarios.models import (
    HorarioProveedor,
    MecanicoDomicilio,
    MiembroTaller,
    Taller,
    Usuario,
)
from mecanimovilapp.apps.usuarios.services.disponibilidad_proveedor import (
    duracion_rango_oferta,
    intervalos_ocupados_dia,
)


def resolver_proveedor_usuario(user: Usuario) -> tuple[Taller | None, MecanicoDomicilio | None]:
    if hasattr(user, 'taller'):
        try:
            return user.taller, None
        except Taller.DoesNotExist:
            pass
    if hasattr(user, 'mecanico_domicilio'):
        try:
            return None, user.mecanico_domicilio
        except MecanicoDomicilio.DoesNotExist:
            pass
    return None, None


def _intervalo_cita(
    fecha: date,
    hora,
    duracion_minutos: int,
    tiempo_descanso: int = 0,
) -> tuple[datetime, datetime]:
    inicio = datetime.combine(fecha, hora)
    fin = inicio + timedelta(minutes=duracion_minutos + tiempo_descanso)
    return inicio, fin


def _solapa(
    a_ini: datetime,
    a_fin: datetime,
    b_ini: datetime,
    b_fin: datetime,
) -> bool:
    return a_ini < b_fin and b_ini < a_fin


def validar_horario_laboral(
    *,
    taller: Taller | None,
    mecanico: MecanicoDomicilio | None,
    fecha: date,
    hora,
    duracion_minutos: int,
) -> HorarioProveedor:
    dia_semana = fecha.weekday()
    horario_qs = HorarioProveedor.objects.filter(dia_semana=dia_semana, activo=True)
    if taller:
        horario_qs = horario_qs.filter(taller=taller)
    else:
        horario_qs = horario_qs.filter(mecanico=mecanico)

    horario = horario_qs.order_by('id').first()
    if horario is None:
        raise ValidationError('El proveedor no atiende este día.')

    inicio_cita, fin_cita = _intervalo_cita(fecha, hora, duracion_minutos, horario.tiempo_descanso)
    dia_inicio = datetime.combine(fecha, horario.hora_inicio)
    dia_fin = datetime.combine(fecha, horario.hora_fin)

    if inicio_cita < dia_inicio or fin_cita > dia_fin:
        raise ValidationError('La cita queda fuera del horario laboral configurado.')

    if fecha == timezone.localdate():
        ahora = timezone.localtime().replace(tzinfo=None)
        if inicio_cita < ahora:
            raise ValidationError('No se puede agendar en un horario ya pasado.')

    return horario


def validar_slot_disponible(
    *,
    taller: Taller | None,
    mecanico: MecanicoDomicilio | None,
    fecha: date,
    hora,
    duracion_minutos: int,
    excluir_cita_id: int | None = None,
) -> None:
    horario = validar_horario_laboral(
        taller=taller,
        mecanico=mecanico,
        fecha=fecha,
        hora=hora,
        duracion_minutos=duracion_minutos,
    )

    ocupados = intervalos_ocupados_dia(
        taller=taller,
        mecanico=mecanico,
        fecha=fecha,
        tiempo_descanso=horario.tiempo_descanso,
        duracion_fallback=duracion_minutos,
        excluir_cita_personal_id=excluir_cita_id,
    )

    propuesta_ini, propuesta_fin = _intervalo_cita(
        fecha, hora, duracion_minutos, horario.tiempo_descanso,
    )
    for occ_ini, occ_fin in ocupados:
        if _solapa(propuesta_ini, propuesta_fin, occ_ini, occ_fin):
            raise ValidationError('El horario seleccionado ya está ocupado.')


def resolver_duracion_minutos(
    *,
    oferta_servicio: OfertaServicio | None,
    duracion_manual: int | None,
) -> int:
    if duracion_manual and duracion_manual > 0:
        return int(duracion_manual)
    if oferta_servicio is not None:
        _, max_dur = duracion_rango_oferta(oferta_servicio)
        return int(max_dur)
    return 60


def validar_oferta_pertenece_proveedor(
    oferta: OfertaServicio | None,
    *,
    taller: Taller | None,
    mecanico: MecanicoDomicilio | None,
) -> None:
    if oferta is None:
        return
    if taller and oferta.taller_id != taller.id:
        raise ValidationError('La oferta de servicio no pertenece a este taller.')
    if mecanico and oferta.mecanico_id != mecanico.id:
        raise ValidationError('La oferta de servicio no pertenece a este mecánico.')


def validar_detalle(detalle_data: dict, *, tipo_servicio: str) -> None:
    if tipo_servicio == 'domicilio' and not (detalle_data.get('direccion') or '').strip():
        raise ValidationError({'direccion': 'Dirección requerida para servicio a domicilio.'})

    oferta_id = detalle_data.get('oferta_servicio')
    nombre = (detalle_data.get('servicio_nombre') or '').strip()
    if not oferta_id and not nombre:
        raise ValidationError(
            'Debe indicar una oferta de servicio del catálogo o un nombre de servicio manual.',
        )


@transaction.atomic
def crear_cita_personal(
    *,
    user: Usuario,
    cabecera: dict,
    detalle: dict,
) -> CitaAgendaPersonal:
    taller, mecanico = resolver_proveedor_usuario(user)
    if not taller and not mecanico:
        raise ValidationError('Usuario sin perfil de proveedor.')

    tipo_servicio = cabecera.get('tipo_servicio', 'taller')
    validar_detalle(detalle, tipo_servicio=tipo_servicio)

    # Mecánico asignado opcional (solo talleres con equipo)
    miembro = None
    miembro_id = cabecera.get('miembro_taller')
    if miembro_id:
        if taller is None:
            raise ValidationError('Solo los talleres pueden asignar un mecánico a la cita.')
        miembro = MiembroTaller.objects.filter(pk=miembro_id, taller=taller).first()
        if miembro is None:
            raise ValidationError({'miembro_taller': 'El mecánico no pertenece a este taller.'})

    oferta = None
    oferta_id = detalle.pop('oferta_servicio', None)
    if oferta_id:
        if isinstance(oferta_id, OfertaServicio):
            oferta = oferta_id
        else:
            oferta = OfertaServicio.objects.filter(pk=oferta_id).first()
        validar_oferta_pertenece_proveedor(oferta, taller=taller, mecanico=mecanico)
        detalle['oferta_servicio'] = oferta

    duracion = resolver_duracion_minutos(
        oferta_servicio=oferta,
        duracion_manual=cabecera.get('duracion_minutos'),
    )

    fecha = cabecera['fecha_servicio']
    hora = cabecera['hora_servicio']
    validar_slot_disponible(
        taller=taller,
        mecanico=mecanico,
        fecha=fecha,
        hora=hora,
        duracion_minutos=duracion,
    )

    cita = CitaAgendaPersonal(
        taller=taller,
        mecanico=mecanico,
        miembro_taller=miembro,
        fecha_servicio=fecha,
        hora_servicio=hora,
        duracion_minutos=duracion,
        tipo_servicio=tipo_servicio,
        creado_por=user,
    )
    cita.full_clean()
    cita.save()

    det = CitaAgendaPersonalDetalle(cita=cita, **detalle)
    det.full_clean()
    det.save()
    return cita


@transaction.atomic
def actualizar_cita_personal(
    cita: CitaAgendaPersonal,
    *,
    cabecera: dict | None = None,
    detalle: dict | None = None,
) -> CitaAgendaPersonal:
    if cita.estado != 'activa':
        raise ValidationError('Solo se pueden editar citas activas.')

    cabecera = cabecera or {}
    detalle = detalle or {}

    det_obj = cita.detalle
    tipo_servicio = cabecera.get('tipo_servicio', cita.tipo_servicio)

    merged_detalle = {
        'cliente_nombre': detalle.get('cliente_nombre', det_obj.cliente_nombre),
        'cliente_telefono': detalle.get('cliente_telefono', det_obj.cliente_telefono),
        'direccion': detalle.get('direccion', det_obj.direccion),
        'vehiculo_marca': detalle.get('vehiculo_marca', det_obj.vehiculo_marca),
        'vehiculo_modelo': detalle.get('vehiculo_modelo', det_obj.vehiculo_modelo),
        'vehiculo_patente': detalle.get('vehiculo_patente', det_obj.vehiculo_patente),
        'vehiculo_anio': detalle.get('vehiculo_anio', det_obj.vehiculo_anio),
        'vehiculo_cilindraje': detalle.get('vehiculo_cilindraje', det_obj.vehiculo_cilindraje),
        'vehiculo_color': detalle.get('vehiculo_color', det_obj.vehiculo_color),
        'servicio_nombre': detalle.get('servicio_nombre', det_obj.servicio_nombre),
        'descripcion': detalle.get('descripcion', det_obj.descripcion),
        'precio_referencia': detalle.get('precio_referencia', det_obj.precio_referencia),
    }

    oferta = det_obj.oferta_servicio
    if 'oferta_servicio' in detalle:
        oferta_raw = detalle['oferta_servicio']
        if oferta_raw is None:
            oferta = None
        elif isinstance(oferta_raw, OfertaServicio):
            oferta = oferta_raw
        else:
            oferta = OfertaServicio.objects.filter(pk=oferta_raw).first()
        merged_detalle['oferta_servicio'] = oferta

    validar_detalle(merged_detalle, tipo_servicio=tipo_servicio)
    validar_oferta_pertenece_proveedor(
        oferta,
        taller=cita.taller,
        mecanico=cita.mecanico,
    )

    fecha = cabecera.get('fecha_servicio', cita.fecha_servicio)
    hora = cabecera.get('hora_servicio', cita.hora_servicio)
    duracion = resolver_duracion_minutos(
        oferta_servicio=oferta,
        duracion_manual=cabecera.get('duracion_minutos', cita.duracion_minutos),
    )

    validar_slot_disponible(
        taller=cita.taller,
        mecanico=cita.mecanico,
        fecha=fecha,
        hora=hora,
        duracion_minutos=duracion,
        excluir_cita_id=cita.pk,
    )

    for field, value in cabecera.items():
        if field in ('fecha_servicio', 'hora_servicio', 'duracion_minutos', 'tipo_servicio'):
            setattr(cita, field, value if field != 'duracion_minutos' else duracion)
    cita.duracion_minutos = duracion

    # Reasignación de mecánico (opcional, solo talleres con equipo)
    if 'miembro_taller' in cabecera:
        miembro_id = cabecera.get('miembro_taller')
        if not miembro_id:
            cita.miembro_taller = None
        elif cita.taller_id is None:
            raise ValidationError('Solo los talleres pueden asignar un mecánico a la cita.')
        else:
            miembro = MiembroTaller.objects.filter(pk=miembro_id, taller_id=cita.taller_id).first()
            if miembro is None:
                raise ValidationError({'miembro_taller': 'El mecánico no pertenece a este taller.'})
            cita.miembro_taller = miembro
    cita.full_clean()
    cita.save()

    for field, value in merged_detalle.items():
        setattr(det_obj, field, value)
    det_obj.full_clean()
    det_obj.save()
    return cita
