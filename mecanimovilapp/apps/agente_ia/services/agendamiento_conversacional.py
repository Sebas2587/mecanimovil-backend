"""Agendamiento conversacional post-aprobación de cotización IA."""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from django.core.exceptions import ValidationError
from django.utils import timezone

from mecanimovilapp.apps.agente_ia.models import AgenteConversacionSesion, AgenteMensajeLog
from mecanimovilapp.apps.agente_ia.services.notificaciones import notificar_cita_confirmada_por_agente
from mecanimovilapp.apps.agente_ia.services.orquestador import _llamar_gemini_agente, enviar_respuesta_agente
from mecanimovilapp.apps.chat.models import Conversation, Message
from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, CotizacionCanal
from mecanimovilapp.apps.ordenes.services.cita_agenda_personal import (
    actualizar_cita_personal,
    resolver_miembro_cita_personal,
)
from mecanimovilapp.apps.usuarios.models import Taller
from mecanimovilapp.apps.usuarios.services.disponibilidad_proveedor import (
    disponibilidad_con_duracion,
)

logger = logging.getLogger(__name__)

_JSON_FENCE = re.compile(r'```(?:json)?\s*([\s\S]*?)\s*```', re.IGNORECASE)
_DIAS_ES = {
    0: 'lun',
    1: 'mar',
    2: 'mié',
    3: 'jue',
    4: 'vie',
    5: 'sáb',
    6: 'dom',
}


def _parse_json(text: str) -> dict[str, Any] | None:
    if not text or not str(text).strip():
        return None
    raw = str(text).strip()
    fence = _JSON_FENCE.search(raw)
    if fence:
        raw = fence.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find('{')
        end = raw.rfind('}')
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def _formatear_fecha_legible(fecha_iso: str) -> str:
    try:
        f = date.fromisoformat(fecha_iso)
    except ValueError:
        return fecha_iso
    return f'{_DIAS_ES.get(f.weekday(), "")} {f.day}/{f.month:02d}'


def _construir_resumen_dias(fechas: list[str]) -> str:
    if not fechas:
        return 'No tengo cupos disponibles en los próximos días.'
    partes = [_formatear_fecha_legible(f) for f in fechas[:8]]
    return ', '.join(partes)


def _obtener_slots_dia(
    *,
    taller: Taller,
    fecha_iso: str,
    modalidad: str,
    duracion_minutos: int,
) -> list[dict[str, Any]]:
    try:
        fecha = date.fromisoformat(fecha_iso)
    except ValueError:
        return []
    data = disponibilidad_con_duracion(
        taller=taller,
        fecha=fecha,
        modalidad=modalidad,
        requiere_especialidad=False,
    )
    if not data.get('proveedor_disponible'):
        return []
    slots = data.get('slots_disponibles') or []
    return [
        {
            'fecha': fecha_iso,
            'hora': slot.get('hora'),
            'hora_fin_estimada': slot.get('hora_fin_estimada'),
        }
        for slot in slots
        if slot.get('hora') and slot.get('disponible', True)
    ]


def _recopilar_slots_ofrecidos(
    *,
    taller: Taller,
    modalidad: str,
    duracion_minutos: int,
    dias_adelante: int = 10,
    offset_dias: int = 0,
) -> dict[str, Any]:
    hoy = timezone.localdate()
    inicio = hoy + timedelta(days=offset_dias)
    fechas: list[str] = []
    slots_por_dia: dict[str, list[dict[str, Any]]] = {}

    for offset in range(dias_adelante):
        f = inicio + timedelta(days=offset)
        fecha_iso = f.isoformat()
        slots = _obtener_slots_dia(
            taller=taller,
            fecha_iso=fecha_iso,
            modalidad=modalidad,
            duracion_minutos=duracion_minutos,
        )
        if slots:
            fechas.append(fecha_iso)
            slots_por_dia[fecha_iso] = slots

    return {
        'fechas': fechas,
        'slots_por_dia': slots_por_dia,
        'offset_dias': offset_dias,
        'modalidad': modalidad,
        'duracion_minutos': duracion_minutos,
    }


