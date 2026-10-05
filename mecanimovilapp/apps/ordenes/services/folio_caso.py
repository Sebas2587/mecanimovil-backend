"""Folio por taller: sigla propia y serie que parte en 0.

Los MM- ya emitidos se conservan. Las cotizaciones nuevas usan {SIGLA}-000000.
"""
from __future__ import annotations

import re
import unicodedata

from django.db import transaction

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


def _sin_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize('NFKD', texto or '')
    return ''.join(c for c in normalizado if not unicodedata.combining(c))


def prefijo_desde_nombre(nombre: str) -> str:
    palabras = re.findall(r'[A-Za-z0-9]+', _sin_acentos(nombre))
    if not palabras:
        return 'TL'
    if len(palabras) == 1:
        base = palabras[0][:3]
    else:
        base = ''.join(palabra[0] for palabra in palabras[:4])
    base = re.sub(r'[^A-Za-z0-9]', '', base).upper()
    return (base or 'TL')[:4]


def asegurar_prefijo_taller(taller) -> str:
    """Sigla estable del taller. Se guarda la primera vez y no cambia si renombran."""
    guardado = (getattr(taller, 'prefijo_folio', None) or '').strip().upper()
    if guardado:
        return guardado
    from mecanimovilapp.apps.usuarios.models import Taller

    base = prefijo_desde_nombre(getattr(taller, 'nombre', '') or '')
    prefijo = base
    n = 2
    while Taller.objects.exclude(pk=taller.pk).filter(prefijo_folio=prefijo).exists():
        prefijo = f'{base[:3]}{n}'[:6]
        n += 1
    taller.prefijo_folio = prefijo
    taller.save(update_fields=['prefijo_folio'])
    return prefijo


def asignar_folio_taller(taller) -> str:
    """Siguiente folio del taller. El primero es {SIGLA}-000000."""
    from mecanimovilapp.apps.ordenes.models import CotizacionCanal
    from mecanimovilapp.apps.usuarios.models import Taller

    with transaction.atomic():
        bloqueado = Taller.objects.select_for_update().get(pk=taller.pk)
        prefijo = asegurar_prefijo_taller(bloqueado)
        patron = re.compile(rf'^{re.escape(prefijo)}-(\d+)$', re.IGNORECASE)
        maximo = -1
        folios = (
            CotizacionCanal.objects.filter(taller_id=bloqueado.pk)
            .exclude(numero_publico__isnull=True)
            .exclude(numero_publico='')
            .values_list('numero_publico', flat=True)
        )
        for folio in folios:
            coincide = patron.match(str(folio).strip())
            if coincide:
                maximo = max(maximo, int(coincide.group(1)))
        return f'{prefijo}-{maximo + 1:06d}'


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

    taller = getattr(cita, 'taller', None)
    cita.numero_publico = (
        asignar_folio_taller(taller) if taller is not None else asignar_folio_unico(preferido_pk=cita.pk)
    )
    cita.save(update_fields=['numero_publico'])
    return cita


def asegurar_numero_publico_orden(orden):
    """MM propio para reservas de la app usuarios / catálogo."""
    stored = (getattr(orden, 'numero_publico', None) or '').strip()
    if stored:
        return orden
    if orden.pk is None:
        orden.save()
    taller = getattr(orden, 'taller', None)
    orden.numero_publico = (
        asignar_folio_taller(taller) if taller is not None else asignar_folio_unico(preferido_pk=orden.pk)
    )
    orden.save(update_fields=['numero_publico'])
    return orden
