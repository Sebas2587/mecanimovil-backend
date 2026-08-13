"""Sincroniza cotización de canal cuando se cancela/elimina su cita personal."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def marcar_cotizacion_origen_cancelada(cita) -> None:
    """
    Si la cita nació de una cotización aceptada, al cancelar/eliminar la cita
    el lead comercial no puede seguir como «aceptada/agendada».
    Pasa a cancelada → Perdidos en bandeja.
    También cierra cotizaciones adicionales pendientes de esa visita.
    """
    cot = getattr(cita, 'cotizacion_canal_origen', None)
    if cot is not None and cot.estado not in ('cancelada', 'rechazada', 'expirada'):
        cot.estado = 'cancelada'
        cot.save(update_fields=['estado', 'actualizado_en'])
        logger.info(
            'Cotización canal %s → cancelada (cita personal %s %s)',
            cot.id,
            cita.id,
            cita.estado,
        )

    adicionales = getattr(cita, 'cotizaciones_adicionales', None)
    if adicionales is None:
        return
    pendientes = adicionales.filter(estado__in=('borrador', 'enviada'))
    updated = pendientes.update(estado='cancelada')
    if updated:
        logger.info(
            '%s cotización(es) adicional(es) canceladas con cita personal %s',
            updated,
            cita.id,
        )


def cotizacion_aceptada_tiene_cita_activa(cotizacion) -> bool:
    from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal

    if cotizacion.es_cotizacion_adicional:
        return False
    return CitaAgendaPersonal.objects.filter(
        cotizacion_canal_origen_id=cotizacion.id,
        estado='activa',
    ).exists()
