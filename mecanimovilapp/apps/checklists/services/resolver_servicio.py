"""
Resuelve o crea un Servicio de catálogo a partir de texto libre (citas personales).
"""
from __future__ import annotations

import re
import unicodedata

from django.db import transaction

from mecanimovilapp.apps.servicios.models import Servicio

# Alias → nombres sembrados en populate_checklists_por_servicio (evita templates IA vacíos).
_ALIAS_SERVICIO_CANONICO: list[tuple[re.Pattern[str], tuple[str, ...]]] = [
    (
        re.compile(r'aceite.*(filtro|filtros)|(filtro|filtros).*aceite|aceite y filtro'),
        (
            'Cambio aceite motor y filtro',
            'Cambio de aceite motor y filtro',
            'Cambio de aceite y filtro',
        ),
    ),
    (
        re.compile(r'cambio\s+de\s+aceite|cambio\s+aceite|aceite\s+motor'),
        (
            'Cambio de aceite motor',
            'Cambio aceite motor',
        ),
    ),
]


def _normalizar_nombre_servicio(nombre: str) -> str:
    raw = (nombre or '').strip()
    if not raw:
        return ''
    nfkd = unicodedata.normalize('NFKD', raw)
    sin_tildes = ''.join(c for c in nfkd if not unicodedata.combining(c))
    colapsado = re.sub(r'\s+', ' ', sin_tildes).strip().lower()
    return colapsado


def _buscar_por_clave(clave: str) -> Servicio | None:
    for servicio in Servicio.objects.all().only('id', 'nombre', 'descripcion'):
        if _normalizar_nombre_servicio(servicio.nombre) == clave:
            return servicio
    return None


def _buscar_alias_canonico(clave: str) -> Servicio | None:
    for patron, candidatos in _ALIAS_SERVICIO_CANONICO:
        if not patron.search(clave):
            continue
        for nombre_canonico in candidatos:
            encontrado = _buscar_por_clave(_normalizar_nombre_servicio(nombre_canonico))
            if encontrado is not None:
                return encontrado
    return None


def resolver_servicio_desde_texto(nombre: str, *, descripcion: str = '') -> Servicio | None:
    """
    Busca un Servicio existente por nombre normalizado o crea uno nuevo marcado
    para curaduría posterior. Retorna None si el nombre está vacío.
    """
    nombre_limpio = (nombre or '').strip()
    if not nombre_limpio:
        return None

    clave = _normalizar_nombre_servicio(nombre_limpio)
    if not clave:
        return None

    exacto = _buscar_por_clave(clave)
    if exacto is not None:
        return exacto

    # Preferir servicios con checklist sembrado (aceite/filtros) antes de crear otro.
    alias = _buscar_alias_canonico(clave)
    if alias is not None:
        return alias

    with transaction.atomic():
        # Re-check dentro de la transacción por condiciones de carrera
        for servicio in Servicio.objects.select_for_update().only('id', 'nombre'):
            if _normalizar_nombre_servicio(servicio.nombre) == clave:
                return servicio

        alias_locked = _buscar_alias_canonico(clave)
        if alias_locked is not None:
            return alias_locked

        desc = (descripcion or '').strip() or f'Servicio registrado automáticamente: {nombre_limpio}'
        return Servicio.objects.create(
            nombre=nombre_limpio[:255],
            descripcion=desc[:2000],
        )
