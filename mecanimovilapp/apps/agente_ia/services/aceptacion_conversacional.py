"""Post-envío: aceptación verbal y dudas sin reservar cupo."""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import timedelta
from typing import Any

from django.utils import timezone

from mecanimovilapp.apps.agente_ia.models import AgenteConversacionSesion, AgenteMensajeLog
from mecanimovilapp.apps.agente_ia.services.alcance_pedido import (
    _cliente_pide_agregar_a_cotizacion,
    _cliente_pide_quitar_de_cotizacion,
)
from mecanimovilapp.apps.agente_ia.services.duracion_trabajo import (
    formatear_duracion_humana,
    resolver_duracion_trabajo,
)
from mecanimovilapp.apps.chat.models import Conversation, Message
from mecanimovilapp.apps.ordenes.models import CotizacionCanal

logger = logging.getLogger(__name__)

_ACEPTA_FUERTE_RE = re.compile(
    r'(?:'
    r'\b(?:la\s+acepto|acepto\s+la\s+cotizaci[oó]n|acepto\s+la\s+coti|'
    r'dale\s+con\s+esa|vamos\s+con\s+esa|'
    r'me\s+parece\s+ok|me\s+parece\s+bien|'
    r'est[aá]\s+ok|ok\s+la\s+coti|ok\s+el\s+precio|'
    r'aprobada|aprobemos|cerramos|la\s+tomo|hagamos\s+esa)\b|'
    r'estoy\s+viendo\s+la\s+coti(?:zaci[oó]n)?\s+y\s+me\s+parece\s+(?:ok|bien)'
    r')',
    re.IGNORECASE,
)

_RECHAZA_RE = re.compile(
    r'\b(?:'
    r'me\s+parece\s+cara|est[aá]\s+cara|muy\s+caro|'
    r'lo\s+voy\s+a\s+pensar|la\s+voy\s+a\s+pensar|'
    r'lo\s+pienso|d[eé]jamelo\s+pensar'
    r')\b',
    re.IGNORECASE,
)

_OK_SUELTO_RE = re.compile(
    r'^\s*(?:ok|oka|okey|dale|s[ií]|perfecto)\s*[!.]*\s*$',
    re.IGNORECASE,
)

_PREGUNTA_ACEPTA_RE = re.compile(
    r'aceptas|aceptar\s+la\s+cotiz|confirmas\s+que\s+acept',
    re.IGNORECASE,
)

_MISMO_DIA_RE = re.compile(
    r'(?:'
    r'mismo\s+d[ií]a|'
    r'el\s+mismo\s+d[ií]a|'
    r'queda\s+listo\s+hoy|'
    r'lo\s+hacen\s+hoy|'
    r'lo\s+hacen\s+en\s+el\s+mismo|'
    r'dentro\s+del\s+mismo\s+d[ií]a'
    r')',
    re.IGNORECASE,
)

_DURACION_PREGUNTA_RE = re.compile(
    r'(?:'
    r'cu[aá]nto\s+(?:se\s+)?demora|'
    r'cu[aá]ntas\s+horas|'
    r'cu[aá]nto\s+dura|'
    r'cu[aá]nto\s+tiempo|'
    r'tiempo\s+toma|'
    r'cu[aá]nto\s+se\s+tarda'
    r')',
    re.IGNORECASE,
)

_AGENDA_INTENT_RE = re.compile(
    r'\b(?:'
    r'ma[nñ]ana|pasado\s+ma[nñ]ana|'
    r'lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|'
    r'a\s+las\s+\d{1,2}|'
    r'\d{1,2}\s*(?:am|pm|hrs?)|'
    r'horario|agendar|coordin(?:ar|emos)|'
    r'qu[eé]\s+d[ií]a|puedo\s+agendar|puede\s+ser'
    r')\b',
    re.IGNORECASE,
)

_PAGO_RE = re.compile(
    r'\b(?:cuenta|transferencia|medios?\s+de\s+pago|comprobante|banco|rut)\b',
    re.IGNORECASE,
)

