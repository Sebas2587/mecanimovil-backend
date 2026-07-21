"""Sincroniza cotización de canal cuando se cancela/elimina su cita personal."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def marcar_cotizacion_origen_cancelada(cita) -> None:
    """
    Si la cita nació de una cotización aceptada, al cancelar/eliminar la cita
    el lead comercial no puede seguir como «aceptada/agendada».
    Pasa a cancelada → Perdidos en bandeja.
    """
    cot = getattr(cita, 'cotizacion_canal_origen', None)
    if cot is None:
        return
    if cot.estado in ('cancelada', 'rechazada', 'expirada'):
        return
    cot.estado = 'cancelada'
    cot.save(update_fields=['estado', 'actualizado_en'])
    logger.info(
        'Cotización canal %s → cancelada (cita personal %s %s)',
        cot.id,
        cita.id,
        cita.estado,
    )


def cotizacion_aceptada_tiene_cita_activa(cotizacion) -> bool:
    from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal

    return CitaAgendaPersonal.objects.filter(
        cotizacion_canal_origen_id=cotizacion.id,
        estado='activa',
    ).exists()
