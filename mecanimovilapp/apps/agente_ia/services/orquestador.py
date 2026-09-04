"""Orquestador principal del agente IA conversacional."""
from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from typing import Any

import requests
from django.conf import settings
from django.utils import timezone

from mecanimovilapp.apps.agente_ia.models import (
    AgenteClienteMemoria,
    AgenteConversacionSesion,
    AgenteMensajeLog,
    LeadCalificacion,
    TallerAgenteConfig,
)
from mecanimovilapp.apps.agente_ia.services.cotizacion_borrador import (
    crear_cotizacion_borrador_desde_agente,
    procesar_ficha_sdr_spec,
)
from mecanimovilapp.apps.agente_ia.specs.agente_1_sdr_spec import (
    FichaLeadCapturada,
    VehiculoCapturado,
    ClienteCapturado,
)
from mecanimovilapp.apps.agente_ia.specs.agente_2_agenda_spec import (
    CoordinacionCitaOutput,
    BloqueHorarioSugerido,
)
from mecanimovilapp.apps.agente_ia.services.alcance_pedido import (
    _CLIENTE_PIDE_PRECIO_RE,
    _SOLO_SERVICIO_RE,
    _acotar_servicios_al_pedido,
    _clave_servicio_dedup,
    _cliente_niega_pedir_precio,
    _cliente_pide_agregar_a_cotizacion,
    _cliente_pide_quitar_de_cotizacion,
    _extraer_servicios_mencionados_en_texto,
)
from mecanimovilapp.apps.agente_ia.services.notificaciones import notificar_escalamiento_humano
from mecanimovilapp.apps.agente_ia.services.rag import buscar_contexto_taller_combinado
from mecanimovilapp.apps.agente_ia.services.taller_resolver import canal_conversacion, resolver_taller_desde_conversation
from mecanimovilapp.apps.chat.models import Conversation, Message

logger = logging.getLogger(__name__)

_MENSAJES_RECIENTES_LIMITE = 16
_RESUMEN_CONVERSACION_MAX = 500

_JSON_FENCE = re.compile(r'```(?:json)?\s*([\s\S]*?)\s*```', re.IGNORECASE)


def agente_ia_habilitado() -> bool:
    return bool(getattr(settings, 'AGENTE_IA_CHAT_ENABLED', False))


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


def _mensajes_recientes(conversation: Conversation, limite: int = _MENSAJES_RECIENTES_LIMITE) -> str:
    lineas: list[str] = []
    qs = conversation.messages.order_by('-timestamp')[:limite]
    for msg in reversed(list(qs)):
        quien = 'Cliente' if msg.direction == 'inbound' else 'Taller'
        meta = msg.channel_metadata or {}
        if meta.get('from_agente_ia'):
            quien = 'Asistente IA'
        texto = (msg.content or '').strip()
        analisis = meta.get('media_analisis') if isinstance(meta.get('media_analisis'), dict) else None
        if analisis and analisis.get('resumen_para_chat'):
            resumen = str(analisis['resumen_para_chat']).strip()
            if resumen and resumen not in texto:
                kind = analisis.get('tipo_medio') or 'media'
                texto = f'{texto} [{kind}: {resumen}]'.strip() if texto else f'[{kind}: {resumen}]'
        elif meta.get('media') and not texto:
            kind = (meta.get('media') or {}).get('kind') or 'adjunto'
            texto = f'[{kind}]'
        if texto:
            lineas.append(f'{quien}: {texto[:700]}')
    return '\n'.join(lineas) or 'Sin mensajes.'


def _fusionar_resumen_conversacion(previo: str, turno: str) -> str:
    """Acumula resumen de conversación larga sin crecer indefinidamente."""
    turno = (turno or '').strip()
    if not turno:
        return (previo or '').strip()
    base = (previo or '').strip()
    if base and turno.lower() in base.lower():
        return base[:_RESUMEN_CONVERSACION_MAX]
    merged = f'{base} {turno}'.strip() if base else turno
    if len(merged) <= _RESUMEN_CONVERSACION_MAX:
        return merged
    return merged[-_RESUMEN_CONVERSACION_MAX:].lstrip(' ,.;')


def _disposicion_desde_senal(senal: str) -> str:
    s = (senal or '').strip().lower()
    if s in ('listo_agendar',):
        return AgenteClienteMemoria.DISPOSICION_LISTO_AGENDAR
    if s in ('interesado',):
        return AgenteClienteMemoria.DISPOSICION_INTERESADO
    if s in ('sin_presupuesto', 'comparando_precios'):
        return AgenteClienteMemoria.DISPOSICION_NO_LISTO
    if s in ('curioso', 'no_automotriz'):
        return AgenteClienteMemoria.DISPOSICION_CURIOSO
    return ''


def _obtener_memoria_cliente(taller_id: int, external_contact_id: int | None) -> AgenteClienteMemoria | None:
    if not external_contact_id:
        return None
    return AgenteClienteMemoria.objects.filter(
        taller_id=taller_id,
        external_contact_id=external_contact_id,
    ).first()


def _upsert_memoria_cliente(
    *,
    taller_id: int,
    external_contact_id: int | None,
    conversation_id: int,
    resumen: str,
    senal_lead: str,
) -> None:
    if not external_contact_id:
        return
    disposicion = _disposicion_desde_senal(senal_lead)
    resumen_txt = (resumen or '').strip()[:2000]
    if not resumen_txt and not disposicion:
        return
    defaults: dict[str, Any] = {
        'ultima_conversacion_id': conversation_id,
    }
    if resumen_txt:
        defaults['resumen'] = resumen_txt
    if disposicion:
        defaults['disposicion_reciente'] = disposicion
    AgenteClienteMemoria.objects.update_or_create(
        taller_id=taller_id,
        external_contact_id=external_contact_id,
        defaults=defaults,
    )


def _mensaje_cliente_superado(message: Message) -> bool:
    """True si llegó otro mensaje del cliente después (debounce / pensar con contexto completo)."""
    from mecanimovilapp.apps.agente_ia.hooks import es_mensaje_de_cliente

    for newer in Message.objects.filter(
        conversation_id=message.conversation_id,
        id__gt=message.id,
    ).order_by('id')[:20]:
        if es_mensaje_de_cliente(newer):
            return True
    return False


def _contexto_minimo_para_cotizar(
    datos: dict,
    *,
    requiere_direccion_antes_de_cotizar: bool = False,
) -> bool:
    vehiculo = datos.get('vehiculo') or {}
    patente = (
        (vehiculo.get('patente') or '').strip()
        or (datos.get('patente_enriquecida') or '').strip()
    )
    if not patente:
        return False
    telefono = (datos.get('cliente_telefono') or '').strip()
    if len(''.join(c for c in telefono if c.isdigit())) < 8:
        return False
    problema = (
        (datos.get('descripcion_problema') or '').strip()
        or (datos.get('servicio_nombre') or '').strip()
    )
    if len(problema) < 12:
        return False
    if requiere_direccion_antes_de_cotizar:
        modalidad = (datos.get('modalidad') or '').strip().lower()
        if modalidad != 'taller':
            # Cliente pidió cotización primero / dirección después → no bloquear borrador.
            if datos.get('direccion_diferida'):
                return True
            # Comuna o sector basta para armar borrador (calle exacta al coordinar visita).
            direccion = (datos.get('direccion_servicio') or '').strip()
            if len(direccion) < 4:
                return False
    return True


# Comunas frecuentes RM + algunas regiones (match case-insensitive).
_COMUNAS_CL_KNOWN = frozenset(
    {
        'vitacura',
        'las condes',
        'providencia',
        'santiago',
        'ñuñoa',
        'nunoa',
        'la reina',
        'lo barnechea',
        'huechuraba',
        'recoleta',
        'independencia',
        'maipu',
        'maipú',
        'puente alto',
        'la florida',
        'macul',
        'peñalolen',
        'penalolen',
        'san miguel',
        'la cisterna',
        'el bosque',
        'san bernardo',
        'colina',
        'quilicura',
        'renca',
        'cerro navia',
        'pudahuel',
        'estacion central',
        'estación central',
        'conchali',
        'conchalí',
        'lo prado',
        'pedro aguirre cerda',
        'san joaquin',
        'san joaquín',
        'la granja',
        'la pintana',
        'el monte',
        'talagante',
        'buin',
        'paine',
        'melipilla',
        'valparaiso',
        'valparaíso',
        'viña del mar',
        'vina del mar',
        'concepcion',
        'concepción',
        'temuco',
        'antofagasta',
        'la serena',
        'rancagua',
    }
)

_DIRECCION_CAPTURA_RE = re.compile(
    r'(?:'
    r'(?:vivo|estoy|quedo|qued[eé]|ando|andamos)\s+en\s+'
    r'(?P<p1>[A-Za-zÁÉÍÓÚáéíóúÑñÜü][A-Za-zÁÉÍÓÚáéíóúÑñÜü\s]{2,40})|'
    r'comuna(?:\s+de)?\s+(?P<p2>[A-Za-zÁÉÍÓÚáéíóúÑñÜü][A-Za-zÁÉÍÓÚáéíóúÑñÜü\s]{2,40})|'
    r'(?:sector|barrio)\s+(?P<p3>[A-Za-zÁÉÍÓÚáéíóúÑñÜü][A-Za-zÁÉÍÓÚáéíóúÑñÜü\s]{2,40})|'
    r'^(?P<p4>[A-Za-zÁÉÍÓÚáéíóúÑñÜü][A-Za-zÁÉÍÓÚáéíóúÑñÜü\s]{2,30})\s*,?\s+'
    r'ya\s+(?:te|me|le)\s+'
    r')',
    re.IGNORECASE,
)

_DIRECCION_DIFERIDA_RE = re.compile(
    r'(?:'
    r'(?:te\s+)?(?:la|lo)\s+doy\s+(?:despu[eé]s|luego|al\s+aprobar|de\s+aprobar)|'
    r'(?:direcci[oó]n|calle).{0,60}(?:despu[eé]s|luego|cuando\s+(?:apruebe|acepte|tenga)|primero)|'
    r'(?:cotizaci[oó]n|presupuesto|precio).{0,40}(?:primero|antes)|'
    r'(?:primero).{0,40}(?:cotizaci[oó]n|presupuesto|cu[aá]nto)|'
    r'aprobar(?:se)?\s+la\s+cotizaci[oó]n|'
    r'saber\s+primero\s+cu[aá]nto'
    r')',
    re.IGNORECASE,
)

_RE_SALUDO_AGENTE = re.compile(
    r'^\s*Hola,?\s+soy\s+.+\s+de\s+.+?(?:\.|!|\n|$)',
    re.IGNORECASE,
)

_STOP_LUGAR = frozenset(
    {
        'el',
        'la',
        'los',
        'las',
        'un',
        'una',
        'mi',
        'casa',
        'auto',
        'taller',
        'domicilio',
        'semana',
        'sabado',
        'sábado',
        'lunes',
        'martes',
        'miercoles',
        'miércoles',
        'jueves',
        'viernes',
        'domingo',
    }
)

# Palabras que NUNCA son comuna/sector (evita "Cuánto cuesta", "Muchas gracias").
_STOP_UBICACION_TOKENS = frozenset(
    {
        'cuanto',
        'cuesta',
        'vale',
        'sale',
        'cobra',
        'cobran',
        'precio',
        'tarifa',
        'presupuesto',
        'cotizacion',
        'cotizar',
        'gracias',
        'muchas',
        'hola',
        'buenas',
        'buenos',
        'noches',
        'dias',
        'tardes',
        'ok',
        'okay',
        'dale',
        'listo',
        'perfecto',
        'excelente',
        'claro',
        'si',
        'no',
        'por',
        'favor',
        'necesito',
        'quiero',
        'realizar',
        'cambio',
        'aceite',
        'filtro',
        'servicio',
        'telefono',
        'patente',
        'kilometraje',
        'tiene',
        'conlleva',
        'incluye',
        'puede',
        'podria',
        'ayuda',
        'ayudar',
        'auto',
        'vehiculo',
        'moto',
    }
)

_BASURA_DIRECCION_RE = re.compile(
    r'(?:'
    r'cu[aá]nto\s+(?:cuesta|vale|sale)|'
    r'\b(?:precio|cotizaci[oó]n|presupuesto|gracias|hola|buenas?)\b|'
    r'\?'
    r')',
    re.IGNORECASE,
)


def _clave_lugar(texto: str) -> str:
    return ''.join(
        c for c in unicodedata.normalize('NFKD', (texto or '').strip().lower())
        if not unicodedata.combining(c)
    )


def _normalizar_lugar(texto: str) -> str:
    t = re.sub(r'\s+', ' ', (texto or '').strip(' .,;:!?¿¡'))
    # Corta coletillas ("Vitacura pero quiero…")
    t = re.split(r'\b(?:pero|y|aunque|porque|para|donde|dónde)\b', t, maxsplit=1, flags=re.I)[0]
    return t.strip(' .,;:!?¿¡')


def _es_comuna_conocida(texto: str) -> bool:
    return _clave_lugar(texto) in _COMUNAS_CL_KNOWN


def _parece_comuna_o_sector(texto: str, *, solo_conocida: bool = False) -> bool:
    t = _normalizar_lugar(texto)
    if len(t) < 4 or len(t) > 40:
        return False
    if _BASURA_DIRECCION_RE.search(t):
        return False
    if _es_comuna_conocida(t):
        return True
    if solo_conocida:
        return False
    palabras = [p for p in t.split() if p]
    if not (1 <= len(palabras) <= 3):
        return False
    if any(ch.isdigit() for ch in t):
        return False
    claves = {_clave_lugar(p) for p in palabras}
    if claves & _STOP_UBICACION_TOKENS:
        return False
    if all(p.lower() in _STOP_LUGAR for p in palabras):
        return False
    # Exige mayúscula inicial o pinta a nombre propio (no frase verbal).
    return t[0].isalpha()


def _formatear_comuna(texto: str) -> str:
    t = _normalizar_lugar(texto)
    if not t:
        return ''
    clave = _clave_lugar(t)
    pretty = {
        'nunoa': 'Ñuñoa',
        'penalolen': 'Peñalolén',
        'maipu': 'Maipú',
        'conchali': 'Conchalí',
        'san joaquin': 'San Joaquín',
        'estacion central': 'Estación Central',
        'valparaiso': 'Valparaíso',
        'vina del mar': 'Viña del Mar',
        'concepcion': 'Concepción',
    }
    if clave in pretty:
        return pretty[clave]
    return t.title() if t.islower() or t.isupper() else (t[0].upper() + t[1:])


def _extraer_ubicacion_cliente(texto: str) -> str:
    """Heurística estricta: solo comuna/sector real (nunca 'cuánto cuesta')."""
    raw = (texto or '').strip()
    if not raw:
        return ''

    tiene_ancla = bool(
        re.search(r'\b(?:vivo|estoy|quedo|qued[eé]|ando|andamos|comuna|sector|barrio)\b', raw, re.I)
    )

    # "Cuánto cuesta?" / "Muchas gracias" solos → nunca ubicación.
    if not tiene_ancla and (_BASURA_DIRECCION_RE.search(raw) or _CLIENTE_PIDE_PRECIO_RE.search(raw)):
        return ''

    m = _DIRECCION_CAPTURA_RE.search(raw)
    if m:
        cand = _normalizar_lugar(
            m.group('p1') or m.group('p2') or m.group('p3') or m.group('p4') or ''
        )
        if _es_comuna_conocida(cand):
            return _formatear_comuna(cand)
        # "vivo en / sector / comuna X" con nombre propio limpio (no listado).
        if (m.group('p1') or m.group('p2') or m.group('p3')) and _parece_comuna_o_sector(
            cand, solo_conocida=False
        ):
            return _formatear_comuna(cand)

    # Mensaje corto: SOLO comunas del listado.
    words = [w for w in re.split(r'\s+', _normalizar_lugar(raw)) if w]
    if 1 <= len(words) <= 3 and _es_comuna_conocida(raw):
        return _formatear_comuna(raw)

    # Comuna conocida embebida en frase con ancla o sin basura de precio.
    if not tiene_ancla and _CLIENTE_PIDE_PRECIO_RE.search(raw):
        return ''
    low = _clave_lugar(raw)
    for comuna in sorted(_COMUNAS_CL_KNOWN, key=len, reverse=True):
        if re.search(rf'\b{re.escape(comuna)}\b', low):
            return _formatear_comuna(comuna)
    return ''


def _direccion_parece_basura(texto: str) -> bool:
    t = (texto or '').strip()
    if not t:
        return False
    if _BASURA_DIRECCION_RE.search(t):
        return True
    if _CLIENTE_PIDE_PRECIO_RE.search(t) and not _es_comuna_conocida(t):
        return True
    claves = {_clave_lugar(p) for p in t.split()}
    if claves & _STOP_UBICACION_TOKENS and not _es_comuna_conocida(t):
        return True
    return False


def _cliente_diferir_direccion(texto: str) -> bool:
    return bool(_DIRECCION_DIFERIDA_RE.search(texto or ''))


def _agente_ya_respondio(conversation: Conversation) -> bool:
    """True si el asistente IA ya envió al menos un mensaje en este chat."""
    for msg in conversation.messages.filter(direction='outbound').order_by('-timestamp')[:30]:
        meta = msg.channel_metadata or {}
        if meta.get('from_agente_ia'):
            return True
    return False


