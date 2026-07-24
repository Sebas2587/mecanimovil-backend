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
    AgenteConversacionSesion,
    AgenteMensajeLog,
    TallerAgenteConfig,
)
from mecanimovilapp.apps.agente_ia.services.cotizacion_borrador import crear_cotizacion_borrador_desde_agente
from mecanimovilapp.apps.agente_ia.services.notificaciones import notificar_escalamiento_humano
from mecanimovilapp.apps.agente_ia.services.rag import buscar_contexto_taller_combinado
from mecanimovilapp.apps.agente_ia.services.taller_resolver import canal_conversacion, resolver_taller_desde_conversation
from mecanimovilapp.apps.chat.models import Conversation, Message

logger = logging.getLogger(__name__)

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


def _mensajes_recientes(conversation: Conversation, limite: int = 16) -> str:
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
            'maxOutputTokens': 1600,
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
    instrucciones: str,
    chunks_texto: str,
    datos_capturados: dict,
    chat_reciente: str,
    mensaje_cliente: str,
    mensaje_bienvenida: str,
    contexto_patente: str = '',
    contexto_media: str = '',
    contexto_operativo_taller: str = '',
) -> str:
    datos_json = json.dumps(datos_capturados or {}, ensure_ascii=False)
    tiene_contexto = bool((chunks_texto or '').strip())
    nombre = (nombre_taller or '').strip() or 'el taller'
    bienvenida_default = (
        f'Hola, soy el asistente de {nombre}. Cuéntame qué le pasa a tu auto y te oriento.'
    )
    return f"""Eres el asesor virtual de "{nombre}", un taller mecánico en Chile. Habla SIEMPRE en nombre de {nombre} (nunca digas solo "el taller" genérico si conoces el nombre). NO eres un bot de ventas rígido: eres un mecánico que escucha, orienta y recién después cotiza cuando tiene sentido.

Tu prioridad en este orden:
1) Entender qué le pasa al auto (asesoría experta).
2) Obtener la PATENTE del vehículo (dato obligatorio antes de cotizar o agendar).
3) Hacer preguntas cortas para completar el diagnóstico.
4) Cotizar SOLO cuando el cliente quiera precio/presupuesto Y ya haya patente + contexto suficiente.

Nombre real del taller (úsarlo en saludos y cuando te presentes):
{nombre}

Instrucciones del taller:
{instrucciones or 'Sé cordial, profesional y humano. Primero asesora; cotiza cuando el cliente lo pida o cuando el problema ya esté claro.'}

Mensaje de bienvenida sugerido (solo primer contacto sin historial; si está vacío, usa el default con el nombre real):
{mensaje_bienvenida or bienvenida_default}

FICHA OPERATIVA DEL TALLER (verdad operativa en vivo: no inventes precios ni servicios fuera de catálogo/especialidades. Marcas fuera de lista: NO rechaces el lead. Categorías de servicio fuera de especialidad: no cotices ese tipo — primero diagnostica con datos reales y explica con sutileza):
---
{contexto_operativo_taller or 'Sin datos operativos configurados todavía.'}
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

Historial reciente del chat:
{chat_reciente}

Último mensaje del cliente (ya puede incluir transcripción o descripción de media):
{mensaje_cliente}

REGLAS DE CONVERSACIÓN:
1. Español chileno, cálido, concreto. Nada de frases robot ("¡Claro! Con gusto te ayudo a cotizar…") ni empujar cotización en cada turno.
1b. En el primer saludo o cuando te presentes, usa el nombre real del taller ("{nombre}"). No digas "asistente del taller" sin nombrarlo.
2. Si el cliente saluda o habla en genérico, responde humano (presentándote por {nombre} si es el primer contacto) y pregunta qué le ocurre al vehículo (síntoma), no saltes a cotizar.
3. Muchos clientes NO saben qué servicio necesitan: primero asesora (posibles causas, qué revisar, urgencia) y pide 1 dato faltante clave.
4. UNA sola pregunta de clarificación por turno (ej: cuándo ocurre el ruido, si hay luz en tablero, si pierde potencia). Si el taller solo atiende en una modalidad según la FICHA OPERATIVA, no la preguntes: infórmasela directamente.
4b. PATENTE OBLIGATORIA: la patente es el dato maestro del vehículo (marca, modelo, año, cilindraje, motor, historial). SIEMPRE debes pedirla antes de cotizar o agendar. Puedes asesorar el síntoma sin patente, pero NO marques listo_para_cotizar=true ni prometas presupuesto definitivo ni agendamiento sin patente en "Datos ya capturados". Marca/modelo/año que diga el cliente NO reemplazan la patente: esos datos los completa el sistema al consultar la patente (bloque "Contexto automático de la patente").
5. Usa adjuntos: si hay audio, responde a la transcripción/ruido; si hay foto de tablero/vano/pieza, comenta lo visto y pide confirmación. Si el análisis del adjunto falló o está pendiente, dile al cliente que no pudiste procesar el archivo y pídele que lo reenvíe o lo describa con palabras — nunca ignores el adjunto en silencio.
6. Si hay patente identificada y verificada, confírmala brevemente y avanza (no vuelvas a pedir la patente).
6b. PROHIBIDO INVENTAR marca/modelo/año/cilindraje del vehículo. SOLO puedes escribir esos campos en "datos_actualizados.vehiculo" si el bloque "Contexto automático de la patente" ya los identificó (API GetAPI.cl o registro Mecanimovil) o ya estaban verificados en "Datos ya capturados". NO uses marca+modelo+año que el cliente mencione como sustituto de la patente. Si la patente no se pudo verificar, pide que la confirme o reenvíe — no rellenes marca/modelo por tu cuenta.
7. Lee el historial: no repitas preguntas ya respondidas.
8. MARCAS (captura de leads): NUNCA rechaces ni asustes al cliente porque su marca no esté en la lista de especialidad de marcas del taller. Si la marca SÍ es de especialidad, resáltalo con naturalidad. Si NO lo es, igual avanza (patente → diagnóstico → cotización) diciendo que pueden revisar su caso; el humano decide al enviar. Solo si la modalidad pedida (ej. domicilio) NO existe en la ficha, acláralo sin cerrar el lead.
8b. ESPECIALIDADES DE SERVICIO (categorías): son distintas a las marcas. El taller SOLO cubre las categorías/especialidades de la FICHA (ej. Diagnóstico mecánico, Mantención, Frenos — NO "Diagnóstico electrónico" si no está). Flujo obligatorio:
    (1) Primero RECAUDA la mayor información útil del problema (síntoma, cuándo ocurre, ruidos, luces, audio/foto) sin especular ni inventar fallas.
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
13. cliente_pide_cotizacion=true únicamente si en este turno (o el historial reciente) el cliente pidió precio/cotización/presupuesto de forma explícita o claramente implícita.
14. UNA SOLA COTIZACIÓN por conversación/vehículo: si el cliente pide otro servicio para el MISMO auto, agrégalo a la misma cotización (lista "servicios") — NO trates cada servicio como cotización aparte. El sistema edita un único borrador hasta que el taller lo cierre/envíe.
15. PRECIOS: NUNCA digas al cliente un precio inventado ni un total en pesos si no está en la FICHA OPERATIVA / catálogo. Puedes decir que el taller te enviará la cotización revisada. Si un servicio no está publicado para ese auto, indícalo con naturalidad ("ese valor lo confirma el taller") sin inventar cifras — igual deja el borrador para que el humano complete (solo si está dentro de especialidad).
16. ENVÍO: TÚ NO envías la cotización por WhatsApp ni confirmas precios finales. Solo preparas el borrador; un humano del taller la revisa en "Cotizar con IA" y la envía. Dile al cliente que el taller le enviará la cotización.
17. Si el cliente menciona preferencia de día/hora/técnico para la visita, guárdalo en preferencias_agenda (fecha ISO si puedes, hora HH:MM, tecnico_nombre). Eso se usa al aceptar para agendar sin perder el acuerdo.
18. MODALIDAD Y DIRECCIÓN: modalidad debe ser "taller" o "domicilio" según lo que pida el cliente Y lo que permita la FICHA. Si modalidad=domicilio, OBLIGATORIO pedir y guardar direccion_servicio (calle/comuna). Sin dirección no digas que ya quedó a domicilio. Si es taller, modalidad="taller" y direccion_servicio puede ir vacío.
19. TELÉFONO: si en "Datos ya capturados" NO hay cliente_telefono, DEBES pedirle al cliente su número de teléfono (móvil con código de área Chile si puedes) y guardarlo en datos_actualizados.cliente_telefono. Sin teléfono no marques listo_para_cotizar=true. Si ya está, no lo vuelvas a pedir.
20. KILOMETRAJE: si el contexto de patente trae km registrados, trátarlo SOLO como referencia aproximada / último dato conocido — el auto pudo seguir circulando. NUNCA digas "tu auto tiene X km exactos". Puedes decir "según registro, el último km conocido era aprox. X; ¿me confirmas el kilometraje actual?" y guarda vehiculo.kilometraje_actual si el cliente lo confirma.
21. respuesta_cliente: para asesoría normal, 1-3 frases naturales con un mini consejo + 1 pregunta. Si el cliente pidió explícitamente el listado de servicios, puedes extenderte lo necesario para nombrarlos todos. NUNCA dejes respuesta_cliente vacío (sobre todo si hubo audio/foto).

Responde SOLO JSON válido:
{{
  "respuesta_cliente": "...",
  "intencion": "saludo|asesoria|cotizacion|agenda|otro",
  "cliente_pide_cotizacion": false,
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
    "preferencias_agenda": {{"fecha": "", "hora": "", "tecnico_nombre": "", "nota": ""}}
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
            vistos = {str(x).strip().lower() for x in prev if x}
            for item in val:
                nombre = item if isinstance(item, str) else (item or {}).get('nombre') if isinstance(item, dict) else ''
                nombre = (nombre or '').strip()
                if nombre and nombre.lower() not in vistos:
                    prev.append(nombre)
                    vistos.add(nombre.lower())
            if prev:
                resultado[key] = prev
        elif val not in ('', []):
            resultado[key] = val
    # Si llegó un servicio_nombre nuevo, también lo suma a la lista de servicios.
    sn = (resultado.get('servicio_nombre') or '').strip()
    if sn:
        lista = list(resultado.get('servicios') or [])
        keys = {str(x).strip().lower() for x in lista}
        if sn.lower() not in keys and ' + ' not in sn:
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
            'Casos anteriores similares atendidos por el taller (otros clientes; referencia diagnóstico/precio, '
            'NO confundir con el historial del vehículo actual):\n'
            + '\n---\n'.join(c.contenido for c in chunks_historico if c.contenido)
        )
    chunks_texto = '\n\n'.join(partes_rag)
    chunk_ids = [c.id for c in chunks]

    from mecanimovilapp.apps.agente_ia.services.ficha_taller import (
        construir_ficha_operativa_taller,
    )

    contexto_operativo_txt = construir_ficha_operativa_taller(taller)

    prompt = _construir_prompt_agente(
        nombre_taller=(taller.nombre or '').strip(),
        instrucciones=config.instrucciones_personalizadas,
        chunks_texto=chunks_texto,
        datos_capturados=sesion.datos_capturados,
        chat_reciente=_mensajes_recientes(conversation),
        mensaje_cliente=texto_cliente,
        mensaje_bienvenida=config.mensaje_bienvenida,
        contexto_patente=contexto_patente_txt,
        contexto_media=contexto_media_txt,
        contexto_operativo_taller=contexto_operativo_txt,
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
    respuesta = (decision.get('respuesta_cliente') or '').strip()
    cliente_pide_cotizacion = bool(decision.get('cliente_pide_cotizacion'))
    intencion = (decision.get('intencion') or '').strip().lower()

    # Válvula de seguridad: no cotizar “de oficio” sin contexto ni pedido del cliente.
    if listo_cotizar:
        if not _contexto_minimo_para_cotizar(datos):
            listo_cotizar = False
        elif not cliente_pide_cotizacion and intencion not in ('cotizacion', 'cotizar', 'presupuesto'):
            listo_cotizar = False

    if necesita_humano:
        from datetime import timedelta

        sesion.pausado_por_taller = True
        sesion.pausado_hasta = timezone.now() + timedelta(minutes=minutos_pausa_manual())
        sesion.estado = AgenteConversacionSesion.ESTADO_PAUSADO
        sesion.save(update_fields=['pausado_por_taller', 'pausado_hasta', 'estado', 'actualizado_en'])
        if respuesta:
            enviar_respuesta_agente(
                conversation=conversation,
                proveedor_user_id=proveedor_user_id,
                texto=respuesta,
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
                'media': bool(analisis_media),
            },
        )
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
        mensaje_cliente = respuesta or (
            'Ya tengo lo necesario: estoy armando tu cotización para que el taller la revise '
            'y te la envíe por este chat. Si necesitas agregar otro servicio al mismo auto, '
            'dímelo y lo sumo a la misma cotización.'
        )
        if cotizacion:
            enviar_respuesta_agente(
                conversation=conversation,
                proveedor_user_id=proveedor_user_id,
                texto=mensaje_cliente,
            )
        elif respuesta:
            enviar_respuesta_agente(
                conversation=conversation,
                proveedor_user_id=proveedor_user_id,
                texto=respuesta,
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
                'media': bool(analisis_media and not analisis_media.get('error')),
            },
        )
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
    if not respuesta and hubo_media:
        kind_media = (
            (analisis_media or {}).get('tipo_medio')
            or (analisis_media or {}).get('kind')
            or 'audio'
        )
        if analisis_media and (analisis_media.get('error') or analisis_media.get('pendiente')):
            respuesta = (
                f'Recibí tu {kind_media}, pero no pude procesarlo bien. '
                '¿Me lo reenvías o me describes con palabras qué se oye/ve?'
            )
        else:
            respuesta = (
                f'Recibí tu {kind_media}. ¿Me confirmas qué le pasa al auto '
                'o me das la patente para orientarte mejor?'
            )

    if respuesta:
        enviar_respuesta_agente(
            conversation=conversation,
            proveedor_user_id=proveedor_user_id,
            texto=respuesta,
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
            'media': bool(analisis_media and not analisis_media.get('error')),
            'media_kind': (analisis_media or {}).get('tipo_medio') or (analisis_media or {}).get('kind'),
            'fallback_respuesta_vacia': hubo_media and not (decision.get('respuesta_cliente') or '').strip(),
        },
    )
    return {'ok': True, 'accion': 'responder'}