def cotizacion_enviada_de_sesion(sesion: AgenteConversacionSesion) -> CotizacionCanal | None:
    """Cotización enviada de este chat: la ligada a la sesión, o la más reciente no adicional."""
    cot = getattr(sesion, 'cotizacion_borrador', None)
    if cot is not None and cot.estado == 'enviada':
        return cot
    conv_id = getattr(sesion, 'conversation_id', None)
    if not conv_id:
        return None
    qs = CotizacionCanal.objects.filter(
        conversation_id=conv_id,
        estado='enviada',
        es_cotizacion_adicional=False,
    )
    if cot is not None:
        ligada = qs.filter(pk=cot.id).first()
        if ligada is not None:
            return ligada
    return qs.order_by('-enviada_en', '-id').first()


def cliente_acepta_cotizacion(
    texto: str,
    *,
    ultimo_mensaje_agente: str = '',
) -> bool | None:
    """True = acepta, False = no, None = ok ambiguo (pedir confirmación)."""
    t = (texto or '').strip()
    if not t:
        return False
    if _RECHAZA_RE.search(t):
        return False
    if _cliente_pide_agregar_a_cotizacion(t) or _cliente_pide_quitar_de_cotizacion(t):
        return False
    if _ACEPTA_FUERTE_RE.search(t):
        return True
    if _OK_SUELTO_RE.match(t):
        if _PREGUNTA_ACEPTA_RE.search(ultimo_mensaje_agente or ''):
            return True
        return None
    return False


def _pide_modificar_cotizacion(texto: str) -> bool:
    t = (texto or '').strip()
    if _cliente_pide_agregar_a_cotizacion(t) or _cliente_pide_quitar_de_cotizacion(t):
        return True
    raw = unicodedata.normalize('NFKD', t)
    sin = ''.join(ch for ch in raw if not unicodedata.combining(ch)).lower()
    return bool(re.search(r'\b(?:sumale|agrega|quita|saca|cambia\s+a)\b', sin))


def _ultimo_mensaje_agente(conversation: Conversation) -> str:
    msg = (
        Message.objects.filter(conversation=conversation, direction='outbound')
        .order_by('-id')
        .first()
    )
    return (msg.content or '') if msg else ''


def aceptar_desde_agente(
    *,
    sesion: AgenteConversacionSesion,
    cotizacion: CotizacionCanal,
    conversation: Conversation,
) -> dict[str, Any]:
    """Misma tubería que la página. Idempotente si ya está aceptada."""
    from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
        aceptar_cotizacion_publica,
        on_cotizacion_respondida,
    )

    if cotizacion.estado == 'aceptada':
        if sesion.estado != AgenteConversacionSesion.ESTADO_AGENDANDO:
            from mecanimovilapp.apps.agente_ia.tasks import iniciar_agendamiento_task

            iniciar_agendamiento_task.delay(cotizacion.id)
        return {
            'ok': True,
            'accion': 'ya_aceptada',
            'cotizacion_id': cotizacion.id,
        }
    if cotizacion.estado != 'enviada':
        return {'ok': False, 'accion': 'estado_invalido', 'estado': cotizacion.estado}

    try:
        cotizacion, cita = aceptar_cotizacion_publica(cotizacion)
    except ValueError as exc:
        logger.info('aceptar_desde_agente no pudo aceptar cot=%s: %s', cotizacion.id, exc)
        return {'ok': False, 'accion': 'error_aceptar', 'error': str(exc)}

    on_cotizacion_respondida(
        cotizacion,
        'aceptar',
        conversation=conversation,
        cita_id=cita.id if cita else None,
    )
    return {
        'ok': True,
        'accion': 'aceptada',
        'cotizacion_id': cotizacion.id,
        'cita_id': cita.id if cita else None,
    }


