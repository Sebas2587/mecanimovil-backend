"""Job diario de aprendizaje por taller (hallazgos + RAG opcional)."""
from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

from django.utils import timezone

from mecanimovilapp.apps.agente_ia.models import (
    AgenteAprendizajeDiario,
    AgenteMensajeLog,
    LeadCalificacion,
    TallerAgenteConfig,
    TallerConocimientoChunk,
)
from mecanimovilapp.apps.chat.models import Message
from mecanimovilapp.apps.ordenes.models import CotizacionCanal

logger = logging.getLogger(__name__)

MIN_TURNOS_LEAD_PERDIDO = 4
MIN_REPETICIONES_PATRON = 3


def _ventana_dia(fecha: date | None = None) -> tuple[datetime, datetime, date]:
    tz = timezone.get_current_timezone()
    dia = fecha or timezone.localdate()
    inicio = timezone.make_aware(datetime.combine(dia, datetime.min.time()), tz)
    fin = inicio + timedelta(days=1)
    return inicio, fin, dia


def _analizar_leads_perdidos(
    *,
    taller_id: int,
    inicio: datetime,
    fin: datetime,
) -> list[dict[str, Any]]:
    categorias_bajas = {
        LeadCalificacion.CATEGORIA_CURIOSO,
        LeadCalificacion.CATEGORIA_SIN_PRESUPUESTO,
        LeadCalificacion.CATEGORIA_COMPARANDO,
    }
    hallazgos: list[dict[str, Any]] = []
    qs = LeadCalificacion.objects.filter(
        taller_id=taller_id,
        categoria__in=categorias_bajas,
        actualizado_en__gte=inicio,
        actualizado_en__lt=fin,
    ).select_related('conversation')
    for lead in qs.iterator():
        n_msgs = Message.objects.filter(conversation_id=lead.conversation_id).count()
        if n_msgs < MIN_TURNOS_LEAD_PERDIDO:
            continue
        hallazgos.append(
            {
                'conversation_id': lead.conversation_id,
                'categoria': lead.categoria,
                'score': lead.score,
                'turnos': n_msgs,
            }
        )
    return hallazgos


def _analizar_respuestas_insuficientes(
    *,
    taller_id: int,
    inicio: datetime,
    fin: datetime,
) -> list[dict[str, Any]]:
    hallazgos: list[dict[str, Any]] = []
    qs = AgenteMensajeLog.objects.filter(
        sesion__taller_id=taller_id,
        fecha__gte=inicio,
        fecha__lt=fin,
        accion=AgenteMensajeLog.ACCION_ESCALAR,
    ).select_related('sesion')
    for log in qs.iterator():
        hallazgos.append(
            {
                'conversation_id': log.sesion.conversation_id,
                'motivo': (log.metadata or {}).get('motivo', ''),
                'preview': (log.mensaje_entrante or '')[:200],
            }
        )
    return hallazgos