def iniciar_agendamiento(
    *,
    cita: CitaAgendaPersonal,
    conversation: Conversation,
    taller: Taller,
    proveedor_user_id: int,
    sesion: AgenteConversacionSesion | None = None,
) -> dict[str, Any]:
    """Ofrece días disponibles y entra en modo agendamiento."""
    if sesion is None:
        sesion = AgenteConversacionSesion.objects.filter(conversation=conversation).first()
    if sesion is None:
        return {'ok': False, 'error': 'sin_sesion'}

    modalidad = cita.tipo_servicio or 'taller'
    duracion = cita.duracion_minutos or 60
    oferta = _recopilar_slots_ofrecidos(
        taller=taller,
        modalidad=modalidad,
        duracion_minutos=duracion,
    )

    datos = dict(sesion.datos_capturados or {})
    datos['slots_ofrecidos'] = oferta
    sesion.datos_capturados = datos
    sesion.estado = AgenteConversacionSesion.ESTADO_AGENDANDO
    sesion.cita_en_negociacion = cita
    sesion.save(update_fields=['datos_capturados', 'estado', 'cita_en_negociacion', 'actualizado_en'])

    resumen = _construir_resumen_dias(oferta.get('fechas') or [])
    texto = (
        f'¡Tu cotización fue aprobada! Tengo estos días disponibles: {resumen}. '
        '¿Cuál te acomoda y a qué hora?'
    )
    if not oferta.get('fechas'):
        texto = (
            '¡Tu cotización fue aprobada! Por ahora no veo cupos en los próximos días. '
            '¿Qué día u horario te acomodaría? Te busco alternativas.'
        )

    enviar_respuesta_agente(
        conversation=conversation,
        proveedor_user_id=proveedor_user_id,
        texto=texto,
    )
    return {'ok': True, 'accion': 'iniciar_agendamiento', 'fechas': oferta.get('fechas')}


def _cliente_pide_otro_rango(texto: str) -> bool:
    t = texto.lower()
    indicadores = (
        'no puedo',
        'otra semana',
        'semana que viene',
        'más adelante',
        'mas adelante',
        'otro día',
        'otro dia',
        'más tarde',
        'mas tarde',
        'no me sirve',
        'ninguno',
    )
    return any(x in t for x in indicadores)


def _prompt_match_slot(texto_cliente: str, slots_ctx: dict[str, Any]) -> str:
    slots_json = json.dumps(slots_ctx, ensure_ascii=False)
    return f"""Eres un asistente de agendamiento de taller mecánico en Chile.
El cliente debe elegir un horario REAL de la lista. NO inventes fechas ni horas fuera de la lista.

Slots disponibles (JSON):
{slots_json}

Mensaje del cliente:
{texto_cliente}

Responde SOLO JSON válido:
{{
  "resultado": "match|sin_match|pedir_mas_fechas",
  "fecha": "YYYY-MM-DD o null",
  "hora": "HH:MM o null",
  "motivo": "breve explicación en español"
}}

Reglas:
- "match" solo si fecha+hora existen exactamente en slots_por_dia.
- "pedir_mas_fechas" si pide otra semana/rango distinto.
- "sin_match" si no calza con ningún slot ofrecido."""


def _interpretar_slot_cliente(texto_cliente: str, slots_ctx: dict[str, Any]) -> dict[str, Any]:
    decision, error = _llamar_gemini_agente(_prompt_match_slot(texto_cliente, slots_ctx))
    if not decision:
        logger.warning('Gemini agendamiento sin respuesta: %s', error)
        return {'resultado': 'sin_match', 'motivo': error or 'No pude interpretar la respuesta.'}
    return decision


def _confirmar_slot(
    *,
    cita: CitaAgendaPersonal,
    taller: Taller,
    fecha_iso: str,
    hora_str: str,
) -> tuple[CitaAgendaPersonal, Any]:
    fecha = date.fromisoformat(fecha_iso)
    hora = datetime.strptime(hora_str, '%H:%M').time()
    miembro = resolver_miembro_cita_personal(
        taller=taller,
        miembro_id=None,
        tipo_servicio=cita.tipo_servicio,
        fecha=fecha,
        hora=hora,
        duracion_minutos=cita.duracion_minutos or 60,
        excluir_cita_id=cita.pk,
    )
    cita = actualizar_cita_personal(
        cita,
        cabecera={'fecha_servicio': fecha, 'hora_servicio': hora},
    )
    return cita, miembro