def _enriquecer_ubicacion_en_datos(datos: dict, texto_cliente: str) -> dict:
    """Persiste comuna/sector y flag de dirección diferida sin depender del LLM."""
    out = dict(datos or {})
    actual = (out.get('direccion_servicio') or '').strip()
    # Limpia basura ya persistida ("Cuánto cuesta", "Muchas gracias").
    if actual and _direccion_parece_basura(actual):
        out['direccion_servicio'] = ''
        actual = ''
    ubic = _extraer_ubicacion_cliente(texto_cliente)
    if ubic:
        if not actual:
            out['direccion_servicio'] = ubic
        elif ubic.lower() not in actual.lower() and not re.search(r'\d', actual):
            # Actual es solo comuna/sector corto → actualiza; no pisa calle+número.
            out['direccion_servicio'] = ubic
    if _cliente_diferir_direccion(texto_cliente):
        out['direccion_diferida'] = True
    return out


def _nota_ubicacion_para_prompt(datos: dict) -> str:
    dir_txt = (datos.get('direccion_servicio') or '').strip()
    if dir_txt and _direccion_parece_basura(dir_txt):
        dir_txt = ''
    diferida = bool(datos.get('direccion_diferida'))
    modalidad = (datos.get('modalidad') or '').strip().lower()
    partes: list[str] = []
    if dir_txt:
        partes.append(
            f'Ubicación YA CAPTURADA del cliente: "{dir_txt}". '
            'PROHIBIDO volver a preguntar comuna/sector. '
            'Calle exacta SOLO al coordinar visita o si el cliente la ofrece.'
        )
    elif diferida:
        partes.append(
            'El cliente pidió cotización ANTES de dar dirección exacta. '
            'Respeta eso: NO insistas en la calle. Arma el borrador y dile que '
            'la dirección se coordina al aprobar/agendar.'
        )
    elif modalidad == 'domicilio':
        telefono_ok = len(
            ''.join(c for c in str(datos.get('cliente_telefono') or '') if c.isdigit())
        ) >= 8
        patente_ok = bool(
            ((datos.get('vehiculo') or {}).get('patente') or datos.get('patente_enriquecida') or '')
            .strip()
        )
        if telefono_ok and patente_ok:
            partes.append(
                'Falta comuna/sector para el servicio a domicilio. '
                'Pídela UNA sola vez, al final, con naturalidad '
                '(ej. "¿En qué comuna te atiendes para coordinar la visita?"). '
                'NO la pidas junto al saludo ni antes de patente/teléfono. '
                'Si el cliente aplaza la dirección, no insistas.'
            )
    return ' '.join(partes)


def _quitar_re_saludo(burbujas: list[str], *, ya_presentado: bool) -> list[str]:
    if not ya_presentado or not burbujas:
        return burbujas
    out: list[str] = []
    for i, b in enumerate(burbujas):
        txt = (b or '').strip()
        if not txt:
            continue
        if i == 0 and _RE_SALUDO_AGENTE.search(txt):
            limpio = _RE_SALUDO_AGENTE.sub('', txt).strip()
            if limpio:
                out.append(limpio)
            continue
        out.append(txt)
    return out or burbujas


_PEDIDO_CONCRETO_RE = re.compile(
    r'\b(?:'
    r'cotiz|presupuesto|precio|cu[aá]nto|'
    r'cambio\s+de|quiero\s+(?:un\s+)?(?:servicio|cotiz)|necesito|'
    r'revisi[oó]n|diagn[oó]stico|alineaci[oó]n|balanceo|'
    r'filtro|aceite|freno|pastillas|embrague|buj[ií]as|'
    r'patente|agendar|a\s+domicilio'
    r')\b',
    re.IGNORECASE,
)

_CLIENTE_RECHAZO_O_CERRADO_RE = re.compile(
    r'\b(?:'
    r'ya\s+(?:realic[eé]|hice|hize|arregl[eé]|repar[eé]|solucion[eé]|cambi[eé]|vend[ií])|'
    r'ya\s+lo\s+(?:hice|hicieron|arreglaron|arregl[eé]|solucionaron|cambiaron|tengo)|'
    r'ya\s+no\s+(?:necesito|quiero|busco|voy\s+a)|'
    r'no\s+gracias|gracias\s+de\s+todos\s+modos|'
    r'encontr[eé]\s+otro|en\s+otro\s+taller|con\s+otro\s+mecanico|'
    r'cancelar\s+(?:cotizac|servicio)|no\s+me\s+interesa|'
    r'desisto|olv[ií]dalo'
    r')\b',
    re.IGNORECASE,
)

_SOLO_SALUDO_RE = re.compile(
    r'^\s*(?:hola|holi|hey|ola|buenas?(?:\s+tardes|\s+noches|\s+d[ií]as)?)\s*[!.?…]*\s*$',
    re.IGNORECASE,
)

_UBICACION_TACTICA_TERRENO_RE = re.compile(
    r'\b(?:'
    r'subterr[aá]neo|piso\s*-?\d+|menos\s*\d+|nivel\s*-?\d+|'
    r'estoy\s+abajo|est[aá]\s+bajando|bajando|'
    r'te\s+estoy\s+llamando|te\s+llamo|d[oó]nde\s+est[aá]s|en\s+qu[eé]\s+piso|'
    r'llegu[eé]|estoy\s+afuera|en\s+la\s+puerta'
    r')\b',
    re.IGNORECASE,
)


def _es_mensaje_terreno_tactico(texto: str) -> bool:
    return bool(_UBICACION_TACTICA_TERRENO_RE.search(texto or ''))


def _prevenir_respuestas_repetitivas(conversation: Conversation, textos: list[str]) -> list[str]:
    """Evita que el agente caiga en bucles repetitivos de plantillas idénticas."""
    limpios = [t.strip() for t in (textos or []) if (t or '').strip()]
    if not limpios:
        return limpios
    recientes = list(
        conversation.messages.filter(direction='outbound')
        .order_by('-timestamp')[:4]
    )
    textos_recientes = [
        re.sub(r'\s+', ' ', (m.content or '').strip().lower())
        for m in recientes
        if (m.channel_metadata or {}).get('from_agente_ia')
    ]
    if not textos_recientes:
        return limpios

    out: list[str] = []
    for txt in limpios:
        txt_norm = re.sub(r'\s+', ' ', txt.strip().lower())
        es_rep = False
        for rec in textos_recientes:
            if rec and (txt_norm == rec or (len(txt_norm) > 25 and txt_norm[:60] in rec)):
                es_rep = True
                break
        if es_rep:
            out.append(
                'Entendido. He notificado directamente al equipo para confirmar los detalles de inmediato.'
            )
            break
        out.append(txt)
    return out

_RESPUESTA_ABIERTA_RE = re.compile(
    r'(?:en\s+qu[eé]\s+te\s+puedo\s+ayudar|qu[eé]\s+le\s+pasa\s+al\s+auto|'
    r'c[oó]mo\s+te\s+puedo\s+ayudar)',
    re.IGNORECASE,
)


def _cliente_solo_saluda(texto: str) -> bool:
    t = (texto or '').strip()
    if not t:
        return True
    if _SOLO_SALUDO_RE.match(t):
        return True
    # "Hola buenas" corto sin pedido
    if len(t) <= 32 and not _PEDIDO_CONCRETO_RE.search(t):
        low = t.lower()
        if any(s in low for s in ('hola', 'buenas', 'hey', 'qué tal', 'que tal')):
            return True
    return False


def _cliente_trae_pedido_concreto(texto: str) -> bool:
    """True si el mensaje ya trae servicio/cotización/síntoma (no es solo 'hola')."""
    t = (texto or '').strip()
    if not t or _cliente_solo_saluda(t):
        return False
    return bool(_PEDIDO_CONCRETO_RE.search(t))


def _respuesta_ignora_pedido_inicial(burbujas: list[str], texto_cliente: str) -> bool:
    """True si el cliente pidió algo concreto y la IA solo respondió bienvenida abierta."""
    if not _cliente_trae_pedido_concreto(texto_cliente):
        return False
    joined = ' '.join(b or '' for b in (burbujas or [])).strip()
    if not joined:
        return True
    # No menciona nada del pedido y pregunta genérica → ignoró el contexto.
    if _RESPUESTA_ABIERTA_RE.search(joined) and not _PEDIDO_CONCRETO_RE.search(joined):
        return True
    return False


def _hint_servicio_desde_texto(texto: str) -> str:
    t = (texto or '').lower()
    if re.search(r'aceite', t):
        if re.search(r'filtro', t):
            return 'el cambio de aceite y filtro'
        return 'el cambio de aceite'
    if re.search(r'filtro\s+de\s+aire', t):
        return 'el cambio de filtro de aire'
    if re.search(r'polen|habit[aá]culo', t):
        return 'el cambio de filtro de polen'
    if re.search(r'embrague', t):
        return 'el cambio de kit de embrague'
    if re.search(r'pastillas|freno', t):
        return 'el servicio de frenos'
    if re.search(r'diagn[oó]stico', t):
        return 'el diagnóstico'
    if re.search(r'alineaci[oó]n', t):
        return 'la alineación'
    return 'el servicio que pediste'


def _respuesta_fallback_pedido_inicial(
    texto_cliente: str,
    *,
    nombre_agente: str,
    nombre_taller: str,
) -> list[str]:
    """Respuesta determinística cuando el LLM ignora un pedido en el primer mensaje."""
    taller = (nombre_taller or '').strip() or 'el taller'
    agente = (nombre_agente or '').strip()
    servicio = _hint_servicio_desde_texto(texto_cliente)
    if agente:
        b1 = f'Hola, soy {agente} de {taller}. Perfecto, te ayudo con {servicio}.'
    else:
        b1 = f'Hola, soy de {taller}. Perfecto, te ayudo con {servicio}.'
    b2 = 'Para armarte una cotización precisa, ¿me indicas la patente del auto?'
    return [b1, b2]


def _cotizacion_editable_sesion(sesion: AgenteConversacionSesion):
    from mecanimovilapp.apps.agente_ia.services.cotizacion_borrador import (
        _cotizacion_editable_por_agente,
    )

    cot = getattr(sesion, 'cotizacion_borrador', None)
    taller = getattr(sesion, 'taller', None) or getattr(cot, 'taller', None)
    if cot and taller is not None and _cotizacion_editable_por_agente(cot, taller):
        return cot
    return None


def _claves_servicios_en_cotizacion(cot) -> set[str]:
    if not cot:
        return set()
    meta = cot.metadata or {}
    claves: set[str] = set()
    for lin in meta.get('servicios_lineas') or []:
        if isinstance(lin, dict):
            c = _clave_servicio_dedup(str(lin.get('nombre') or ''))
            if c:
                claves.add(c)
    titulo = (cot.servicio_nombre or '').strip()
    if titulo:
        if ' + ' in titulo:
            for parte in titulo.split(' + '):
                c = _clave_servicio_dedup(parte.strip())
                if c:
                    claves.add(c)
        else:
            c = _clave_servicio_dedup(titulo)
            if c:
                claves.add(c)
    return claves


def _cliente_modifica_cotizacion_existente(
    sesion: AgenteConversacionSesion,
    datos: dict,
    *,
    texto_cliente: str = '',
) -> bool:
    """True si el cliente pide agregar/modificar una cotización ya iniciada."""
    cot = _cotizacion_editable_sesion(sesion)
    if not cot:
        return False
    if datos.get('repuestos_incluidos_ultimo_servicio') is not None:
        return True
    if _cliente_pide_agregar_a_cotizacion(texto_cliente):
        return True
    claves_cot = _claves_servicios_en_cotizacion(cot)
    from mecanimovilapp.apps.agente_ia.services.cotizacion_borrador import _parse_servicios_solicitados

    for nombre in _parse_servicios_solicitados(datos):
        clave = _clave_servicio_dedup(nombre)
        if clave and clave not in claves_cot:
            return True
    return False


def _asegurar_servicios_para_actualizar_cotizacion(
    *,
    sesion: AgenteConversacionSesion,
    datos: dict,
    texto_cliente: str,
) -> dict:
    """Garantiza que servicios nuevos del chat queden en datos antes de armar el borrador."""
    cot = _cotizacion_editable_sesion(sesion)
    if not cot:
        return datos
    from mecanimovilapp.apps.agente_ia.services.cotizacion_borrador import _parse_servicios_solicitados

    from mecanimovilapp.apps.agente_ia.services.cotizacion_borrador import (
        _expandir_nombre_servicio,
        _servicios_equivalentes,
    )

    datos = dict(datos or {})
    lista = list(_parse_servicios_solicitados(datos))
    claves = {_clave_servicio_dedup(n) for n in lista}

    def _ya_incluido(nombre: str) -> bool:
        clave = _clave_servicio_dedup(nombre)
        if clave and clave in claves:
            return True
        return any(_servicios_equivalentes(nombre, n) for n in lista)

    # Conserva los ya cotizados al SUMAR; no los reinyectes si el cliente pidió quitar/solo.
    poda = _cliente_pide_quitar_de_cotizacion(texto_cliente) or bool(
        _SOLO_SERVICIO_RE.search(texto_cliente or '')
    )
    if not poda:
        for lin in (cot.metadata or {}).get('servicios_lineas') or []:
            if not isinstance(lin, dict):
                continue
            nombre = (lin.get('nombre') or '').strip()
            if not nombre or _ya_incluido(nombre):
                continue
            lista.append(nombre)
            claves.add(_clave_servicio_dedup(nombre))
    if _cliente_pide_agregar_a_cotizacion(texto_cliente):
        for nombre in _extraer_servicios_mencionados_en_texto(texto_cliente):
            for parte in _expandir_nombre_servicio(nombre) or [nombre]:
                if not parte or _ya_incluido(parte):
                    continue
                lista.append(parte)
                claves.add(_clave_servicio_dedup(parte))
    if lista:
        datos['servicios'] = lista
    return datos


_MONTO_CLP_RE = re.compile(
    r'(?:\$\s*[\d]{1,3}(?:[.\s]\d{3})+(?:,\d+)?|\$\s*\d+(?:[.,]\d+)?|\b\d{1,3}(?:[.\s]\d{3})+\s*(?:CLP|pesos)?\b)',
    re.IGNORECASE,
)

# Frases donde el modelo afirma un precio / tarifa aunque el monto ya se haya borrado.
# OJO: todas las alternativas usan \b antes de la palabra clave para NO matchear
# substrings dentro de otras palabras (ej. "es de" NO debe matchear dentro de
# "antes de", "después de", "a través de", etc.) — eso causaba truncar frases a
# la mitad ("...tu auto ant." en vez de "...tu auto antes de cotizar.").
_PRECIO_CLAIM_RE = re.compile(
    r'(?:'
    r'\b(?:el\s+)?valor\s+(?:de\s+)?(?:la\s+)?(?:visita|diagn[oó]stico|inspecci[oó]n|servicio|revisi[oó]n)[^.!?\n]*[.!?]?'
    r'|\b(?:cuesta|sale|vale)\s+(?:alrededor\s+de\s+|unos?\s+|aprox\.?\s+)?(?:\$|[^.!?\n])*[.!?]?'
    r'|\btarifas?\s+(?:de\s+)?(?:visita|diagn[oó]stico)[^.!?\n]*[.!?]?'
    r'|\bse\s+descuentan?\s+del\s+total[^.!?\n]*[.!?]?'
    r'|\bes\s+de\s*,?\s*(?:los\s+cuales)?[^.!?\n]*[.!?]?'
    r'|\blos\s+cuales\s+se\s+descuentan?[^.!?\n]*[.!?]?'
    r')',
    re.IGNORECASE,
)

_FRASE_SIN_PRECIO_CATALOGO = (
    'Ese servicio no tiene una tarifa publicada en nuestro catálogo, '
    'así que el valor exacto te lo confirma el taller en la cotización. '
    'Si quieres, dejamos armado el borrador para que lo revisen y te lo envíen.'
)

_FRASE_SANITIZER_LEGACY = re.compile(
    r'Ese valor lo confirma el taller en la cotización[^.]*\.',
    re.IGNORECASE,
)

def _respuesta_contiene_monto(texto: str) -> bool:
    return bool(_MONTO_CLP_RE.search(texto or ''))


def _respuesta_afirma_precio(texto: str) -> bool:
    t = texto or ''
    if _respuesta_contiene_monto(t):
        return True
    if _PRECIO_CLAIM_RE.search(t):
        return True
    low = t.lower()
    return 'se descuent' in low or 'tarifa de visita' in low


def _cliente_pide_precio_en_turno(
    *,
    texto_cliente: str,
    cliente_pide_cotizacion: bool,
    intencion: str,
) -> bool:
    """True solo si el cliente pidió precio/cotización en este contexto."""
    if _cliente_niega_pedir_precio(texto_cliente):
        return False
    if cliente_pide_cotizacion:
        return True
    if (intencion or '').strip().lower() in ('cotizacion', 'cotizar', 'presupuesto'):
        return True
    return bool(_CLIENTE_PIDE_PRECIO_RE.search(texto_cliente or ''))


def _servicios_candidato_precio(datos: dict) -> list[str]:
    from mecanimovilapp.apps.agente_ia.services.cotizacion_borrador import _parse_servicios_solicitados

    servicios = _parse_servicios_solicitados(datos)
    if servicios:
        return servicios
    sn = (datos.get('servicio_nombre') or '').strip()
    if sn:
        return [sn]
    problema = (datos.get('descripcion_problema') or '').strip()
    if problema:
        return [problema[:80]]
    return ['diagnóstico']


