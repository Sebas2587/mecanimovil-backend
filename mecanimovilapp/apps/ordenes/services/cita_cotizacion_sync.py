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


def preparar_cierre_caso_aceptado(cotizacion) -> str:
    """
    Cierra un caso aceptado según lo que todavía está vivo.

    - Visita ya realizada (checklist completo o cita cerrada) → no pasa a Perdidos.
    - Solo queda el placeholder sin día/hora → se cancela y el lead puede ir a Perdidos.
    - Visita confirmada todavía activa → no se cierra desde aquí.
    - Trabajos adicionales ya rechazados o cancelados no bloquean.
    - Trabajos adicionales todavía enviados sí bloquean.

    Returns 'terminada' si el servicio principal ya se hizo, 'perdida' si el
    lead comercial puede marcarse cancelado.
    """
    from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, CotizacionCanal
    from mecanimovilapp.apps.ordenes.services.cita_cierre_sync import (
        asegurar_cierre_cita_si_checklist_completo,
    )

    if getattr(cotizacion, 'es_cotizacion_adicional', False):
        return 'perdida'

    citas = list(
        CitaAgendaPersonal.objects.filter(cotizacion_canal_origen_id=cotizacion.id)
    )
    for cita in citas:
        if cita.estado == 'activa':
            asegurar_cierre_cita_si_checklist_completo(cita)
            cita.refresh_from_db()

    activas = [c for c in citas if c.estado == 'activa']
    confirmadas = [c for c in activas if not c.horario_por_confirmar]
    if confirmadas:
        raise ValueError(
            'Hay una visita agendada en curso. Complétala o cancélala antes de cerrar el caso.'
        )
    for placeholder in activas:
        placeholder.cancelar()
        placeholder.save(update_fields=['estado', 'cancelada_en', 'fecha_actualizacion'])

    abiertos = CotizacionCanal.objects.filter(
        cotizacion_original_id=cotizacion.id,
        estado__in=('borrador', 'enviada', 'aceptada'),
    ).exists()
    if abiertos:
        raise ValueError(
            'Cierra primero los trabajos adicionales que el cliente todavía no rechazó.'
        )
    if any(c.estado == 'cerrada' for c in citas):
        return 'terminada'
    return 'perdida'


def cotizacion_aceptada_tiene_cita_activa(cotizacion) -> bool:
    from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal

    if cotizacion.es_cotizacion_adicional:
        return False
    return CitaAgendaPersonal.objects.filter(
        cotizacion_canal_origen_id=cotizacion.id,
        estado='activa',
    ).exists()