def procesar_turno_agendamiento(
    *,
    sesion: AgenteConversacionSesion,
    message: Message,
    texto_cliente: str,
    conversation: Conversation,
    taller: Taller,
    proveedor_user_id: int,
) -> dict[str, Any]:
    cita = sesion.cita_en_negociacion
    if cita is None:
        sesion.estado = AgenteConversacionSesion.ESTADO_CAPTURANDO
        sesion.save(update_fields=['estado', 'actualizado_en'])
        return {'ok': False, 'error': 'sin_cita_negociacion'}

    cita = CitaAgendaPersonal.objects.select_related('detalle', 'miembro_taller').filter(pk=cita.pk).first()
    if cita is None:
        sesion.cita_en_negociacion = None
        sesion.estado = AgenteConversacionSesion.ESTADO_CAPTURANDO
        sesion.save(update_fields=['cita_en_negociacion', 'estado', 'actualizado_en'])
        return {'ok': False, 'error': 'cita_no_encontrada'}

    datos = dict(sesion.datos_capturados or {})
    slots_ctx = datos.get('slots_ofrecidos') or {}
    modalidad = cita.tipo_servicio or 'taller'
    duracion = cita.duracion_minutos or 60

    if _cliente_pide_otro_rango(texto_cliente):
        offset = int(slots_ctx.get('offset_dias') or 0) + 7
        slots_ctx = _recopilar_slots_ofrecidos(
            taller=taller,
            modalidad=modalidad,
            duracion_minutos=duracion,
            offset_dias=offset,
        )
        datos['slots_ofrecidos'] = slots_ctx
        sesion.datos_capturados = datos
        sesion.save(update_fields=['datos_capturados', 'actualizado_en'])
        resumen = _construir_resumen_dias(slots_ctx.get('fechas') or [])
        respuesta = (
            f'Entiendo. Estos días tengo cupo más adelante: {resumen}. '
            '¿Cuál te acomoda y a qué hora?'
        )
        enviar_respuesta_agente(
            conversation=conversation,
            proveedor_user_id=proveedor_user_id,
            texto=respuesta,
        )
        AgenteMensajeLog.objects.create(
            sesion=sesion,
            mensaje_entrante=texto_cliente,
            respuesta_generada=respuesta,
            accion=AgenteMensajeLog.ACCION_RESPONDER,
            metadata={'agendamiento': True, 'reoferta': True},
        )
        return {'ok': True, 'accion': 'reofertar_slots'}

    decision = _interpretar_slot_cliente(texto_cliente, slots_ctx)
    resultado = (decision.get('resultado') or 'sin_match').strip().lower()

    if resultado == 'pedir_mas_fechas':
        offset = int(slots_ctx.get('offset_dias') or 0) + 7
        slots_ctx = _recopilar_slots_ofrecidos(
            taller=taller,
            modalidad=modalidad,
            duracion_minutos=duracion,
            offset_dias=offset,
        )
        datos['slots_ofrecidos'] = slots_ctx
        sesion.datos_capturados = datos
        sesion.save(update_fields=['datos_capturados', 'actualizado_en'])
        resumen = _construir_resumen_dias(slots_ctx.get('fechas') or [])
        respuesta = f'Busqué más fechas: {resumen}. ¿Cuál prefieres y a qué hora?'
        enviar_respuesta_agente(
            conversation=conversation,
            proveedor_user_id=proveedor_user_id,
            texto=respuesta,
        )
        return {'ok': True, 'accion': 'reofertar_slots'}

    fecha_iso = (decision.get('fecha') or '').strip()
    hora_str = (decision.get('hora') or '').strip()
    slots_dia = (slots_ctx.get('slots_por_dia') or {}).get(fecha_iso) or []
    horas_validas = {s.get('hora') for s in slots_dia}

    if resultado != 'match' or not fecha_iso or not hora_str or hora_str not in horas_validas:
        respuesta = (
            'No logré ubicar ese horario en la disponibilidad actual. '
            f'Tengo estos días: {_construir_resumen_dias(slots_ctx.get("fechas") or [])}. '
            '¿Podrías indicarme día y hora de esa lista?'
        )
        enviar_respuesta_agente(
            conversation=conversation,
            proveedor_user_id=proveedor_user_id,
            texto=respuesta,
        )
        AgenteMensajeLog.objects.create(
            sesion=sesion,
            mensaje_entrante=texto_cliente,
            respuesta_generada=respuesta,
            accion=AgenteMensajeLog.ACCION_RESPONDER,
            metadata={'agendamiento': True, 'sin_match': True},
        )
        return {'ok': True, 'accion': 'sin_match'}

    try:
        cita, miembro = _confirmar_slot(
            cita=cita,
            taller=taller,
            fecha_iso=fecha_iso,
            hora_str=hora_str,
        )
    except (ValidationError, ValueError) as exc:
        logger.info('Slot tomado o inválido en agendamiento IA: %s', exc)
        slots_ctx = _recopilar_slots_ofrecidos(
            taller=taller,
            modalidad=modalidad,
            duracion_minutos=duracion,
        )
        datos['slots_ofrecidos'] = slots_ctx
        sesion.datos_capturados = datos
        sesion.save(update_fields=['datos_capturados', 'actualizado_en'])
        respuesta = (
            'Disculpa, ese horario acaba de tomarse. '
            f'Te ofrezco estos cupos: {_construir_resumen_dias(slots_ctx.get("fechas") or [])}. '
            '¿Cuál te acomoda?'
        )
        enviar_respuesta_agente(
            conversation=conversation,
            proveedor_user_id=proveedor_user_id,
            texto=respuesta,
        )
        return {'ok': True, 'accion': 'slot_ocupado'}

    mecanico_nombre = ''
    if miembro is not None:
        mecanico_nombre = (miembro.nombre or '').strip() or 'nuestro equipo'
    fecha_legible = _formatear_fecha_legible(fecha_iso)
    respuesta = (
        f'¡Listo! Quedó agendado para el {fecha_legible} a las {hora_str}.'
    )
    if mecanico_nombre:
        respuesta += f' Te atenderá {mecanico_nombre}.'
    respuesta += ' Te esperamos.'

    enviar_respuesta_agente(
        conversation=conversation,
        proveedor_user_id=proveedor_user_id,
        texto=respuesta,
    )

    notificar_cita_confirmada_por_agente(
        proveedor_user_id=proveedor_user_id,
        cita=cita,
        conversation_id=conversation.id,
    )
    if miembro is not None:
        from mecanimovilapp.apps.ordenes.services.notificaciones_proveedor import (
            notificar_cita_asignada_mecanico,
        )

        notificar_cita_asignada_mecanico(cita, miembro)

    sesion.estado = AgenteConversacionSesion.ESTADO_CAPTURANDO
    sesion.cita_en_negociacion = None
    sesion.save(update_fields=['estado', 'cita_en_negociacion', 'actualizado_en'])

    AgenteMensajeLog.objects.create(
        sesion=sesion,
        mensaje_entrante=texto_cliente,
        respuesta_generada=respuesta,
        accion=AgenteMensajeLog.ACCION_RESPONDER,
        metadata={
            'agendamiento': True,
            'cita_id': cita.id,
            'fecha': fecha_iso,
            'hora': hora_str,
        },
    )
    return {'ok': True, 'accion': 'cita_confirmada', 'cita_id': cita.id}


