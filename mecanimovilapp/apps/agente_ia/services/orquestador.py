"""Orquestador principal del agente IA conversacional."""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import requests
from django.conf import settings
from django.utils import timezone

from mecanimovilapp.apps.agente_ia.models import (
    AgenteClienteMemoria,
    AgenteConversacionSesion,
    AgenteMensajeLog,
    TallerAgenteConfig,
)
from mecanimovilapp.apps.agente_ia.services.cotizacion_borrador import crear_cotizacion_borrador_desde_agente
from mecanimovilapp.apps.agente_ia.services.notificaciones import notificar_escalamiento_humano
from mecanimovilapp.apps.agente_ia.services.rag import buscar_contexto_taller_combinado
from mecanimovilapp.apps.agente_ia.services.taller_resolver import canal_conversacion, resolver_taller_desde_conversation
from mecanimovilapp.apps.chat.models import Conversation, Message
from mecanimovilapp.apps.ordenes.services.catalogo_pricing import normalizar_nombre_servicio

logger = logging.getLogger(__name__)

_MENSAJES_RECIENTES_LIMITE = 16
_RESUMEN_CONVERSACION_MAX = 500

_JSON_FENCE = re.compile(r'```(?:json)?\s*([\s\S]*?)\s*```', re.IGNORECASE)
_SERVICIO_PAREN_RE = re.compile(
    r'\s*\([^)]*(?:repuesto|sin repuesto|con repuesto|incluye|no incluye)[^)]*\)\s*',
    re.IGNORECASE,
)


def _clave_servicio_dedup(nombre: str) -> str:
    """Clave estable para deduplicar servicios en datos capturados."""
    base = _SERVICIO_PAREN_RE.sub('', (nombre or '').strip())
    base = re.sub(r'\s*\([^)]*\)\s*', ' ', base).strip()
    return normalizar_nombre_servicio(base)


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


def _contexto_minimo_para_cotizar(datos: dict) -> bool:
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
    return len(problema) >= 12


def _cliente_modifica_cotizacion_existente(sesion: AgenteConversacionSesion, datos: dict) -> bool:
    """True si el cliente pide agregar/modificar una cotización ya iniciada."""
    cot = getattr(sesion, 'cotizacion_borrador', None)
    if not cot or cot.estado not in ('borrador', 'enviada'):
        return False
    if datos.get('repuestos_incluidos_ultimo_servicio') is not None:
        return True
    servicios = datos.get('servicios') or []
    if isinstance(servicios, list) and servicios:
        return True
    sn = (datos.get('servicio_nombre') or '').strip()
    return bool(sn)


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

_CLIENTE_PIDE_PRECIO_RE = re.compile(
    r'\b(?:'
    r'cu[aá]nto\s+(?:sale|cuesta|vale|cobra|cobran)|'
    r'precio|tarifa|presupuesto|cotizaci[oó]n|cotizar|'
    r'vale\s+la\s+pena|'
    r'cu[aá]nto\s+me\s+(?:sale|cuesta|cobran)'
    r')\b',
    re.IGNORECASE,
)

