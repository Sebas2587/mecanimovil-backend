"""Búsqueda semántica y sincronización de chunks."""
from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from pgvector.django import CosineDistance

from mecanimovilapp.apps.agente_ia.models import (
    TallerAgenteConfig,
    TallerConocimientoChunk,
    TallerConocimientoDocumento,
)
from mecanimovilapp.apps.agente_ia.services.chunking import extraer_texto_pdf, fragmentar_texto
from mecanimovilapp.apps.agente_ia.services.embeddings import generar_embedding

logger = logging.getLogger(__name__)


def buscar_contexto_taller(taller_id: int, query_text: str, *, top_k: int = 8) -> list[TallerConocimientoChunk]:
    """Recupera los chunks más relevantes para una consulta."""
    query_vec = generar_embedding(query_text)
    if not query_vec:
        return list(
            TallerConocimientoChunk.objects.filter(taller_id=taller_id)
            .order_by('-fecha_actualizacion')[:top_k]
        )

    return list(
        TallerConocimientoChunk.objects.filter(taller_id=taller_id, embedding__isnull=False)
        .order_by(CosineDistance('embedding', query_vec))[:top_k]
    )


def buscar_contexto_taller_por_fuente(
    taller_id: int,
    query_text: str,
    *,
    fuente: str,
    top_k: int = 3,
) -> list[TallerConocimientoChunk]:
    """Búsqueda semántica acotada a una fuente (ej. histórico cross-cliente)."""
    return buscar_contexto_taller_por_fuentes(
        taller_id,
        query_text,
        fuentes=[fuente],
        top_k=top_k,
    )


def buscar_contexto_taller_por_fuentes(
    taller_id: int,
    query_text: str,
    *,
    fuentes: list[str] | tuple[str, ...],
    top_k: int = 3,
) -> list[TallerConocimientoChunk]:
    """Búsqueda semántica acotada a una o más fuentes."""
    if not fuentes:
        return []
    query_vec = generar_embedding(query_text)
    qs = TallerConocimientoChunk.objects.filter(taller_id=taller_id, fuente__in=list(fuentes))
    if not query_vec:
        return list(qs.order_by('-fecha_actualizacion')[:top_k])
    return list(
        qs.filter(embedding__isnull=False).order_by(CosineDistance('embedding', query_vec))[:top_k]
    )


def buscar_contexto_taller_combinado(
    taller_id: int,
    query_text: str,
    *,
    top_k_general: int = 7,
    top_k_historico: int = 3,
) -> tuple[list[TallerConocimientoChunk], list[TallerConocimientoChunk]]:
    """General (catálogo/docs/instrucciones) + histórico/conversaciones exitosas dedicado."""
    fuentes_referencia = {
        TallerConocimientoChunk.FUENTE_HISTORICO,
        TallerConocimientoChunk.FUENTE_CONVERSACION_EXITOSA,
    }
    general = [
        c
        for c in buscar_contexto_taller(taller_id, query_text, top_k=top_k_general + top_k_historico)
        if c.fuente not in fuentes_referencia
    ][:top_k_general]
    historico = buscar_contexto_taller_por_fuentes(
        taller_id,
        query_text,
        fuentes=(
            TallerConocimientoChunk.FUENTE_HISTORICO,
            TallerConocimientoChunk.FUENTE_CONVERSACION_EXITOSA,
        ),
        top_k=top_k_historico,
    )
    return general, historico


