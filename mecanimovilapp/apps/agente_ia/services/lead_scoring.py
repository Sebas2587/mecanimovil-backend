"""Motor de calificación de leads comerciales (heurística + señal LLM)."""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

from django.db.models import Q
from django.utils import timezone

from mecanimovilapp.apps.agente_ia.models import (
    AgenteConversacionSesion,
    AgenteMensajeLog,
    LeadCalificacion,
)
from mecanimovilapp.apps.chat.models import Message
from mecanimovilapp.apps.ordenes.models import CotizacionCanal

logger = logging.getLogger(__name__)

_OBJECION_PRECIO_RE = re.compile(
    r'(?:muy\s+car[oa]|demasiado\s+car[oa]|no\s+tengo\s+(?:esa\s+)?(?:plata|lucas|dinero)|'
    r'm[aá]s\s+barat[oa]|algo\s+m[aá]s\s+barat[oa]|descuent[oa]|rebaj[ae]|'
    r'no\s+me\s+alcanza|fuera\s+de\s+(?:mi\s+)?presupuesto)',
    re.IGNORECASE,
)
_COMPARACION_RE = re.compile(
    r'(?:estoy\s+(?:viendo|cotizando|preguntando)|voy\s+a\s+(?:preguntar|cotizar)|'
    r'otro\s+taller|en\s+otro\s+lado|cu[aá]nto\s+cobran|comparar|me\s+dijeron\s+que)',
    re.IGNORECASE,
)

EVENTO_PUNTOS = {
    'enviada': 15,
    'vista': 10,
    'aceptada': 30,
    'rechazada': -40,
    'cancelada': -40,
}

CATEGORIAS_ALTA_INTENCION = frozenset({
    LeadCalificacion.CATEGORIA_INTERESADO,
    LeadCalificacion.CATEGORIA_LISTO_AGENDAR,
})

CATEGORIAS_BAJA_INTENCION = frozenset({
    LeadCalificacion.CATEGORIA_CURIOSO,
    LeadCalificacion.CATEGORIA_SIN_PRESUPUESTO,
    LeadCalificacion.CATEGORIA_NO_AUTOMOTRIZ,
})


def _telefono_valido(val: str | None) -> bool:
    return len(''.join(c for c in (val or '') if c.isdigit())) >= 8


def _problema_util(datos: dict | None) -> bool:
    if not datos:
        return False
    problema = (
        (datos.get('descripcion_problema') or '').strip()
        or (datos.get('servicio_nombre') or '').strip()
    )
    return len(problema) >= 12


def _patente_en_datos(datos: dict | None) -> bool:
    if not datos:
        return False
    vehiculo = datos.get('vehiculo') or {}
    return bool(
        (vehiculo.get('patente') or '').strip()
        or (datos.get('patente_enriquecida') or '').strip()
    )


def _mensajes_cliente_texto(conversation_id: int, limite: int = 40) -> str:
    partes: list[str] = []
    qs = Message.objects.filter(
        conversation_id=conversation_id,
        direction='inbound',
    ).order_by('-timestamp')[:limite]
    for msg in reversed(list(qs)):
        meta = msg.channel_metadata or {}
        if meta.get('from_agente_ia'):
            continue
        texto = (msg.content or '').strip()
        if texto:
            partes.append(texto.lower())
    return '\n'.join(partes)


def _conteo_pide_cotizacion(sesion_id: int | None) -> int:
    if not sesion_id:
        return 0
    count = 0
    for log in AgenteMensajeLog.objects.filter(sesion_id=sesion_id).order_by('-fecha')[:30]:
        meta = log.metadata if isinstance(log.metadata, dict) else {}
        if meta.get('cliente_pide_cotizacion'):
            count += 1
    return min(count, 2)


def _listo_para_cotizar_alguna_vez(sesion_id: int | None) -> bool:
    if not sesion_id:
        return False
    return AgenteMensajeLog.objects.filter(
        sesion_id=sesion_id,
        accion=AgenteMensajeLog.ACCION_COTIZAR,
    ).exists()


def _estado_cotizacion_conversation(conversation_id: int) -> dict[str, Any]:
    cot = (
        CotizacionCanal.objects.filter(conversation_id=conversation_id)
        .order_by('-actualizado_en')
        .first()
    )
    if cot is None:
        return {}
    out: dict[str, Any] = {'estado': cot.estado}
    if cot.estado == 'enviada':
        fecha_ref = cot.enviada_en or cot.actualizado_en
        if fecha_ref and timezone.now() - fecha_ref >= timedelta(hours=48):
            out['inactivo_48h'] = True
    if cot.visto_en:
        out['vista'] = True
    return out


