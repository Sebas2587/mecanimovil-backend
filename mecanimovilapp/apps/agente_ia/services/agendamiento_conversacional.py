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

# weekday Python: lun=0 … dom=6
_NOMBRE_DIA_A_WEEKDAY = {
    'lunes': 0,
    'lun': 0,
    'martes': 1,
    'mar': 1,
    'miercoles': 2,
    'miércoles': 2,
    'mie': 2,
    'mié': 2,
    'jueves': 3,
    'jue': 3,
    'viernes': 4,
    'vie': 4,
    'sabado': 5,
    'sábado': 5,
    'sab': 5,
    'sáb': 5,
    'domingo': 6,
    'dom': 6,
}

_PEDIR_MAS_FECHAS_RE = re.compile(
    r'\b(?:'
    r'otra\s+semana|semana\s+que\s+viene|m[aá]s\s+adelante|'
    r'otros?\s+d[ií]as?|m[aá]s\s+fechas|m[aá]s\s+opciones|'
    r'qu[eé]\s+otros?\s+d[ií]as?|alguna\s+otra\s+fecha|'
    r'ninguno\s+de\s+(?:esos|ellos|estos)|no\s+me\s+sirve\s+(?:ninguno|nada)'
    r')\b',
    re.IGNORECASE,
)

# Hora explícita: exige :MM, AM/PM, "hrs", o prefijo "a las" (evita tomar el "4" de "martes 4").
_HORA_RE = re.compile(
    r'(?:'
    r'(?:a\s+las?\s+|las\s+)(\d{1,2})(?::|\.)?(\d{2})?\s*(a\.?\s*m\.?|p\.?\s*m\.?|am|pm)?'
    r'|'
    r'\b(\d{1,2})(?::|\.)(\d{2})\s*(a\.?\s*m\.?|p\.?\s*m\.?|am|pm)?'
    r'|'
    r'\b(\d{1,2})\s*(a\.?\s*m\.?|p\.?\s*m\.?|am|pm)'
    r'|'
    r'\b(\d{1,2})\s*hrs?\b'
    r')',
    re.IGNORECASE,
)

_RANGO_HORA_RE = re.compile(
    r'\b(?:entre\s+las?\s*)?(\d{1,2})(?::(\d{2}))?\s*(a\.?\s*m\.?|p\.?\s*m\.?|am|pm)?'
    r'\s*(?:u|o|y|/|-|a)\s*'
    r'(?:las?\s*)?(\d{1,2})(?::(\d{2}))?\s*(a\.?\s*m\.?|p\.?\s*m\.?|am|pm)?',
    re.IGNORECASE,
)

_FECHA_DM_RE = re.compile(
    r'\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b',
)

_DIA_NOMBRE_RE = re.compile(
    r'\b(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|'
    r'lun|mar|mie|mi[eé]|jue|vie|sab|s[aá]b|dom)\b',
    re.IGNORECASE,
)


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
    datos.pop('fecha_agenda_pendiente', None)
    if categorias_req:
        datos['categorias_requeridas'] = categorias_req
    preferencias = _preferencias_agenda_desde_sesion(sesion, cita)
    if preferencias:
        datos['preferencias_agenda'] = preferencias
    mejor_previo = _mejor_slot_proximo(oferta, preferencias)
    if mejor_previo:
        oferta = dict(oferta)
        oferta['propuesta_actual'] = {
            'fecha': mejor_previo[0],
            'hora': mejor_previo[1],
        }
        datos['slots_ofrecidos'] = oferta
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
    """Solo pedidos explícitos de otra ventana — no 'el miércoles' ni 'martes 4'."""
    t = (texto or '').strip()
    if not t:
        return False
    # Si elige un día concreto, NUNCA desplazar la ventana.
    if _DIA_NOMBRE_RE.search(t) or _FECHA_DM_RE.search(t):
        return False
    return bool(_PEDIR_MAS_FECHAS_RE.search(t))