def reaccionar_rechazo_cotizacion(
    *,
    cotizacion: CotizacionCanal,
    conversation: Conversation,
    taller: Taller,
    proveedor_user_id: int,
    sesion: AgenteConversacionSesion | None = None,
) -> dict[str, Any]:
    """Respuesta empática cuando el cliente rechaza la cotización."""
    if sesion is None:
        sesion = AgenteConversacionSesion.objects.filter(conversation=conversation).first()

    total = int(cotizacion.total_clp or 0)
    servicio = cotizacion.servicio_nombre or 'servicio'
    modalidad = cotizacion.modalidad or 'taller'
    prompt = f"""El cliente rechazó esta cotización:
- Servicio: {servicio}
- Modalidad: {modalidad}
- Total: ${total:,} CLP

Responde breve y empático en español (máx. 3 oraciones). Pregunta qué no le acomodó
(precio, tiempo, modalidad) y ofrece ajustar si quiere.

Responde SOLO JSON:
{{"respuesta_cliente": "..."}}""".replace(',', '.')

    decision, error = _llamar_gemini_agente(prompt)
    texto = (decision or {}).get('respuesta_cliente') or (
        'Entiendo, gracias por avisarnos. ¿Qué fue lo que no te acomodó — '
        'el precio, el tiempo o la modalidad? Si quieres, podemos ajustar la cotización.'
    )

    enviar_respuesta_agente(
        conversation=conversation,
        proveedor_user_id=proveedor_user_id,
        texto=texto.strip(),
    )

    if sesion:
        sesion.estado = AgenteConversacionSesion.ESTADO_CAPTURANDO
        sesion.save(update_fields=['estado', 'actualizado_en'])
        AgenteMensajeLog.objects.create(
            sesion=sesion,
            mensaje_entrante='[rechazo cotización]',
            respuesta_generada=texto,
            accion=AgenteMensajeLog.ACCION_RESPONDER,
            metadata={'cotizacion_id': cotizacion.id, 'rechazo': True, 'error': error},
        )

    return {'ok': True, 'accion': 'rechazo_empatico'}