def _guardar_preferencia_agenda(sesion: AgenteConversacionSesion, texto: str) -> dict[str, str]:
    from mecanimovilapp.apps.agente_ia.services.agendamiento_conversacional import (
        _DIA_NOMBRE_RE,
        _extraer_horas_candidatas,
        _NOMBRE_DIA_A_WEEKDAY,
    )

    datos = dict(sesion.datos_capturados or {})
    pref = dict(datos.get('preferencias_agenda') or {})
    hoy = timezone.localdate()
    low = (texto or '').lower()

    if 'pasado mañana' in low or 'pasado manana' in low:
        pref['fecha'] = (hoy + timedelta(days=2)).isoformat()
    elif re.search(r'\bma[nñ]ana\b', low):
        pref['fecha'] = (hoy + timedelta(days=1)).isoformat()
    elif re.search(r'\bhoy\b', low):
        pref['fecha'] = hoy.isoformat()
    else:
        m_dia = _DIA_NOMBRE_RE.search(texto or '')
        if m_dia:
            key = m_dia.group(1).lower().replace('é', 'e').replace('á', 'a')
            weekday = _NOMBRE_DIA_A_WEEKDAY.get(m_dia.group(1).lower()) or _NOMBRE_DIA_A_WEEKDAY.get(key)
            if weekday is not None:
                delta = (weekday - hoy.weekday()) % 7
                if delta == 0:
                    delta = 7
                pref['fecha'] = (hoy + timedelta(days=delta)).isoformat()

    horas = _extraer_horas_candidatas(texto or '')
    if horas:
        pref['hora'] = horas[0]
    pref['confirmado_verbal'] = False
    datos['preferencias_agenda'] = pref
    sesion.datos_capturados = datos
    sesion.save(update_fields=['datos_capturados', 'actualizado_en'])
    return pref


def _copy_invitar_aceptar(cotizacion: CotizacionCanal) -> str:
    servicio = (cotizacion.servicio_nombre or 'el servicio').strip()
    total = int(cotizacion.total_clp or 0)
    monto = f' por ${total:,}'.replace(',', '.') if total else ''
    return (
        f'La cotización de {servicio}{monto} ya te la enviaron. '
        'Si te acomoda, acéptala en el detalle o dime que la aceptas '
        'y coordinamos el día con la agenda real del taller.'
    )


def _copy_duracion(cotizacion: CotizacionCanal) -> str:
    minutos = resolver_duracion_trabajo(cotizacion)
    humana = formatear_duracion_humana(minutos)
    if minutos >= 240:
        extra = (
            f' Ese trabajo suele tomar {humana}; si partimos a primera hora, '
            'podemos dejarlo listo dentro del mismo día.'
        )
    else:
        extra = f' Ese trabajo suele tomar {humana}.'
    return extra.strip() + ' ' + _copy_invitar_aceptar(cotizacion)


def _copy_preferencia_guardada(pref: dict[str, str], cotizacion: CotizacionCanal) -> str:
    partes = []
    if pref.get('fecha'):
        partes.append(pref['fecha'])
    if pref.get('hora'):
        partes.append(f"a las {pref['hora']}")
    cuando = ' '.join(partes) if partes else 'ese horario'
    return (
        f'Anoto {cuando} como preferencia. '
        'Para confirmar el cupo hay que aceptar la cotización: '
        'házlo en el detalle o dime que la aceptas.'
    )


def _responder(
    *,
    sesion: AgenteConversacionSesion,
    conversation: Conversation,
    proveedor_user_id: int,
    texto_cliente: str,
    respuesta: str,
    accion: str,
    extra_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from mecanimovilapp.apps.agente_ia.services.orquestador import enviar_respuesta_agente

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
        metadata={'esperando_aceptacion': True, 'accion': accion, **(extra_meta or {})},
    )
    return {'ok': True, 'accion': accion}