def _analizar_correcciones_taller(
    *,
    taller_id: int,
    inicio: datetime,
    fin: datetime,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Devuelve hallazgos individuales y conteo de patrones por clave."""
    hallazgos: list[dict[str, Any]] = []
    patrones: Counter[str] = Counter()

    qs = (
        CotizacionCanal.objects.filter(
            taller_id=taller_id,
            estado='enviada',
            enviada_en__gte=inicio,
            enviada_en__lt=fin,
        )
        .only('id', 'metadata', 'servicio_nombre')
    )
    for cot in qs.iterator():
        meta = cot.metadata or {}
        corr = meta.get('correcciones_taller') or {}
        cambios = corr.get('cambios') or []
        if not cambios:
            continue
        hallazgos.append(
            {
                'cotizacion_id': cot.id,
                'servicio_nombre': cot.servicio_nombre,
                'cambios': cambios,
            }
        )
        for cambio in cambios:
            campo = cambio.get('campo') or 'desconocido'
            clave = campo
            if campo == 'servicios_lineas':
                nombres = [
                    (l.get('nombre') or '').strip().lower()
                    for l in (cambio.get('valor_humano') or [])
                    if isinstance(l, dict)
                ]
                clave = f'servicios_lineas:{",".join(sorted(n for n in nombres if n))}'
            elif campo in ('mano_obra_clp', 'total_clp'):
                clave = f'{campo}:{cot.servicio_nombre or ""}'.strip().lower()
            patrones[clave] += 1

    return hallazgos, dict(patrones)


def _crear_chunks_patrones(
    *,
    taller_id: int,
    dia: date,
    patrones: dict[str, int],
    correcciones: list[dict[str, Any]],
) -> list[str]:
    from mecanimovilapp.apps.agente_ia.services.rag import _upsert_chunk

    refs: list[str] = []
    for clave, n in patrones.items():
        if n < MIN_REPETICIONES_PATRON:
            continue
        contenido = (
            f'Lección operativa ({dia.isoformat()}): el taller corrigió {n} veces el mismo tipo '
            f'de dato en cotizaciones IA enviadas ayer — patrón "{clave}". '
            f'Revisar catálogo, estimados o instrucciones del agente para este caso.'
        )
        ref = f'leccion_diaria:{taller_id}:{dia.isoformat()}:{clave[:80]}'
        _upsert_chunk(
            taller_id=taller_id,
            fuente=TallerConocimientoChunk.FUENTE_LECCION_DIARIA,
            contenido=contenido,
            referencia_externa=ref,
            metadata={'patron': clave, 'repeticiones': n, 'fecha': dia.isoformat()},
        )
        refs.append(ref)
    return refs


def ejecutar_aprendizaje_diario_taller(
    taller_id: int,
    *,
    fecha: date | None = None,
) -> dict[str, Any]:
    """Analiza un día de actividad del taller y persiste hallazgos estructurados."""
    config = TallerAgenteConfig.objects.filter(taller_id=taller_id, habilitado=True).first()
    if not config:
        return {'ok': False, 'reason': 'agente_no_habilitado', 'taller_id': taller_id}

    inicio, fin, dia = _ventana_dia(fecha)
    resumen: dict[str, Any] = {
        'ok': True,
        'taller_id': taller_id,
        'fecha': dia.isoformat(),
        'hallazgos': 0,
    }

    leads = _analizar_leads_perdidos(taller_id=taller_id, inicio=inicio, fin=fin)
    for item in leads:
        AgenteAprendizajeDiario.objects.create(
            taller_id=taller_id,
            fecha=dia,
            tipo_hallazgo=AgenteAprendizajeDiario.TIPO_LEAD_PERDIDO,
            detalle_json=item,
        )
        resumen['hallazgos'] += 1

    insuficientes = _analizar_respuestas_insuficientes(taller_id=taller_id, inicio=inicio, fin=fin)
    for item in insuficientes:
        AgenteAprendizajeDiario.objects.create(
            taller_id=taller_id,
            fecha=dia,
            tipo_hallazgo=AgenteAprendizajeDiario.TIPO_RESPUESTA_INSUFICIENTE,
            detalle_json=item,
        )
        resumen['hallazgos'] += 1

    correcciones, patrones = _analizar_correcciones_taller(taller_id=taller_id, inicio=inicio, fin=fin)
    for item in correcciones:
        AgenteAprendizajeDiario.objects.create(
            taller_id=taller_id,
            fecha=dia,
            tipo_hallazgo=AgenteAprendizajeDiario.TIPO_CORRECCION_SISTEMATICA,
            detalle_json=item,
        )
        resumen['hallazgos'] += 1

    refs_rag = _crear_chunks_patrones(
        taller_id=taller_id,
        dia=dia,
        patrones=patrones,
        correcciones=correcciones,
    )
    for clave, n in patrones.items():
        if n < MIN_REPETICIONES_PATRON:
            continue
        AgenteAprendizajeDiario.objects.create(
            taller_id=taller_id,
            fecha=dia,
            tipo_hallazgo=AgenteAprendizajeDiario.TIPO_PATRON_ALTA_CONFIANZA,
            detalle_json={'patron': clave, 'repeticiones': n, 'chunks_rag': refs_rag},
        )
        resumen['hallazgos'] += 1

    logger.info(
        'Aprendizaje diario taller=%s fecha=%s hallazgos=%s chunks_rag=%s',
        taller_id,
        dia,
        resumen['hallazgos'],
        len(refs_rag),
    )
    return resumen
