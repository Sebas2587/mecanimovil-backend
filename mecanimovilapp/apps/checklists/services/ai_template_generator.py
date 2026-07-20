"""
Genera ChecklistTemplate estructurados vía Gemini cuando no existe uno para el servicio.
"""
from __future__ import annotations

import logging
from typing import Any

from django.db import transaction

from mecanimovilapp.apps.checklists.models import (
    ChecklistItemCatalog,
    ChecklistItemTemplate,
    ChecklistTemplate,
)
from mecanimovilapp.apps.ordenes.services.asistente_diagnostico.generador import (
    _llamar_gemini,
    asistente_habilitado,
)
from mecanimovilapp.apps.servicios.models import Servicio

logger = logging.getLogger(__name__)

_TIPOS_PERMITIDOS = {
    t[0] for t in ChecklistItemCatalog.TIPO_PREGUNTA_CHOICES
}
_CATEGORIAS_PERMITIDAS = {
    c[0] for c in ChecklistItemCatalog.CATEGORIA_CHOICES
}

_PROMPT_TEMPLATE = """Eres un experto en procesos de taller mecánico automotriz en Chile.
Genera un checklist operativo estructurado para el siguiente servicio de catálogo.

Servicio: {nombre_servicio}
Descripción: {descripcion_servicio}

Devuelve SOLO un JSON con esta estructura exacta:
{{
  "nombre_template": "Checklist ...",
  "descripcion": "...",
  "tipo_intencion_default": "REPARACION|INSPECCION|PRECOMPRA|MIXTO",
  "items": [
    {{
      "nombre": "Identificador corto del ítem",
      "categoria": "Una de las categorías del sistema",
      "tipo_pregunta": "Uno de los tipos permitidos",
      "pregunta_texto": "Pregunta clara para el técnico",
      "descripcion_ayuda": "Opcional",
      "es_obligatorio": true,
      "min_fotos": null,
      "max_fotos": null,
      "opciones_seleccion": null
    }}
  ]
}}

REGLAS:
1. Entre 6 y 14 ítems, orden lógico de ejecución (km → inspección → trabajo → fotos → firma).
2. Incluye al menos: KILOMETER_INPUT, una inspección (BOOLEAN o SELECT), al menos un PHOTO, WORK_SUMMARY o FINAL_NOTES, y SIGNATURE o CLIENT_CONFIRMATION.
3. tipo_pregunta válidos: {tipos}
4. categoria válidas: {categorias}
5. Para PHOTO usa min_fotos entre 1 y 3.
6. El checklist es genérico por tipo de servicio, NO por marca de vehículo.
7. Responde en español chileno, técnico pero claro.
"""


def _construir_prompt(servicio: Servicio) -> str:
    return _PROMPT_TEMPLATE.format(
        nombre_servicio=servicio.nombre,
        descripcion_servicio=(servicio.descripcion or servicio.nombre).strip()[:1200],
        tipos=', '.join(sorted(_TIPOS_PERMITIDOS)),
        categorias=', '.join(sorted(_CATEGORIAS_PERMITIDAS)),
    )


def _get_or_create_catalog_item(item_data: dict[str, Any]) -> ChecklistItemCatalog:
    tipo = str(item_data.get('tipo_pregunta') or 'TEXT').upper()
    if tipo not in _TIPOS_PERMITIDOS:
        tipo = 'TEXT'

    categoria = str(item_data.get('categoria') or 'INFORMACION_GENERAL').upper()
    if categoria not in _CATEGORIAS_PERMITIDAS:
        categoria = 'INFORMACION_GENERAL'

    nombre = str(item_data.get('nombre') or item_data.get('pregunta_texto') or 'Ítem')[:255]
    pregunta = str(item_data.get('pregunta_texto') or nombre)[:2000]

    existing = (
        ChecklistItemCatalog.objects
        .filter(nombre=nombre, tipo_pregunta=tipo, categoria=categoria, activo=True)
        .first()
    )
    if existing:
        return existing

    min_fotos = item_data.get('min_fotos')
    max_fotos = item_data.get('max_fotos')
    if tipo == 'PHOTO' and not min_fotos:
        min_fotos = 1
        max_fotos = max_fotos or 3

    return ChecklistItemCatalog.objects.create(
        nombre=nombre,
        categoria=categoria,
        tipo_pregunta=tipo,
        pregunta_texto=pregunta,
        descripcion_ayuda=(item_data.get('descripcion_ayuda') or '')[:2000] or None,
        es_obligatorio_por_defecto=bool(item_data.get('es_obligatorio', True)),
        opciones_seleccion=item_data.get('opciones_seleccion'),
        min_fotos=min_fotos,
        max_fotos=max_fotos,
        activo=True,
    )


