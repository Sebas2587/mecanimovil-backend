"""Notificaciones de seguimiento comercial por tiempo (pipeline)."""
from __future__ import annotations

import logging
from datetime import date

from django.contrib.auth import get_user_model

from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, CotizacionCanal

logger = logging.getLogger(__name__)
User = get_user_model()

HORAS_BORRADOR_LISTO_RECORDATORIO = 4


def _proveedor_user_id_desde_cotizacion(cotizacion: CotizacionCanal) -> int | None:
    if cotizacion.creado_por_id:
        return cotizacion.creado_por_id
    taller = cotizacion.taller
    if taller and getattr(taller, 'usuario_id', None):
        return taller.usuario_id
    return None


def _proveedor_user_id_desde_cita(cita: CitaAgendaPersonal) -> int | None:
    taller = cita.taller
    if taller and getattr(taller, 'usuario_id', None):
        return taller.usuario_id
    return None


def _enviar_push_proveedor(user_id: int, titulo: str, mensaje: str, data: dict) -> None:
    from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification

    try:
        send_expo_push_notification.delay(user_id, titulo, mensaje, data)
    except Exception as exc:
        logger.warning('No se pudo encolar push pipeline: %s', exc)


def _dedup_dia(tipo: str, entidad_id: int) -> dict:
    return {'type': tipo, 'entidad_id': entidad_id, 'bucket': date.today().isoformat()}


def notificar_borrador_listo_sin_enviar(*, cotizacion: CotizacionCanal) -> None:
    from mecanimovilapp.apps.usuarios.models import Notificacion

    meta = cotizacion.metadata if isinstance(cotizacion.metadata, dict) else {}
    if not meta.get('listo_para_enviar'):
        return

    user_id = _proveedor_user_id_desde_cotizacion(cotizacion)
    if not user_id:
        return
    usuario = User.objects.filter(pk=user_id).first()
    if not usuario:
        return

    servicio = cotizacion.servicio_nombre or 'servicio'
    total_txt = f'${int(cotizacion.total_clp or 0):,} CLP'.replace(',', '.')
    titulo = 'Cotización lista sin enviar'
    mensaje = (
        f'El borrador de "{servicio}" ({total_txt}) sigue pendiente de envío. '
        f'Revisa en Cotizar con IA.'
    )
    data = {
        'type': 'pipeline_borrador_listo_sin_enviar',
        'cotizacion_id': cotizacion.id,
        'conversation_id': cotizacion.conversation_id,
    }
    Notificacion.crear_unica(
        usuario,
        tipo='system',
        titulo=titulo,
        mensaje=mensaje,
        data=data,
        ventana_horas=12,
        dedup_key=_dedup_dia('pipeline_borrador_listo_sin_enviar', cotizacion.id),
    )
    _enviar_push_proveedor(user_id, titulo, mensaje, data)


def notificar_cotizacion_sin_respuesta_24h(*, cotizacion: CotizacionCanal) -> None:
    from mecanimovilapp.apps.usuarios.models import Notificacion

    user_id = _proveedor_user_id_desde_cotizacion(cotizacion)
    if not user_id:
        return
    usuario = User.objects.filter(pk=user_id).first()
    if not usuario:
        return

    servicio = cotizacion.servicio_nombre or 'servicio'
    cliente = cotizacion.cliente_nombre or 'El cliente'
    titulo = 'Cotización sin respuesta (+24h)'
    mensaje = (
        f'{cliente} aún no responde a la cotización de "{servicio}". '
        f'Puedes hacer seguimiento desde la bandeja o el chat.'
    )
    data = {
        'type': 'pipeline_cotizacion_sin_respuesta_24h',
        'cotizacion_id': cotizacion.id,
        'conversation_id': cotizacion.conversation_id,
    }
    Notificacion.crear_unica(
        usuario,
        tipo='system',
        titulo=titulo,
        mensaje=mensaje,
        data=data,
        ventana_horas=12,
        dedup_key=_dedup_dia('pipeline_cotizacion_sin_respuesta_24h', cotizacion.id),
    )
    _enviar_push_proveedor(user_id, titulo, mensaje, data)