# Si el cliente NIEGA haber pedido precio/cotización ("no he pedido cotización",
# "todavía no quiero cotizar", "aún no"), NO debe contar como una petición —
# aunque la palabra "cotización"/"precio" aparezca literalmente en su frase.
_NEGACION_PRECIO_RE = re.compile(
    r'\b(?:no|nunca|jam[aá]s|todav[ií]a\s+no|a[uú]n\s+no)\b'
    r'(?:\s+\S+){0,4}?\s+'
    r'(?:cotizaci[oó]n|cotizar|presupuesto|precio|tarifa)\b',
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


def _cliente_niega_pedir_precio(texto_cliente: str) -> bool:
    """True si el cliente está aclarando que NO pidió precio/cotización (negación)."""
    return bool(_NEGACION_PRECIO_RE.search(texto_cliente or ''))


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


def _sanitizar_respuesta_sin_precio_catalogo(
    respuesta: str,
    *,
    cliente_pide_precio: bool = False,
) -> str:
    """
    Cuando no hay precio de catálogo, elimina afirmaciones de tarifa/monto.
    El disclaimer largo SOLO se agrega si el cliente pidió precio/cotización;
    en turnos de captura (patente/teléfono) solo se limpia el texto inventado.
    """
    texto = (respuesta or '').strip()
    if not texto or not _respuesta_afirma_precio(texto):
        return texto

    limpio = _MONTO_CLP_RE.sub('', texto)
    limpio = _PRECIO_CLAIM_RE.sub('', limpio)
    limpio = _FRASE_SANITIZER_LEGACY.sub('', limpio)
    # Si el modelo ya pegó el disclaimer, quitarlo cuando el cliente no pidió precio.
    if not cliente_pide_precio:
        limpio = re.sub(re.escape(_FRASE_SIN_PRECIO_CATALOGO), '', limpio, flags=re.IGNORECASE)
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
) -> str:
    datos_json = json.dumps(datos_capturados or {}, ensure_ascii=False)
    tiene_contexto = bool((chunks_texto or '').strip())
    nombre = (nombre_taller or '').strip() or 'el taller'
    agente = (nombre_agente or '').strip()
    if agente:
        bienvenida_default = (
            f'Hola, soy {agente} de {nombre}. ¿En qué te puedo ayudar con el auto?'
        )
        identidad = (
            f'Tu nombre es "{agente}" y representas al taller "{nombre}". '
            f'En el primer saludo o cuando te presentes, di que eres {agente} de {nombre} '
            f'(ej. "Hola, soy {agente} de {nombre}"). Habla SIEMPRE como {agente} del taller {nombre}.'
        )
        regla_presentacion = (
            f'0a. SOLO SALUDO / social ("hola", "buenas noches", "hey") sin problema ni pedido:\n'
            f'    - Responde cálido y breve (1-2 frases). Preséntate como "{agente} de {nombre}" si es el primer contacto.\n'
            f'    - Pregunta abierta tipo "¿en qué te puedo ayudar?" / "¿qué le pasa al auto?".\n'
            f'    - PROHIBIDO en este turno pedir patente, teléfono, modalidad, dirección o listar checklist de datos.'
        )
        regla_1b = (
            f'1b. En el primer saludo o cuando te presentes, usa tu nombre "{agente}" y el del taller "{nombre}" '
            f'(ej. "soy {agente} de {nombre}"). No digas solo "asistente del taller" ni te presentes sin nombrarte.'
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
            f'0a. SOLO SALUDO / social ("hola", "buenas noches", "hey") sin problema ni pedido:\n'
            f'    - Responde cálido y breve (1-2 frases). Preséntate con "{nombre}" si es el primer contacto.\n'
            f'    - Pregunta abierta tipo "¿en qué te puedo ayudar?" / "¿qué le pasa al auto?".\n'
            f'    - PROHIBIDO en este turno pedir patente, teléfono, modalidad, dirección o listar checklist de datos.'
        )
        regla_1b = (
            f'1b. En el primer saludo o cuando te presentes, usa el nombre real del taller ("{nombre}"). '
            f'No digas "asistente del taller" sin nombrarlo.'
        )
    return f"""{identidad} NO eres un bot de captura de leads ni un formulario: eres un mecánico/vendedor de soporte que conversa con naturalidad, escucha el momento del cliente y recién pide datos cuando aportan.

Tu prioridad en este orden:
1) Leer el contexto del turno (saludo vs pregunta vs caso ya detallado) y responder en consecuencia.
2) Entender qué le pasa al auto / qué necesita el cliente (asesoría humana).
3) Pedir SOLO el siguiente dato faltante más útil (una pregunta por turno).
4) Pedir PATENTE cuando ya hay síntoma o el cliente quiere precio/agenda (obligatoria antes de cotizar/agendar, NO en el primer "hola").
5) Cotizar SOLO cuando el cliente quiera precio/presupuesto Y ya haya patente + contexto suficiente.

Nombre real del taller (úsarlo cuando hables del taller):
{nombre}

Nombre del agente / vendedor (cómo debes presentarte; vacío = solo usar el nombre del taller):
{agente or '(sin nombre propio configurado — preséntate como del taller)'}

Instrucciones del taller (guía de fondo; NO las conviertas en checklist del primer mensaje — aplica el ritmo natural de abajo):
{instrucciones or 'Sé cordial, profesional y humano. Primero conversa; cotiza cuando el cliente lo pida o cuando el problema ya esté claro.'}

Mensaje de bienvenida (tono/referencia opcional para el primer contacto; NO lo pegues entero ni lo combines con patente+modalidad+síntoma en un solo mensaje):
{mensaje_bienvenida or bienvenida_default}

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

REGLAS DE CONVERSACIÓN:
0. LEE EL MOMENTO (CRÍTICO — prima sobre pedirle datos): adapta TONO y RITMO al mensaje actual. PROHIBIDO responder con un formulario (patente + síntoma + domicilio/taller + teléfono) en un solo mensaje. Máximo UNA pregunta nueva por turno — esto incluye preguntas compuestas unidas con "y" (ej. "¿en qué sector estás Y qué le pasa al auto?" cuenta como DOS preguntas, prohibido). Si dudas entre dos datos por pedir, prioriza SIEMPRE el síntoma/problema del auto antes que sector/dirección/teléfono.
{regla_presentacion}
0b. PREGUNTA RÁPIDA o dump de info (pide precio/servicio, o ya cuenta síntoma/patente/auto sin saludar):
    - Contesta PRIMERO lo que preguntó o reconoce lo que ya dijo (no ignores su mensaje).
    - Guarda en datos_actualizados lo que ya entregó.
    - Luego pide SOLO el siguiente dato faltante más útil (si falta síntoma → síntoma; si ya hay síntoma y falta patente para cotizar → patente; etc.).
0c. CASO YA AVANZADO (historial con datos o cliente insistiendo en cotizar/agendar):
    - No reinicies con bienvenida genérica.
    - Avanza: confirma lo que tienes, pide el faltante, o prepara cotización si cumple regla 12.
1. Español chileno, cálido, concreto. Nada de frases robot ("¡Claro! Con gusto te ayudo a cotizar…", "Para poder revisar tu caso y ver si podemos atenderte…") ni empujar cotización en cada turno.
{regla_1b}
1c. PROHIBIDO FALSA CONTINUIDAD (CRÍTICO — rompe la naturalidad): nunca digas "como te comentaba", "como te mencioné", "como te decía", "como habíamos hablado" o equivalentes SALVO que tú literalmente ya hayas dicho eso mismo antes en ESTE chat (revisa el historial reciente). Si es la primera vez que explicas algo (ej. modalidad a domicilio, dirección, horario), dilo directo y natural, sin fingir que ya se había hablado del tema. Tampoco repitas la MISMA frase textual del bloque de FICHA OPERATIVA palabra por palabra — parafraséala como lo diría una persona, no como un párrafo copiado de una configuración.
2. Si el cliente saluda o habla en genérico, aplica 0a. No saltes a cotizar ni a capturar patente.
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
14. UNA SOLA COTIZACIÓN por conversación/vehículo: si el cliente pide otro servicio para el MISMO auto, agrégalo a la misma cotización (lista "servicios") — NO trates cada servicio como cotización aparte. El sistema edita un único borrador hasta que el taller lo cierre/envíe. Si el taller ya envió una cotización y el cliente pide agregar/modificar algo, marca listo_para_cotizar=true para actualizar ESA misma cotización (se reabrirá a borrador); NO prometas una cotización nueva aparte.
14b. SERVICIOS ESTABLES: usa nombres cortos y consistentes en "servicios" (ej. "Diagnóstico de frenos", "Cambio de pastillas de freno delanteras"). NO repitas ni reformules un servicio ya capturado. NO agregues variantes con paréntesis como "(con repuestos)" en el nombre — usa repuestos_incluidos_ultimo_servicio. NO fusiones dos servicios en una frase ("diagnóstico y pastillas") si ya existen por separado.
15. PRECIOS (ANTI-ALUCINACIÓN, CRÍTICO): Solo puedes mencionar un monto en pesos ($, CLP) si ese EXACTO valor aparece en la FICHA OPERATIVA / catálogo publicado para ese servicio y vehículo. Si el cliente pregunta "cuánto sale / cuánto cuesta" y NO hay precio publicado (ej. inspección/diagnóstico a domicilio sin tarifa en catálogo):
    - PROHIBIDO inventar cifras, rangos ("entre X e Y"), "unos treinta lucas", o dejar huecos tipo "el valor es de,".
    - PROHIBIDO inventar políticas de descuento ("se descuenta del total", "se abona a la reparación").
    - Responde con esta idea (puedes parafrasear, mismo sentido): "Ese servicio no tiene una tarifa publicada en catálogo; el valor exacto te lo confirma el taller en la cotización. Si quieres, dejamos armado el borrador para que lo revisen y te lo envíen."
    - Luego pide SOLO el dato que falte (teléfono o dirección), una pregunta.
    - Si el cliente PIDIÓ precio en este turno (no antes de que lo pidiera) y ya tienes patente + teléfono + problema, marca listo_para_cotizar=true (borrador en $0; el humano completa el precio). Si el cliente NO ha pedido precio/cotización todavía, sigue asesorando con normalidad y NO marques listo_para_cotizar=true ni digas que "vas a armar el borrador" — eso se siente invasivo y genera desconfianza.
15b. COTIZACIÓN MIXTA (catálogo + sin catálogo): si agregas un servicio SIN precio publicado a una cotización que ya tiene otros servicios, NO digas que "ya quedó todo con precio" ni que "ya sumé X servicio con su valor". Aclara que ESE servicio específico lo confirma el taller al revisar el borrador; los que sí tienen catálogo pueden mencionarse solo si el monto está en la FICHA.
15c. COBERTURA MARCA/MODELO (CRÍTICO): el catálogo puede tener el mismo servicio con precios distintos por marca/modelo (ej. "Cambio de aceite" para Toyota ≠ Honda).
    - Solo puedes citar un precio si la cobertura de esa línea es "todas las marcas/modelos" O coincide con la marca/modelo del vehículo del cliente (datos capturados / contexto patente / tag [APLICA A ESTE AUTO]).
    - PROHIBIDO tomar el precio de otra marca/modelo aunque el nombre del servicio sea idéntico. Trátalo como "sin tarifa publicada para ESTE auto".
    - Respuesta estratégica (parafraseable): reconoce que sí hacen el servicio, aclara que para su marca/modelo el valor exacto lo confirma el taller en la cotización, y ofrece armar el borrador. NO inventes un "precio aproximado" a partir de otra cobertura.
15d. REPUESTOS Y GARANTÍA (proactivo): si la FICHA OPERATIVA indica repuestos con marca/calidad (Original, OEM, Alternativo) y/o días de garantía para un servicio, menciónalo al explicar ese servicio o cuando el cliente pregunte por repuestos ("¿con qué pieza queda?", "¿es original?"). Ofrece la opción configurada en catálogo con naturalidad (ej. "trabajamos con disco marca X, calidad OEM, con garantía de N días"). PROHIBIDO inventar marcas, calidades o plazos de garantía que no figuren en la ficha.
16. ENVÍO: TÚ NO envías la cotización por WhatsApp ni confirmas precios finales. Solo preparas el borrador; un humano del taller la revisa en "Cotizar con IA" y la envía. Dile al cliente que el taller le enviará la cotización.
17. Si el cliente menciona preferencia de día/hora/técnico para la visita, guárdalo en preferencias_agenda (fecha ISO si puedes, hora HH:MM, tecnico_nombre, nota). Si el día/hora propuesto cae dentro del horario del taller en la FICHA OPERATIVA, confirma verbalmente de forma proactiva (ej. "perfecto, tráelo el jueves a primera hora") y marca confirmado_verbal=true. Esto NO reserva un cupo formal; el agendamiento real ocurre al aceptar la cotización. Si el día cae fuera de horario, indícalo con amabilidad y sugiere el horario más cercano disponible.
18. MODALIDAD Y DIRECCIÓN (CRÍTICO — CERO INVENCIÓN): modalidad debe ser "taller" o "domicilio" según lo que pida el cliente Y lo que permita la FICHA OPERATIVA (bloque "Modalidad de atención del taller"). Pídela solo cuando sea relevante (cliente quiere venir/ir, o vas a cotizar/agendar) — nunca en un saludo vacío.
    - Si la FICHA dice que el taller SOLO atiende a domicilio: PROHIBIDO ofrecer, mencionar o inventar un local/sucursal física, calle, número o comuna del taller. NUNCA digas que "para casos complejos hay que llevarlo al taller" ni des una dirección — esa modalidad no existe para este taller. Si el cliente pregunta por una dirección, aclara que la atención es a domicilio y pide LA DIRECCIÓN DEL CLIENTE.
    - Si modalidad=domicilio, OBLIGATORIO pedir y guardar direccion_servicio (calle/comuna del CLIENTE). Sin dirección no digas que ya quedó a domicilio.
    - Si el taller SÍ tiene local (modalidad "en taller" o "ambas"): SOLO puedes dar la dirección física si aparece EXACTA en la FICHA OPERATIVA ("Dirección física EXACTA y verificada del taller"). PROHIBIDO inventar, completar o "adivinar" calle/número/comuna aunque el cliente insista o pregunte varias veces. Si la ficha indica que no hay dirección registrada, dilo tal cual (no inventes) y ofrece confirmarla al coordinar o escala a humano si el cliente insiste.
    - Si es taller, modalidad="taller" y direccion_servicio puede ir vacío (se usa la dirección del taller, no la del cliente).
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

Responde SOLO JSON válido:
{{
  "respuesta_cliente": "...",
  "respuestas_cliente": ["...", "..."],
  "intencion": "saludo|asesoria|cotizacion|agenda|otro",
  "cliente_pide_cotizacion": false,
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
    "modalidad": "taller",
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

    message = Message.objects.create(
        conversation=conversation,
        sender_id=proveedor_user_id,
        content=texto,
        direction='outbound',
        channel_metadata={'from_agente_ia': True},
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
        if enriq.get('vehiculo'):
            vehiculo_previo = _merge_datos(vehiculo_previo, enriq['vehiculo'])
            datos_previos['vehiculo'] = vehiculo_previo
            datos_previos['patente_enriquecida'] = patente_detectada
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

    vehiculo_ficha = (sesion.datos_capturados or {}).get('vehiculo') or {}
    verificado_ficha = (sesion.datos_capturados or {}).get('vehiculo_verificado') or {}
    if not isinstance(vehiculo_ficha, dict):
        vehiculo_ficha = {}
    if not isinstance(verificado_ficha, dict):
        verificado_ficha = {}
    marca_ficha = str(vehiculo_ficha.get('marca') or verificado_ficha.get('marca') or '').strip()
    modelo_ficha = str(vehiculo_ficha.get('modelo') or verificado_ficha.get('modelo') or '').strip()

    contexto_operativo_txt = construir_ficha_operativa_taller(
        taller,
        marca_vehiculo=marca_ficha,
        modelo_vehiculo=modelo_ficha,
    )

    from mecanimovilapp.apps.agente_ia.services.conocimiento_diagnostico import (
        bloque_diagnostico_relevante,
    )

    datos_prev = sesion.datos_capturados or {}
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

    prompt = _construir_prompt_agente(
        nombre_taller=(taller.nombre or '').strip(),
        nombre_agente=(config.nombre_agente or '').strip(),
        instrucciones=config.instrucciones_personalizadas,
        chunks_texto=chunks_texto,
        datos_capturados=sesion.datos_capturados,
        chat_reciente=_mensajes_recientes(conversation),
        mensaje_cliente=texto_cliente,
        mensaje_bienvenida=config.mensaje_bienvenida,
        contexto_patente=contexto_patente_txt,
        contexto_media=contexto_media_txt,
        contexto_operativo_taller=contexto_operativo_txt,
        contexto_diagnostico=contexto_diagnostico_txt,
        resumen_conversacion=resumen_conv,
        memoria_cliente=memoria_txt,
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
    cliente_pide_precio = _cliente_pide_precio_en_turno(
        texto_cliente=texto_cliente,
        cliente_pide_cotizacion=cliente_pide_cotizacion,
        intencion=intencion,
    )

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
    puede_mencionar_precio = _tiene_precio_catalogo_mencionable(taller, datos)
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

    # Válvula de seguridad: no cotizar “de oficio” sin contexto ni pedido del cliente.
    if listo_cotizar:
        if not _contexto_minimo_para_cotizar(datos):
            listo_cotizar = False
        elif (
            not cliente_pide_cotizacion
            and intencion not in ('cotizacion', 'cotizar', 'presupuesto')
            and not _cliente_modifica_cotizacion_existente(sesion, datos)
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
        notificar_escalamiento_humano(
            proveedor_user_id=proveedor_user_id,
            conversation_id=conversation.id,
            preview=texto_cliente,
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

    if listo_cotizar:
        datos_cot = dict(datos)
        datos_cot['contexto_rag'] = '\n'.join(
            filter(None, [chunks_texto, contexto_patente_txt])
        )
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
