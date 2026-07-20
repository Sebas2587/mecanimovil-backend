"""
Genera ChecklistTemplate estructurados vía Gemini cuando no existe uno para el servicio.
Si la IA no está disponible o falla, persiste un template mínimo de fallback.
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

_FALLBACK_ITEMS = [
    ('Kilometraje actual', 'KILOMETER_INPUT', 'DATOS_VEHICULO', 'Registra el kilometraje actual del vehículo'),
    ('Estado general del vehículo', 'BOOLEAN', 'INFORMACION_GENERAL', '¿El vehículo llega en condiciones aptas para el servicio?'),
    ('Inspección visual inicial', 'PHOTO', 'FOTOS_INICIALES', 'Toma fotos del estado inicial del vehículo'),
    ('Trabajo realizado', 'WORK_SUMMARY', 'OBSERVACIONES_TECNICO', 'Describe el trabajo realizado'),
    ('Fotos del trabajo final', 'PHOTO', 'FOTOS_FINALES', 'Toma fotos del resultado del servicio'),
    ('Firma del técnico', 'SIGNATURE', 'FIRMAS_CONFORMIDAD', 'Firma para confirmar el servicio'),
]

_PROMPT_TEMPLATE = """Eres un experto en procesos de taller mecánico automotriz en Chile.
Genera un checklist operativo estructurado para el siguiente servicio.

Servicio: {nombre_servicio}
Descripción / requerimiento: {descripcion_servicio}
Vehículo (contexto opcional): {vehiculo_contexto}

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
6. El checklist es reutilizable por tipo de servicio. Usa el vehículo solo para adaptar ítems relevantes (p.ej. diésel vs gasolina), no crees un template exclusivo de esa marca.
7. Responde en español chileno, técnico pero claro.
"""


def _construir_prompt(
    servicio: Servicio,
    *,
    descripcion_extra: str = '',
    vehiculo_contexto: str = '',
) -> str:
    descripcion = (descripcion_extra or servicio.descripcion or servicio.nombre or '').strip()
    return _PROMPT_TEMPLATE.format(
        nombre_servicio=servicio.nombre,
        descripcion_servicio=descripcion[:1200],
        vehiculo_contexto=(vehiculo_contexto or 'No especificado').strip()[:400],
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


def _agregar_items_fallback(template: ChecklistTemplate, orden_inicio: int = 1) -> int:
    orden = orden_inicio
    for fb_nombre, fb_tipo, fb_cat, fb_pregunta in _FALLBACK_ITEMS:
        catalog_item = _get_or_create_catalog_item({
            'nombre': fb_nombre,
            'tipo_pregunta': fb_tipo,
            'categoria': fb_cat,
            'pregunta_texto': fb_pregunta,
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
    return orden


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
            _agregar_items_fallback(template, orden_inicio=1)

        return template


def _persistir_template_fallback(servicio: Servicio) -> ChecklistTemplate:
    """Template mínimo operativo cuando Gemini no está disponible o falla."""
    with transaction.atomic():
        template = ChecklistTemplate.objects.create(
            nombre=f'Checklist {servicio.nombre}'[:255],
            descripcion=f'Checklist base generado automáticamente para {servicio.nombre}'[:2000],
            servicio=servicio,
            tipo_intencion_default='MIXTO',
            activo=True,
            generado_por_ia=True,
            version='1.0-fallback',
        )
        _agregar_items_fallback(template, orden_inicio=1)
        return template


def generar_template_checklist_ia(
    servicio: Servicio,
    *,
    descripcion_extra: str = '',
    vehiculo_contexto: str = '',
) -> ChecklistTemplate | None:
    """
    Intenta generar con Gemini un ChecklistTemplate reutilizable.
    Si la IA falla o está deshabilitada, crea un fallback mínimo (nunca deja sin checklist).
    """
    # Doble-check: otro proceso pudo crear el template mientras tanto.
    existing = (
        ChecklistTemplate.objects
        .filter(servicio=servicio, activo=True)
        .order_by('-fecha_creacion')
        .first()
    )
    if existing:
        return existing

    if asistente_habilitado():
        prompt = _construir_prompt(
            servicio,
            descripcion_extra=descripcion_extra,
            vehiculo_contexto=vehiculo_contexto,
        )
        data, _uso, error = _llamar_gemini(prompt)
        if not error and data:
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
                logger.exception(
                    'Error persistiendo template IA para servicio %s: %s',
                    servicio.id,
                    exc,
                )
        else:
            logger.warning(
                'Generador IA checklist falló para servicio %s: %s — usando fallback',
                servicio.id,
                error or 'sin datos',
            )
    else:
        logger.info(
            'Generador IA checklist deshabilitado para servicio %s — usando fallback',
            servicio.id,
        )

    try:
        template = _persistir_template_fallback(servicio)
        logger.info(
            'ChecklistTemplate fallback creado id=%s servicio=%s',
            template.id,
            servicio.id,
        )
        return template
    except Exception as exc:
        logger.exception('Error creando template fallback para servicio %s: %s', servicio.id, exc)
        return None