def _mapear_categoria(
    score: int,
    *,
    senales: dict[str, int],
    senal_llm: str,
    datos: dict | None,
    evento: str | None,
    cot_estado: str | None,
) -> str:
    if evento in ('rechazada', 'cancelada') or cot_estado in ('rechazada', 'cancelada', 'expirada'):
        return LeadCalificacion.CATEGORIA_CURIOSO
    if evento == 'aceptada' or cot_estado == 'aceptada':
        return LeadCalificacion.CATEGORIA_LISTO_AGENDAR

    llm_cat = LeadCalificacion.SENAL_LLM_MAP.get((senal_llm or '').strip().lower())
    if llm_cat == LeadCalificacion.CATEGORIA_NO_AUTOMOTRIZ:
        return LeadCalificacion.CATEGORIA_NO_AUTOMOTRIZ
    if llm_cat == LeadCalificacion.CATEGORIA_LISTO_AGENDAR:
        return LeadCalificacion.CATEGORIA_LISTO_AGENDAR

    preferencias = (datos or {}).get('preferencias_agenda') or {}
    tiene_agenda = any(
        (preferencias.get(k) or '').strip()
        for k in ('fecha', 'hora', 'tecnico_nombre', 'nota')
    )

    if score >= 70 and (tiene_agenda or llm_cat == LeadCalificacion.CATEGORIA_LISTO_AGENDAR):
        return LeadCalificacion.CATEGORIA_LISTO_AGENDAR
    if score >= 45:
        return LeadCalificacion.CATEGORIA_INTERESADO
    if senales.get('objecion_precio', 0) < 0 or llm_cat == LeadCalificacion.CATEGORIA_SIN_PRESUPUESTO:
        return LeadCalificacion.CATEGORIA_SIN_PRESUPUESTO
    if senales.get('comparacion', 0) < 0 or llm_cat == LeadCalificacion.CATEGORIA_COMPARANDO:
        return LeadCalificacion.CATEGORIA_COMPARANDO
    if score >= 25:
        return LeadCalificacion.CATEGORIA_SIN_CALIFICAR
    if llm_cat:
        return llm_cat
    return LeadCalificacion.CATEGORIA_CURIOSO


def calcular_score_lead(
    *,
    conversation_id: int,
    taller_id: int,
    datos: dict | None = None,
    decision: dict | None = None,
    sesion: AgenteConversacionSesion | None = None,
    evento: str | None = None,
    senales_previas: dict | None = None,
) -> dict[str, Any]:
    """Calcula score 0-100 y categoría sugerida."""
    senales: dict[str, int] = dict(senales_previas or {})
    datos = datos or {}
    decision = decision or {}

    if _patente_en_datos(datos):
        senales['patente'] = 15
    if _telefono_valido(datos.get('cliente_telefono')):
        senales['telefono'] = 10
    if _problema_util(datos):
        senales['problema'] = 10

    sesion_id = sesion.id if sesion else None
    pide_count = _conteo_pide_cotizacion(sesion_id)
    if pide_count:
        senales['pide_cotizacion'] = 10 * pide_count
    if _listo_para_cotizar_alguna_vez(sesion_id) or decision.get('listo_para_cotizar'):
        senales['listo_para_cotizar'] = 20

    cot_info = _estado_cotizacion_conversation(conversation_id)
    cot_estado = cot_info.get('estado')
    if cot_estado == 'enviada' and cot_info.get('vista'):
        senales.setdefault('evento_vista', EVENTO_PUNTOS['vista'])
    if cot_estado == 'enviada' and cot_info.get('inactivo_48h'):
        senales['inactivo_48h'] = -10
    if cot_estado == 'aceptada':
        senales['evento_aceptada'] = EVENTO_PUNTOS['aceptada']

    if evento and evento in EVENTO_PUNTOS:
        senales[f'evento_{evento}'] = EVENTO_PUNTOS[evento]

    texto_cliente = _mensajes_cliente_texto(conversation_id)
    if texto_cliente:
        if _OBJECION_PRECIO_RE.search(texto_cliente):
            senales['objecion_precio'] = -20
        if _COMPARACION_RE.search(texto_cliente):
            senales['comparacion'] = -10

    score_heur = max(0, min(100, sum(senales.values())))

    senal_llm = (decision.get('senal_lead') or '').strip().lower()
    ajuste_llm = 0
    if senal_llm == 'interesado':
        ajuste_llm = 10
    elif senal_llm == 'listo_agendar':
        ajuste_llm = 15
    elif senal_llm in ('comparando_precios', 'sin_presupuesto'):
        ajuste_llm = -10
    elif senal_llm == 'curioso':
        ajuste_llm = -5
    elif senal_llm == 'no_automotriz':
        ajuste_llm = -15

    ajuste_llm = max(-15, min(15, ajuste_llm))
    if ajuste_llm:
        senales['ajuste_llm'] = ajuste_llm

    score = max(0, min(100, score_heur + ajuste_llm))

    if evento in ('rechazada', 'cancelada'):
        score = 0
    elif evento == 'aceptada' or cot_estado == 'aceptada':
        score = max(score, 85)

    categoria = _mapear_categoria(
        score,
        senales=senales,
        senal_llm=senal_llm,
        datos=datos,
        evento=evento,
        cot_estado=cot_estado,
    )

    return {
        'score': score,
        'categoria': categoria,
        'senal_llm': senal_llm,
        'senales': senales,
    }