def _upsert_chunk(
    *,
    taller_id: int,
    fuente: str,
    contenido: str,
    referencia_externa: str,
    metadata: dict[str, Any] | None = None,
    documento_id: int | None = None,
) -> TallerConocimientoChunk | None:
    contenido = (contenido or '').strip()
    if not contenido:
        return None

    embedding = generar_embedding(contenido)
    if embedding is None:
        logger.warning(
            'Chunk sin embedding (taller=%s fuente=%s ref=%s). '
            'Quedará invisible para búsqueda semántica hasta backfill/reindex.',
            taller_id,
            fuente,
            referencia_externa or '(sin_ref)',
        )

    defaults = {
        'fuente': fuente,
        'contenido': contenido,
        'metadata': metadata or {},
        'documento_id': documento_id,
    }
    # Nunca pisar un embedding válido con None (p. ej. fallo puntual de Gemini).
    if embedding is not None:
        defaults['embedding'] = embedding

    if referencia_externa:
        existing = TallerConocimientoChunk.objects.filter(
            taller_id=taller_id,
            referencia_externa=referencia_externa,
        ).first()
        if existing is None:
            return TallerConocimientoChunk.objects.create(
                taller_id=taller_id,
                referencia_externa=referencia_externa,
                embedding=embedding,
                **defaults,
            )
        for key, value in defaults.items():
            setattr(existing, key, value)
        existing.save()
        return existing

    return TallerConocimientoChunk.objects.create(
        taller_id=taller_id,
        referencia_externa='',
        embedding=embedding,
        **defaults,
    )


def backfill_embeddings_faltantes(taller_id: int | None = None, limite: int = 200) -> int:
    """
    Regenera embeddings para chunks que quedaron con embedding=NULL.
    Retorna cuántos chunks se actualizaron con éxito.
    """
    qs = TallerConocimientoChunk.objects.filter(embedding__isnull=True).order_by('id')
    if taller_id is not None:
        qs = qs.filter(taller_id=taller_id)
    actualizados = 0
    for chunk in qs[: max(1, limite)]:
        emb = generar_embedding(chunk.contenido or '')
        if emb is None:
            continue
        chunk.embedding = emb
        chunk.save(update_fields=['embedding', 'fecha_actualizacion'])
        actualizados += 1
    return actualizados


@transaction.atomic
def sincronizar_instrucciones_taller(taller_id: int) -> None:
    """Indexa las instrucciones personalizadas del taller como chunk único."""
    config = TallerAgenteConfig.objects.filter(taller_id=taller_id).first()
    texto = (config.instrucciones_personalizadas if config else '') or ''
    TallerConocimientoChunk.objects.filter(
        taller_id=taller_id,
        fuente=TallerConocimientoChunk.FUENTE_INSTRUCCION,
    ).delete()
    if texto.strip():
        _upsert_chunk(
            taller_id=taller_id,
            fuente=TallerConocimientoChunk.FUENTE_INSTRUCCION,
            contenido=texto,
            referencia_externa=f'instruccion:{taller_id}',
            metadata={'tipo': 'instrucciones_personalizadas'},
        )


def sincronizar_chunk_oferta_servicio(oferta_servicio_id: int) -> None:
    from mecanimovilapp.apps.servicios.models import OfertaServicio

    oferta = (
        OfertaServicio.objects.select_related('servicio', 'taller', 'marca_vehiculo_seleccionada', 'modelo_vehiculo_seleccionado')
        .filter(pk=oferta_servicio_id, taller_id__isnull=False)
        .first()
    )
    if not oferta or not oferta.taller_id:
        return

    from mecanimovilapp.apps.agente_ia.services.catalogo_oferta_texto import (
        resumen_repuestos_garantia_oferta,
    )

    servicio = oferta.servicio
    marca = getattr(oferta.marca_vehiculo_seleccionada, 'nombre', '') or ''
    modelo = getattr(oferta.modelo_vehiculo_seleccionado, 'nombre', '') or ''
    rep_gar = resumen_repuestos_garantia_oferta(oferta)
    contenido = (
        f'Servicio: {servicio.nombre}\n'
        f'Descripción: {servicio.descripcion or ""}\n'
        f'Precio con repuestos: {oferta.precio_con_repuestos} CLP\n'
        f'Precio sin repuestos: {oferta.precio_sin_repuestos} CLP\n'
        f'Mano de obra: {oferta.costo_mano_de_obra_sin_iva} CLP\n'
        f'Repuestos: {oferta.costo_repuestos_sin_iva} CLP\n'
        f'Duración estimada: {oferta.duracion_minima_minutos}-{oferta.duracion_maxima_minutos} min\n'
        f'Motor: {oferta.tipo_motor or "general"}\n'
        f'Vehículo: {marca} {modelo}\n'
        f'Detalles: {oferta.detalles_adicionales or ""}'
    ).strip()
    if rep_gar:
        contenido = f'{contenido}\nRepuestos/garantía: {rep_gar}'

    if not oferta.disponible:
        TallerConocimientoChunk.objects.filter(
            taller_id=oferta.taller_id,
            referencia_externa=f'oferta_servicio:{oferta.id}',
        ).delete()
        return

    _upsert_chunk(
        taller_id=oferta.taller_id,
        fuente=TallerConocimientoChunk.FUENTE_CATALOGO,
        contenido=contenido,
        referencia_externa=f'oferta_servicio:{oferta.id}',
        metadata={'oferta_servicio_id': oferta.id, 'servicio_id': servicio.id},
    )


