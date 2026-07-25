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
from mecanimovilapp.apps.ordenes.services.asignacion_mecanico import _modalidad_desde_tipo_servicio
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


def _categorias_desde_cotizacion(cotizacion: CotizacionCanal | None) -> list[int]:
    """Categorías de servicio requeridas según las ofertas del borrador/cotización."""
    if cotizacion is None:
        return []
    meta = cotizacion.metadata if isinstance(getattr(cotizacion, 'metadata', None), dict) else {}
    lineas = meta.get('servicios_lineas') or []
    ids_oferta = [
        int(l['oferta_servicio_id'])
        for l in lineas
        if l.get('oferta_servicio_id')
    ]
    if not ids_oferta:
        return []
    from mecanimovilapp.apps.servicios.models import OfertaServicio

    cat_ids: set[int] = set()
    for oferta in OfertaServicio.objects.filter(pk__in=ids_oferta).select_related('servicio'):
        cat_ids.update(oferta.servicio.categorias.values_list('id', flat=True))
    return sorted(cat_ids)


def _oferta_servicio_id_desde_cotizacion(cotizacion: CotizacionCanal | None) -> int | None:
    if cotizacion is None:
        return None
    meta = cotizacion.metadata if isinstance(getattr(cotizacion, 'metadata', None), dict) else {}
    for linea in meta.get('servicios_lineas') or []:
        oid = linea.get('oferta_servicio_id')
        if oid:
            return int(oid)
    return None


def _mejor_slot_proximo(
    slots_ctx: dict[str, Any],
    preferencias: dict[str, Any],
) -> tuple[str, str] | None:
    """Slot más próximo: preferencia del cliente si sigue libre, si no el primero disponible."""
    slots_por_dia = slots_ctx.get('slots_por_dia') or {}
    fecha_pref = (preferencias.get('fecha') or '').strip()
    hora_pref = (preferencias.get('hora') or '').strip()
    if fecha_pref and hora_pref:
        slots_dia = slots_por_dia.get(fecha_pref) or []
        horas_libres = {s.get('hora') for s in slots_dia if s.get('hora')}
        if hora_pref in horas_libres:
            return fecha_pref, hora_pref
    for fecha in sorted(slots_por_dia.keys()):
        slots = slots_por_dia.get(fecha) or []
        for slot in slots:
            hora = (slot.get('hora') or '').strip()
            if hora:
                return fecha, hora
    return None


def _obtener_slots_dia(
    *,
    taller: Taller,
    fecha_iso: str,
    modalidad: str,
    duracion_minutos: int,
    oferta_servicio_id: int | None = None,
    requiere_especialidad: bool = True,
) -> list[dict[str, Any]]:
    try:
        fecha = date.fromisoformat(fecha_iso)
    except ValueError:
        return []
    # tipo_servicio ('taller'/'domicilio') ≠ modalidad_tecnico ('en_taller'/'a_domicilio').
    # Mapear antes de llamar a disponibilidad_con_duracion para que el filtro
    # mecanicos_aptos_taller compare valores compatibles y no devuelva siempre vacío.
    modalidad_tecnico = _modalidad_desde_tipo_servicio(modalidad)
    kwargs_base = {
        'taller': taller,
        'fecha': fecha,
        'oferta_servicio_id': oferta_servicio_id,
        'modalidad': modalidad_tecnico,
    }
    data = disponibilidad_con_duracion(
        **kwargs_base,
        requiere_especialidad=requiere_especialidad and bool(oferta_servicio_id),
    )
    slots = data.get('slots_disponibles') or []
    if not slots and requiere_especialidad and oferta_servicio_id:
        data = disponibilidad_con_duracion(**kwargs_base, requiere_especialidad=False)
        slots = data.get('slots_disponibles') or []
    # Fallback: si el filtro por modalidad dejó sin cupos, usa horario global del
    # taller / unión de mecánicos sin filtrar modalidad (evita "horario pendiente"
    # eterno cuando el equipo no tiene modalidad alineada pero el taller sí atiende).
    if not slots:
        data = disponibilidad_con_duracion(
            taller=taller,
            fecha=fecha,
            oferta_servicio_id=oferta_servicio_id,
            modalidad=None,
            requiere_especialidad=False,
        )
        slots = data.get('slots_disponibles') or []
    if not data.get('proveedor_disponible') and not slots:
        return []
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
    oferta_servicio_id: int | None = None,
    requiere_especialidad: bool = True,
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
            oferta_servicio_id=oferta_servicio_id,
            requiere_especialidad=requiere_especialidad,
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


