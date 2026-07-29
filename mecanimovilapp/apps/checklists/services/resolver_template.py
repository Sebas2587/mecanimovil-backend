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

    # Si el servicio es libre (p.ej. "cambio de aceite y filtros") pero existe
    # un template sembrado de un alias canónico, reutilizarlo en vez de IA.
    from mecanimovilapp.apps.checklists.services.resolver_servicio import (
        _buscar_alias_canonico,
        _normalizar_nombre_servicio,
    )

    alias = _buscar_alias_canonico(_normalizar_nombre_servicio(servicio.nombre or ''))
    if alias is not None and alias.id != servicio.id:
        template_alias = (
            ChecklistTemplate.objects
            .filter(servicio=alias, activo=True)
            .prefetch_related('items__catalog_item')
            .order_by('generado_por_ia', '-fecha_creacion')  # preferir no-IA
            .first()
        )
        if template_alias is not None:
            logger.info(
                'Reutilizando template %s del servicio canónico %s para %s',
                template_alias.id,
                alias.id,
                servicio.id,
            )
            return template_alias

    if not generar_si_ausente:
        logger.info('Sin template para servicio %s y generación IA deshabilitada', servicio.id)
        return None

    logger.info('Generando template IA para servicio %s (%s)', servicio.id, servicio.nombre)
    return generar_template_checklist_ia(
        servicio,
        descripcion_extra=descripcion_extra,
        vehiculo_contexto=vehiculo_contexto,
    )