def _tiene_precio_catalogo_mencionable(taller, datos: dict) -> bool:
    """True solo si hay oferta publicada con precio > 0 para el servicio del turno."""
    from mecanimovilapp.apps.ordenes.services.catalogo_pricing import (
        buscar_oferta_exacta,
        precio_publico_oferta,
    )

    vehiculo = datos.get('vehiculo') or {}
    marca = (vehiculo.get('marca') or '').strip()
    modelo = (vehiculo.get('modelo') or '').strip()
    tipo_motor = (vehiculo.get('tipo_motor') or '').strip()
    for nombre in _servicios_candidato_precio(datos):
        oferta = buscar_oferta_exacta(
            taller=taller,
            servicio_nombre=nombre,
            marca=marca,
            modelo=modelo,
            tipo_motor=tipo_motor,
        )
        if not oferta:
            continue
        precio, _ = precio_publico_oferta(oferta, con_repuestos=True)
        if precio > 0:
            return True
    return False


def _tiene_precio_mencionable(
    taller,
    datos: dict,
    *,
    permite_estimados_historicos: bool = True,
) -> bool:
    """Catálogo publicado o referencia histórica válida (mediana con n≥3)."""
    if _tiene_precio_catalogo_mencionable(taller, datos):
        return True
    from mecanimovilapp.apps.agente_ia.services.historial_pricing import (
        tiene_estimado_historico_mencionable,
    )

    vehiculo = datos.get('vehiculo') or {}
    return tiene_estimado_historico_mencionable(
        taller=taller,
        servicios=_servicios_candidato_precio(datos),
        marca=(vehiculo.get('marca') or '').strip(),
        modelo=(vehiculo.get('modelo') or '').strip(),
        tipo_motor=(vehiculo.get('tipo_motor') or '').strip(),
        permite_estimados=permite_estimados_historicos,
    )


def _tiene_solo_estimado_historico(
    taller,
    datos: dict,
    *,
    permite_estimados_historicos: bool = True,
) -> bool:
    """True si NO hay catálogo pero sí histórico válido para mencionar."""
    if _tiene_precio_catalogo_mencionable(taller, datos):
        return False
    return _tiene_precio_mencionable(
        taller,
        datos,
        permite_estimados_historicos=permite_estimados_historicos,
    )


# Corta oraciones completas (no solo el monto) para nunca dejar fragmentos
# colgando a mitad de frase (ej. "El valor del servicio... " sin terminar).
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑÜ¡¿])')


def _sanitizar_respuesta_sin_precio_catalogo(
    respuesta: str,
    *,
    cliente_pide_precio: bool = False,
) -> str:
    """
    Cuando no hay precio de catálogo, elimina la ORACIÓN COMPLETA que afirma
    tarifa/monto (no solo el número), para no dejar frases a medias como
    "El valor del servicio de cambio de aceite para tu [auto]." sin terminar.
    El disclaimer largo SOLO se agrega si el cliente pidió precio/cotización;
    en turnos de captura (patente/teléfono) solo se limpia el texto inventado.
    """
    texto = (respuesta or '').strip()
    if not texto or not _respuesta_afirma_precio(texto):
        return texto

    texto = _FRASE_SANITIZER_LEGACY.sub('', texto)
    oraciones = _SENTENCE_SPLIT_RE.split(texto)
    conservadas: list[str] = []
    for oracion in oraciones:
        o = oracion.strip()
        if not o:
            continue
        if _respuesta_afirma_precio(o):
            # Descarta la oración entera (no solo el monto) para no dejar fragmentos.
            continue
        if not cliente_pide_precio and _FRASE_SIN_PRECIO_CATALOGO.lower() in o.lower():
            continue
        conservadas.append(o)

    limpio = ' '.join(conservadas).strip()
    limpio = re.sub(r'\s{2,}', ' ', limpio)
    limpio = re.sub(r'\s+([,.;:])', r'\1', limpio)
    limpio = re.sub(r',\s*,+', ',', limpio)
    limpio = re.sub(r'\.\s*\.', '.', limpio)
    limpio = limpio.strip(' ,;')

    if len(limpio) < 24 or limpio.lower().startswith(('es de', 'los cuales', 'de,')):
        return _FRASE_SIN_PRECIO_CATALOGO if cliente_pide_precio else ''

    if cliente_pide_precio and _FRASE_SIN_PRECIO_CATALOGO[:40].lower() not in limpio.lower():
        if limpio and not limpio.endswith(('.', '!', '?')):
            limpio = f'{limpio}.'
        limpio = f'{_FRASE_SIN_PRECIO_CATALOGO} {limpio}'.strip()
    return limpio


def _extraer_respuestas_cliente(decision: dict[str, Any] | None) -> list[str]:
    """Normaliza respuestas_cliente[] o respuesta_cliente a lista de burbujas cortas."""
    if not isinstance(decision, dict):
        return []
    multi = decision.get('respuestas_cliente')
    out: list[str] = []
    if isinstance(multi, list):
        for item in multi:
            texto = str(item or '').strip()
            if texto:
                out.append(texto)
    if not out:
        single = str(decision.get('respuesta_cliente') or '').strip()
        if single:
            # Si el modelo metió párrafos separados, partir en burbujas.
            partes = [p.strip() for p in re.split(r'\n{2,}', single) if p.strip()]
            out = partes if len(partes) > 1 else [single]
    # Máximo 3 burbujas; cada una no demasiado larga.
    limpios: list[str] = []
    for texto in out[:3]:
        t = re.sub(r'\s+', ' ', texto).strip()
        if t:
            limpios.append(t[:700])
    return _sanitizar_muletillas_robot(limpios)


_MULETILLAS_ROBOT = re.compile(
    r'^(?:'
    r'Entendido[.,!]?\s*|'
    r'Entiendo[.,!]?\s*|'
    r'Perfecto[.,!]?\s+(?:ya\s+tengo|ya\s+anoté|ya\s+registré|anoté|registré)?\s*|'
    r'Con\s+(?:mucho\s+)?gusto\s+te\s+ayud[aoe]\w*\s*|'
    r'¡?Claro!?\s*[.,]?\s*(?:con\s+gusto)?\s*|'
    r'Excelente[.,!]?\s*|'
    r'Genial[.,!]?\s*'
    r')',
    re.IGNORECASE,
)

_RECAPITULACION_DATOS_ROBOT = re.compile(
    r'^(?:Ya\s+tengo\s+tus\s+datos|Ya\s+registré\s+tu\s+información|Ya\s+anoté\s+tus\s+datos)[^.!?]*[.!?]\s*',
    re.IGNORECASE,
)

_CIERRE_ROBOT = re.compile(
    r'(?:\s+|^)(?:'
    r'Quedo\s+atento\s+(?:a\s+tu\s+respuesta|a\s+tus\s+comentarios)?|'
    r'No\s+dudes?\s+en\s+(?:escribir(?:me)?|consultar(?:me)?|contactar(?:me)?)|'
    r'Estoy\s+aqu[ií]\s+para\s+ayudarte|'
    r'A\s+la\s+brevedad'
    r')[^.!?]*[.!?]?\s*$',
    re.IGNORECASE,
)


def _sanitizar_muletillas_robot(textos: list[str]) -> list[str]:
    """Limpia muletillas robot de inicio, recitación de datos y cierres genéricos de bot."""
    limpios: list[str] = []
    for texto in textos:
        t = (texto or '').strip()
        if not t:
            continue
        t = _RECAPITULACION_DATOS_ROBOT.sub('', t).strip()
        t = _MULETILLAS_ROBOT.sub('', t).strip()
        t = _CIERRE_ROBOT.sub('', t).strip()
        if t and t[0].islower():
            t = t[0].upper() + t[1:]
        if t:
            limpios.append(t)
    return limpios



def _llamar_gemini_agente(prompt: str) -> tuple[dict[str, Any] | None, str | None]:
    api_key = (getattr(settings, 'GEMINI_API_KEY', '') or '').strip()
    model = (
        getattr(settings, 'AGENTE_IA_GEMINI_MODEL', '')
        or getattr(settings, 'ASISTENTE_COTIZACION_GEMINI_MODEL', '')
        or getattr(settings, 'GEMINI_MODEL', 'gemini-3.1-flash-lite')
        or 'gemini-3.1-flash-lite'
    ).strip()
    if not api_key:
        return None, 'GEMINI_API_KEY no configurada.'

    timeout = int(getattr(settings, 'AGENTE_IA_TIMEOUT', 20) or 20)
    url = (
        f'https://generativelanguage.googleapis.com/v1beta/models/{model}:'
        f'generateContent?key={api_key}'
    )
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': 0.55,
            'maxOutputTokens': 2000,
            'responseMimeType': 'application/json',
        },
    }
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException:
        return None, 'Error de conexión con Gemini.'

    if resp.status_code != 200:
        return None, f'Gemini HTTP {resp.status_code}'

    try:
        body = resp.json()
        text = body['candidates'][0]['content']['parts'][0]['text']
    except (KeyError, IndexError, TypeError, ValueError):
        return None, 'Respuesta Gemini inesperada.'

    return _parse_json(text), None