def notificar_cotizacion_demorada_48h(*, cotizacion: CotizacionCanal) -> None:
    from mecanimovilapp.apps.usuarios.models import Notificacion

    user_id = _proveedor_user_id_desde_cotizacion(cotizacion)
    if not user_id:
        return
    usuario = User.objects.filter(pk=user_id).first()
    if not usuario:
        return

    servicio = cotizacion.servicio_nombre or 'servicio'
    cliente = cotizacion.cliente_nombre or 'El cliente'
    titulo = 'Seguimiento urgente (+48h)'
    mensaje = (
        f'{cliente} lleva más de 48 h sin responder la cotización de "{servicio}". '
        f'Considera contactarlo o cerrar el caso desde la bandeja.'
    )
    data = {
        'type': 'pipeline_cotizacion_demorada_48h',
        'cotizacion_id': cotizacion.id,
        'conversation_id': cotizacion.conversation_id,
    }
    Notificacion.crear_unica(
        usuario,
        tipo='system',
        titulo=titulo,
        mensaje=mensaje,
        data=data,
        ventana_horas=12,
        dedup_key=_dedup_dia('pipeline_cotizacion_demorada_48h', cotizacion.id),
    )
    _enviar_push_proveedor(user_id, titulo, mensaje, data)


def notificar_agenda_pendiente_confirmacion(*, cita: CitaAgendaPersonal) -> None:
    from mecanimovilapp.apps.usuarios.models import Notificacion

    if not getattr(cita, 'horario_por_confirmar', False):
        return

    user_id = _proveedor_user_id_desde_cita(cita)
    if not user_id:
        return
    usuario = User.objects.filter(pk=user_id).first()
    if not usuario:
        return

    det = cita.detalle
    cliente = (det.cliente_nombre if det else None) or 'Cliente'
    servicio = (det.servicio_nombre or det.descripcion if det else None) or 'servicio'
    titulo = 'Agenda pendiente de confirmar'
    mensaje = (
        f'{cliente} aceptó "{servicio}" pero el horario sigue sin confirmar. '
        f'Revisa la cita o el chat para cerrar la agenda.'
    )
    data = {
        'type': 'pipeline_agenda_pendiente_confirmacion',
        'cita_id': cita.id,
        'conversation_id': cita.conversation_origen_id,
    }
    Notificacion.crear_unica(
        usuario,
        tipo='system',
        titulo=titulo,
        mensaje=mensaje,
        data=data,
        ventana_horas=12,
        dedup_key=_dedup_dia('pipeline_agenda_pendiente_confirmacion', cita.id),
    )
    _enviar_push_proveedor(user_id, titulo, mensaje, data)


def notificar_cotizacion_adicional_borrador(
    *,
    proveedor_user_id: int,
    cotizacion: CotizacionCanal,
    conversation_id: int | None,
) -> None:
    from mecanimovilapp.apps.usuarios.models import Notificacion

    usuario = User.objects.filter(pk=proveedor_user_id).first()
    if not usuario:
        return

    servicio = cotizacion.servicio_nombre or 'servicio adicional'
    total_txt = f'${int(cotizacion.total_clp or 0):,} CLP'.replace(',', '.')
    titulo = 'Cotización adicional por revisar'
    mensaje = (
        f'Se creó un borrador de "{servicio}" ({total_txt}) sobre un trabajo en curso. '
        f'Revisa y envía desde Cotizar con IA.'
    )
    data = {
        'type': 'pipeline_cotizacion_adicional_borrador',
        'cotizacion_id': cotizacion.id,
        'conversation_id': conversation_id,
    }
    Notificacion.crear_unica(
        usuario,
        tipo='system',
        titulo=titulo,
        mensaje=mensaje,
        data=data,
        ventana_horas=6,
        dedup_key={'type': 'pipeline_cotizacion_adicional_borrador', 'cotizacion_id': cotizacion.id},
    )
    _enviar_push_proveedor(proveedor_user_id, titulo, mensaje, data)
