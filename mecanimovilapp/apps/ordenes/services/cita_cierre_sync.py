"""Alinea estado de CitaAgendaPersonal cuando el checklist ya cerró el servicio."""
from __future__ import annotations

import logging

from django.db import transaction

logger = logging.getLogger(__name__)


def asegurar_cierre_cita_si_checklist_completo(cita) -> bool:
    """
    Si el checklist de la cita ya está COMPLETADO (con firmas mínimas) pero la
    cita sigue activa, cierra la cita.

    Esto repara desfases donde `finalize` / firma pública guardó el checklist
    y falló el cierre de la cita (p. ej. fuera de una transacción atómica).

    Returns True si cerró la cita en esta llamada.
    """
    if cita is None or getattr(cita, 'estado', None) != 'activa':
        return False

    from mecanimovilapp.apps.checklists.models import ChecklistInstance

    inst = (
        ChecklistInstance.objects
        .filter(cita_personal_id=cita.id)
        .only(
            'id',
            'estado',
            'firma_tecnico',
            'firma_cliente',
            'firma_supervisor',
            'cita_personal_id',
        )
        .first()
    )
    if inst is None or inst.estado != 'COMPLETADO':
        return False
    if not inst.firma_tecnico:
        return False
    # Taller: exige firma de cliente (flujo informe). Sin taller (domicilio puro):
    # basta con firma del técnico.
    if cita.taller_id and not inst.firma_cliente:
        return False

    update_fields = ['estado', 'cerrada_en', 'fecha_actualizacion']
    with transaction.atomic():
        locked = type(cita).objects.select_for_update().filter(pk=cita.pk, estado='activa').first()
        if locked is None:
            return False
        # El servicio ya terminó: no bloquear cierre por flag de cotización.
        if locked.horario_por_confirmar:
            locked.horario_por_confirmar = False
            update_fields.append('horario_por_confirmar')
        locked.cerrar()
        locked.save(update_fields=update_fields)
        cita.estado = locked.estado
        cita.cerrada_en = locked.cerrada_en
        cita.horario_por_confirmar = locked.horario_por_confirmar

    logger.info(
        'Cita personal %s cerrada por sync (checklist COMPLETADO id=%s)',
        cita.id,
        inst.id,
    )
    return True


def reparar_citas_activas_con_checklist_completo(queryset) -> int:
    """Cierra en lote citas activas del queryset cuyo checklist ya está completo."""
    cerradas = 0
    for cita in queryset.filter(estado='activa').iterator(chunk_size=50):
        if asegurar_cierre_cita_si_checklist_completo(cita):
            cerradas += 1
    return cerradas