def _construir_prompt_agente(
    *,
    nombre_taller: str,
    nombre_agente: str = '',
    instrucciones: str,
    chunks_texto: str,
    datos_capturados: dict,
    chat_reciente: str,
    mensaje_cliente: str,
    mensaje_bienvenida: str,
    contexto_patente: str = '',
    contexto_media: str = '',
    contexto_operativo_taller: str = '',
    contexto_diagnostico: str = '',
    resumen_conversacion: str = '',
    memoria_cliente: str = '',
    tiene_estimado_historico: bool = False,
    reglas_comerciales: str = '',
    calificacion_lead: str = '',
    primer_contacto: bool = True,
    nota_ubicacion: str = '',
    pedido_en_primer_mensaje: bool = False,
    es_coordinacion_terreno: bool = False,
    contexto_repuestos: str = '',
) -> str:
    datos_json = json.dumps(datos_capturados or {}, ensure_ascii=False)
    tiene_contexto = bool((chunks_texto or '').strip())
    nombre = (nombre_taller or '').strip() or 'el taller'
    agente = (nombre_agente or '').strip()

    bloque_terreno = ''
    if es_coordinacion_terreno:
        bloque_terreno = (
            '\n🚨 MODO COORDINACIÓN EN TERRENO ACTIVO (CRÍTICO):\n'
            'El cliente está físicamente en el vehículo, subterráneo, estacionamiento o intentando contactar al equipo en sitio.\n'
            '1. PROHIBIDO solicitar patente, pedir datos del auto o enviar plantillas de cotización/horarios comerciales.\n'
            '2. Responde en 1 frase corta confirmando que estás coordinando directamente con el mecánico o equipo en sitio.\n'
            '3. Mantén la calma, concisión y naturalidad táctica.\n'
        )
    if primer_contacto and pedido_en_primer_mensaje:
        flag_contacto = (
            'PRIMER_CONTACTO=true con PEDIDO CONCRETO en el mismo mensaje. '
            'OBLIGATORIO: preséntate en 1 frase Y reconoce el pedido (ej. cambio de aceite / cotización). '
            'PROHIBIDO responder solo con "¿en qué te puedo ayudar?" o pegar la bienvenida genérica '
            'ignorando lo que ya pidió. Siguiente paso útil: pedir la patente.'
        )
    elif primer_contacto:
        flag_contacto = (
            'PRIMER_CONTACTO=true. El cliente SOLO saluda (sin pedido). '
            'Puedes presentarte y preguntar en qué le ayudas.'
        )
    else:
        flag_contacto = (
            'PRIMER_CONTACTO=false. La conversación YA empezó. '
            f'PROHIBIDO reiniciar con "Hola, soy {agente or "…"} de {nombre}" u otra bienvenida. '
            'Continúa el hilo con naturalidad.'
        )
    if agente:
        bienvenida_default = (
            f'Hola, soy {agente} de {nombre}. ¿En qué te puedo ayudar con el auto?'
        )
        identidad = (
            f'Tu nombre es "{agente}" y representas al taller "{nombre}". '
            f'Solo en el PRIMER contacto puedes presentarte como {agente} de {nombre}. '
            f'Habla SIEMPRE como {agente} del taller {nombre}.'
        )
        regla_presentacion = (
            f'0a. SOLO SALUDO / social ("hola", "buenas noches") SIN pedido ni servicio:\n'
            f'    - Responde cálido y breve (1-2 frases). '
            f'Preséntate como "{agente} de {nombre}" SOLO si PRIMER_CONTACTO=true.\n'
            f'    - Pregunta abierta tipo "¿en qué te puedo ayudar?".\n'
            f'    - PROHIBIDO pedir patente/teléfono/dirección en ese turno.\n'
            f'0a2. HOLA + PEDIDO en el mismo mensaje ("hola, quiero cotizar cambio de aceite"):\n'
            f'    - Aplica 0b, NO 0a. Preséntate breve + reconoce el servicio + pide el siguiente dato útil '
            f'(casi siempre la patente). NUNCA ignores el pedido con una bienvenida genérica.'
        )
        regla_1b = (
            f'1b. Si PRIMER_CONTACTO=true y te presentas, usa tu nombre "{agente}" y el del taller "{nombre}". '
            f'Si PRIMER_CONTACTO=false, NO te presentes de nuevo.'
        )
    else:
        bienvenida_default = (
            f'Hola, soy de {nombre}. ¿En qué te puedo ayudar con el auto?'
        )
        identidad = (
            f'Eres el asesor virtual de "{nombre}", un taller mecánico en Chile. '
            f'Habla SIEMPRE en nombre de {nombre} (nunca digas solo "el taller" genérico si conoces el nombre).'
        )
        regla_presentacion = (
            f'0a. SOLO SALUDO / social ("hola", "buenas noches") SIN pedido ni servicio:\n'
            f'    - Responde cálido y breve (1-2 frases). '
            f'Preséntate con "{nombre}" SOLO si PRIMER_CONTACTO=true.\n'
            f'    - Pregunta abierta tipo "¿en qué te puedo ayudar?".\n'
            f'    - PROHIBIDO pedir patente/teléfono/dirección en ese turno.\n'
            f'0a2. HOLA + PEDIDO en el mismo mensaje: aplica 0b (reconoce el pedido + patente). '
            f'PROHIBIDO bienvenida genérica que ignore lo pedido.'
        )
        regla_1b = (
            f'1b. Si PRIMER_CONTACTO=true y te presentas, usa el nombre real del taller ("{nombre}"). '
            f'Si PRIMER_CONTACTO=false, NO te presentes de nuevo.'
        )
    bloque_ubicacion = (
        f'\nUBICACIÓN / DIRECCIÓN (sistema — respeta esto por encima de preguntar de nuevo):\n'
        f'{nota_ubicacion}\n'
        if (nota_ubicacion or '').strip()
        else ''
    )
    if primer_contacto and pedido_en_primer_mensaje:
        bloque_bienvenida = (
            'Mensaje de bienvenida: NO lo uses como respuesta. El cliente YA pidió algo concreto; '
            'preséntate en una frase y atiende ese pedido (no preguntes "¿en qué te ayudo?").\n'
        )
    elif primer_contacto:
        bloque_bienvenida = (
            f'Mensaje de bienvenida (tono/referencia opcional SOLO si el cliente solo saluda; '
            f'NO lo pegues entero ni lo combines con patente+modalidad+síntoma):\n'
            f'{mensaje_bienvenida or bienvenida_default}\n'
        )
    else:
        bloque_bienvenida = (
            'Mensaje de bienvenida: NO APLICA (conversación en curso — no reinicies).\n'
        )
    regla_15e = ''
    if tiene_estimado_historico:
        regla_15e = """
15e. REFERENCIA HISTÓRICA (cuando NO hay tarifa de catálogo pero SÍ aparece bloque "Referencia histórica de precios" en la FICHA):
    - Puedes mencionar la MEDIANA indicada como orientación ("por casos similares completados suele rondar…", "como referencia, trabajos parecidos han quedado alrededor de…").
    - OBLIGATORIO aclarar que NO es precio fijo ni cotización final: el taller lo confirma al revisar el borrador.
    - PROHIBIDO presentarlo como tarifa publicada de catálogo ni prometer ese monto exacto.
    - Usa el número EXACTO de la mediana del bloque histórico (no inventes otro monto ni rango distinto al indicado)."""
    return f"""{identidad} NO eres un bot de captura de leads ni un formulario: eres un mecánico/vendedor de soporte que conversa con naturalidad, escucha el momento del cliente y recién pide datos cuando aportan.

Tu prioridad en este orden:
1) Leer el contexto del turno (saludo vs pregunta vs caso ya detallado) y responder en consecuencia.
2) Entender qué le pasa al auto / qué necesita el cliente (asesoría humana).
3) Pedir SOLO el siguiente dato faltante más útil (una pregunta por turno).
4) Pedir PATENTE cuando ya hay síntoma o el cliente quiere precio/agenda (obligatoria antes de cotizar/agendar, NO en el primer "hola").
5) Cotizar SOLO cuando el cliente quiera precio/presupuesto Y ya haya patente + contexto suficiente.

Estado de contacto (OBLIGATORIO):
{flag_contacto}

Nombre real del taller (úsarlo cuando hables del taller):
{nombre}

Nombre del agente / vendedor (cómo debes presentarte; vacío = solo usar el nombre del taller):
{agente or '(sin nombre propio configurado — preséntate como del taller)'}

Instrucciones del taller (guía de fondo; NO las conviertas en checklist del primer mensaje — aplica el ritmo natural de abajo):
{instrucciones or 'Sé cordial, profesional y humano. Primero conversa; cotiza cuando el cliente lo pida o cuando el problema ya esté claro.'}

{bloque_bienvenida}{bloque_ubicacion}{bloque_terreno}{contexto_repuestos or ''}
FICHA OPERATIVA DEL TALLER (verdad operativa en vivo: no inventes precios ni servicios fuera de catálogo/especialidades. Marcas fuera de lista: NO rechaces el lead. Categorías de servicio fuera de especialidad: no cotices ese tipo — primero diagnostica con datos reales y explica con sutileza):
---
{contexto_operativo_taller or 'Sin datos operativos configurados todavía.'}
---

Conocimiento técnico de diagnóstico (orientación por síntomas; NO es diagnóstico certero sin ver el auto):
---
{contexto_diagnostico or 'Sin síntomas suficientes para orientación técnica específica en este turno.'}
---

Contexto automático de la patente (API + registro + historial + salud + catálogo). Fuente de verdad del vehículo; NO repitas marca/modelo/año si ya están:
---
{contexto_patente or 'Sin consulta de patente en este turno.'}
---

Análisis del adjunto de ESTE turno (audio/imagen/video; puede estar vacío):
---
{contexto_media or 'Sin adjunto analizado en este turno.'}
---

Conocimiento adicional del taller (historial de trabajos, documentos, notas) recuperado para ESTA consulta puntual:
---
{chunks_texto if tiene_contexto else 'Sin contexto adicional indexado para esta consulta.'}
---

Datos ya capturados (JSON; no los repreguntes si ya están):
{datos_json}

Resumen de conversación previa (mensajes antiguos ya no visibles en el historial reciente):
{resumen_conversacion or 'Sin resumen acumulado todavía.'}

Historial con este cliente en conversaciones anteriores (otros hilos; NO confundir con el chat actual):
{memoria_cliente or 'Sin historial previo con este cliente.'}

Historial reciente del chat:
{chat_reciente}

Último mensaje del cliente (ya puede incluir transcripción o descripción de media):
{mensaje_cliente}

{reglas_comerciales or 'REGLAS COMERCIALES DEL TALLER: configuración por defecto (tono balanceado, insistencia media).'}

{calificacion_lead}

REGLAS DE CONVERSACIÓN:
0. LEE EL MOMENTO (CRÍTICO — prima sobre pedirle datos): adapta TONO y RITMO al mensaje actual. PROHIBIDO responder con un formulario (patente + síntoma + domicilio/taller + teléfono) en un solo mensaje. Máximo UNA pregunta nueva por turno — esto incluye preguntas compuestas unidas con "y" (ej. "¿en qué sector estás Y qué le pasa al auto?" cuenta como DOS preguntas, prohibido). Si dudas entre dos datos por pedir, prioriza SIEMPRE el síntoma/problema del auto antes que sector/dirección/teléfono.
{regla_presentacion}
0b. PREGUNTA RÁPIDA o dump de info (pide precio/servicio, o ya cuenta síntoma/patente/auto; también "hola, quiero cotizar X"):
    - Contesta PRIMERO lo que preguntó o reconoce lo que ya dijo (no ignores su mensaje).
    - Guarda en datos_actualizados lo que ya entregó (servicio_nombre / servicios).
    - Luego pide SOLO el siguiente dato faltante más útil (si ya pidió cotizar un servicio → patente).
0c. CASO YA AVANZADO (historial con datos o cliente insistiendo en cotizar/agendar):
    - No reinicies con bienvenida genérica.
    - Avanza: confirma lo que tienes, pide el faltante, o prepara cotización si cumple regla 12.
0d. NO SIGAS UN CHECKLIST RÍGIDO (CRÍTICO — así responde un vendedor humano, no un formulario): el orden patente→teléfono→dirección es una GUÍA, no una secuencia obligatoria. Si el cliente te interrumpe ese flujo para preguntar algo puntual (ej. "pero espera, ¿cuánto cuesta?"), RESPONDE ESO PRIMERO con la info real que tengas (si el servicio SÍ tiene precio de catálogo, dilo directo — no sigas pidiendo el siguiente dato del checklist como si no te hubiera preguntado nada). Solo vuelve a pedir el dato pendiente en la burbuja siguiente, y solo si tiene sentido en ese momento.
1. Español chileno, cálido, concreto. Nada de frases robot ("¡Claro! Con gusto te ayudo a cotizar…", "Para poder revisar tu caso y ver si podemos atenderte…") ni empujar cotización en cada turno.
{regla_1b}
1c. PROHIBIDO FALSA CONTINUIDAD (CRÍTICO — rompe la naturalidad): nunca digas "como te comentaba", "como te mencioné", "como te decía", "como habíamos hablado" o equivalentes SALVO que tú literalmente ya hayas dicho eso mismo antes en ESTE chat (revisa el historial reciente). Si es la primera vez que explicas algo (ej. modalidad a domicilio, dirección, horario), dilo directo y natural, sin fingir que ya se había hablado del tema. Tampoco repitas la MISMA frase textual del bloque de FICHA OPERATIVA palabra por palabra — parafraséala como lo diría una persona, no como un párrafo copiado de una configuración.
1c2. MULETILLAS PROHIBIDAS DE BOT (CRÍTICO — son la bandera roja de un bot):
    NUNCA uses estas frases ni variantes cercanas para iniciar o cerrar mensajes:
    - "Entendido" / "Entiendo" como inicio de oración (prohibido).
    - "Perfecto, ya tengo..." / "Ya tengo tus datos" / "Ya anoté..." (prohibido recitar datos capturados).
    - "Con gusto te ayudo" / "Con mucho gusto" / "¡Claro!" como muletilla de inicio.
    - "A la brevedad" / "Lo antes posible".
    - "Para poder revisar tu caso..." / "Para poder ayudarte...".
    - "Quedo atento a tu respuesta" / "No dudes en escribirme" / "Estoy aquí para ayudarte".
    - "Agendaremos" / "Procederemos" (términos corporativos fríos; usa "coordinamos", "te armo", "vemos").
    EN VEZ DE CONFIRMAR DATOS, AVANZA DIRECTO: si el cliente da su teléfono o datos, NO digas "Perfecto, ya tengo tu teléfono" — avanza a lo que SIGUE ("Dale, te armo el borrador" o haz la pregunta útil directa). Un vendedor humano no recita lo que acaba de anotar.
1d. VARIEDAD LÉXICA (CRÍTICO — rompe el loop de repetición):
    - NO empieces 2 mensajes consecutivos con la misma palabra o expresión (ej. "dale", "perfecto", "excelente").
    - Alterna entre estilos: a veces confirma directo, a veces haz una observación técnica útil, a veces avanza con una pregunta.
    - PROHIBIDO recapitular todos los datos capturados en un solo mensaje ("Tengo tu nombre X, teléfono Y, patente Z, problema W..."). Menciona únicamente lo que aporta en ESTE turno.
2. Si el cliente SOLO saluda (sin pedido), aplica 0a. Si saluda Y pide algo (cotizar, cambio de aceite, etc.), aplica 0a2/0b — NUNCA 0a solo.
3. Muchos clientes NO saben qué servicio necesitan: primero asesora (posibles causas, qué revisar, urgencia) y pide 1 dato faltante clave.
3b. DIAGNÓSTICO PROACTIVO (CRÍTICO — suena a mecánico experto, NO a bot genérico): si hay bloque de "Conocimiento técnico de diagnóstico", apóyate en él para dar 2-3 causas CONCRETAS y nombradas (ej. "sensor de velocidad de rueda (ABS)", "sensor de ángulo del volante" — nunca solo "un sensor" a secas ni "problemas eléctricos" en genérico). Menciona con naturalidad las reparaciones asociadas que suelen ir de la mano, y advierte si hay riesgo de seguir circulando. Si el cliente pregunta "¿qué puede estar originando esto?", "¿por qué pasa?" o similar, PROFUNDIZA usando más causas del mismo bloque (no repitas lo que ya dijiste) y responde como un mecánico real conversando, no con una frase de relleno. Puedes cerrar con 1 pregunta específica del bloque para seguir afinando el diagnóstico. NUNCA afirmes un diagnóstico certero sin inspección física; di "podría ser", "suele ser", "conviene revisar". Esta respuesta es 100% asesoría técnica: NO la conviertas en pedido de teléfono/presupuesto en el mismo turno (ver regla 19).
3c. PROHIBIDO REPETIR LA MISMA HIPÓTESIS (CRÍTICO): revisa el historial reciente antes de responder. Si ya dijiste una hipótesis (ej. "podría ser la pinza de freno o el freno de mano") NO la repitas casi textual en el siguiente turno. Cuando el cliente aporte un dato NUEVO (ej. huele a quemado, se calienta la llanta, pasa solo en frío), usa ESE dato para AVANZAR el razonamiento: confirma o descarta la hipótesis anterior con esa nueva evidencia ("Ese olor a quemado confirma que..."; "Como también se calienta solo esa rueda, ahora apunto más a...") en vez de repetir la misma frase genérica. Cada respuesta debe sumar información nueva, no reciclar la anterior.
3d. EXPERTISE POR MARCA/MODELO: una vez que conoces la marca y modelo del vehículo (por patente verificada), úsalo para sonar como un especialista — menciónalo por su nombre al hablar del problema (ej. "en el Fiat Bravo..."), y si es un patrón ampliamente conocido para esa marca/modelo (ej. falla común de fábrica, pieza que se desgasta rápido en esos motores) puedes mencionarlo con cautela ("es un problema conocido en algunos..."). PROHIBIDO inventar boletines técnicos, códigos de falla específicos o cifras que no tengas certeza de que existen — si no estás seguro de un dato específico de esa marca, quédate en el diagnóstico general por síntoma sin fingir precisión que no tienes.
4. UNA sola pregunta de clarificación por turno (ej: cuándo ocurre el ruido, si hay luz en tablero, si pierde potencia). Si el taller solo atiende en una modalidad según la FICHA OPERATIVA, no la preguntes: infórmasela solo cuando sea relevante (no en el saludo).
4b. PATENTE (cuándo pedirla): es el dato maestro del vehículo y es OBLIGATORIA antes de cotizar o agendar. NO la pidas en un saludo vacío ni como primera pregunta si el cliente aún no contó el problema. Momento correcto: cuando ya hay síntoma/servicio en conversación, o el cliente pide precio/agenda, o ya trae datos del auto. Mientras tanto puedes asesorar el síntoma sin patente. NO marques listo_para_cotizar=true ni prometas presupuesto definitivo ni agendamiento sin patente en "Datos ya capturados". Marca/modelo/año que diga el cliente NO reemplazan la patente.
5. Usa adjuntos: si hay audio, responde a la transcripción/ruido; si hay foto de tablero/vano/pieza, comenta lo visto y pide confirmación. Si el análisis del adjunto falló o está pendiente, dile al cliente que no pudiste procesar el archivo y pídele que lo reenvíe o lo describa con palabras — nunca ignores el adjunto en silencio.
6. Si hay patente identificada y verificada, confírmala brevemente y avanza (no vuelvas a pedir la patente).
6b. PROHIBIDO INVENTAR marca/modelo/año/cilindraje del vehículo. SOLO puedes escribir esos campos en "datos_actualizados.vehiculo" si el bloque "Contexto automático de la patente" ya los identificó (API GetAPI.cl o registro Mecanimovil) o ya estaban verificados en "Datos ya capturados". NO uses marca+modelo+año que el cliente mencione como sustituto de la patente. Si la patente no se pudo verificar, pide que la confirme o reenvíe — no rellenes marca/modelo por tu cuenta.
7. Lee el historial: no repitas preguntas ya respondidas ni reinicies el tono como si fuera el primer mensaje.
8. MARCAS (captura de leads): NUNCA rechaces ni asustes al cliente porque su marca no esté en la lista de especialidad de marcas del taller. Si la marca SÍ es de especialidad, resáltalo con naturalidad. Si NO lo es, igual avanza (diagnóstico → patente → cotización) diciendo que pueden revisar su caso; el humano decide al enviar. Solo si la modalidad pedida (ej. domicilio) NO existe en la ficha, acláralo sin cerrar el lead.
8b. ESPECIALIDADES DE SERVICIO (categorías): son distintas a las marcas. El taller SOLO cubre las categorías/especialidades de la FICHA (ej. Diagnóstico mecánico, Mantención, Frenos — NO "Diagnóstico electrónico" si no está). Flujo obligatorio:
    (1) Primero RECAUDA la mayor información útil del problema (síntoma, cuándo ocurre, ruidos, luces, audio/foto) sin especular ni inventar fallas — a ritmo conversacional, no a checklist.
    (2) Con ese contexto, orienta técnicamente con honestidad según lo que SÍ hace el taller.
    (3) Si el requerimiento cae FUERA de las especialidades/categorías configuradas, explícalo con sutileza (sin despreciar al cliente ni sonar a rechazo frío): indícale que {nombre} se enfoca en [especialidades reales] y ese tipo de trabajo (ej. electrónica avanzada) no es su línea. Ofrece lo que SÍ puedan revisar dentro de su especialidad o escala a humano (necesita_humano=true) si el cliente insiste.
    (4) NO marques listo_para_cotizar=true ni armes cotización de un servicio fuera de especialidad. NO especules diagnósticos electrónicos/complejos si el taller no los ofrece.
9. Si el cliente pregunta qué servicios ofrece el taller, responde citando los nombres reales del catálogo de la FICHA OPERATIVA (puedes listar varios) y menciona las especialidades/categorías reales.
10. Si el cliente escribe fuera del horario de atención del taller, NO rechaces ni cortes la conversación: indica el horario y sigue asesorando/cotizando con normalidad. Solo al agendar una cita concreta la fecha/hora debe caer dentro del horario del taller o del mecánico indicado en la FICHA OPERATIVA. Usa la "Fecha y hora actual" de la ficha para no confundir "mañana" con un día de la próxima semana.
11. Fuera de automotriz / cliente muy enojado → necesita_humano=true.
12. listo_para_cotizar=true SOLO si:
    - hay PATENTE en datos capturados (vehiculo.patente o patente_enriquecida) Y
    - hay problema/servicio suficientemente claro Y dentro de las especialidades/categorías del taller Y
    - hay cliente_telefono en datos capturados (del chat o preguntado al cliente) Y
    - el cliente pide cotización/presupuesto/precio O ya confirmó que quiere que le armes el presupuesto.
    Sin patente, sin teléfono o servicio fuera de especialidad → listo_para_cotizar=false.
13. cliente_pide_cotizacion=true únicamente si en este turno (o el historial reciente) el cliente pidió precio/cotización/presupuesto de forma explícita o claramente implícita. NUNCA lo marques true solo porque ya tienes patente+teléfono+síntoma completos — la disposición de datos NO es lo mismo que la intención de compra. Si el cliente usa una NEGACIÓN cerca de la palabra ("no he pedido cotización", "todavía no quiero cotizar", "aún no"), es FALSO aunque la palabra "cotización" aparezca en su frase — está aclarando que NO la pidió, no pidiéndola.
14. UNA SOLA COTIZACIÓN por conversación y el MISMO vehículo: si el cliente pide EXPLÍCITAMENTE otro servicio para ESTE auto ("súmale", "agrega", "también quiero"), agrégalo a la misma cotización (lista "servicios"). NO trates cada servicio como cotización aparte. NO agregues un servicio solo porque se mencionó en el chat, en memoria de otros hilos, en el historial de la patente o porque el taller lo ofrece. Si cambia la patente/vehículo, parte de cero (no heredes servicios del auto anterior). Si el taller ya envió una cotización y el cliente pide agregar/modificar algo de ESTE auto, marca listo_para_cotizar=true para actualizar ESA misma cotización (se reabrirá a borrador); NO prometas una cotización nueva aparte.
14b. SERVICIOS ESTABLES: usa nombres cortos y consistentes en "servicios" (ej. "Diagnóstico de frenos", "Cambio de pastillas de freno delanteras"). NO repitas ni reformules un servicio ya capturado. NO agregues variantes con paréntesis como "(con repuestos)" en el nombre — usa repuestos_incluidos_ultimo_servicio. NO fusiones dos servicios en una frase ("diagnóstico y pastillas") si ya existen por separado. CRÍTICO: NUNCA metas la modalidad dentro del nombre del servicio (mal: "Cambio de aceite a domicilio", "Diagnóstico en taller") — la modalidad va SOLO en el campo "modalidad". Si mezclas modalidad en el nombre, el sistema no puede encontrar el precio real del catálogo y termina diciendo que no hay tarifa aunque sí exista. Usa solo el nombre del servicio en sí (ej. "Cambio de aceite").
14b2. ACEITE Y FILTROS: "cambio de aceite y filtro" = UN servicio (aceite + filtro de ACEITE). NUNCA lo mapees a "filtro Gasolina/combustible" ni copies SKUs del catálogo con sufijo de motor. Si el cliente pide EXPLÍCITAMENTE además filtro de aire y/o polen/habitáculo, agrégalos como entradas SEPARADAS en "servicios". Al actualizar, "servicios" incluye TODOS los pedidos explícitos de ESTE auto (anteriores + nuevos), no menciones sueltas ni trabajos de otro vehículo. Si dice "quita X" o "solo el aceite", deja únicamente lo pedido.
14b4. PRECIOS HISTÓRICOS: NUNCA cites ni copies el precio de una cotización de OTRO marca/modelo (Toyota ≠ BAIC). Solo puedes reusar un monto histórico si es el mismo marca Y el mismo modelo exactos.
14b3. REPUESTOS AL AGREGAR SERVICIOS: si el cliente pide cambio de filtro (aire/polen/aceite), pastillas, discos o aceite, asume que VAN CON REPUESTOS (repuestos_incluidos_ultimo_servicio=true) salvo que diga "solo mano de obra" / "sin repuestos". No hace falta preguntar en cada turno; el taller ajusta precios en el borrador. Al sumar aire/polen a una cotización ya armada, márcalos en "servicios" y listo_para_cotizar=true para que el sistema agregue esas piezas al borrador.
15. PRECIOS (ANTI-ALUCINACIÓN, CRÍTICO): Solo puedes mencionar un monto en pesos ($, CLP) si ese EXACTO valor aparece en la FICHA OPERATIVA / catálogo publicado para ese servicio y vehículo, O si el bloque de historial de la red trae un rango "en la red $X–$Y" (citas ESE rango, ni un peso más ni menos). Si el cliente pregunta "cuánto sale / cuánto cuesta" y NO hay precio publicado (ej. inspección/diagnóstico a domicilio sin tarifa en catálogo):
    - PROHIBIDO inventar cifras, rangos ("entre X e Y"), "unos treinta lucas", o dejar huecos tipo "el valor es de,". El rango de la red del historial NO se inventa: solo se cita si ya está escrito en ese bloque.
    - PROHIBIDO citar el monto exacto de otro taller. El rango anónimo de la red no es la boleta de ese taller.
    - PROHIBIDO inventar políticas de descuento ("se descuenta del total", "se abona a la reparación").
    - Responde con esta idea (puedes parafrasear, mismo sentido): "Ese servicio no tiene una tarifa publicada en catálogo; el valor exacto te lo confirma el taller en la cotización. Si quieres, dejamos armado el borrador para que lo revisen y te lo envíen."
    - Luego pide SOLO el dato que falte (teléfono o dirección), una pregunta.
    - Si el cliente PIDIÓ precio en este turno (no antes de que lo pidiera) y ya tienes patente + teléfono + problema, marca listo_para_cotizar=true (borrador en $0; el humano completa el precio). Si el cliente NO ha pedido precio/cotización todavía, sigue asesorando con normalidad y NO marques listo_para_cotizar=true ni digas que "vas a armar el borrador" — eso se siente invasivo y genera desconfianza.
15b. COTIZACIÓN MIXTA (catálogo + sin catálogo): si agregas un servicio SIN precio publicado a una cotización que ya tiene otros servicios, NO digas que "ya quedó todo con precio" ni que "ya sumé X servicio con su valor". Aclara que ESE servicio específico lo confirma el taller al revisar el borrador; los que sí tienen catálogo pueden mencionarse solo si el monto está en la FICHA.
15c. COBERTURA MARCA/MODELO (CRÍTICO): el catálogo puede tener el mismo servicio con precios distintos por marca/modelo (ej. "Cambio de aceite" para Toyota ≠ Honda).
    - Solo puedes citar un precio si la cobertura de esa línea es "todas las marcas/modelos" O coincide con la marca/modelo del vehículo del cliente (datos capturados / contexto patente / tag [APLICA A ESTE AUTO]).
    - PROHIBIDO tomar el precio de otra marca/modelo aunque el nombre del servicio sea idéntico. Trátalo como "sin tarifa publicada para ESTE auto".
    - Respuesta estratégica (parafraseable): reconoce que sí hacen el servicio, aclara que para su marca/modelo el valor exacto lo confirma el taller en la cotización, y ofrece armar el borrador. NO inventes un "precio aproximado" a partir de otra cobertura.
15d. REPUESTOS Y GARANTÍA (proactivo): si la FICHA OPERATIVA indica repuestos con marca/calidad (Original, OEM, Alternativo) y/o días de garantía para un servicio, menciónalo al explicar ese servicio o cuando el cliente pregunte por repuestos ("¿con qué pieza queda?", "¿es original?"). Ofrece la opción configurada en catálogo con naturalidad (ej. "trabajamos con disco marca X, calidad OEM, con garantía de N días"). PROHIBIDO inventar marcas, calidades o plazos de garantía que no figuren en la ficha.{regla_15e}
16. ENVÍO: TÚ NO envías la cotización por WhatsApp ni confirmas precios finales. Solo preparas el borrador; un humano del taller la revisa en "Cotizar con IA" y la envía. Dile al cliente que el taller le enviará la cotización.
17. Si el cliente menciona preferencia de día/hora/técnico para la visita, guárdalo en preferencias_agenda (fecha ISO si puedes, hora HH:MM, tecnico_nombre, nota). Si el día/hora propuesto cae dentro del horario del taller en la FICHA OPERATIVA, confirma verbalmente de forma proactiva (ej. "perfecto, tráelo el jueves a primera hora") y marca confirmado_verbal=true. Esto NO reserva un cupo formal; el agendamiento real ocurre al aceptar la cotización. Si el día cae fuera de horario, indícalo con amabilidad y sugiere el horario más cercano disponible.
18. MODALIDAD Y DIRECCIÓN (CRÍTICO — CERO INVENCIÓN): modalidad debe ser "taller" o "domicilio" según lo que pida el cliente Y lo que permita la FICHA OPERATIVA. Pídela solo cuando sea relevante — nunca en un saludo vacío.
    - Si la FICHA dice SOLO a domicilio: PROHIBIDO inventar local/sucursal. Si pregunta por dirección del taller, aclara que trabajan a domicilio.
    - Para BORRADOR a domicilio basta COMUNA o sector en direccion_servicio (ej. "Vitacura"). NO exijas calle/número para armar cotización.
    - PROHIBIDO guardar en direccion_servicio frases del chat que no sean lugar (mal: "Cuánto cuesta", "Muchas gracias", "cambio de aceite"). Solo comuna/sector/calle reales.
    - Momento correcto para pedir comuna (domicilio): DESPUÉS de patente + teléfono (o cuando vas a armar el borrador), UNA pregunta suave al cierre. NUNCA en el saludo ni como primera respuesta a "cuánto cuesta".
    - Calle exacta se pide SOLO al coordinar la visita o cuando el cliente ya aceptó/aprobó la cotización.
    - Si el cliente dice que dará la dirección DESPUÉS de ver/aprobar la cotización ("te la doy al aprobar", "primero el precio"): respeta eso. NO vuelvas a pedir la dirección. Marca listo_para_cotizar si ya hay patente+teléfono+servicio+pedido de precio (y comuna si la dio).
    - Si YA tienes comuna/sector REAL en "Datos ya capturados" o en el bloque UBICACIÓN: PROHIBIDO preguntarla de nuevo.
    - Si el taller tiene local: SOLO da la dirección EXACTA de la FICHA. PROHIBIDO inventar calle/número/comuna.
    - Si modalidad=taller, direccion_servicio puede ir vacío.
18b. INTENCIÓN DEL CLIENTE (CRÍTICO): si pide "cuánto vale", "qué conlleva", "quiero cotizar" o "envíame la cotización primero", RESPONDE eso (qué incluye + armar borrador). NO desvíes a pedir comuna/dirección/preferencia de día otra vez si ya la tienes o si el cliente la aplazó. "Cuánto cuesta" NO es una dirección.
19. TELÉFONO Y RITMO COMERCIAL (CRÍTICO — no ser insistente): pide el teléfono SOLO cuando el cliente muestre intención real de avanzar (pide presupuesto/cotización/precio, quiere agendar o llevar el auto, pregunta "cuándo puedo llevarlo", o ya aceptó que le armes el borrador). NO lo pidas automáticamente solo porque ya tienes patente + síntoma: mientras el cliente siga en modo consulta/duda técnica (preguntando causas, qué puede ser, si es grave, etc.) quédate en modo asesoría (regla 3b) y NO reintroduzcas el pedido de teléfono en cada respuesta — se siente a bot insistente. Guárdalo en datos_actualizados.cliente_telefono cuando lo entregue. Sin teléfono no marques listo_para_cotizar=true. Si ya está, no lo vuelvas a pedir.
20. KILOMETRAJE: si el contexto de patente trae km registrados, trátarlo SOLO como referencia aproximada / último dato conocido — el auto pudo seguir circulando. NUNCA digas "tu auto tiene X km exactos". Puedes decir "según registro, el último km conocido era aprox. X; ¿me confirmas el kilometraje actual?" y guarda vehiculo.kilometraje_actual si el cliente lo confirma.
21. MENSAJES CORTOS Y SEPARADOS (como WhatsApp humano): responde con "respuestas_cliente" = lista de 1 a 3 burbujas.
    - Cada burbuja = UNA idea (confirmación, tip técnico, o UNA pregunta).
    - PROHIBIDO meter en un solo mensaje: disclaimer de precio + diagnóstico + pedido de teléfono.
    - Si el cliente sigue en modo consulta técnica (aún no pide presupuesto/agendar), NO metas pedido de teléfono al final — cierra con una pregunta de diagnóstico o déjalo abierto a que siga preguntando (regla 19).
    - Ejemplo tras recibir patente (cliente aún consultando, sin pedir cotización): ["Listo, anoté tu patente. Es un Fiat Bravo, ¿cierto?", "El aviso de Hill Holder suele encenderse por una falla en el sensor de freno de mano o en el interruptor del pedal de freno; a veces también por el sensor de inclinación.", "¿El aviso está siempre prendido o solo cuando frenas en pendiente?"]
    - Ejemplo cuando el cliente YA pide presupuesto/agendar: ["Dale, te armo el borrador para que el taller te confirme el valor.", "¿Me confirmas tu teléfono de contacto para coordinarlo?"]
    - En saludo: 1 burbuja. En asesoría simple: 1-2. Máximo 3.
    - También rellena "respuesta_cliente" concatenando las burbujas (fallback). NUNCA dejes ambas vacías (sobre todo con audio/foto).
21b. CIERRE NATURAL (CRÍTICO — no cerrar como bot):
    - PROHIBIDO cerrar mensajes con "quedo atento a tu respuesta", "estoy aquí para ayudarte", "no dudes en escribirnos" o equivalentes.
    - Si la respuesta entrega una confirmación o información sin pregunta pendiente, simplemente ciérrala ahí con naturalidad.

22. senal_lead: clasifica la intención REAL del cliente en ESTE turno (no solo lo que dice, sino si avanza hacia contratar):
    - curioso: pregunta genérica, no da datos del vehículo/problema, respuestas cortas, poco compromiso.
    - comparando_precios: pide precio pero evita dar patente/teléfono, o menciona otras opciones/talleres.
    - sin_presupuesto: objeta el precio mencionado o pide descuento repetido sin avanzar.
    - interesado: entrega datos reales (patente/problema/teléfono) y pide cotización formalmente.
    - listo_agendar: acepta cotización o pide agendar/coordinar día y hora directamente.
    - no_automotriz: fuera de tema o spam.
23. NO INSISTIR: si el resumen de conversación, la memoria del cliente o el historial indican que el cliente solo quería asesoría, está comparando, dijo que lo pensará, o mostró baja disposición (senal_lead curioso/comparando_precios/sin_presupuesto), NO vuelvas a empujar cotización o agendamiento en cada turno. Deja que el cliente marque el ritmo; solo retoma la propuesta si hay señal clara de avance en ESTE mensaje (pide precio, confirma que quiere cotizar, da patente/teléfono para avanzar).
24. resumen_turno: una frase breve (máx. 120 caracteres) sobre lo esencial de ESTE turno para memoria futura (tema, disposición del cliente, acuerdos). Ej: "Preguntó por pastillas; quiere pensarlo; no pidió cotizar aún." Si no hay nada nuevo relevante, déjalo vacío "".
25. APRENDIZAJE DE VENTAS: si el bloque RAG trae "conversaciones que resultaron en venta", aprende el TONO y los ARGUMENTOS que funcionaron (cómo explicaron repuestos, garantía, objeciones). NUNCA copies datos de otro cliente (nombre, patente, teléfono). Úsalo como inspiración de estilo, no como script literal.
26. NO hables de tarifas ni de "armar borrador" si el cliente solo entregó un dato (patente/teléfono/síntoma) y NO pidió precio. Primero confirma/asesora y pide el siguiente dato.
27. ALCANCE DE REPUESTOS (CRÍTICO): declara alcance_repuestos en cada turno donde haya
    servicio identificado: "con_repuestos" | "solo_mano_obra" | "no_definido".
    - Si el cliente dice "solo mano de obra", "yo pongo los repuestos", "ya tengo la pieza"
      → "solo_mano_obra". NUNCA agregues piezas en ese caso.
    - Si pide un cambio de pieza (pastillas, filtros, aceite, discos, batería,
      amortiguadores) sin aclarar → "con_repuestos".
    - Si solo pide diagnóstico o revisión → "no_definido". NO asumas piezas.
    - PROHIBIDO dejar "no_definido" cuando el cliente ya nombró la pieza.
28. CALIDAD DE LA PIEZA: si el bloque PREFERENCIA DE REPUESTOS ya trae una calidad
    conocida para este cliente, ÚSALA y NO preguntes. Si no la trae y la pieza es de las
    que cambian mucho de precio, el sistema enviará la pregunta con botones — tú solo
    marcas calidad_preferida="" y sigues. NUNCA inventes marcas ni precios de una calidad.
    - "original" = pieza de la marca del auto (concesionario). Suele no tener referencia
      web: si el cliente la elige, la línea puede quedar sin precio y eso está BIEN.
    - "oem" = misma fábrica que la original, sin la caja de la marca.
    - "alternativo" = equivalente de otra marca, más económico.
    - PROHIBIDO decir que una calidad es "mala" o "insegura". Se comparan precio y garantía.
29. PIEZAS MENCIONADAS: llena piezas_mencionadas SOLO con lo que el cliente nombró
    explícitamente en ESTE auto. No agregues piezas por asociación técnica
    (pastillas ≠ discos), ni por lo que el taller ofrece, ni por el historial de la patente.
30. RESUMEN DE ALCANCE: cuando el sistema te pida el resumen, lista la mano de obra y las
    piezas que van al borrador, en viñetas cortas, SIN montos (salvo que el monto esté en
    la FICHA OPERATIVA). Cierra con UNA pregunta: si quiere sumar algo o lo dejas así.
    Una sola vez por cotización. Si el cliente ya dijo "mándame el precio ya" o equivalente,
    NO resumas: avanza.
31. VITRINA: cuando el sistema haya enviado el link de opciones, NO repitas las opciones en
    texto ni describas fotos que no viste. Una frase para invitarlo a elegir y listo. Si el
    cliente no la abre, NO insistas más de una vez.

Responde SOLO JSON válido:
{{
  "respuesta_cliente": "...",
  "respuestas_cliente": ["...", "..."],
  "intencion": "saludo|asesoria|cotizacion|agenda|otro",
  "cliente_pide_cotizacion": false,
  "alcance_repuestos": "no_definido",
  "calidad_preferida": "",
  "piezas_mencionadas": [],
  "repuestos_incluidos_ultimo_servicio": null,
  "senal_lead": "curioso",
  "resumen_turno": "",
  "datos_actualizados": {{
    "cliente_nombre": "",
    "cliente_telefono": "",
    "vehiculo": {{"marca": "", "modelo": "", "anio": "", "patente": "", "cilindraje": "", "vin": "", "kilometraje_registrado": "", "kilometraje_actual": ""}},
    "servicio_nombre": "",
    "servicios": [],
    "descripcion_problema": "",
    "modalidad": "",
    "direccion_servicio": "",
    "urgencia": "",
    "preferencias_agenda": {{"fecha": "", "hora": "", "tecnico_nombre": "", "nota": "", "confirmado_verbal": false}}
  }},
  "listo_para_cotizar": false,
  "necesita_humano": false,
  "motivo_escalamiento": ""
}}"""