def _normalizar_hora(hora_str: str | None) -> str:
    """'9:00' / '9' / '10 AM' → 'HH:MM'."""
    raw = (hora_str or '').strip().lower().replace('.', '')
    if not raw:
        return ''
    m = re.match(
        r'^(\d{1,2})(?::(\d{2}))?\s*(a\s*m|p\s*m|am|pm)?$',
        raw,
    )
    if not m:
        return (hora_str or '').strip()
    h = int(m.group(1))
    mins = int(m.group(2) or 0)
    ampm = (m.group(3) or '').replace(' ', '')
    if ampm in ('pm', 'p.m', 'p.m.') and h < 12:
        h += 12
    if ampm in ('am', 'a.m', 'a.m.') and h == 12:
        h = 0
    if h > 23 or mins > 59:
        return ''
    return f'{h:02d}:{mins:02d}'


def _extraer_horas_candidatas(
    texto: str,
    *,
    permitir_hora_suelta: bool = False,
) -> list[str]:
    """Horas o rangos ('entre 10 y 11 AM') → lista de HH:MM preferidas."""
    t = texto or ''
    out: list[str] = []
    m_rango = _RANGO_HORA_RE.search(t)
    if m_rango:
        h1 = int(m_rango.group(1))
        min1 = int(m_rango.group(2) or 0)
        ap1 = (m_rango.group(3) or '').lower().replace('.', '').replace(' ', '')
        h2 = int(m_rango.group(4))
        min2 = int(m_rango.group(5) or 0)
        ap2 = (m_rango.group(6) or '').lower().replace('.', '').replace(' ', '')
        # Si solo el segundo trae AM/PM, aplícalo a ambos (10 u 11 AM).
        if not ap1 and ap2:
            ap1 = ap2
        if not ap2 and ap1:
            ap2 = ap1
        for h, mins, ap in ((h1, min1, ap1), (h2, min2, ap2)):
            norm = _normalizar_hora(f'{h}:{mins:02d} {ap}'.strip())
            if norm and norm not in out:
                out.append(norm)
        if out:
            return out
    for m in _HORA_RE.finditer(t):
        # Grupos: (1,2,3)=a las H[:MM][ampm] | (4,5,6)=H:MM[ampm] | (7,8)=H ampm | (9)=H hrs
        if m.group(1) is not None:
            h = int(m.group(1))
            mins = int(m.group(2) or 0)
            ap = (m.group(3) or '').lower().replace('.', '').replace(' ', '')
            norm = _normalizar_hora(f'{h}:{mins:02d} {ap}'.strip())
        elif m.group(4) is not None:
            h = int(m.group(4))
            mins = int(m.group(5))
            ap = (m.group(6) or '').lower().replace('.', '').replace(' ', '')
            norm = _normalizar_hora(f'{h}:{mins:02d} {ap}'.strip())
        elif m.group(7) is not None:
            h = int(m.group(7))
            ap = (m.group(8) or '').lower().replace('.', '').replace(' ', '')
            norm = _normalizar_hora(f'{h} {ap}'.strip())
        else:
            h = int(m.group(9))
            norm = _normalizar_hora(f'{h}:00')
        if norm and norm not in out:
            out.append(norm)
    # Con día ya elegido, aceptar "10" / "10:00" sueltos como hora.
    if not out and permitir_hora_suelta:
        m_suelta = re.match(
            r'^\s*(?:a\s+las?\s+)?(\d{1,2})(?::(\d{2}))?\s*(a\.?\s*m\.?|p\.?\s*m\.?|am|pm)?\s*[!.]?\s*$',
            t,
            re.I,
        )
        if m_suelta:
            h = int(m_suelta.group(1))
            mins = int(m_suelta.group(2) or 0)
            ap = (m_suelta.group(3) or '').lower().replace('.', '').replace(' ', '')
            if 7 <= h <= 20 or ap:
                norm = _normalizar_hora(f'{h}:{mins:02d} {ap}'.strip())
                if norm:
                    out.append(norm)
    return out


def _fechas_ofrecidas(slots_ctx: dict[str, Any]) -> list[str]:
    return list(slots_ctx.get('fechas') or [])


def _horas_del_dia(slots_ctx: dict[str, Any], fecha_iso: str) -> list[str]:
    slots = (slots_ctx.get('slots_por_dia') or {}).get(fecha_iso) or []
    horas: list[str] = []
    for s in slots:
        h = _normalizar_hora(s.get('hora'))
        if h and h not in horas:
            horas.append(h)
    return horas