def sincronizar_chunk_historico_solicitud(solicitud_id: int) -> None:
    from mecanimovilapp.apps.ordenes.models import LineaServicio, SolicitudServicio

    solicitud = (
        SolicitudServicio.objects.select_related('taller', 'vehiculo', 'vehiculo__marca', 'vehiculo__modelo')
        .filter(pk=solicitud_id, estado='completado', taller_id__isnull=False)
        .first()
    )
    if not solicitud or not solicitud.taller_id:
        return

    lineas = LineaServicio.objects.filter(solicitud=solicitud).select_related('oferta_servicio__servicio')
    servicios_txt = []
    total = 0
    for linea in lineas:
        nombre = ''
        if linea.oferta_servicio and linea.oferta_servicio.servicio:
            nombre = linea.oferta_servicio.servicio.nombre
        precio = int(linea.precio_final or linea.precio_unitario or 0)
        total += precio
        servicios_txt.append(f'- {nombre}: {precio} CLP')

    veh = solicitud.vehiculo
    marca = getattr(getattr(veh, 'marca', None), 'nombre', '') if veh else ''
    modelo = getattr(getattr(veh, 'modelo', None), 'nombre', '') if veh else ''
    patente = getattr(veh, 'patente', '') if veh else ''

    contenido = (
        f'Servicio completado en {solicitud.fecha_servicio or solicitud.fecha_hora_solicitud}\n'
        f'Vehículo: {marca} {modelo} patente {patente}\n'
        f'Notas cliente: {solicitud.notas_cliente or ""}\n'
        f'Notas taller: {solicitud.notas_proveedor or ""}\n'
        f'Servicios:\n' + '\n'.join(servicios_txt) + f'\nTotal: {total} CLP'
    ).strip()

    _upsert_chunk(
        taller_id=solicitud.taller_id,
        fuente=TallerConocimientoChunk.FUENTE_HISTORICO,
        contenido=contenido,
        referencia_externa=f'solicitud:{solicitud.id}',
        metadata={'solicitud_id': solicitud.id},
    )


_TRANSCRIPT_MAX_MENSAJES = 40
_TRANSCRIPT_MAX_CHARS = 12000


def _llamar_gemini_texto(prompt: str) -> str | None:
    import requests
    from django.conf import settings

    api_key = (getattr(settings, 'GEMINI_API_KEY', '') or '').strip()
    model = (
        getattr(settings, 'AGENTE_IA_GEMINI_MODEL', '')
        or getattr(settings, 'ASISTENTE_COTIZACION_GEMINI_MODEL', '')
        or getattr(settings, 'GEMINI_MODEL', 'gemini-3.1-flash-lite')
        or 'gemini-3.1-flash-lite'
    ).strip()
    if not api_key:
        return None

    timeout = int(getattr(settings, 'AGENTE_IA_TIMEOUT', 20) or 20)
    url = (
        f'https://generativelanguage.googleapis.com/v1beta/models/{model}:'
        f'generateContent?key={api_key}'
    )
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': 0.4,
            'maxOutputTokens': 900,
        },
    }
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException:
        logger.exception('Error conexión Gemini resumen conversación')
        return None

    if resp.status_code != 200:
        logger.warning('Gemini resumen conversación HTTP %s', resp.status_code)
        return None

    try:
        body = resp.json()
        return (body['candidates'][0]['content']['parts'][0]['text'] or '').strip()
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _armar_transcript_conversacion(conversation, *, limite: int = _TRANSCRIPT_MAX_MENSAJES) -> str:
    from mecanimovilapp.apps.chat.models import Message

    mensajes = list(
        Message.objects.filter(conversation=conversation)
        .order_by('-timestamp')[:limite]
    )
    mensajes.reverse()
    lineas: list[str] = []
    for msg in mensajes:
        texto = (msg.content or '').strip()
        if not texto:
            meta = msg.channel_metadata or {}
            if isinstance(meta, dict):
                texto = (meta.get('transcripcion') or meta.get('caption') or '').strip()
        if not texto:
            continue
        rol = 'Cliente' if msg.direction == 'inbound' else 'Taller'
        lineas.append(f'{rol}: {texto[:800]}')
    transcript = '\n'.join(lineas)
    if len(transcript) > _TRANSCRIPT_MAX_CHARS:
        transcript = transcript[-_TRANSCRIPT_MAX_CHARS:]
    return transcript