def _merge_datos(previos: dict, nuevos: dict) -> dict:
    resultado = dict(previos or {})
    for key, val in (nuevos or {}).items():
        if val is None:
            continue
        if isinstance(val, dict):
            base = dict(resultado.get(key) or {})
            for sk, sv in val.items():
                if sv not in (None, '', []):
                    base[sk] = sv
            resultado[key] = base
        elif key in ('servicios', 'servicios_solicitados') and isinstance(val, list):
            prev = list(resultado.get(key) or [])
            vistos = {_clave_servicio_dedup(str(x)) for x in prev if x}
            for item in val:
                nombre = item if isinstance(item, str) else (item or {}).get('nombre') if isinstance(item, dict) else ''
                nombre = (nombre or '').strip()
                clave = _clave_servicio_dedup(nombre)
                if nombre and clave and clave not in vistos:
                    prev.append(nombre)
                    vistos.add(clave)
            if prev:
                resultado[key] = prev
        elif val not in ('', []):
            resultado[key] = val
    # Si llegó un servicio_nombre nuevo, también lo suma a la lista de servicios.
    sn = (resultado.get('servicio_nombre') or '').strip()
    if sn:
        lista = list(resultado.get('servicios') or [])
        keys = {_clave_servicio_dedup(str(x)) for x in lista if x}
        clave_sn = _clave_servicio_dedup(sn)
        if clave_sn and clave_sn not in keys and ' + ' not in sn:
            lista.append(sn)
            resultado['servicios'] = lista
    return resultado