def _resolver_fecha_por_nombre_dia(
    texto: str,
    fechas: list[str],
    *,
    hoy: date | None = None,  # noqa: ARG001 — API estable / callers
) -> str | None:
    """'lunes' / 'martes 4' → primera fecha ofrecida que calza."""
    m = _DIA_NOMBRE_RE.search(texto or '')
    if not m:
        return None
    key = m.group(1).lower().replace('é', 'e').replace('á', 'a')
    # Normalizar miércoles/miercoles/mie
    aliases = {
        'miercoles': 'miércoles',
        'mie': 'mié',
        'sabado': 'sábado',
        'sab': 'sáb',
    }
    nombre = aliases.get(key, m.group(1).lower())
    weekday = _NOMBRE_DIA_A_WEEKDAY.get(nombre) or _NOMBRE_DIA_A_WEEKDAY.get(key)
    if weekday is None:
        # Reintento con acentos del match original
        weekday = _NOMBRE_DIA_A_WEEKDAY.get(m.group(1).lower())
    if weekday is None:
        return None

    dia_num = None
    m_dia = re.search(
        r'\b(?:el\s+)?(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)'
        r'\s+(\d{1,2})\b',
        texto or '',
        re.I,
    )
    if m_dia:
        dia_num = int(m_dia.group(1))
    else:
        # "el martes 4" / "martes 4"
        m_dia2 = re.search(rf'\b{re.escape(m.group(1))}\s+(\d{{1,2}})\b', texto or '', re.I)
        if m_dia2:
            dia_num = int(m_dia2.group(1))

    candidatas = []
    for f_iso in fechas:
        try:
            f = date.fromisoformat(f_iso)
        except ValueError:
            continue
        if f.weekday() != weekday:
            continue
        if dia_num is not None and f.day != dia_num:
            continue
        candidatas.append(f_iso)
    return candidatas[0] if candidatas else None


def _resolver_fecha_por_dm(texto: str, fechas: list[str]) -> str | None:
    """'4/08', '4-8', '29/07' → ISO en lista ofrecida."""
    m = _FECHA_DM_RE.search(texto or '')
    if not m:
        return None
    dia = int(m.group(1))
    mes = int(m.group(2))
    anio_raw = m.group(3)
    for f_iso in fechas:
        try:
            f = date.fromisoformat(f_iso)
        except ValueError:
            continue
        if f.day == dia and f.month == mes:
            if anio_raw:
                anio = int(anio_raw)
                if anio < 100:
                    anio += 2000
                if f.year != anio:
                    continue
            return f_iso
    return None


def _elegir_hora_en_dia(
    horas_validas: list[str],
    horas_pedidas: list[str],
) -> str | None:
    if not horas_validas:
        return None
    for h in horas_pedidas:
        if h in horas_validas:
            return h
    # Rango 10–11: si ninguna exacta, primera del intervalo
    if len(horas_pedidas) >= 2:
        try:
            lo = min(horas_pedidas)
            hi = max(horas_pedidas)
            for h in horas_validas:
                if lo <= h <= hi:
                    return h
        except TypeError:
            pass
    return None


def _construir_resumen_horas(horas: list[str], *, max_n: int = 12) -> str:
    if not horas:
        return 'sin cupos'
    mostradas = horas[:max_n]
    texto = ', '.join(mostradas)
    if len(horas) > max_n:
        texto += f' (+{len(horas) - max_n} más)'
    return texto