def actualizar_calificacion_lead(
    *,
    conversation_id: int | None,
    taller_id: int | None,
    datos: dict | None = None,
    decision: dict | None = None,
    sesion: AgenteConversacionSesion | None = None,
    evento: str | None = None,
) -> LeadCalificacion | None:
    if not conversation_id or not taller_id:
        return None

    prev = LeadCalificacion.objects.filter(conversation_id=conversation_id).first()
    senales_previas = dict(prev.senales) if prev and isinstance(prev.senales, dict) else {}

    if sesion is None:
        sesion = AgenteConversacionSesion.objects.filter(conversation_id=conversation_id).first()
    if datos is None and sesion is not None:
        datos = sesion.datos_capturados or {}

    resultado = calcular_score_lead(
        conversation_id=conversation_id,
        taller_id=taller_id,
        datos=datos,
        decision=decision,
        sesion=sesion,
        evento=evento,
        senales_previas=senales_previas,
    )

    lead, _ = LeadCalificacion.objects.update_or_create(
        conversation_id=conversation_id,
        defaults={
            'taller_id': taller_id,
            'categoria': resultado['categoria'],
            'score': resultado['score'],
            'senal_llm': resultado.get('senal_llm') or '',
            'senales': resultado['senales'],
        },
    )
    return lead


def actualizar_calificacion_desde_cotizacion(
    cotizacion: CotizacionCanal,
    *,
    evento: str,
) -> LeadCalificacion | None:
    if not cotizacion.conversation_id or not cotizacion.taller_id:
        return None
    return actualizar_calificacion_lead(
        conversation_id=cotizacion.conversation_id,
        taller_id=cotizacion.taller_id,
        evento=evento,
    )


def recalcular_leads_taller_heuristica(taller_id: int, limite: int = 80) -> int:
    """
    Recalcula leads de conversaciones con actividad reciente sin turno de agente IA.
    Usado en el barrido periódico de pipeline.
    """
    hace_7d = timezone.now() - timedelta(days=7)
    conv_ids = (
        CotizacionCanal.objects.filter(
            taller_id=taller_id,
            conversation_id__isnull=False,
        )
        .filter(
            Q(actualizado_en__gte=hace_7d)
            | Q(enviada_en__gte=hace_7d)
        )
        .values_list('conversation_id', flat=True)
        .distinct()[:limite]
    )
    count = 0
    for conv_id in conv_ids:
        try:
            actualizar_calificacion_lead(
                conversation_id=conv_id,
                taller_id=taller_id,
            )
            count += 1
        except Exception:
            logger.exception('Error recalculando lead conv=%s', conv_id)
    return count


def lead_calificacion_por_conversation_ids(
    conversation_ids: list[int],
) -> dict[int, LeadCalificacion]:
    if not conversation_ids:
        return {}
    qs = LeadCalificacion.objects.filter(conversation_id__in=conversation_ids)
    return {lc.conversation_id: lc for lc in qs}


def es_lead_alta_intencion(categoria: str | None) -> bool:
    return (categoria or '') in CATEGORIAS_ALTA_INTENCION


def es_lead_baja_intencion(categoria: str | None) -> bool:
    return (categoria or '') in CATEGORIAS_BAJA_INTENCION


def umbrales_seguimiento_por_lead(categoria: str | None) -> tuple[int, int]:
    """
    Horas para alerta sin respuesta y demorado según calificación.
    Returns (horas_sin_respuesta, horas_demorado). demorado=999 omite alerta +48h.
    """
    if es_lead_alta_intencion(categoria):
        return 12, 24
    if es_lead_baja_intencion(categoria):
        return 24, 999
    return 24, 48


def recalcular_leads_pipeline_periodico() -> int:
    """Recalcula leads heurísticos para talleres con cotizaciones recientes."""
    hace_7d = timezone.now() - timedelta(days=7)
    taller_ids = (
        CotizacionCanal.objects.filter(
            conversation_id__isnull=False,
            actualizado_en__gte=hace_7d,
        )
        .values_list('taller_id', flat=True)
        .distinct()
    )
    total = 0
    for taller_id in taller_ids:
        if taller_id:
            total += recalcular_leads_taller_heuristica(taller_id)
    return total