def sincronizar_chunk_conversacion_exitosa(cotizacion_id: int) -> None:
    """Indexa un resumen de venta a partir de una cotización aceptada."""
    from mecanimovilapp.apps.ordenes.models import CotizacionCanal

    cotizacion = (
        CotizacionCanal.objects.select_related('conversation', 'taller')
        .filter(pk=cotizacion_id, estado='aceptada', taller_id__isnull=False)
        .first()
    )
    if not cotizacion or not cotizacion.taller_id:
        return

    conversation = cotizacion.conversation
    transcript = _armar_transcript_conversacion(conversation) if conversation else ''
    if not transcript:
        logger.info('Sin transcript para conversación exitosa cotización %s', cotizacion_id)
        return

    servicio = (cotizacion.servicio_nombre or '').strip()
    total = int(cotizacion.total_clp or 0)
    problema = (cotizacion.descripcion_problema or '').strip()[:400]

    prompt = f"""Eres un analista de ventas de talleres mecánicos en Chile.
Resume esta conversación que TERMINÓ EN VENTA (cotización aceptada) para que otros asesores aprendan el patrón.

TRANSCRIPT (puede contener datos personales — NO los copies al resumen):
---
{transcript}
---

Datos de la venta:
- Servicio cotizado: {servicio or 'no indicado'}
- Total aceptado: {total} CLP
- Problema/diagnóstico inicial: {problema or 'no indicado'}

Escribe un resumen en español (máx. 350 palabras) con estas secciones:
1) Problema/síntoma inicial del cliente
2) Objeciones o dudas del cliente y cómo se resolvieron
3) Argumentos o explicaciones técnicas que funcionaron para cerrar
4) Servicios/repuestos acordados y rango de precio final
5) Tono/estilo que ayudó (breve)

PROHIBIDO incluir: nombres, teléfonos, patentes, direcciones, RUT u otros datos personales.
Usa términos genéricos ("el cliente", "su vehículo")."""

    resumen = _llamar_gemini_texto(prompt)
    if not resumen:
        resumen = (
            f'Venta cerrada: {servicio or "servicio mecánico"}. '
            f'Total {total} CLP. Problema: {problema or "consulta general"}.'
        )

    contenido = (
        f'Conversación que resultó en venta (patrón reutilizable, sin datos personales):\n'
        f'{resumen}\n'
        f'Servicio: {servicio or "N/D"}\n'
        f'Total aceptado: {total} CLP'
    ).strip()

    _upsert_chunk(
        taller_id=cotizacion.taller_id,
        fuente=TallerConocimientoChunk.FUENTE_CONVERSACION_EXITOSA,
        contenido=contenido,
        referencia_externa=f'conversacion_exitosa:{cotizacion.id}',
        metadata={
            'cotizacion_id': cotizacion.id,
            'conversation_id': getattr(conversation, 'id', None),
            'servicio_nombre': servicio,
            'total_clp': total,
        },
    )


