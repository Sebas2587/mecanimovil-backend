"""Servicio de seguimiento proactivo del agente IA para cotizaciones enviadas sin respuesta."""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

from django.utils import timezone

from mecanimovilapp.apps.agente_ia.models import (
    AgenteClienteMemoria,
    AgenteConversacionSesion,
    AgenteMensajeLog,
    LeadCalificacion,
    TallerAgenteConfig,
)
from mecanimovilapp.apps.agente_ia.services.lead_scoring import umbrales_seguimiento_por_lead
from mecanimovilapp.apps.agente_ia.services.taller_resolver import canal_conversacion, resolver_taller_desde_conversation
from mecanimovilapp.apps.chat.models import Conversation, Message
from mecanimovilapp.apps.ordenes.models import CotizacionCanal

logger = logging.getLogger(__name__)

# Pattern para detectar cuando un cliente responde indicando que se fue con la competencia o resolvió en otro lado.
_PERDIDA_COMPETENCIA_RE = re.compile(
    r'(?:'
    r'ya\s+lo\s+(?:arregl[eé]|repar[eé]|llev[eé]|hice|solucion[eé])\b|'
    r'lo\s+llev[eé]\s+a\s+otro\b|'
    r'con\s+otro\s+(?:taller|mec[aá]nico)\b|'
    r'ya\s+(?:encontr[eé]|tengo)\s+(?:quien|otro|mec[aá]nico|taller)\b|'
    r'm[aá]s\s+barato\s+en\s+otro\b|'
    r'me\s+fui\s+con\s+otra\s+opci[oó]n|'
    r'ya\s+compr[eé]\s+en\s+otro\b|'
    r'ya\s+no\s+lo\s+necesito\b'
    r')',
    re.IGNORECASE,
)


def es_respuesta_perdida_competencia(texto: str) -> bool:
    """Retorna True si el mensaje del cliente indica que resolvió el problema con otro taller o competencia."""
    if not texto:
        return False
    return bool(_PERDIDA_COMPETENCIA_RE.search(texto))


def documentar_lead_perdido(
    conversation_id: int,
    taller_id: int,
    motivo: str = 'competencia',
) -> None:
    """Marca el lead como perdido por competencia/otro motivo y detiene seguimientos futuros."""
    try:
        lead, _ = LeadCalificacion.objects.get_or_create(
            conversation_id=conversation_id,
            defaults={'taller_id': taller_id},
        )
        lead.perdido_por_competencia = True
        lead.motivo_perdida = motivo[:100]
        senales = dict(lead.senales or {})
        senales['competencia'] = True
        senales['motivo_perdida'] = motivo
        lead.senales = senales
        lead.categoria = LeadCalificacion.CATEGORIA_NO_AUTOMOTRIZ if motivo == 'no_automotriz' else LeadCalificacion.CATEGORIA_CURIOSO
        lead.save(update_fields=['perdido_por_competencia', 'motivo_perdida', 'senales', 'categoria', 'actualizado_en'])

        # Actualiza memoria del cliente si existe
        conv = Conversation.objects.filter(pk=conversation_id).first()
        ext_id = getattr(conv, 'external_contact_id', None)
        if ext_id and taller_id:
            AgenteClienteMemoria.objects.filter(
                taller_id=taller_id,
                external_contact_id=ext_id,
            ).update(
                disposicion_reciente=AgenteClienteMemoria.DISPOSICION_NO_LISTO,
                actualizado_en=timezone.now(),
            )

        logger.info(
            'Lead documentado como perdido (conv=%s taller=%s motivo=%s)',
            conversation_id,
            taller_id,
            motivo,
        )
    except Exception:
        logger.exception(
            'Error documentando lead perdido conv=%s taller=%s',
            conversation_id,
            taller_id,
        )


def _generar_mensaje_followup(
    cotizacion: CotizacionCanal,
    nombre_agente: str = '',
    nombre_taller: str = '',
) -> str | None:
    """Utiliza Gemini para generar un mensaje de seguimiento personalizado y natural."""
    from mecanimovilapp.apps.agente_ia.services.orquestador import _llamar_gemini_agente

    taller_nombre = nombre_taller or getattr(cotizacion.taller, 'nombre', '') or 'el taller'
    agente_nombre = nombre_agente or 'Carlos'
    servicio = cotizacion.servicio_nombre or 'servicio'
    vehiculo = f'{cotizacion.vehiculo_marca} {cotizacion.vehiculo_modelo}'.strip() or 'auto'
    total = int(cotizacion.total_clp or 0)
    total_txt = f'${total:,} CLP'.replace(',', '.') if total > 0 else 'cotización'

    prompt = f"""Eres {agente_nombre} del taller "{taller_nombre}".
Hace un tiempo enviaste al cliente el presupuesto de "{servicio}" para su {vehiculo} (monto {total_txt}).
El cliente aún no ha respondido.

Escribe UN mensaje de seguimiento personalizado para WhatsApp (1 a 2 frases cortas, máximo 40 palabras).
Reglas:
- Sé cálido, servicial y profesional como un vendedor humano.
- NO uses muletillas robot ("Entendido", "Perfecto", "Quedo atento", "A la brevedad").
- Pregunta si le quedó alguna duda sobre el presupuesto o si prefiere coordinar un día para realizar el trabajo.
- NO seas agresivo ni insistente.

Responde SOLO JSON válido:
{{"respuesta_cliente": "..."}}"""

    decision, error = _llamar_gemini_agente(prompt)
    if decision and isinstance(decision, dict):
        resp = str(decision.get('respuesta_cliente') or '').strip()
        if resp:
            return resp

    # Fallback conversacional sin muletillas si falla el LLM
    return (
        f'Hola! Te escribo de {taller_nombre} para saber si pudiste revisar la cotización '
        f'de {servicio} para tu {vehiculo}. Si tienes alguna duda con el valor o los repuestos, me comentas!'
    )


