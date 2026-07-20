"""
Resolución unificada de ChecklistTemplate: existente o generado por IA.
"""
from __future__ import annotations

import logging

from mecanimovilapp.apps.checklists.models import ChecklistTemplate
from mecanimovilapp.apps.servicios.models import Servicio

from .ai_template_generator import generar_template_checklist_ia

logger = logging.getLogger(__name__)


def resolver_o_generar_template(
    servicio: Servicio | None,
    *,
    generar_si_ausente: bool = True,
    descripcion_extra: str = '',
    vehiculo_contexto: str = '',
) -> ChecklistTemplate | None:
    """
    Devuelve el template activo para el servicio. Si no existe y generar_si_ausente
    es True, genera uno vía IA (o fallback mínimo).
    """
    if servicio is None:
        return None

    template = (
        ChecklistTemplate.objects
        .filter(servicio=servicio, activo=True)
        .prefetch_related('items__catalog_item')
        .order_by('-fecha_creacion')
        .first()
    )
    if template:
        return template

    if not generar_si_ausente:
        logger.info('Sin template para servicio %s y generación IA deshabilitada', servicio.id)
        return None

    logger.info('Generando template IA para servicio %s (%s)', servicio.id, servicio.nombre)
    return generar_template_checklist_ia(
        servicio,
        descripcion_extra=descripcion_extra,
        vehiculo_contexto=vehiculo_contexto,
    )