def _match_slot_deterministico(
    texto_cliente: str,
    slots_ctx: dict[str, Any],
    *,
    fecha_pendiente: str | None = None,
) -> dict[str, Any]:
    """Parsea día/hora en español sin depender del LLM.

    Resultados:
      - match: fecha+hora válidos
      - dia_sin_hora: fecha OK, falta elegir hora
      - pedir_mas_fechas
      - consulta_dia: pregunta si un día tiene cupo
      - sin_match
    """
    texto = (texto_cliente or '').strip()
    if not texto:
        return {'resultado': 'sin_match', 'motivo': 'mensaje vacío'}

    if _cliente_pide_otro_rango(texto):
        return {'resultado': 'pedir_mas_fechas', 'motivo': 'pide otra ventana'}

    fechas = _fechas_ofrecidas(slots_ctx)
    horas_pedidas = _extraer_horas_candidatas(
        texto,
        permitir_hora_suelta=bool(fecha_pendiente),
    )

    # "mañana" / "pasado mañana" contra la lista ofrecida
    low = texto.lower()
    hoy = timezone.localdate()
    fecha_iso = _resolver_fecha_por_dm(texto, fechas)
    if not fecha_iso:
        if 'pasado mañana' in low or 'pasado manana' in low:
            cand = (hoy + timedelta(days=2)).isoformat()
            if cand in fechas:
                fecha_iso = cand
        elif re.search(r'\bma[nñ]ana\b', low):
            cand = (hoy + timedelta(days=1)).isoformat()
            if cand in fechas:
                fecha_iso = cand
    if not fecha_iso:
        fecha_iso = _resolver_fecha_por_nombre_dia(texto, fechas, hoy=hoy)

    # Si ya había día pendiente y ahora solo manda hora ("a las 10")
    if not fecha_iso and fecha_pendiente and fecha_pendiente in fechas and horas_pedidas:
        fecha_iso = fecha_pendiente

    # Confirmación implícita del slot propuesto: "sí", "ok", "dale"
    if not fecha_iso and not horas_pedidas:
        prop = slots_ctx.get('propuesta_actual') or {}
        if isinstance(prop, dict) and prop.get('fecha') and prop.get('hora'):
            if re.match(
                r'^\s*(?:s[ií]|ok|oka|okey|dale|perfecto|me\s+acomoda|de\s+acuerdo|'
                r'te\s+confirmo|ese|esa|ese\s+horario)\s*[!.]*\s*$',
                texto,
                re.I,
            ):
                return {
                    'resultado': 'match',
                    'fecha': prop['fecha'],
                    'hora': _normalizar_hora(prop['hora']),
                    'motivo': 'acepta propuesta',
                }

    # Nombre de día sin número (ej. "el lunes", "¿el miércoles?") → buscar el
    # próximo de ese weekday en ventana amplia (no el de dentro de 2 semanas).
    m_dia_solo = _DIA_NOMBRE_RE.search(texto)
    tiene_dia_num = bool(
        re.search(
            r'\b(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\s+\d{1,2}\b',
            texto,
            re.I,
        )
        or _FECHA_DM_RE.search(texto)
    )
    if m_dia_solo and not tiene_dia_num and not horas_pedidas:
        return {
            'resultado': 'consulta_dia',
            'fecha': fecha_iso,
            'hora': None,
            'motivo': 'buscar próximo día de semana',
            'texto_dia': m_dia_solo.group(1),
        }

    if not fecha_iso:
        if m_dia_solo:
            return {
                'resultado': 'consulta_dia',
                'fecha': None,
                'hora': None,
                'motivo': 'día no está en la oferta actual',
                'texto_dia': m_dia_solo.group(1),
            }
        return {'resultado': 'sin_match', 'motivo': 'no detecté día'}

    horas_validas = _horas_del_dia(slots_ctx, fecha_iso)
    if not horas_validas:
        return {
            'resultado': 'sin_match',
            'fecha': fecha_iso,
            'motivo': 'día sin cupos',
        }

    if horas_pedidas:
        hora = _elegir_hora_en_dia(horas_validas, horas_pedidas)
        if hora:
            return {
                'resultado': 'match',
                'fecha': fecha_iso,
                'hora': hora,
                'motivo': 'match determinístico',
            }
        return {
            'resultado': 'dia_sin_hora',
            'fecha': fecha_iso,
            'hora': None,
            'motivo': 'hora pedida no disponible ese día',
            'hora_pedida': horas_pedidas,
        }

    # Solo día → pedir hora (no inventar 08:00)
    return {
        'resultado': 'dia_sin_hora',
        'fecha': fecha_iso,
        'hora': None,
        'motivo': 'día elegido sin hora',
    }