def procesar_turno_esperando_aceptacion(
    *,
    sesion: AgenteConversacionSesion,
    texto_cliente: str,
    conversation: Conversation,
    proveedor_user_id: int,
) -> dict[str, Any]:
    """Dudas + aceptación verbal. `fallthrough` si el cliente quiere modificar la coti."""
    if _pide_modificar_cotizacion(texto_cliente):
        return {'ok': True, 'accion': 'fallthrough'}

    cotizacion = cotizacion_enviada_de_sesion(sesion)
    if cotizacion is None:
        return {'ok': True, 'accion': 'fallthrough'}

    ultimo = _ultimo_mensaje_agente(conversation)
    decision = cliente_acepta_cotizacion(texto_cliente, ultimo_mensaje_agente=ultimo)

    if decision is True:
        result = aceptar_desde_agente(
            sesion=sesion,
            cotizacion=cotizacion,
            conversation=conversation,
        )
        AgenteMensajeLog.objects.create(
            sesion=sesion,
            mensaje_entrante=texto_cliente,
            respuesta_generada='[aceptacion_verbal]',
            accion=AgenteMensajeLog.ACCION_RESPONDER,
            metadata={'esperando_aceptacion': True, **result},
        )
        # El primer mensaje de agenda lo escribe iniciar_agendamiento (task).
        return result

    if decision is None:
        servicio = (cotizacion.servicio_nombre or 'el servicio').strip()
        total = int(cotizacion.total_clp or 0)
        monto = f' por ${total:,}'.replace(',', '.') if total else ''
        return _responder(
            sesion=sesion,
            conversation=conversation,
            proveedor_user_id=proveedor_user_id,
            texto_cliente=texto_cliente,
            respuesta=f'¿Confirmas que aceptas la cotización de {servicio}{monto}?',
            accion='confirmar_aceptacion',
        )

    if _MISMO_DIA_RE.search(texto_cliente) or _DURACION_PREGUNTA_RE.search(texto_cliente):
        return _responder(
            sesion=sesion,
            conversation=conversation,
            proveedor_user_id=proveedor_user_id,
            texto_cliente=texto_cliente,
            respuesta=_copy_duracion(cotizacion),
            accion='duda_duracion',
        )

    if _AGENDA_INTENT_RE.search(texto_cliente):
        pref = _guardar_preferencia_agenda(sesion, texto_cliente)
        return _responder(
            sesion=sesion,
            conversation=conversation,
            proveedor_user_id=proveedor_user_id,
            texto_cliente=texto_cliente,
            respuesta=_copy_preferencia_guardada(pref, cotizacion),
            accion='preferencia_sin_aceptar',
            extra_meta={'preferencias_agenda': pref},
        )

    if _PAGO_RE.search(texto_cliente):
        return _responder(
            sesion=sesion,
            conversation=conversation,
            proveedor_user_id=proveedor_user_id,
            texto_cliente=texto_cliente,
            respuesta=(
                'El detalle de pago aparece en la cotización. '
                'No te invento banco ni cuenta: si aceptas, el taller te confirma '
                'cómo cancelar los repuestos. '
                + _copy_invitar_aceptar(cotizacion)
            ),
            accion='duda_pago',
        )

    from mecanimovilapp.apps.agente_ia.services.orquestador import _llamar_gemini_agente

    minutos = resolver_duracion_trabajo(cotizacion)
    prompt = (
        'Eres el asesor del taller por WhatsApp. La cotización YA FUE ENVIADA '
        f'({cotizacion.servicio_nombre}, ${int(cotizacion.total_clp or 0)}). '
        f'Duración estimada: {formatear_duracion_humana(minutos)}. '
        'Responde la duda del cliente en 1-2 frases, español chileno. '
        'PROHIBIDO confirmar día, hora, "quedamos listos" o "tenemos disponibilidad". '
        'PROHIBIDO inventar banco, RUT o correo de comprobante. '
        'Cierra invitando a aceptar la cotización en el detalle o diciéndotelo. '
        f'Cliente: {texto_cliente}\n'
        'Responde SOLO JSON: {"respuesta_cliente": "..."}'
    )
    data, _err = _llamar_gemini_agente(prompt)
    texto_llm = ''
    if isinstance(data, dict):
        texto_llm = (data.get('respuesta_cliente') or '').strip()
    if not texto_llm:
        texto_llm = _copy_invitar_aceptar(cotizacion)
    return _responder(
        sesion=sesion,
        conversation=conversation,
        proveedor_user_id=proveedor_user_id,
        texto_cliente=texto_cliente,
        respuesta=texto_llm,
        accion='duda_general',
    )