def _persistir_template_desde_ia(servicio: Servicio, data: dict[str, Any]) -> ChecklistTemplate:
    intencion = str(data.get('tipo_intencion_default') or 'MIXTO').upper()
    if intencion not in dict(ChecklistTemplate.TIPO_INTENCION_CHOICES):
        intencion = 'MIXTO'

    nombre_template = str(data.get('nombre_template') or f'Checklist {servicio.nombre}')[:255]
    descripcion = str(data.get('descripcion') or '')[:2000] or None
    items_raw = data.get('items') or []
    if not isinstance(items_raw, list):
        items_raw = []

    with transaction.atomic():
        template = ChecklistTemplate.objects.create(
            nombre=nombre_template,
            descripcion=descripcion,
            servicio=servicio,
            tipo_intencion_default=intencion,
            activo=True,
            generado_por_ia=True,
            version='1.0-ia',
        )

        orden = 1
        for raw in items_raw[:20]:
            if not isinstance(raw, dict):
                continue
            catalog_item = _get_or_create_catalog_item(raw)
            ChecklistItemTemplate.objects.create(
                checklist_template=template,
                catalog_item=catalog_item,
                orden_visual=orden,
                es_obligatorio=bool(raw.get('es_obligatorio', True)),
            )
            orden += 1

        if orden == 1:
            # Fallback mínimo si la IA no devolvió ítems válidos
            fallback_items = [
                ('Kilometraje actual', 'KILOMETER_INPUT', 'DATOS_VEHICULO'),
                ('Estado general del vehículo', 'BOOLEAN', 'INFORMACION_GENERAL'),
                ('Fotos del trabajo realizado', 'PHOTO', 'FOTOS_FINALES'),
                ('Resumen del trabajo', 'WORK_SUMMARY', 'OBSERVACIONES_TECNICO'),
                ('Firma del técnico', 'SIGNATURE', 'FIRMAS_CONFORMIDAD'),
            ]
            for fb_nombre, fb_tipo, fb_cat in fallback_items:
                catalog_item = _get_or_create_catalog_item({
                    'nombre': fb_nombre,
                    'tipo_pregunta': fb_tipo,
                    'categoria': fb_cat,
                    'pregunta_texto': fb_nombre,
                    'es_obligatorio': True,
                    'min_fotos': 1 if fb_tipo == 'PHOTO' else None,
                    'max_fotos': 3 if fb_tipo == 'PHOTO' else None,
                })
                ChecklistItemTemplate.objects.create(
                    checklist_template=template,
                    catalog_item=catalog_item,
                    orden_visual=orden,
                    es_obligatorio=True,
                )
                orden += 1

        return template


def generar_template_checklist_ia(servicio: Servicio) -> ChecklistTemplate | None:
    """
    Llama a Gemini y persiste un ChecklistTemplate reutilizable para el servicio.
    Retorna None si la IA no está habilitada o falla.
    """
    if not asistente_habilitado():
        logger.info('Generador IA checklist: asistente deshabilitado para servicio %s', servicio.id)
        return None

    prompt = _construir_prompt(servicio)
    data, _uso, error = _llamar_gemini(prompt)
    if error or not data:
        logger.warning(
            'Generador IA checklist falló para servicio %s: %s',
            servicio.id,
            error or 'sin datos',
        )
        return None

    try:
        template = _persistir_template_desde_ia(servicio, data)
        logger.info(
            'ChecklistTemplate IA creado id=%s servicio=%s items=%s',
            template.id,
            servicio.id,
            template.items.count(),
        )
        return template
    except Exception as exc:
        logger.exception('Error persistiendo template IA para servicio %s: %s', servicio.id, exc)
        return None