def _prompt_match_slot(texto_cliente: str, slots_ctx: dict[str, Any]) -> str:
    hoy = timezone.localdate().isoformat()
    # Compactar contexto: fechas + horas por día (sin objetos largos)
    compacto: dict[str, Any] = {
        'fechas': slots_ctx.get('fechas') or [],
        'horas_por_dia': {
            f: _horas_del_dia(slots_ctx, f)[:16]
            for f in (slots_ctx.get('fechas') or [])[:12]
        },
    }
    slots_json = json.dumps(compacto, ensure_ascii=False)
    return f"""Eres un asistente de agendamiento de taller mecánico en Chile.
El cliente debe elegir un horario REAL de la lista. NO inventes fechas ni horas fuera de la lista.

Fecha de HOY (referencia para "mañana", "el miércoles", etc.): {hoy}

Slots disponibles (JSON):
{slots_json}

Mensaje del cliente:
{texto_cliente}

Responde SOLO JSON válido:
{{
  "resultado": "match|dia_sin_hora|sin_match|pedir_mas_fechas",
  "fecha": "YYYY-MM-DD o null",
  "hora": "HH:MM (24h, con cero: 09:00) o null",
  "motivo": "breve explicación en español"
}}

Reglas CRÍTICAS:
- Si el cliente elige un día de la lista (ej. "el miércoles", "martes 4", "4/08") SIN hora → resultado "dia_sin_hora" con esa fecha. NUNCA "pedir_mas_fechas".
- "match" solo si fecha+hora existen exactamente en horas_por_dia (hora en formato HH:MM).
- "pedir_mas_fechas" SOLO si pide explícitamente otra semana / más fechas / otros días, SIN elegir uno concreto.
- "sin_match" si no calza con ningún slot ofrecido.
- Normaliza "10 AM" → "10:00", "9" → "09:00"."""


