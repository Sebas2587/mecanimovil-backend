"""Folio MM compartido entre cotización, cita y orden de la app usuarios."""
from __future__ import annotations

import re

from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
    asegurar_numero_publico,
    formatear_numero_publico,
)

_FOLIO_N_RE = re.compile(r'^MM-(\d+)$', re.IGNORECASE)


def folio_publico_cita(cita) -> str:
    """Folio visible: el persistido, o el de la cotización origen."""
    stored = (getattr(cita, 'numero_publico', None) or '').strip()
    if stored:
        return stored
    cot = getattr(cita, 'cotizacion_canal_origen', None)
    if cot is not None:
        return (getattr(cot, 'numero_publico', None) or '').strip()
    return ''


def _folios_ocupados() -> set[str]:
    from mecanimovilapp.apps.ordenes.models import (
        CitaAgendaPersonal,
        CotizacionCanal,
        SolicitudServicio,
    )

    ocupados: set[str] = set()
    ocupados.update(
        CotizacionCanal.objects.exclude(numero_publico__isnull=True)
        .exclude(numero_publico='')
        .values_list('numero_publico', flat=True)
    )
    ocupados.update(
        CitaAgendaPersonal.objects.exclude(numero_publico='')
        .values_list('numero_publico', flat=True)
    )
    ocupados.update(
        SolicitudServicio.objects.exclude(numero_publico='')
        .values_list('numero_publico', flat=True)
    )
    return {str(f).strip() for f in ocupados if f}


def _siguiente_folio_libre(ocupados: set[str]) -> str:
    max_n = 0
    for folio in ocupados:
        m = _FOLIO_N_RE.match(folio)
        if m:
            max_n = max(max_n, int(m.group(1)))
    n = max_n + 1
    while True:
        folio = formatear_numero_publico(n)
        if folio not in ocupados:
            return folio
        n += 1


def asignar_folio_unico(*, preferido_pk: int | None = None) -> str:
    """Siguiente MM libre en el pool cotización + cita + orden app."""
    ocupados = _folios_ocupados()
    if preferido_pk is not None:
        preferred = formatear_numero_publico(preferido_pk)
        if preferred not in ocupados:
            return preferred
    return _siguiente_folio_libre(ocupados)


def asegurar_numero_publico_cita(cita):
    """Mismo MM que la cotización del caso; si no hay coti, emite un MM nuevo."""
    stored = (getattr(cita, 'numero_publico', None) or '').strip()
    cot = getattr(cita, 'cotizacion_canal_origen', None)
    if cot is not None:
        asegurar_numero_publico(cot)
        folio = (cot.numero_publico or '').strip()
        if folio and stored != folio:
            cita.numero_publico = folio
            cita.save(update_fields=['numero_publico'])
        return cita

    if stored:
        return cita

    cita.numero_publico = asignar_folio_unico(preferido_pk=cita.pk)
    cita.save(update_fields=['numero_publico'])
    return cita


def asegurar_numero_publico_orden(orden):
    """MM propio para reservas de la app usuarios / catálogo."""
    stored = (getattr(orden, 'numero_publico', None) or '').strip()
    if stored:
        return orden
    if orden.pk is None:
        orden.save()
    orden.numero_publico = asignar_folio_unico(preferido_pk=orden.pk)
    orden.save(update_fields=['numero_publico'])
    return orden
