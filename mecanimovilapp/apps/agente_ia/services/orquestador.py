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
from mecanimovilapp.apps.agente_ia.services.rag import buscar_contexto_taller
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


def _mensajes_recientes(conversation: Conversation, limite: int = 12) -> str:
    lineas: list[str] = []
    qs = conversation.messages.order_by('-timestamp')[:limite]
    for msg in reversed(list(qs)):
        quien = 'Cliente' if msg.direction == 'inbound' else 'Taller'
        meta = msg.channel_metadata or {}
        if meta.get('from_agente_ia'):
            quien = 'Asistente IA'
        texto = (msg.content or '').strip()
        if texto:
            lineas.append(f'{quien}: {texto[:500]}')
    return '\n'.join(lineas) or 'Sin mensajes.'


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
            'temperature': 0.4,
            'maxOutputTokens': 1200,
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
    instrucciones: str,
    chunks_texto: str,
    datos_capturados: dict,
    chat_reciente: str,
    mensaje_cliente: str,
    mensaje_bienvenida: str,
    contexto_patente: str = '',
) -> str:
    datos_json = json.dumps(datos_capturados or {}, ensure_ascii=False)
    tiene_contexto = bool((chunks_texto or '').strip())
    return f"""Eres el asistente virtual de un taller mecánico en Chile. Tu rol es conversar con clientes por chat, capturar información del vehículo y del problema, y preparar una cotización referencial que el cliente podrá aceptar o rechazar.

Instrucciones del taller:
{instrucciones or 'Sé cordial, profesional y conciso. Pide patente y descripción del problema antes de cotizar.'}

Mensaje de bienvenida sugerido (úsalo solo si es el primer contacto y no hay historial):
{mensaje_bienvenida or 'Hola, soy el asistente del taller. ¿En qué puedo ayudarte con tu vehículo?'}

Contexto automático de la patente (API + registro interno + historial + salud + catálogo del taller). Úsalo como fuente de verdad del vehículo; NO pidas de nuevo marca/modelo/año si ya aparecen aquí:
---
{contexto_patente or 'Sin consulta de patente en este turno.'}
---

Conocimiento del taller recuperado para ESTA consulta (catálogo, historial, documentos):
---
{chunks_texto if tiene_contexto else 'Sin contexto indexado todavía para esta consulta.'}
---

Datos ya capturados de este cliente (JSON; no los repreguntes si ya están):
{datos_json}

Historial reciente del chat:
{chat_reciente}

Último mensaje del cliente:
{mensaje_cliente}

REGLAS:
1. Responde en español chileno, tono profesional, cálido y CONCRETO. Cero relleno genérico.
2. Si el cliente envió una patente y el contexto automático la identificó, confirma marca/modelo/año al cliente y avanza a preguntar el problema o el servicio (no vuelvas a pedir la patente).
3. Lee el historial: no repitas preguntas ya respondidas.
4. Haz UNA sola pregunta de captura por turno.
5. Usa el catálogo del taller (contexto patente + RAG) para proponer servicios reales con/sin repuestos cuando aplique. No inventes precios si no hay datos.
6. NO prometas fechas exactas de agenda; la cotización es referencial hasta que el cliente la acepte y el taller agenda.
7. Captura pendiente en orden: patente → (si falta) marca/modelo/año → problema/servicio → urgencia → modalidad.
8. Fuera de servicio automotriz / muy enojado → necesita_humano=true.
9. Si ya tienes vehículo identificado (por patente o datos) + problema/servicio claro → listo_para_cotizar=true. En ese caso el sistema enviará la cotización con botones de aceptar/rechazar.
10. respuesta_cliente breve (1-2 párrafos), específica al mensaje.

Responde SOLO JSON válido:
{{
  "respuesta_cliente": "...",
  "datos_actualizados": {{
    "cliente_nombre": "",
    "cliente_telefono": "",
    "vehiculo": {{"marca": "", "modelo": "", "anio": "", "patente": "", "cilindraje": ""}},
    "servicio_nombre": "",
    "descripcion_problema": "",
    "modalidad": "taller",
    "urgencia": ""
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
        elif val not in ('', []):
            resultado[key] = val
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
    """Opt-in / opt-out del agente en una sola conversación."""
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
    canal = canal_conversacion(conversation)
    # Canal permitido a nivel taller (lista vacía = todos). El opt-in real es por chat.
    canales = config.canales_habilitados or []
    if canales and canal not in canales:
        return {'skipped': True, 'reason': 'canal_disabled'}

    if taller.usuario_id:
        from mecanimovilapp.apps.suscripciones.cuotas_services import agente_ia_incluido_en_plan

        if not agente_ia_incluido_en_plan(taller.usuario):
            return {'skipped': True, 'reason': 'plan_sin_agente_ia'}

    sesion = _obtener_o_crear_sesion(conversation, taller.id)
    # Opt-in estricto por conversación (estilo ManyChat / WhatsApp bots).
    if not sesion.habilitado_en_chat:
        return {'skipped': True, 'reason': 'chat_agente_off'}

    sesion = _reanudar_si_pausa_expiro(sesion)
    if sesion.pausado_por_taller or sesion.estado in (
        AgenteConversacionSesion.ESTADO_PAUSADO,
        AgenteConversacionSesion.ESTADO_CERRADO,
    ):
        return {'skipped': True, 'reason': 'sesion_pausada'}

    texto_cliente = (message.content or '').strip()
    if not texto_cliente:
        return {'skipped': True, 'reason': 'empty_message'}

    # ── Lookup automático de patente ──────────────────────────────────────
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
    patente_detectada = detectar_patente_en_texto(texto_cliente) or normalizar_patente(
        vehiculo_previo.get('patente') or ''
    )
    contexto_patente_txt = ''
    if patente_detectada and not datos_previos.get('patente_enriquecida'):
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
    chunks = buscar_contexto_taller(taller.id, query_rag, top_k=10)
    chunks_texto = '\n---\n'.join(c.contenido for c in chunks if c.contenido)
    chunk_ids = [c.id for c in chunks]

    prompt = _construir_prompt_agente(
        instrucciones=config.instrucciones_personalizadas,
        chunks_texto=chunks_texto,
        datos_capturados=sesion.datos_capturados,
        chat_reciente=_mensajes_recientes(conversation),
        mensaje_cliente=texto_cliente,
        mensaje_bienvenida=config.mensaje_bienvenida,
        contexto_patente=contexto_patente_txt,
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
    ):
        if key in (sesion.datos_capturados or {}) and key not in datos:
            datos[key] = sesion.datos_capturados[key]
    sesion.datos_capturados = datos
    sesion.ultima_interaccion_ia = timezone.now()
    sesion.save(update_fields=['datos_capturados', 'ultima_interaccion_ia', 'actualizado_en'])

    necesita_humano = bool(decision.get('necesita_humano'))
    listo_cotizar = bool(decision.get('listo_para_cotizar'))
    respuesta = (decision.get('respuesta_cliente') or '').strip()

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
            metadata={'motivo': decision.get('motivo_escalamiento', '')},
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
        enviada = False
        if cotizacion and proveedor:
            try:
                from mecanimovilapp.apps.ordenes.services.cotizacion_canal import enviar_cotizacion_canal
                from mecanimovilapp.apps.ordenes.services.cotizacion_publica import asegurar_token_cotizacion
                from mecanimovilapp.apps.omnichannel.tasks import send_meta_message
                from mecanimovilapp.apps.agente_ia.services.notificaciones import (
                    notificar_cotizacion_enviada_agente,
                )

                asegurar_token_cotizacion(cotizacion)
                if cotizacion.url_publica:
                    meta_extra = dict(cotizacion.metadata or {})
                    meta_extra['url_publica'] = cotizacion.url_publica
                    cotizacion.metadata = meta_extra
                    cotizacion.save(update_fields=['metadata', 'actualizado_en'])

                message = enviar_cotizacion_canal(cotizacion, proveedor)
                if conversation.source_channel != 'APP':
                    send_meta_message.delay(message.id)

                sesion.estado = AgenteConversacionSesion.ESTADO_CAPTURANDO
                sesion.save(update_fields=['estado', 'actualizado_en'])
                notificar_cotizacion_enviada_agente(
                    proveedor_user_id=proveedor_user_id,
                    cotizacion=cotizacion,
                    conversation_id=conversation.id,
                )
                enviada = True
            except Exception as exc:
                logger.exception('No se pudo enviar cotización automática del agente: %s', exc)

        if respuesta and not enviada:
            enviar_respuesta_agente(
                conversation=conversation,
                proveedor_user_id=proveedor_user_id,
                texto=respuesta
                or 'Estoy preparando tu cotización referencial; te la envío en un momento.',
            )
        elif enviada and respuesta:
            # Mensaje corto previo opcional; la cotización interactive ya va en el canal
            pass

        AgenteMensajeLog.objects.create(
            sesion=sesion,
            mensaje_entrante=texto_cliente,
            chunks_usados=chunk_ids,
            respuesta_generada=respuesta,
            accion=AgenteMensajeLog.ACCION_COTIZAR,
            metadata={
                'cotizacion_id': cotizacion.id if cotizacion else None,
                'enviada_auto': enviada,
            },
        )
        return {
            'ok': True,
            'accion': 'cotizar',
            'cotizacion_id': cotizacion.id if cotizacion else None,
            'enviada': enviada,
        }

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
    )
    return {'ok': True, 'accion': 'responder'}