def _interpretar_slot_cliente(
    texto_cliente: str,
    slots_ctx: dict[str, Any],
    *,
    fecha_pendiente: str | None = None,
) -> dict[str, Any]:
    det = _match_slot_deterministico(
        texto_cliente,
        slots_ctx,
        fecha_pendiente=fecha_pendiente,
    )
    if det.get('resultado') in ('match', 'dia_sin_hora', 'pedir_mas_fechas', 'consulta_dia'):
        return det

    decision, error = _llamar_gemini_agente(_prompt_match_slot(texto_cliente, slots_ctx))
    if not decision:
        logger.warning('Gemini agendamiento sin respuesta: %s', error)
        return det if det.get('resultado') != 'sin_match' else {
            'resultado': 'sin_match',
            'motivo': error or 'No pude interpretar la respuesta.',
        }
    # Normalizar hora del LLM
    if decision.get('hora'):
        decision['hora'] = _normalizar_hora(decision.get('hora'))
    # Guardrail: si el LLM dice pedir_mas_fechas pero el texto elige un día, ignóralo
    if (decision.get('resultado') or '').lower() == 'pedir_mas_fechas' and (
        _DIA_NOMBRE_RE.search(texto_cliente or '') or _FECHA_DM_RE.search(texto_cliente or '')
    ):
        decision['resultado'] = 'dia_sin_hora' if decision.get('fecha') else 'sin_match'
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
    omitir_especialidad = False
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
            omitir_especialidad = True
        else:
            raise
    cabecera: dict[str, Any] = {
        'fecha_servicio': fecha,
        'hora_servicio': hora,
    }
    if miembro is not None:
        cabecera['miembro_taller'] = miembro.id

    try:
        cita = actualizar_cita_personal(
            cita,
            cabecera=cabecera,
            omitir_especialidad=omitir_especialidad,
        )
    except ValidationError:
        # Último recurso: el cupo se ofreció con filtros relajados; confirmar
        # sin exigir especialidad del catálogo (evita falso "acaba de tomarse").
        if not omitir_especialidad:
            cita = actualizar_cita_personal(
                cita,
                cabecera=cabecera,
                omitir_especialidad=True,
            )
        else:
            raise

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

    fecha_pendiente = (datos.get('fecha_agenda_pendiente') or '').strip() or None

    if _cliente_pide_otro_rango(texto_cliente):
        offset = int(slots_ctx.get('offset_dias') or 0) + 7
        slots_ctx = _recopilar_slots_ofrecidos(
            offset_dias=offset,
            **slot_kwargs,
        )
        datos['slots_ofrecidos'] = slots_ctx
        datos.pop('fecha_agenda_pendiente', None)
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

    decision = _interpretar_slot_cliente(
        texto_cliente,
        slots_ctx,
        fecha_pendiente=fecha_pendiente,
    )
    resultado = (decision.get('resultado') or 'sin_match').strip().lower()

    if resultado == 'pedir_mas_fechas':
        offset = int(slots_ctx.get('offset_dias') or 0) + 7
        slots_ctx = _recopilar_slots_ofrecidos(
            offset_dias=offset,
            **slot_kwargs,
        )
        datos['slots_ofrecidos'] = slots_ctx
        datos.pop('fecha_agenda_pendiente', None)
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

    # Cliente pregunta por un día (ej. "¿el lunes?") que no está en la ventana actual:
    # ampliar búsqueda SIN descartar si aparece, o explicar el próximo de ese weekday.
    if resultado == 'consulta_dia':
        texto_dia = (decision.get('texto_dia') or '').strip()
        amplio = _recopilar_slots_ofrecidos(
            offset_dias=0,
            dias_adelante=21,
            **slot_kwargs,
        )
        fecha_amplia = _resolver_fecha_por_nombre_dia(
            texto_cliente,
            amplio.get('fechas') or [],
        )
        if fecha_amplia:
            # Fusiona la ventana actual con la nueva (no pierdas fechas cercanas).
            fechas_merge = list(dict.fromkeys(
                (slots_ctx.get('fechas') or []) + (amplio.get('fechas') or [])
            ))
            slots_merge = dict(slots_ctx.get('slots_por_dia') or {})
            slots_merge.update(amplio.get('slots_por_dia') or {})
            slots_ctx = {
                **slots_ctx,
                'fechas': sorted(fechas_merge),
                'slots_por_dia': slots_merge,
                'offset_dias': 0,
            }
            datos['slots_ofrecidos'] = slots_ctx
            datos['fecha_agenda_pendiente'] = fecha_amplia
            sesion.datos_capturados = datos
            sesion.save(update_fields=['datos_capturados', 'actualizado_en'])
            horas = _horas_del_dia(slots_ctx, fecha_amplia)
            respuesta = (
                f'Sí, el {_formatear_fecha_legible(fecha_amplia)} tengo disponibilidad. '
                f'Horarios: {_construir_resumen_horas(horas)}. ¿Cuál te acomoda?'
            )
            enviar_respuesta_agente(
                conversation=conversation,
                proveedor_user_id=proveedor_user_id,
                texto=respuesta,
            )
            return {'ok': True, 'accion': 'consultar_dia', 'fecha': fecha_amplia}
        nombre = texto_dia or 'ese día'
        resumen = _construir_resumen_dias(slots_ctx.get('fechas') or [])
        respuesta = (
            f'Por ahora no veo cupos el {nombre} en las próximas semanas. '
            f'Tengo estos días: {resumen}. ¿Cuál prefieres y a qué hora?'
        )
        enviar_respuesta_agente(
            conversation=conversation,
            proveedor_user_id=proveedor_user_id,
            texto=respuesta,
        )
        return {'ok': True, 'accion': 'consulta_dia_sin_cupo'}

    fecha_iso = (decision.get('fecha') or '').strip()
    hora_str = _normalizar_hora(decision.get('hora'))
    horas_validas_list = _horas_del_dia(slots_ctx, fecha_iso) if fecha_iso else []
    horas_validas = set(horas_validas_list)

    # Día elegido sin hora (o hora pedida no disponible) → listar horas de ESE día.
    if resultado == 'dia_sin_hora' and fecha_iso and fecha_iso in (slots_ctx.get('fechas') or []):
        datos['fecha_agenda_pendiente'] = fecha_iso
        sesion.datos_capturados = datos
        sesion.save(update_fields=['datos_capturados', 'actualizado_en'])
        horas = horas_validas_list
        pedidas = decision.get('hora_pedida') or []
        if pedidas:
            respuesta = (
                f'El {_formatear_fecha_legible(fecha_iso)} no tengo '
                f'{"/".join(pedidas)}, pero sí: {_construir_resumen_horas(horas)}. '
                '¿Cuál te acomoda?'
            )
        else:
            respuesta = (
                f'Perfecto, el {_formatear_fecha_legible(fecha_iso)}. '
                f'Tengo estos horarios: {_construir_resumen_horas(horas)}. ¿Cuál prefieres?'
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
            metadata={'agendamiento': True, 'dia_sin_hora': True, 'fecha': fecha_iso},
        )
        return {'ok': True, 'accion': 'pedir_hora', 'fecha': fecha_iso}

    if resultado != 'match' or not fecha_iso or not hora_str or hora_str not in horas_validas:
        # Si al menos detectamos día, no digas "no ubiqué" genérico: pide hora.
        if fecha_iso and fecha_iso in (slots_ctx.get('fechas') or []):
            datos['fecha_agenda_pendiente'] = fecha_iso
            sesion.datos_capturados = datos
            sesion.save(update_fields=['datos_capturados', 'actualizado_en'])
            horas = _horas_del_dia(slots_ctx, fecha_iso)
            respuesta = (
                f'Para el {_formatear_fecha_legible(fecha_iso)} tengo: '
                f'{_construir_resumen_horas(horas)}. ¿A qué hora te acomoda?'
            )
            enviar_respuesta_agente(
                conversation=conversation,
                proveedor_user_id=proveedor_user_id,
                texto=respuesta,
            )
            return {'ok': True, 'accion': 'pedir_hora', 'fecha': fecha_iso}
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
        logger.info('Slot inválido en agendamiento IA: %s', exc)
        # Revalidar cupo real del día antes de decir "tomado".
        slots_frescos = _obtener_slots_dia(
            taller=taller,
            fecha_iso=fecha_iso,
            modalidad=modalidad,
            duracion_minutos=duracion,
            oferta_servicio_id=oferta_servicio_id,
            requiere_especialidad=bool(categorias_req or oferta_servicio_id),
        )
        horas_frescas = [_normalizar_hora(s.get('hora')) for s in slots_frescos]
        # Excluir explícitamente la hora que falló para evitar bucles repetitivos
        horas_frescas = [h for h in horas_frescas if h and h != hora_str]
        
        if horas_frescas:
            datos['fecha_agenda_pendiente'] = fecha_iso
            slots_por_dia = dict(slots_ctx.get('slots_por_dia') or {})
            slots_por_dia[fecha_iso] = [s for s in slots_frescos if _normalizar_hora(s.get('hora')) != hora_str]
            slots_ctx = {**slots_ctx, 'slots_por_dia': slots_por_dia}
            datos['slots_ofrecidos'] = slots_ctx
            sesion.datos_capturados = datos
            sesion.save(update_fields=['datos_capturados', 'actualizado_en'])
            respuesta = (
                f'El horario de las {hora_str} no quedó disponible para la reserva del '
                f'{_formatear_fecha_legible(fecha_iso)}. '
                f'Para ese mismo día tengo disponibles: '
                f'{_construir_resumen_horas(horas_frescas)}.'
            )
        else:
            slots_ctx = _recopilar_slots_ofrecidos(**slot_kwargs)
            datos['slots_ofrecidos'] = slots_ctx
            datos.pop('fecha_agenda_pendiente', None)
            sesion.datos_capturados = datos
            sesion.save(update_fields=['datos_capturados', 'actualizado_en'])
            respuesta = (
                f'No tenemos cupo disponible en las {hora_str} del {_formatear_fecha_legible(fecha_iso)}. '
                f'Te ofrezco estos días disponibles: {_construir_resumen_dias(slots_ctx.get("fechas") or [])}. '
                '¿Cuál te acomoda mejor?'
            )
        enviar_respuesta_agente(
            conversation=conversation,
            proveedor_user_id=proveedor_user_id,
            texto=respuesta,
        )
        return {'ok': True, 'accion': 'slot_ocupado'}

    datos.pop('fecha_agenda_pendiente', None)
    sesion.datos_capturados = datos
    sesion.save(update_fields=['datos_capturados', 'actualizado_en'])

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