def reindexar_conocimiento_taller(taller_id: int) -> dict[str, int]:
    """
    Re-encola la indexación de TODO el conocimiento de un taller: catálogo de
    servicios disponibles, historial de servicios completados, instrucciones
    personalizadas y documentos ya cargados.

    Necesario para talleres cuyos datos existían antes de que el worker de
    Celery tuviera configurada `GEMINI_API_KEY` (los chunks quedaron sin
    `embedding` y por lo tanto invisibles para la búsqueda semántica).
    """
    from mecanimovilapp.apps.agente_ia.tasks import (
        backfill_embeddings_faltantes_task,
        procesar_documento_conocimiento_task,
        sincronizar_chunk_historico_task,
        sincronizar_chunk_servicio_task,
        sincronizar_instrucciones_task,
    )
    from mecanimovilapp.apps.ordenes.models import SolicitudServicio
    from mecanimovilapp.apps.servicios.models import OfertaServicio

    ofertas_ids = list(
        OfertaServicio.objects.filter(taller_id=taller_id, disponible=True).values_list('id', flat=True)
    )
    for oferta_id in ofertas_ids:
        sincronizar_chunk_servicio_task.delay(oferta_id)

    solicitudes_ids = list(
        SolicitudServicio.objects.filter(taller_id=taller_id, estado='completado').values_list('id', flat=True)
    )
    for solicitud_id in solicitudes_ids:
        sincronizar_chunk_historico_task.delay(solicitud_id)

    documentos_ids = list(
        TallerConocimientoDocumento.objects.filter(taller_id=taller_id).values_list('id', flat=True)
    )
    for documento_id in documentos_ids:
        procesar_documento_conocimiento_task.delay(documento_id)

    sincronizar_instrucciones_task.delay(taller_id)
    # Después del sync de fuentes, intenta recuperar chunks viejos sin vector.
    backfill_embeddings_faltantes_task.delay(taller_id)

    return {
        'ofertas': len(ofertas_ids),
        'solicitudes': len(solicitudes_ids),
        'documentos': len(documentos_ids),
        'backfill_embeddings': True,
    }


@transaction.atomic
def procesar_documento_conocimiento(documento_id: int) -> None:
    """Extrae, fragmenta e indexa un documento del taller."""
    documento = TallerConocimientoDocumento.objects.select_related('taller').get(pk=documento_id)
    documento.estado_procesamiento = TallerConocimientoDocumento.ESTADO_PROCESANDO
    documento.error_detalle = ''
    documento.save(update_fields=['estado_procesamiento', 'error_detalle', 'actualizado_en'])

    try:
        if documento.archivo:
            nombre = (documento.archivo.name or '').lower()
            if nombre.endswith('.pdf'):
                texto = extraer_texto_pdf(documento.archivo)
            else:
                documento.archivo.open('rb')
                try:
                    raw = documento.archivo.read()
                    texto = raw.decode('utf-8', errors='ignore')
                finally:
                    documento.archivo.close()
        else:
            texto = documento.texto_pegado or ''

        if not (texto or '').strip():
            raise ValueError('El documento no contiene texto procesable.')

        TallerConocimientoChunk.objects.filter(documento=documento).delete()
        fragmentos = fragmentar_texto(texto)
        con_embedding = 0
        for idx, frag in enumerate(fragmentos):
            embedding = generar_embedding(frag)
            if embedding is not None:
                con_embedding += 1
            else:
                logger.warning(
                    'Documento %s fragmento %s sin embedding',
                    documento_id,
                    idx,
                )
            TallerConocimientoChunk.objects.create(
                taller=documento.taller,
                documento=documento,
                fuente=TallerConocimientoChunk.FUENTE_DOCUMENTO,
                contenido=frag,
                embedding=embedding,
                referencia_externa=f'doc:{documento.id}:chunk:{idx}',
                metadata={'documento_id': documento.id, 'chunk_index': idx},
            )

        if con_embedding == 0 and fragmentos:
            raise ValueError(
                'No se pudieron generar embeddings (revisa GEMINI_API_KEY en el worker).'
            )

        documento.estado_procesamiento = TallerConocimientoDocumento.ESTADO_LISTO
        documento.save(update_fields=['estado_procesamiento', 'actualizado_en'])
    except Exception as exc:
        logger.exception('Error procesando documento %s', documento_id)
        documento.estado_procesamiento = TallerConocimientoDocumento.ESTADO_ERROR
        documento.error_detalle = str(exc)[:500]
        documento.save(update_fields=['estado_procesamiento', 'error_detalle', 'actualizado_en'])
