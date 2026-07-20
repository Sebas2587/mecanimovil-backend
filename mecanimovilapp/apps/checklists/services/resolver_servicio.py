"""
Resuelve o crea un Servicio de catálogo a partir de texto libre (citas personales).
"""
from __future__ import annotations

import re
import unicodedata

from django.db import transaction

from mecanimovilapp.apps.servicios.models import Servicio


def _normalizar_nombre_servicio(nombre: str) -> str:
    raw = (nombre or '').strip()
    if not raw:
        return ''
    nfkd = unicodedata.normalize('NFKD', raw)
    sin_tildes = ''.join(c for c in nfkd if not unicodedata.combining(c))
    colapsado = re.sub(r'\s+', ' ', sin_tildes).strip().lower()
    return colapsado


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

    candidatos = Servicio.objects.all().only('id', 'nombre', 'descripcion')
    for servicio in candidatos:
        if _normalizar_nombre_servicio(servicio.nombre) == clave:
            return servicio

    with transaction.atomic():
        # Re-check dentro de la transacción por condiciones de carrera
        for servicio in Servicio.objects.select_for_update().only('id', 'nombre'):
            if _normalizar_nombre_servicio(servicio.nombre) == clave:
                return servicio

        desc = (descripcion or '').strip() or f'Servicio registrado automáticamente: {nombre_limpio}'
        return Servicio.objects.create(
            nombre=nombre_limpio[:255],
            descripcion=desc[:2000],
        )