def revisar_seguimiento_proactivo() -> dict[str, Any]:
    """
    Barrido periódico que evalúa cotizaciones enviadas sin respuesta 
    y envía un mensaje de seguimiento proactivo (máximo 1 por cotización).
    """
    from mecanimovilapp.apps.agente_ia.services.orquestador import (
        _obtener_o_crear_config,
        enviar_respuestas_agente,
    )

    now = timezone.now()
    stats = {
        'evaluadas': 0,
        'followups_enviados': 0,
        'omitidas_ya_enviado': 0,
        'omitidas_perdidas': 0,
        'omitidas_pausadas': 0,
    }

    # Buscar cotizaciones enviadas que tengan conversación asociada
    enviadas_qs = CotizacionCanal.objects.filter(
        estado='enviada',
        conversation__isnull=False,
    ).select_related(
        'conversation',
        'conversation__lead_calificacion',
        'taller',
    )

    for cot in enviadas_qs.iterator(chunk_size=100):
        stats['evaluadas'] += 1
        meta = dict(cot.metadata or {})

        # Verificar si ya se envió el follow-up anteriormente
        if meta.get('followup_enviado'):
            stats['omitidas_ya_enviado'] += 1
            continue

        conv = cot.conversation
        if not conv:
            continue

        taller = cot.taller
        if not taller:
            continue

        config = _obtener_o_crear_config(taller.id)
        if not config.habilitado:
            continue

        canal = canal_conversacion(conv)
        if not config.canal_habilitado(canal):
            continue

        # Verificar si el lead ya fue documentado como perdido por competencia
        lead = getattr(conv, 'lead_calificacion', None)
        if lead and lead.perdido_por_competencia:
            stats['omitidas_perdidas'] += 1
            continue

        # Verificar si la sesión del agente está activa (no pausada ni cerrada)
        sesion = AgenteConversacionSesion.objects.filter(conversation=conv).first()
        if not sesion or not sesion.habilitado_en_chat or sesion.pausado_por_taller:
            stats['omitidas_pausadas'] += 1
            continue

        if sesion.estado in (
            AgenteConversacionSesion.ESTADO_PAUSADO,
            AgenteConversacionSesion.ESTADO_CERRADO,
        ):
            stats['omitidas_pausadas'] += 1
            continue

        # Verificar si el cliente envió mensajes DESPUÉS de enviada la cotización
        fecha_ref = cot.enviada_en or cot.actualizado_en or cot.creado_en
        if not fecha_ref:
            continue

        # Si el cliente ya escribió después de fecha_ref, no enviamos seguimiento automático
        msg_inbound_reciente = Message.objects.filter(
            conversation=conv,
            direction='inbound',
            timestamp__gt=fecha_ref,
        ).exists()
        if msg_inbound_reciente:
            continue

        # Calcular tiempo transcurrido desde el envío de la cotización
        horas_transcurridas = (now - fecha_ref).total_seconds() / 3600
        categoria = lead.categoria if lead else None
        horas_sin_respuesta, _ = umbrales_seguimiento_por_lead(categoria)

        if horas_transcurridas >= horas_sin_respuesta:
            taller, proveedor_user_id = resolver_taller_desde_conversation(conv)
            if not taller or not proveedor_user_id:
                continue

            msg_texto = _generar_mensaje_followup(
                cotizacion=cot,
                nombre_agente=(config.nombre_agente or '').strip(),
                nombre_taller=(taller.nombre or '').strip(),
            )
            if not msg_texto:
                continue

            # Enviar mensaje al cliente por WhatsApp / Omnicanal / App
            enviados = enviar_respuestas_agente(
                conversation=conv,
                proveedor_user_id=proveedor_user_id,
                textos=[msg_texto],
            )

            if enviados:
                meta['followup_enviado'] = True
                meta['followup_enviado_en'] = now.isoformat()
                cot.metadata = meta
                cot.save(update_fields=['metadata', 'actualizado_en'])

                AgenteMensajeLog.objects.create(
                    sesion=sesion,
                    mensaje_entrante='[seguimiento proactivo cotización]',
                    respuesta_generada=msg_texto,
                    accion=AgenteMensajeLog.ACCION_RESPONDER,
                    metadata={
                        'cotizacion_id': cot.id,
                        'followup': True,
                        'horas_sin_respuesta': round(horas_transcurridas, 1),
                    },
                )
                stats['followups_enviados'] += 1
                logger.info(
                    'Seguimiento proactivo enviado para cotización %s (conv=%s horas=%.1f)',
                    cot.id,
                    conv.id,
                    horas_transcurridas,
                )

    logger.info('✅ revisar_seguimiento_proactivo completado: %s', stats)
    return stats