def _obtener_o_crear_config(taller_id: int) -> TallerAgenteConfig:
    config, _ = TallerAgenteConfig.objects.get_or_create(taller_id=taller_id)
    return config


def _obtener_o_crear_sesion(conversation: Conversation, taller_id: int) -> AgenteConversacionSesion:
    sesion, created = AgenteConversacionSesion.objects.get_or_create(
        conversation=conversation,
        defaults={
            'taller_id': taller_id,
            'estado': AgenteConversacionSesion.ESTADO_CAPTURANDO,
            # Chats nuevos: agente activo por defecto (opt-out).
            'habilitado_en_chat': True,
            'pausado_por_taller': False,
        },
    )
    if not created and sesion.taller_id != taller_id:
        sesion.taller_id = taller_id
        sesion.save(update_fields=['taller_id', 'actualizado_en'])
    return sesion


def minutos_pausa_manual() -> int:
    return max(5, int(getattr(settings, 'AGENTE_IA_PAUSA_MANUAL_MINUTOS', 120) or 120))


def pausar_sesion_por_mensaje_taller(conversation_id: int) -> None:
    """
    Pausa el agente SOLO en esta conversación cuando el taller responde manualmente.
    Se reanuda automáticamente después de AGENTE_IA_PAUSA_MANUAL_MINUTOS (o a mano).
    """
    from datetime import timedelta

    hasta = timezone.now() + timedelta(minutes=minutos_pausa_manual())
    AgenteConversacionSesion.objects.filter(
        conversation_id=conversation_id,
        habilitado_en_chat=True,
    ).update(
        pausado_por_taller=True,
        pausado_hasta=hasta,
        estado=AgenteConversacionSesion.ESTADO_PAUSADO,
    )


def _reanudar_si_pausa_expiro(sesion: AgenteConversacionSesion) -> AgenteConversacionSesion:
    if not sesion.pausado_por_taller:
        return sesion
    if sesion.pausado_hasta and timezone.now() >= sesion.pausado_hasta:
        sesion.pausado_por_taller = False
        sesion.pausado_hasta = None
        sesion.estado = AgenteConversacionSesion.ESTADO_CAPTURANDO
        sesion.save(update_fields=['pausado_por_taller', 'pausado_hasta', 'estado', 'actualizado_en'])
    return sesion


def activar_agente_en_conversacion(
    *,
    conversation_id: int,
    taller_id: int,
    activo: bool,
) -> AgenteConversacionSesion:
    """Activa o desactiva el agente en una sola conversación (opt-out por chat)."""
    conversation = Conversation.objects.get(pk=conversation_id)
    sesion = _obtener_o_crear_sesion(conversation, taller_id)
    sesion.habilitado_en_chat = bool(activo)
    if activo:
        sesion.pausado_por_taller = False
        sesion.pausado_hasta = None
        if sesion.estado in (
            AgenteConversacionSesion.ESTADO_PAUSADO,
            AgenteConversacionSesion.ESTADO_CERRADO,
        ):
            sesion.estado = AgenteConversacionSesion.ESTADO_CAPTURANDO
    else:
        sesion.pausado_por_taller = True
        sesion.pausado_hasta = None
        sesion.estado = AgenteConversacionSesion.ESTADO_PAUSADO
    sesion.save(
        update_fields=[
            'habilitado_en_chat',
            'pausado_por_taller',
            'pausado_hasta',
            'estado',
            'actualizado_en',
        ]
    )
    return sesion


_CANALES_TODOS = ('WHATSAPP', 'MESSENGER', 'INSTAGRAM', 'APP')


def desactivar_agente_en_todos_los_chats(taller_id: int) -> int:
    """Apaga el agente en todas las sesiones del taller (master switch OFF)."""
    return AgenteConversacionSesion.objects.filter(
        taller_id=taller_id,
        habilitado_en_chat=True,
    ).update(
        habilitado_en_chat=False,
        pausado_por_taller=True,
        pausado_hasta=None,
        estado=AgenteConversacionSesion.ESTADO_PAUSADO,
    )


def desactivar_agente_en_chats_de_canal(taller_id: int, canal: str) -> int:
    """Apaga el agente en chats del canal indicado (WHATSAPP/MESSENGER/INSTAGRAM/APP)."""
    from django.db.models import Q

    canal_norm = (canal or '').strip().upper()
    if canal_norm not in _CANALES_TODOS:
        return 0
    qs = AgenteConversacionSesion.objects.filter(
        taller_id=taller_id,
        habilitado_en_chat=True,
    )
    if canal_norm == 'APP':
        qs = qs.filter(
            Q(conversation__source_channel='APP')
            | Q(conversation__source_channel__isnull=True)
            | Q(conversation__source_channel='')
        )
    else:
        qs = qs.filter(conversation__source_channel=canal_norm)
    return qs.update(
        habilitado_en_chat=False,
        pausado_por_taller=True,
        pausado_hasta=None,
        estado=AgenteConversacionSesion.ESTADO_PAUSADO,
    )


def enviar_respuesta_agente(
    *,
    conversation: Conversation,
    proveedor_user_id: int,
    texto: str,
    extra_metadata: dict | None = None,
) -> Message | None:
    """Crea mensaje saliente del agente y lo envía por el canal correspondiente."""
    texto = (texto or '').strip()
    if not texto:
        return None

    if conversation.source_channel != 'APP':
        from mecanimovilapp.apps.omnichannel.services.outbound_guard import (
            OutboundBlockedError,
            validate_omnichannel_outbound,
        )
        try:
            validate_omnichannel_outbound(conversation)
        except OutboundBlockedError as exc:
            logger.info(
                'Agente IA no pudo enviar (outbound blocked): conv=%s code=%s',
                conversation.id,
                exc.code,
            )
            return None

    meta_out = {'from_agente_ia': True}
    if extra_metadata:
        meta_out.update(extra_metadata)
        meta_out['from_agente_ia'] = True
    message = Message.objects.create(
        conversation=conversation,
        sender_id=proveedor_user_id,
        content=texto,
        direction='outbound',
        channel_metadata=meta_out,
    )
    conversation.save()

    if conversation.source_channel != 'APP':
        from mecanimovilapp.apps.omnichannel.services.broadcast import (
            broadcast_to_participants,
            build_chat_payload,
        )
        from mecanimovilapp.apps.omnichannel.tasks import send_meta_message
        from mecanimovilapp.apps.omnichannel.utils import channel_to_api_slug

        contact = conversation.external_contact
        channel_slug = channel_to_api_slug(conversation.source_channel)
        payload = build_chat_payload(
            conversation=conversation,
            message=message,
            channel_slug=channel_slug,
            es_proveedor=True,
            sender_name='Asistente IA',
            external_contact=contact,
        )
        broadcast_to_participants(conversation, payload)
        send_meta_message.delay(message.id)
    else:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f'chat_{conversation.id}',
                {
                    'type': 'chat_message',
                    'message': message.content,
                    'content': message.content,
                    'id': message.id,
                    'mensaje_id': message.id,
                    'sender_id': proveedor_user_id,
                    'sender_name': 'Asistente IA',
                    'timestamp': message.timestamp.isoformat(),
                    'es_proveedor': True,
                    'from_agente_ia': True,
                },
            )
    return message


def _intentar_flujo_repuestos_canal(
    *,
    sesion: AgenteConversacionSesion,
    conversation: Conversation,
    taller,
    config,
    proveedor_user_id: int,
    datos: dict,
    decision: dict,
    texto_cliente: str,
    listo_cotizar: bool,
    respuestas: list[str],
    ctx_repuestos: dict,
    chunk_ids: list,
    persistir_lead,
    persistir_memoria,
) -> dict | None:
    """Calidad / resumen / vitrina. None = seguir el flujo normal."""
    from mecanimovilapp.apps.agente_ia.services.contexto_repuestos import (
        alcance_repuestos_habilitado,
    )
    from mecanimovilapp.apps.agente_ia.services.pregunta_calidad import (
        enviar_pregunta_calidad,
        pregunta_calidad_necesaria,
    )
    from mecanimovilapp.apps.agente_ia.services.resumen_alcance import (
        construir_resumen_alcance,
        debe_enviar_resumen,
        marcar_resumen_enviado,
    )

    if not alcance_repuestos_habilitado(config):
        return None

    if pregunta_calidad_necesaria(datos=datos, config=config, ctx_repuestos=ctx_repuestos):
        enviar_pregunta_calidad(
            conversation=conversation,
            proveedor_user_id=proveedor_user_id,
            datos=datos,
            sesion=sesion,
        )
        persistir_lead()
        persistir_memoria()
        return {'ok': True, 'accion': 'pregunta_calidad'}

    if listo_cotizar and debe_enviar_resumen(sesion, decision, texto_cliente):
        burbujas = construir_resumen_alcance(datos)
        enviar_respuestas_agente(
            conversation=conversation,
            proveedor_user_id=proveedor_user_id,
            textos=burbujas,
        )
        marcar_resumen_enviado(sesion)
        sesion.estado = AgenteConversacionSesion.ESTADO_ELIGIENDO_REPUESTOS
        sesion.save(update_fields=['estado', 'actualizado_en'])
        persistir_lead()
        persistir_memoria()
        return {'ok': True, 'accion': 'resumen_alcance'}
    return None


def enviar_respuestas_agente(
    *,
    conversation: Conversation,
    proveedor_user_id: int,
    textos: list[str],
    pausa_segundos: float = 0.85,
) -> list[Message]:
    """Envía 1-N burbujas como mensajes separados (ritmo conversacional tipo WhatsApp)."""
    import time

    enviados: list[Message] = []
    limpios = [t.strip() for t in (textos or []) if (t or '').strip()]
    limpios = _prevenir_respuestas_repetitivas(conversation, limpios)
    for i, texto in enumerate(limpios):
        if i > 0 and pausa_segundos > 0:
            time.sleep(pausa_segundos)
        msg = enviar_respuesta_agente(
            conversation=conversation,
            proveedor_user_id=proveedor_user_id,
            texto=texto,
        )
        if msg is not None:
            enviados.append(msg)
    return enviados


