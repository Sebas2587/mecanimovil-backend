"""
Creación de instancias de checklist para órdenes marketplace y citas personales.
"""
from __future__ import annotations

import logging

from mecanimovilapp.apps.checklists.models import ChecklistInstance
from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, SolicitudServicio
from mecanimovilapp.apps.servicios.models import Servicio

from .resolver_servicio import resolver_servicio_desde_texto
from .resolver_template import resolver_o_generar_template

logger = logging.getLogger(__name__)


def resolver_servicio_desde_cita_personal(cita: CitaAgendaPersonal) -> Servicio | None:
    det = getattr(cita, 'detalle', None)
    if det is None:
        return None

    if det.oferta_servicio_id and det.oferta_servicio:
        servicio = getattr(det.oferta_servicio, 'servicio', None)
        if servicio is not None:
            return servicio

    nombre = (det.servicio_nombre or '').strip()
    if not nombre:
        return None

    return resolver_servicio_desde_texto(nombre, descripcion=(det.descripcion or ''))


def _crear_instancia(
    *,
    template,
    orden: SolicitudServicio | None = None,
    cita_personal: CitaAgendaPersonal | None = None,
) -> ChecklistInstance | None:
    if template is None:
        return None

    if orden is not None:
        existing = ChecklistInstance.objects.filter(orden=orden).first()
        if existing:
            return existing
        return ChecklistInstance.objects.create(
            orden=orden,
            checklist_template=template,
            estado='PENDIENTE',
        )

    if cita_personal is not None:
        existing = ChecklistInstance.objects.filter(cita_personal=cita_personal).first()
        if existing:
            return existing
        return ChecklistInstance.objects.create(
            cita_personal=cita_personal,
            checklist_template=template,
            estado='PENDIENTE',
        )

    return None


def crear_checklist_para_orden(
    orden: SolicitudServicio,
    *,
    generar_template_si_ausente: bool = True,
) -> ChecklistInstance | None:
    primera_linea = orden.lineas.select_related('oferta_servicio__servicio').first()
    if not primera_linea or not primera_linea.oferta_servicio:
        logger.warning('No se pudo obtener servicio de la orden %s', orden.id)
        return None

    servicio = primera_linea.oferta_servicio.servicio
    template = resolver_o_generar_template(
        servicio,
        generar_si_ausente=generar_template_si_ausente,
    )
    if template is None:
        logger.info(
            'Orden %s continuará sin checklist (servicio: %s)',
            orden.id,
            servicio.nombre,
        )
        return None

    instance = _crear_instancia(template=template, orden=orden)
    if instance:
        logger.info(
            'Checklist %s creado para orden %s (template %s, ia=%s)',
            instance.id,
            orden.id,
            template.id,
            template.generado_por_ia,
        )
    return instance


def crear_checklist_para_cita_personal(
    cita: CitaAgendaPersonal,
    *,
    generar_template_si_ausente: bool = True,
) -> ChecklistInstance | None:
    servicio = resolver_servicio_desde_cita_personal(cita)
    if servicio is None:
        logger.warning('No se pudo resolver servicio para cita personal %s', cita.id)
        return None

    template = resolver_o_generar_template(
        servicio,
        generar_si_ausente=generar_template_si_ausente,
    )
    if template is None:
        logger.info(
            'Cita personal %s continuará sin checklist (servicio: %s)',
            cita.id,
            servicio.nombre,
        )
        return None

    instance = _crear_instancia(template=template, cita_personal=cita)
    if instance:
        logger.info(
            'Checklist %s creado para cita %s (template %s, ia=%s)',
            instance.id,
            cita.id,
            template.id,
            template.generado_por_ia,
        )
    return instance