def _preferencias_agenda_desde_sesion(sesion: AgenteConversacionSesion, cita: CitaAgendaPersonal) -> dict[str, Any]:
    datos = dict(sesion.datos_capturados or {})
    pref = dict(datos.get('preferencias_agenda') or {})
    # También desde metadata de la cotización origen (sobrevive al envío).
    cot = getattr(cita, 'cotizacion_canal_origen', None) or getattr(sesion, 'cotizacion_borrador', None)
    if cot and isinstance(getattr(cot, 'metadata', None), dict):
        pref_meta = cot.metadata.get('preferencias_agenda') or {}
        for k, v in pref_meta.items():
            if v not in (None, '', []) and not pref.get(k):
                pref[k] = v
    return pref


def iniciar_agendamiento(
    *,
    cita: CitaAgendaPersonal,
    conversation: Conversation,
    taller: Taller,
    proveedor_user_id: int,
    sesion: AgenteConversacionSesion | None = None,
) -> dict[str, Any]:
    """Ofrece días disponibles y entra en modo agendamiento.

    Si en la captura ya se acordó día/hora (preferencias_agenda) y ese slot sigue
    libre (sin solape con otras citas del técnico/taller), lo confirma de una.
    """
    if sesion is None:
        sesion = AgenteConversacionSesion.objects.filter(conversation=conversation).first()
    if sesion is None:
        return {'ok': False, 'error': 'sin_sesion'}

    modalidad = cita.tipo_servicio or 'taller'
    duracion = cita.duracion_minutos or 60
    cotizacion = getattr(cita, 'cotizacion_canal_origen', None)
    oferta_servicio_id = _oferta_servicio_id_desde_cotizacion(cotizacion)
    categorias_req = _categorias_desde_cotizacion(cotizacion)
    oferta = _recopilar_slots_ofrecidos(
        taller=taller,
        modalidad=modalidad,
        duracion_minutos=duracion,
        oferta_servicio_id=oferta_servicio_id,
        requiere_especialidad=bool(categorias_req or oferta_servicio_id),
    )

    datos = dict(sesion.datos_capturados or {})
    datos['slots_ofrecidos'] = oferta
    if categorias_req:
        datos['categorias_requeridas'] = categorias_req
    preferencias = _preferencias_agenda_desde_sesion(sesion, cita)
    if preferencias:
        datos['preferencias_agenda'] = preferencias
    sesion.datos_capturados = datos
    sesion.estado = AgenteConversacionSesion.ESTADO_AGENDANDO
    sesion.cita_en_negociacion = cita
    sesion.save(update_fields=['datos_capturados', 'estado', 'cita_en_negociacion', 'actualizado_en'])

    # Intento de confirmar slot ya pactado en la conversación (si sigue libre).
    fecha_pref = (preferencias.get('fecha') or '').strip()
    hora_pref = (preferencias.get('hora') or '').strip()
    if fecha_pref and hora_pref:
        slots_dia = (oferta.get('slots_por_dia') or {}).get(fecha_pref) or []
        horas_libres = {s.get('hora') for s in slots_dia if s.get('hora')}
        if hora_pref in horas_libres:
            try:
                cita_ok, miembro = _confirmar_slot(
                    cita=cita,
                    taller=taller,
                    fecha_iso=fecha_pref,
                    hora_str=hora_pref,
                    categorias_requeridas=categorias_req or None,
                )
                tecnico = getattr(miembro, 'nombre', None) or preferencias.get('tecnico_nombre') or 'nuestro equipo'
                texto_ok = (
                    f'¡Tu cotización fue aprobada! Confirmé la cita para '
                    f'{_formatear_fecha_legible(fecha_pref)} a las {hora_pref} con {tecnico}. '
                    'Te esperamos.'
                )
                enviar_respuesta_agente(
                    conversation=conversation,
                    proveedor_user_id=proveedor_user_id,
                    texto=texto_ok,
                )
                notificar_cita_confirmada_por_agente(
                    proveedor_user_id=proveedor_user_id,
                    cita=cita_ok,
                    conversation_id=conversation.id,
                )
                sesion.estado = AgenteConversacionSesion.ESTADO_CERRADO
                sesion.save(update_fields=['estado', 'actualizado_en'])
                AgenteMensajeLog.objects.create(
                    sesion=sesion,
                    mensaje_entrante='[auto] preferencias_agenda',
                    respuesta_generada=texto_ok,
                    accion=AgenteMensajeLog.ACCION_RESPONDER,
                    metadata={
                        'fecha': fecha_pref,
                        'hora': hora_pref,
                        'miembro_id': getattr(miembro, 'id', None),
                        'confirmado_desde_preferencias': True,
                    },
                )
                return {
                    'ok': True,
                    'accion': 'cita_confirmada_desde_preferencias',
                    'fecha': fecha_pref,
                    'hora': hora_pref,
                }
            except ValidationError:
                # Slot ya no está libre: cae al flujo de ofrecer alternativas.
                logger.info(
                    'Preferencia agenda %s %s ya no disponible; ofreciendo slots',
                    fecha_pref,
                    hora_pref,
                )

    resumen = _construir_resumen_dias(oferta.get('fechas') or [])
    pref_txt = ''
    if preferencias.get('fecha') or preferencias.get('hora') or preferencias.get('tecnico_nombre'):
        pref_txt = (
            f' Habías mencionado {preferencias.get("fecha") or "un día"} '
            f'{("a las " + preferencias["hora"]) if preferencias.get("hora") else ""}'
            f'{(" con " + preferencias["tecnico_nombre"]) if preferencias.get("tecnico_nombre") else ""}. '
            'Si ese horario ya no está libre, elige otro de la lista.'
        )
    mejor = _mejor_slot_proximo(oferta, preferencias)
    if not oferta.get('fechas'):
        texto = (
            '¡Tu cotización fue aprobada! Por ahora no veo cupos en los próximos días. '
            '¿Qué día u horario te acomodaría? Te busco alternativas.'
        )
    elif mejor:
        fecha_prop, hora_prop = mejor
        fecha_legible = _formatear_fecha_legible(fecha_prop)
        texto = (
            f'¡Tu cotización fue aprobada! Te propongo el {fecha_legible} a las {hora_prop}. '
            f'¿Te acomoda? Si prefieres otro día u hora, dímelo.{pref_txt}'
        ).replace('  ', ' ')
    else:
        texto = (
            f'¡Tu cotización fue aprobada! Tengo estos días disponibles: {resumen}.{pref_txt} '
            '¿Cuál te acomoda y a qué hora?'
        ).replace('  ', ' ')

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
    hoy = timezone.localdate().isoformat()
    slots_json = json.dumps(slots_ctx, ensure_ascii=False)
    return f"""Eres un asistente de agendamiento de taller mecánico en Chile.
El cliente debe elegir un horario REAL de la lista. NO inventes fechas ni horas fuera de la lista.

Fecha de HOY (referencia para "mañana", "el miércoles", etc.): {hoy}

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


def _enriquecer_detalle_cita_desde_origen(cita: CitaAgendaPersonal) -> None:
    """Rellena teléfono/VIN/cilindraje/dirección vacíos desde la cotización u origen."""
    det = getattr(cita, 'detalle', None)
    if det is None:
        return
    cot = getattr(cita, 'cotizacion_canal_origen', None)
    update_fields: list[str] = []

    if not (det.cliente_telefono or '').strip():
        tel = ''
        if cot and (cot.cliente_telefono or '').strip():
            tel = cot.cliente_telefono.strip()
        else:
            conv = getattr(cita, 'conversation_origen', None) or (
                getattr(cot, 'conversation', None) if cot else None
            )
            contact = getattr(conv, 'external_contact', None) if conv else None
            if contact is not None and hasattr(contact, 'telefono_efectivo'):
                tel = contact.telefono_efectivo()
            elif contact is not None:
                tel = (contact.phone or '') or ''
        if tel:
            det.cliente_telefono = tel[:20]
            update_fields.append('cliente_telefono')

    if cot:
        if not (det.vehiculo_vin or '').strip() and (cot.vehiculo_vin or '').strip():
            det.vehiculo_vin = cot.vehiculo_vin.strip().upper()[:30]
            update_fields.append('vehiculo_vin')
        if not (det.vehiculo_cilindraje or '').strip() and (cot.vehiculo_cilindraje or '').strip():
            det.vehiculo_cilindraje = (cot.vehiculo_cilindraje or '')[:30]
            update_fields.append('vehiculo_cilindraje')
        if (
            cita.tipo_servicio == 'domicilio'
            and not (det.direccion or '').strip()
            and (cot.direccion_servicio or '').strip()
        ):
            det.direccion = cot.direccion_servicio.strip()[:500]
            update_fields.append('direccion')

    if update_fields:
        det.save(update_fields=update_fields)


def _confirmar_slot(
    *,
    cita: CitaAgendaPersonal,
    taller: Taller,
    fecha_iso: str,
    hora_str: str,
    categorias_requeridas: list[int] | None = None,
) -> tuple[CitaAgendaPersonal, Any]:
    fecha = date.fromisoformat(fecha_iso)
    hora = datetime.strptime(hora_str, '%H:%M').time()
    # Preferencia de técnico capturada en la conversación (si aplica).
    pref_tecnico = ''
    cot = getattr(cita, 'cotizacion_canal_origen', None)
    if cot and isinstance(getattr(cot, 'metadata', None), dict):
        pref_tecnico = (
            ((cot.metadata.get('preferencias_agenda') or {}).get('tecnico_nombre') or '')
            .strip()
            .lower()
        )

    miembro_id = None
    if pref_tecnico:
        from mecanimovilapp.apps.usuarios.models import MiembroTaller

        candidato = (
            MiembroTaller.objects.filter(
                taller=taller, rol='mecanico', activo=True, nombre__icontains=pref_tecnico
            )
            .order_by('id')
            .first()
        )
        if candidato:
            miembro_id = candidato.id

    miembro = None
    cats = categorias_requeridas or None
    try:
        miembro = resolver_miembro_cita_personal(
            taller=taller,
            miembro_id=miembro_id,
            tipo_servicio=cita.tipo_servicio,
            fecha=fecha,
            hora=hora,
            duracion_minutos=cita.duracion_minutos or 60,
            categorias_requeridas=cats,
            excluir_cita_id=cita.pk,
        )
    except ValidationError:
        if cats:
            miembro = resolver_miembro_cita_personal(
                taller=taller,
                miembro_id=miembro_id,
                tipo_servicio=cita.tipo_servicio,
                fecha=fecha,
                hora=hora,
                duracion_minutos=cita.duracion_minutos or 60,
                categorias_requeridas=None,
                excluir_cita_id=cita.pk,
            )
        else:
            raise
    cabecera: dict[str, Any] = {
        'fecha_servicio': fecha,
        'hora_servicio': hora,
    }
    if miembro is not None:
        cabecera['miembro_taller'] = miembro.id

    cita = actualizar_cita_personal(cita, cabecera=cabecera)

    # Cinturón de seguridad: el flag debe quedar false tras confirmar slot real.
    if cita.horario_por_confirmar:
        cita.horario_por_confirmar = False
        cita.save(update_fields=['horario_por_confirmar', 'fecha_actualizacion'])

    _enriquecer_detalle_cita_desde_origen(cita)
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
    cotizacion = getattr(cita, 'cotizacion_canal_origen', None)
    oferta_servicio_id = _oferta_servicio_id_desde_cotizacion(cotizacion)
    categorias_req = datos.get('categorias_requeridas') or _categorias_desde_cotizacion(cotizacion)
    slot_kwargs = {
        'taller': taller,
        'modalidad': modalidad,
        'duracion_minutos': duracion,
        'oferta_servicio_id': oferta_servicio_id,
        'requiere_especialidad': bool(categorias_req or oferta_servicio_id),
    }

    if _cliente_pide_otro_rango(texto_cliente):
        offset = int(slots_ctx.get('offset_dias') or 0) + 7
        slots_ctx = _recopilar_slots_ofrecidos(
            offset_dias=offset,
            **slot_kwargs,
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
            offset_dias=offset,
            **slot_kwargs,
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
            categorias_requeridas=categorias_req or None,
        )
    except (ValidationError, ValueError) as exc:
        logger.info('Slot tomado o inválido en agendamiento IA: %s', exc)
        slots_ctx = _recopilar_slots_ofrecidos(**slot_kwargs)
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