def procesar_mensaje_entrante_ia(message_id: int) -> dict[str, Any]:
    """Procesa un mensaje entrante de cliente con el agente IA."""
    if not agente_ia_habilitado():
        return {'skipped': True, 'reason': 'feature_disabled'}

    message = Message.objects.select_related(
        'conversation',
        'conversation__external_contact',
        'conversation__external_contact__connection',
    ).get(pk=message_id)

    conversation = message.conversation
    taller, proveedor_user_id = resolver_taller_desde_conversation(conversation)
    if not taller or not proveedor_user_id:
        return {'skipped': True, 'reason': 'no_taller'}

    # Omnicanal: solo inbound. Chat APP: direction suele ser outbound para ambos lados.
    meta = message.channel_metadata or {}
    if meta.get('from_agente_ia'):
        return {'skipped': True, 'reason': 'own_agent_message'}
    if conversation.source_channel != 'APP':
        if message.direction != 'inbound':
            return {'skipped': True, 'reason': 'not_inbound'}
    else:
        if message.sender_id == proveedor_user_id:
            return {'skipped': True, 'reason': 'taller_message'}

    config = _obtener_o_crear_config(taller.id)
    # Master switch del taller: si está apagado, no responde en ningún chat.
    if not config.habilitado:
        return {'skipped': True, 'reason': 'taller_agente_off'}

    canal = canal_conversacion(conversation)
    # Canal permitido a nivel taller (lista vacía = todos).
    if not config.canal_habilitado(canal):
        return {'skipped': True, 'reason': 'canal_disabled'}

    if taller.usuario_id:
        from mecanimovilapp.apps.suscripciones.cuotas_services import agente_ia_incluido_en_plan

        if not agente_ia_incluido_en_plan(taller.usuario):
            return {'skipped': True, 'reason': 'plan_sin_agente_ia'}

    sesion = _obtener_o_crear_sesion(conversation, taller.id)
    # Opt-out por conversación: si el taller lo apagó en este chat, no contesta nada.
    if not sesion.habilitado_en_chat:
        return {'skipped': True, 'reason': 'chat_agente_off'}

    sesion = _reanudar_si_pausa_expiro(sesion)
    if sesion.pausado_por_taller or sesion.estado in (
        AgenteConversacionSesion.ESTADO_PAUSADO,
        AgenteConversacionSesion.ESTADO_CERRADO,
    ):
        return {'skipped': True, 'reason': 'sesion_pausada'}

    from mecanimovilapp.apps.agente_ia.services.ws_broadcast import emitir_evento_ws_agente_ia

    emitir_evento_ws_agente_ia(
        taller_id=taller.id,
        event_type='agente_ia_procesando',
        conversation_id=conversation.id,
        mensaje_preview=(message.content or '')[:120],
    )

    # Debounce: si el cliente siguió escribiendo, este turno queda obsoleto.
    if _mensaje_cliente_superado(message):
        return {'skipped': True, 'reason': 'superseded_by_newer_message'}

    # Espera breve si Meta aún está bajando el adjunto.
    media_meta = (message.channel_metadata or {}).get('media')
    if media_meta and not message.attachment:
        for _ in range(6):
            time.sleep(1.0)
            message.refresh_from_db(fields=['attachment', 'content', 'channel_metadata'])
            if message.attachment:
                break
        # Revisa de nuevo: durante la espera pudo llegar otro mensaje del cliente.
        if _mensaje_cliente_superado(message):
            return {'skipped': True, 'reason': 'superseded_by_newer_message'}

    from mecanimovilapp.apps.agente_ia.services.media_analisis import (
        analizar_adjunto_mensaje,
        texto_cliente_enriquecido,
    )
    from mecanimovilapp.apps.agente_ia.services.contexto_patente import (
        detectar_patente_en_texto,
        enriquecer_contexto_patente,
        normalizar_patente,
    )
    from django.contrib.auth import get_user_model

    User = get_user_model()
    proveedor = User.objects.filter(pk=proveedor_user_id).first()

    datos_previos = dict(sesion.datos_capturados or {})
    vehiculo_previo = dict(datos_previos.get('vehiculo') or {})
    # Teléfono real del WhatsApp (phone o external_id) para que llegue a la cita.
    if not (datos_previos.get('cliente_telefono') or '').strip():
        contact = getattr(conversation, 'external_contact', None)
        tel = ''
        if contact is not None and hasattr(contact, 'telefono_efectivo'):
            tel = contact.telefono_efectivo()
        elif contact is not None:
            tel = (contact.phone or '') or ''
        if tel:
            datos_previos['cliente_telefono'] = tel

    analisis_media: dict[str, Any] = {}
    if message.attachment or (message.channel_metadata or {}).get('media'):
        analisis_media = analizar_adjunto_mensaje(message, vehiculo=vehiculo_previo) or {}
        message.refresh_from_db(fields=['content', 'channel_metadata', 'attachment'])

        if analisis_media.get('pendiente') and not message.attachment:
            meta = dict(message.channel_metadata or {})
            if not meta.get('media_reintento_agente'):
                meta['media_reintento_agente'] = True
                message.channel_metadata = meta
                message.save(update_fields=['channel_metadata'])
                from mecanimovilapp.apps.agente_ia.tasks import procesar_mensaje_entrante_task

                procesar_mensaje_entrante_task.apply_async(args=[message.id], countdown=8)
                return {'skipped': True, 'reason': 'media_pendiente_reintento'}

    texto_cliente = texto_cliente_enriquecido(message, analisis_media)
    if not texto_cliente:
        return {'skipped': True, 'reason': 'empty_message'}

    from mecanimovilapp.apps.agente_ia.services.seguimiento_proactivo import (
        documentar_lead_perdido,
        es_respuesta_perdida_competencia,
    )
    if es_respuesta_perdida_competencia(texto_cliente):
        documentar_lead_perdido(conversation.id, taller.id, motivo='competencia')

    if sesion.estado == AgenteConversacionSesion.ESTADO_AGENDANDO:
        from mecanimovilapp.apps.agente_ia.services.agendamiento_conversacional import (
            procesar_turno_agendamiento,
        )

        return procesar_turno_agendamiento(
            sesion=sesion,
            message=message,
            texto_cliente=texto_cliente,
            conversation=conversation,
            taller=taller,
            proveedor_user_id=proveedor_user_id,
        )

    contexto_media_txt = ''
    if analisis_media and not analisis_media.get('pendiente') and not analisis_media.get('error'):
        contexto_media_txt = json.dumps(analisis_media, ensure_ascii=False)
        if analisis_media.get('sintoma_sintetizado') and not datos_previos.get('descripcion_problema'):
            datos_previos['descripcion_problema'] = analisis_media['sintoma_sintetizado']
            sesion.datos_capturados = datos_previos
            sesion.save(update_fields=['datos_capturados', 'actualizado_en'])
    elif analisis_media.get('pendiente') or analisis_media.get('error'):
        from mecanimovilapp.apps.agente_ia.services.media_analisis import _nota_adjunto_degradado

        contexto_media_txt = _nota_adjunto_degradado(analisis_media)

    # ── Lookup automático de patente ──────────────────────────────────────
    patente_prev_enriquecida = normalizar_patente(datos_previos.get('patente_enriquecida') or '')
    patente_nueva_en_mensaje = detectar_patente_en_texto(texto_cliente)
    patente_detectada = patente_nueva_en_mensaje or normalizar_patente(
        vehiculo_previo.get('patente') or patente_prev_enriquecida or ''
    )
    debe_enriquecer_patente = bool(
        patente_detectada
        and (
            not patente_prev_enriquecida
            or (
                patente_nueva_en_mensaje
                and patente_nueva_en_mensaje != patente_prev_enriquecida
            )
        )
    )
    contexto_patente_txt = ''
    if debe_enriquecer_patente:
        enriq = enriquecer_contexto_patente(
            patente=patente_detectada,
            taller_id=taller.id,
            proveedor_user=proveedor,
        )
        contexto_patente_txt = enriq.get('texto_contexto') or ''
        persistir_enriquecimiento = False
        if enriq.get('historial_red'):
            datos_previos['historial_red'] = enriq['historial_red']
            persistir_enriquecimiento = True
        if enriq.get('vehiculo'):
            persistir_enriquecimiento = True
            vehiculo_previo = _merge_datos(vehiculo_previo, enriq['vehiculo'])
            datos_previos['vehiculo'] = vehiculo_previo
            if (
                patente_prev_enriquecida
                and patente_detectada
                and patente_prev_enriquecida != patente_detectada
            ):
                datos_previos['servicios'] = []
                datos_previos['servicio_nombre'] = ''
                datos_previos['descripcion_problema'] = ''
            datos_previos['vehiculo_registrado'] = bool(enriq.get('registrado_en_sistema'))
            if enriq.get('vehiculo_id'):
                datos_previos['vehiculo_id'] = enriq['vehiculo_id']
            if enriq.get('ofertas'):
                datos_previos['ofertas_catalogo'] = enriq['ofertas']
            if enriq.get('historial'):
                datos_previos['historial_servicios'] = enriq['historial']
            if enriq.get('salud'):
                datos_previos['salud_vehiculo'] = enriq['salud']
            # Dato verificado por fuente real (registro propio o API de patentes).
            # El LLM NUNCA debe pisar esto (ver merge post-Gemini más abajo).
            if enriq.get('vehiculo_fuente') in ('registro_mecanimovil', 'getapi'):
                datos_previos['vehiculo_verificado'] = dict(enriq['vehiculo'])
                datos_previos['vehiculo_fuente'] = enriq['vehiculo_fuente']
            elif patente_nueva_en_mensaje and patente_nueva_en_mensaje != patente_prev_enriquecida:
                datos_previos.pop('vehiculo_verificado', None)
                datos_previos.pop('vehiculo_fuente', None)
        if persistir_enriquecimiento:
            datos_previos['patente_enriquecida'] = patente_detectada
            sesion.datos_capturados = datos_previos
            sesion.save(update_fields=['datos_capturados', 'actualizado_en'])
    elif datos_previos.get('patente_enriquecida'):
        # Reinyecta resumen corto para el prompt en turnos siguientes
        v = vehiculo_previo
        contexto_patente_txt = (
            f"Patente {datos_previos.get('patente_enriquecida')}: "
            f"{v.get('marca', '')} {v.get('modelo', '')} {v.get('anio', '')}. "
            f"Registrado: {'sí' if datos_previos.get('vehiculo_registrado') else 'no'}."
        )
        if datos_previos.get('ofertas_catalogo'):
            contexto_patente_txt += '\nOfertas:\n' + '\n'.join(datos_previos['ofertas_catalogo'][:8])
        if datos_previos.get('salud_vehiculo'):
            contexto_patente_txt += '\n' + str(datos_previos['salud_vehiculo'])
        if datos_previos.get('historial_red'):
            from mecanimovilapp.apps.vehiculos.services.historial_red import texto_historial_red_para_prompt

            texto_red = texto_historial_red_para_prompt(datos_previos['historial_red'])
            if texto_red:
                contexto_patente_txt += '\n' + texto_red

    query_rag = '\n'.join(
        filter(
            None,
            [
                texto_cliente,
                datos_previos.get('descripcion_problema', ''),
                datos_previos.get('servicio_nombre', ''),
                ' '.join(
                    str(vehiculo_previo.get(k, '')) for k in ('marca', 'modelo', 'anio', 'patente')
                ).strip(),
            ],
        )
    )
    chunks_general, chunks_historico = buscar_contexto_taller_combinado(
        taller.id,
        query_rag,
        top_k_general=7,
        top_k_historico=3,
    )
    chunks = chunks_general + [c for c in chunks_historico if c.id not in {g.id for g in chunks_general}]
    partes_rag: list[str] = []
    if chunks_general:
        partes_rag.append(
            'Conocimiento del taller (catálogo, documentos, instrucciones):\n'
            + '\n---\n'.join(c.contenido for c in chunks_general if c.contenido)
        )
    if chunks_historico:
        partes_rag.append(
            'Casos anteriores y conversaciones que resultaron en venta (otros clientes; '
            'referencia de diagnóstico, argumentos de venta y precios orientativos — '
            'NO confundir con el historial del vehículo actual ni copiar datos personales):\n'
            + '\n---\n'.join(c.contenido for c in chunks_historico if c.contenido)
        )
    chunks_texto = '\n\n'.join(partes_rag)
    chunk_ids = [c.id for c in chunks]

    from mecanimovilapp.apps.agente_ia.services.ficha_taller import (
        construir_ficha_operativa_taller,
    )

    datos_prev = sesion.datos_capturados or {}
    vehiculo_ficha = datos_prev.get('vehiculo') or {}
    verificado_ficha = datos_prev.get('vehiculo_verificado') or {}
    if not isinstance(vehiculo_ficha, dict):
        vehiculo_ficha = {}
    if not isinstance(verificado_ficha, dict):
        verificado_ficha = {}
    marca_ficha = str(vehiculo_ficha.get('marca') or verificado_ficha.get('marca') or '').strip()
    modelo_ficha = str(vehiculo_ficha.get('modelo') or verificado_ficha.get('modelo') or '').strip()
    tipo_motor_ficha = str(vehiculo_ficha.get('tipo_motor') or verificado_ficha.get('tipo_motor') or '').strip()
    servicios_ficha = _servicios_candidato_precio(datos_prev)
    # getattr: si la migración 0010 aún no corrió en el entorno, no tumbar el agente.
    permite_hist = bool(getattr(config, 'permite_estimados_historicos', True))

    contexto_operativo_txt = construir_ficha_operativa_taller(
        taller,
        marca_vehiculo=marca_ficha,
        modelo_vehiculo=modelo_ficha,
        servicios_consulta=servicios_ficha,
        tipo_motor=tipo_motor_ficha,
        permite_estimados_historicos=permite_hist,
    )
    tiene_estimado_historico = _tiene_solo_estimado_historico(
        taller,
        datos_prev,
        permite_estimados_historicos=permite_hist,
    )

    from mecanimovilapp.apps.agente_ia.services.conocimiento_diagnostico import (
        bloque_diagnostico_relevante,
    )

    contexto_diagnostico_txt = bloque_diagnostico_relevante(
        texto_cliente=texto_cliente,
        descripcion_problema=str(datos_prev.get('descripcion_problema') or ''),
    )

    total_mensajes = conversation.messages.count()
    resumen_conv = (sesion.datos_capturados or {}).get('resumen_conversacion') or ''
    if total_mensajes > _MENSAJES_RECIENTES_LIMITE and not resumen_conv:
        resumen_conv = (
            'Conversación larga: los mensajes más antiguos no están en el historial reciente. '
            'Usa los datos capturados y el contexto del turno actual.'
        )

    memoria_txt = ''
    external_contact = getattr(conversation, 'external_contact', None)
    external_contact_id = getattr(external_contact, 'id', None) if external_contact else None
    memoria = _obtener_memoria_cliente(taller.id, external_contact_id)
    if memoria:
        partes_mem: list[str] = []
        if (memoria.resumen or '').strip():
            partes_mem.append(memoria.resumen.strip())
        if memoria.disposicion_reciente:
            disp_labels = dict(AgenteClienteMemoria.DISPOSICION_CHOICES)
            partes_mem.append(
                f'Última disposición: {disp_labels.get(memoria.disposicion_reciente, memoria.disposicion_reciente)}.'
            )
        memoria_txt = ' '.join(partes_mem)

    from mecanimovilapp.apps.agente_ia.services.reglas_comerciales import (
        construir_reglas_comerciales,
    )
    from mecanimovilapp.apps.agente_ia.services.reglas_lead import (
        construir_bloque_calificacion_lead,
    )

    lead_prev = LeadCalificacion.objects.filter(conversation_id=conversation.id).first()
    bloque_lead = construir_bloque_calificacion_lead(
        categoria=getattr(lead_prev, 'categoria', '') or '',
        score=int(getattr(lead_prev, 'score', 0) or 0),
    )

    # Persistencia determinística de comuna/objeción "cotización primero"
    # antes del LLM (para que el prompt vea lo ya dicho).
    datos_para_prompt = _enriquecer_ubicacion_en_datos(
        dict(sesion.datos_capturados or {}),
        texto_cliente,
    )
    if getattr(taller, 'modalidad_atencion', '') == 'a_domicilio':
        datos_para_prompt['modalidad'] = 'domicilio'
    elif re.search(r'\ba\s+domicilio\b', texto_cliente or '', re.I):
        datos_para_prompt['modalidad'] = 'domicilio'
    ya_presentado = _agente_ya_respondio(conversation)
    pedido_inicial = (not ya_presentado) and _cliente_trae_pedido_concreto(texto_cliente)
    nota_ubic = _nota_ubicacion_para_prompt(datos_para_prompt)

    es_terreno = _es_mensaje_terreno_tactico(texto_cliente) or sesion.estado == AgenteConversacionSesion.ESTADO_COORDINACION_TERRENO
    if es_terreno and sesion.estado != AgenteConversacionSesion.ESTADO_COORDINACION_TERRENO:
        sesion.estado = AgenteConversacionSesion.ESTADO_COORDINACION_TERRENO
        sesion.save(update_fields=['estado', 'actualizado_en'])

    bloque_rep_txt = ''
    ctx_repuestos: dict = {}
    try:
        from mecanimovilapp.apps.agente_ia.services.contexto_repuestos import (
            alcance_repuestos_habilitado,
            bloque_prompt_repuestos,
            contexto_repuestos_cliente,
        )
        from mecanimovilapp.apps.agente_ia.services.pregunta_calidad import (
            parsear_respuesta_calidad,
        )

        if alcance_repuestos_habilitado(config):
            veh_p = (datos_para_prompt.get('vehiculo') or {})
            patente_ctx = (
                (veh_p.get('patente') or '')
                or (datos_para_prompt.get('patente_enriquecida') or '')
            )
            ctx_repuestos = contexto_repuestos_cliente(
                taller,
                external_contact=conversation.external_contact,
                patente=patente_ctx,
            )
            bloque_rep_txt = bloque_prompt_repuestos(ctx_repuestos)
            parsed_cal = parsear_respuesta_calidad(texto_cliente)
            if parsed_cal and not datos_para_prompt.get('calidad_preferida'):
                datos_para_prompt['calidad_preferida'] = parsed_cal
                sesion.datos_capturados = {
                    **(sesion.datos_capturados or {}),
                    'calidad_preferida': parsed_cal,
                }
                sesion.save(update_fields=['datos_capturados', 'actualizado_en'])
    except Exception:
        logger.exception('contexto_repuestos prompt conv=%s', conversation.id)

    prompt = _construir_prompt_agente(
        nombre_taller=(taller.nombre or '').strip(),
        nombre_agente=(config.nombre_agente or '').strip(),
        instrucciones=config.instrucciones_personalizadas,
        chunks_texto=chunks_texto,
        datos_capturados=datos_para_prompt,
        chat_reciente=_mensajes_recientes(conversation),
        mensaje_cliente=texto_cliente,
        mensaje_bienvenida=config.mensaje_bienvenida,
        contexto_patente=contexto_patente_txt,
        contexto_media=contexto_media_txt,
        contexto_operativo_taller=contexto_operativo_txt,
        contexto_diagnostico=contexto_diagnostico_txt,
        resumen_conversacion=resumen_conv,
        memoria_cliente=memoria_txt,
        tiene_estimado_historico=tiene_estimado_historico,
        reglas_comerciales=construir_reglas_comerciales(config),
        calificacion_lead=bloque_lead,
        primer_contacto=not ya_presentado,
        nota_ubicacion=nota_ubic,
        pedido_en_primer_mensaje=pedido_inicial,
        es_coordinacion_terreno=es_terreno,
        contexto_repuestos=bloque_rep_txt,
    )

    decision, error = _llamar_gemini_agente(prompt)
    if not decision:
        AgenteMensajeLog.objects.create(
            sesion=sesion,
            mensaje_entrante=texto_cliente,
            chunks_usados=chunk_ids,
            respuesta_generada='',
            accion=AgenteMensajeLog.ACCION_IGNORAR,
            metadata={'error': error},
        )
        return {'ok': False, 'error': error}

    datos = _merge_datos(sesion.datos_capturados, decision.get('datos_actualizados') or {})
    datos = _acotar_servicios_al_pedido(
        previos=sesion.datos_capturados or {},
        datos=datos,
        texto_cliente=texto_cliente,
    )
    # Heurística gana al LLM vacío: comuna dicha por el cliente + dirección diferida.
    # El LLM a veces mete frases del chat ("Cuánto cuesta") en direccion_servicio.
    if _direccion_parece_basura(str(datos.get('direccion_servicio') or '')):
        datos['direccion_servicio'] = ''
    datos = _enriquecer_ubicacion_en_datos(datos, texto_cliente)
    if getattr(taller, 'modalidad_atencion', '') == 'a_domicilio':
        datos['modalidad'] = 'domicilio'
    elif re.search(r'\ba\s+domicilio\b', texto_cliente or '', re.I) and not (
        datos.get('modalidad') or ''
    ).strip():
        datos['modalidad'] = 'domicilio'
    # Conserva flags/ubicación ya capturados si el LLM los borró (nunca basura).
    prev_datos = sesion.datos_capturados or {}
    if prev_datos.get('direccion_diferida') and not datos.get('direccion_diferida'):
        datos['direccion_diferida'] = True
    prev_dir = (prev_datos.get('direccion_servicio') or '').strip()
    if (
        prev_dir
        and not (datos.get('direccion_servicio') or '').strip()
        and not _direccion_parece_basura(prev_dir)
    ):
        datos['direccion_servicio'] = prev_dir
    try:
        from mecanimovilapp.apps.agente_ia.services.contexto_repuestos import (
            alcance_repuestos_habilitado,
            aplicar_alcance_repuestos,
        )

        if alcance_repuestos_habilitado(config):
            datos = aplicar_alcance_repuestos(datos, decision, texto_cliente)
        else:
            rep_flag = decision.get('repuestos_incluidos_ultimo_servicio')
            if rep_flag is not None:
                datos['repuestos_incluidos_ultimo_servicio'] = rep_flag
    except Exception:
        logger.exception('aplicar_alcance_repuestos conv=%s', conversation.id)
        rep_flag = decision.get('repuestos_incluidos_ultimo_servicio')
        if rep_flag is not None:
            datos['repuestos_incluidos_ultimo_servicio'] = rep_flag
    resumen_turno = (decision.get('resumen_turno') or '').strip()
    if resumen_turno:
        datos['resumen_conversacion'] = _fusionar_resumen_conversacion(
            (sesion.datos_capturados or {}).get('resumen_conversacion') or '',
            resumen_turno,
        )
    # Preserva flags de enriquecimiento de patente
    for key in (
        'patente_enriquecida',
        'vehiculo_registrado',
        'vehiculo_id',
        'ofertas_catalogo',
        'historial_servicios',
        'salud_vehiculo',
        'vehiculo_verificado',
        'vehiculo_fuente',
    ):
        if key in (sesion.datos_capturados or {}) and key not in datos:
            datos[key] = sesion.datos_capturados[key]
    # Anti-alucinación: si ya tenemos marca/modelo/año verificados por una fuente real
    # (registro del cliente o API de patentes), el LLM NO puede reemplazarlos por su
    # cuenta. Esto evita casos como responder "Kia Morning" para una patente real de
    # un Honda Civic solo porque el modelo lo "completó" en el JSON de salida.
    vehiculo_verificado = datos.get('vehiculo_verificado')
    if vehiculo_verificado:
        datos['vehiculo'] = {**(datos.get('vehiculo') or {}), **vehiculo_verificado}
    else:
        # Sin verificación por patente: conservar solo la patente; no aceptar marca/modelo
        # que el LLM haya tomado del chat como sustituto.
        veh = dict(datos.get('vehiculo') or {})
        patente_ok = (
            (veh.get('patente') or '').strip()
            or (datos.get('patente_enriquecida') or '').strip()
        )
        veh = {'patente': patente_ok} if patente_ok else {}
        datos['vehiculo'] = veh
    patente_enriquecida = (datos.get('patente_enriquecida') or '').strip()
    if patente_enriquecida:
        datos['vehiculo'] = {**(datos.get('vehiculo') or {}), 'patente': patente_enriquecida}
    sesion.datos_capturados = datos
    sesion.ultima_interaccion_ia = timezone.now()
    sesion.save(update_fields=['datos_capturados', 'ultima_interaccion_ia', 'actualizado_en'])

    necesita_humano = bool(decision.get('necesita_humano'))
    listo_cotizar = bool(decision.get('listo_para_cotizar'))
    respuestas = _extraer_respuestas_cliente(decision)
    respuestas = _quitar_re_saludo(respuestas, ya_presentado=ya_presentado)
    # Si el cliente abrió con pedido concreto y la IA solo pegó la bienvenida, corrige.
    if pedido_inicial and _respuesta_ignora_pedido_inicial(respuestas, texto_cliente):
        logger.info(
            'Corrigiendo respuesta genérica que ignoró pedido inicial (conv=%s)',
            conversation.id,
        )
        respuestas = _respuesta_fallback_pedido_inicial(
            texto_cliente,
            nombre_agente=(config.nombre_agente or '').strip(),
            nombre_taller=(taller.nombre or '').strip(),
        )
        # Asegura capturar el servicio en datos aunque el LLM no lo haya puesto.
        if not (datos.get('servicio_nombre') or '').strip() and not (
            datos.get('servicios') or []
        ):
            hint = _hint_servicio_desde_texto(texto_cliente)
            if hint and hint != 'el servicio que pediste':
                # "el cambio de aceite" / "la alineación" → título capitalizado
                nombre_serv = hint
                if nombre_serv.startswith('el '):
                    nombre_serv = nombre_serv[3:].strip()
                elif nombre_serv.startswith('la '):
                    nombre_serv = nombre_serv[3:].strip()
                if nombre_serv:
                    datos['servicio_nombre'] = nombre_serv[0].upper() + nombre_serv[1:]
                    datos['servicios'] = [datos['servicio_nombre']]
                    sesion.datos_capturados = datos
                    sesion.save(update_fields=['datos_capturados', 'actualizado_en'])
    respuesta = ' '.join(respuestas).strip()
    cliente_pide_cotizacion = bool(decision.get('cliente_pide_cotizacion'))
    intencion = (decision.get('intencion') or '').strip().lower()
    senal_lead = (decision.get('senal_lead') or '').strip().lower()
    # Válvula anti-falso-positivo: si el cliente literalmente niega haber pedido
    # precio/cotización en este turno ("no he pedido cotización aún"), el flag del
    # LLM no manda — respetamos la negación explícita del cliente.
    if _cliente_niega_pedir_precio(texto_cliente):
        cliente_pide_cotizacion = False
        if intencion in ('cotizacion', 'cotizar', 'presupuesto'):
            intencion = ''
    # Primer mensaje con "quiero cotizar / cambio de aceite" cuenta como pedido de precio.
    if pedido_inicial and _cliente_trae_pedido_concreto(texto_cliente):
        if re.search(r'\b(?:cotiz|presupuesto|precio|cu[aá]nto|quiero\s+.*servicio)\b', texto_cliente or '', re.I):
            cliente_pide_cotizacion = True
            if intencion not in ('cotizacion', 'cotizar', 'presupuesto', 'asesoria'):
                intencion = 'cotizacion'
    # Si el texto pide precio/cotización (o aplaza dirección tras pedirla),
    # no dejamos que el LLM diluya la intención pidiendo calle otra vez.
    if not _cliente_niega_pedir_precio(texto_cliente) and (
        _CLIENTE_PIDE_PRECIO_RE.search(texto_cliente or '')
        or (
            datos.get('direccion_diferida')
            and _CLIENTE_PIDE_PRECIO_RE.search(texto_cliente or '')
        )
    ):
        cliente_pide_cotizacion = True
        if intencion not in ('cotizacion', 'cotizar', 'presupuesto'):
            intencion = 'cotizacion'
    cliente_pide_precio = _cliente_pide_precio_en_turno(
        texto_cliente=texto_cliente,
        cliente_pide_cotizacion=cliente_pide_cotizacion,
        intencion=intencion,
    )

    cliente_desistio = bool(_CLIENTE_RECHAZO_O_CERRADO_RE.search(texto_cliente or ''))
    if cliente_desistio:
        listo_cotizar = False
        cliente_pide_cotizacion = False
        intencion = 'rechazado'
        senal_lead = 'cerrado_perdido'
        decision['senal_lead'] = 'cerrado_perdido'
        try:
            from mecanimovilapp.apps.ordenes.models import CotizacionCanal
            from mecanimovilapp.apps.agente_ia.services.notificaciones import notificar_cotizacion_rechazada_agente
            cot_canc = CotizacionCanal.objects.filter(
                conversation_id=conversation.id,
                estado__in=['borrador', 'enviada'],
            ).first()
            if cot_canc:
                cot_canc.estado = 'cancelada'
                cot_canc.save(update_fields=['estado', 'actualizado_en'])
                notificar_cotizacion_rechazada_agente(
                    proveedor_user_id=proveedor_user_id,
                    cotizacion=cot_canc,
                    conversation_id=conversation.id,
                )
        except Exception as c_exc:
            logger.warning('Error cancelando cotizaciones por desinterés del cliente: %s', c_exc)
        sesion.estado = AgenteConversacionSesion.ESTADO_CERRADO
        sesion.save(update_fields=['estado', 'actualizado_en'])

    def _persistir_calificacion_lead() -> None:
        try:
            from mecanimovilapp.apps.agente_ia.services.lead_scoring import actualizar_calificacion_lead

            actualizar_calificacion_lead(
                conversation_id=conversation.id,
                taller_id=taller.id,
                datos=datos,
                decision=decision,
                sesion=sesion,
            )
            cal = str(datos.get('calidad_preferida') or '').strip()
            if cal and external_contact_id:
                from mecanimovilapp.apps.agente_ia.models import AgenteClienteMemoria

                mem, _ = AgenteClienteMemoria.objects.get_or_create(
                    taller_id=taller.id,
                    external_contact_id=external_contact_id,
                )
                if not mem.calidad_preferida:
                    mem.calidad_preferida = cal
                    mem.save(update_fields=['calidad_preferida', 'actualizado_en'])
        except Exception:
            logger.exception(
                'Error actualizando calificación lead conv=%s taller=%s',
                conversation.id,
                taller.id,
            )

    def _persistir_memoria_cliente() -> None:
        try:
            resumen_mem = (datos.get('resumen_conversacion') or '').strip()
            _upsert_memoria_cliente(
                taller_id=taller.id,
                external_contact_id=external_contact_id,
                conversation_id=conversation.id,
                resumen=resumen_mem,
                senal_lead=senal_lead,
            )
        except Exception:
            logger.exception(
                'Error actualizando memoria cliente conv=%s taller=%s',
                conversation.id,
                taller.id,
            )

    # Anti-alucinación de precios: sin tarifa de catálogo, limpia montos/afirmaciones.
    # El disclaimer largo solo si el cliente pidió precio; no en captura de patente/teléfono.
    puede_mencionar_precio = _tiene_precio_mencionable(
        taller,
        datos,
        permite_estimados_historicos=bool(getattr(config, 'permite_estimados_historicos', True)),
    )
    if respuestas and not puede_mencionar_precio:
        sanitizadas: list[str] = []
        for burbuja in respuestas:
            if _respuesta_afirma_precio(burbuja):
                limpia = _sanitizar_respuesta_sin_precio_catalogo(
                    burbuja,
                    cliente_pide_precio=cliente_pide_precio,
                )
                if limpia:
                    sanitizadas.append(limpia)
            else:
                sanitizadas.append(burbuja)
        if sanitizadas != respuestas:
            logger.info(
                'Sanitizado precio/tarifa sin catálogo en respuesta agente (conv=%s taller=%s pide_precio=%s)',
                conversation.id,
                taller.id,
                cliente_pide_precio,
            )
        respuestas = sanitizadas
        respuesta = ' '.join(respuestas).strip()

    # Si hay cotización abierta y el cliente pide sumar servicios (aunque el LLM
    # no haya marcado listo_para_cotizar), forzamos actualización del borrador.
    modifica_cotizacion = _cliente_modifica_cotizacion_existente(
        sesion,
        datos,
        texto_cliente=texto_cliente,
    )
    if not modifica_cotizacion and (
        _cliente_pide_quitar_de_cotizacion(texto_cliente)
        or _SOLO_SERVICIO_RE.search(texto_cliente or '')
    ):
        if _cotizacion_editable_sesion(sesion):
            modifica_cotizacion = True
    if not listo_cotizar and modifica_cotizacion:
        listo_cotizar = True
        logger.info(
            'Forzando actualización de cotización por pedido de servicio adicional '
            '(conv=%s taller=%s)',
            conversation.id,
            taller.id,
        )

    requiere_dir = bool(getattr(config, 'requiere_direccion_antes_de_cotizar', False))
    contexto_ok = _contexto_minimo_para_cotizar(
        datos,
        requiere_direccion_antes_de_cotizar=requiere_dir,
    )

    # Si el cliente pidió precio y ya hay patente+teléfono(+comuna/diferida),
    # no dependemos de que el LLM marque listo (suele quedarse pidiendo calle).
    if (
        not listo_cotizar
        and not modifica_cotizacion
        and cliente_pide_cotizacion
        and contexto_ok
    ):
        listo_cotizar = True
        logger.info(
            'Forzando listo_para_cotizar: cliente pidió precio con contexto mínimo '
            '(conv=%s taller=%s dir=%r diferida=%s)',
            conversation.id,
            taller.id,
            (datos.get('direccion_servicio') or '')[:40],
            bool(datos.get('direccion_diferida')),
        )

    # Válvula de seguridad: no cotizar “de oficio” sin contexto ni pedido del cliente.
    if listo_cotizar:
        if not contexto_ok:
            # Al actualizar cotización existente, no exigir de nuevo dirección/teléfono
            # si el borrador ya los tenía (el cliente solo suma un servicio).
            cot_abierta = _cotizacion_editable_sesion(sesion)
            if not (modifica_cotizacion and cot_abierta):
                listo_cotizar = False
        elif (
            not cliente_pide_cotizacion
            and intencion not in ('cotizacion', 'cotizar', 'presupuesto')
            and not modifica_cotizacion
        ):
            listo_cotizar = False

    if necesita_humano:
        from datetime import timedelta

        sesion.pausado_por_taller = True
        sesion.pausado_hasta = timezone.now() + timedelta(minutes=minutos_pausa_manual())
        sesion.estado = AgenteConversacionSesion.ESTADO_PAUSADO
        sesion.save(update_fields=['pausado_por_taller', 'pausado_hasta', 'estado', 'actualizado_en'])
        if respuestas:
            enviar_respuestas_agente(
                conversation=conversation,
                proveedor_user_id=proveedor_user_id,
                textos=respuestas,
            )
        lead_esc = LeadCalificacion.objects.filter(conversation_id=conversation.id).first()
        notificar_escalamiento_humano(
            proveedor_user_id=proveedor_user_id,
            conversation_id=conversation.id,
            preview=texto_cliente,
            lead_categoria=getattr(lead_esc, 'categoria', '') or '',
        )
        AgenteMensajeLog.objects.create(
            sesion=sesion,
            mensaje_entrante=texto_cliente,
            chunks_usados=chunk_ids,
            respuesta_generada=respuesta,
            accion=AgenteMensajeLog.ACCION_ESCALAR,
            metadata={
                'motivo': decision.get('motivo_escalamiento', ''),
                'intencion': intencion,
                'senal_lead': senal_lead,
                'media': bool(analisis_media),
            },
        )
        _persistir_calificacion_lead()
        _persistir_memoria_cliente()
        return {'ok': True, 'accion': 'escalar'}

    try:
        from mecanimovilapp.apps.agente_ia.services.resumen_alcance import (
            cliente_confirma_resumen,
        )

        if datos.get('resumen_alcance_enviado') and cliente_confirma_resumen(texto_cliente):
            listo_cotizar = True
    except Exception:
        pass

    flujo_rep = _intentar_flujo_repuestos_canal(
        sesion=sesion,
        conversation=conversation,
        taller=taller,
        config=config,
        proveedor_user_id=proveedor_user_id,
        datos=datos,
        decision=decision,
        texto_cliente=texto_cliente,
        listo_cotizar=listo_cotizar,
        respuestas=respuestas,
        ctx_repuestos=ctx_repuestos,
        chunk_ids=chunk_ids,
        persistir_lead=_persistir_calificacion_lead,
        persistir_memoria=_persistir_memoria_cliente,
    )
    if flujo_rep is not None:
        return flujo_rep

    if listo_cotizar:
        datos_cot = _asegurar_servicios_para_actualizar_cotizacion(
            sesion=sesion,
            datos=datos,
            texto_cliente=texto_cliente,
        )
        # Persiste servicios fusionados en la sesión para el próximo turno.
        if datos_cot.get('servicios') != (datos.get('servicios') or []):
            datos = dict(datos)
            datos['servicios'] = list(datos_cot.get('servicios') or [])
            sesion.datos_capturados = datos
            sesion.save(update_fields=['datos_capturados', 'actualizado_en'])
        # Filtros/aceite/frenos: por defecto con repuestos (el taller ajusta montos).
        if datos_cot.get('repuestos_incluidos_ultimo_servicio') is None:
            servs = datos_cot.get('servicios') or []
            if any(
                re.search(r'\b(?:filtro|aceite|pastillas|discos|buj[ií]as)\b', str(s), re.I)
                for s in servs
            ):
                datos_cot = dict(datos_cot)
                datos_cot['repuestos_incluidos_ultimo_servicio'] = True
        datos_cot['contexto_rag'] = ''
        cotizacion = crear_cotizacion_borrador_desde_agente(
            sesion=sesion,
            conversation=conversation,
            taller=taller,
            proveedor_user_id=proveedor_user_id,
            datos=datos_cot,
        )
        mensaje_cliente_parts = respuestas or [
            'Ya tengo lo necesario: estoy armando tu cotización para que el taller la revise '
            'y te la envíe por este chat. Si necesitas agregar otro servicio al mismo auto, '
            'dímelo y lo sumo a la misma cotización.'
        ]
        vitrina_txt = ''
        if cotizacion:
            try:
                from mecanimovilapp.apps.ordenes.services.vitrina_repuestos import (
                    crear_vitrina,
                    texto_mensaje_vitrina,
                    vitrina_habilitada,
                )

                if vitrina_habilitada(config):
                    vit = crear_vitrina(
                        taller=taller,
                        cotizacion=cotizacion,
                        conversation=conversation,
                        muestra_bandas=bool(getattr(config, 'vitrina_muestra_bandas', True)),
                    )
                    if vit is not None:
                        sesion.vitrina_activa = vit
                        sesion.estado = AgenteConversacionSesion.ESTADO_ELIGIENDO_REPUESTOS
                        sesion.save(update_fields=['vitrina_activa', 'estado', 'actualizado_en'])
                        vitrina_txt = texto_mensaje_vitrina(vit)
                        mensaje_cliente_parts = [vitrina_txt]
            except Exception:
                logger.exception('enviar vitrina conv=%s', conversation.id)
        mensaje_cliente = ' '.join(mensaje_cliente_parts).strip()
        if cotizacion:
            enviar_respuestas_agente(
                conversation=conversation,
                proveedor_user_id=proveedor_user_id,
                textos=mensaje_cliente_parts,
            )
        elif respuestas:
            enviar_respuestas_agente(
                conversation=conversation,
                proveedor_user_id=proveedor_user_id,
                textos=respuestas,
            )

        AgenteMensajeLog.objects.create(
            sesion=sesion,
            mensaje_entrante=texto_cliente,
            chunks_usados=chunk_ids,
            respuesta_generada=mensaje_cliente if cotizacion else respuesta,
            accion=AgenteMensajeLog.ACCION_COTIZAR,
            metadata={
                'cotizacion_id': cotizacion.id if cotizacion else None,
                'enviada_auto': False,
                'intencion': intencion,
                'cliente_pide_cotizacion': cliente_pide_cotizacion,
                'senal_lead': senal_lead,
                'media': bool(analisis_media and not analisis_media.get('error')),
            },
        )
        _persistir_calificacion_lead()
        _persistir_memoria_cliente()
        return {
            'ok': True,
            'accion': 'cotizar',
            'cotizacion_id': cotizacion.id if cotizacion else None,
            'enviada': False,
        }

    hubo_media = bool(
        message.attachment
        or (message.channel_metadata or {}).get('media')
        or analisis_media
    )
    if not respuestas and hubo_media:
        kind_media = (
            (analisis_media or {}).get('tipo_medio')
            or (analisis_media or {}).get('kind')
            or 'audio'
        )
        if analisis_media and (analisis_media.get('error') or analisis_media.get('pendiente')):
            respuestas = [
                f'Recibí tu {kind_media}, pero no pude procesarlo bien. '
                '¿Me lo reenvías o me describes con palabras qué se oye/ve?'
            ]
        else:
            respuestas = [
                f'Recibí tu {kind_media}. ¿Me confirmas qué le pasa al auto '
                'o me das la patente para orientarte mejor?'
            ]
        respuesta = ' '.join(respuestas)

    if respuestas:
        enviar_respuestas_agente(
            conversation=conversation,
            proveedor_user_id=proveedor_user_id,
            textos=respuestas,
        )
    AgenteMensajeLog.objects.create(
        sesion=sesion,
        mensaje_entrante=texto_cliente,
        chunks_usados=chunk_ids,
        respuesta_generada=respuesta,
        accion=AgenteMensajeLog.ACCION_RESPONDER,
        metadata={
            'intencion': intencion,
            'cliente_pide_cotizacion': cliente_pide_cotizacion,
            'senal_lead': senal_lead,
            'media': bool(analisis_media and not analisis_media.get('error')),
            'media_kind': (analisis_media or {}).get('tipo_medio') or (analisis_media or {}).get('kind'),
            'fallback_respuesta_vacia': hubo_media and not respuestas,
            'burbujas': len(respuestas),
        },
    )
    _persistir_calificacion_lead()
    _persistir_memoria_cliente()
    return {'ok': True, 'accion': 'responder'}
