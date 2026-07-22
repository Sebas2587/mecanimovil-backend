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
    defaults = {
        'fuente': fuente,
        'contenido': contenido,
        'embedding': embedding,
        'metadata': metadata or {},
        'documento_id': documento_id,
    }

    if referencia_externa:
        chunk, _ = TallerConocimientoChunk.objects.update_or_create(
            taller_id=taller_id,
            referencia_externa=referencia_externa,
            defaults=defaults,
        )
        return chunk

    return TallerConocimientoChunk.objects.create(
        taller_id=taller_id,
        referencia_externa='',
        **defaults,
    )


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

    servicio = oferta.servicio
    marca = getattr(oferta.marca_vehiculo_seleccionada, 'nombre', '') or ''
    modelo = getattr(oferta.modelo_vehiculo_seleccionado, 'nombre', '') or ''
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

    return {
        'ofertas': len(ofertas_ids),
        'solicitudes': len(solicitudes_ids),
        'documentos': len(documentos_ids),
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
        for idx, frag in enumerate(fragmentos):
            embedding = generar_embedding(frag)
            TallerConocimientoChunk.objects.create(
                taller=documento.taller,
                documento=documento,
                fuente=TallerConocimientoChunk.FUENTE_DOCUMENTO,
                contenido=frag,
                embedding=embedding,
                referencia_externa=f'doc:{documento.id}:chunk:{idx}',
                metadata={'documento_id': documento.id, 'chunk_index': idx},
            )

        documento.estado_procesamiento = TallerConocimientoDocumento.ESTADO_LISTO
        documento.save(update_fields=['estado_procesamiento', 'actualizado_en'])
    except Exception as exc:
        logger.exception('Error procesando documento %s', documento_id)
        documento.estado_procesamiento = TallerConocimientoDocumento.ESTADO_ERROR
        documento.error_detalle = str(exc)[:500]
        documento.save(update_fields=['estado_procesamiento', 'error_detalle', 'actualizado_en'])
