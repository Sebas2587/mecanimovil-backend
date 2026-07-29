"""Defaults de opciones para ítems de checklist que no pueden quedar vacíos."""
from __future__ import annotations

from typing import Any

# Tipos que requieren opciones no vacías para renderizar UI.
TIPOS_CON_OPCIONES = frozenset({
    'SELECT',
    'MULTISELECT',
    'FLUID_LEVEL',
    'EXTERIOR_INSPECTION',
    'INTERIOR_INSPECTION',
    'ENGINE_INSPECTION',
    'ELECTRICAL_CHECK',
    'BRAKE_CHECK',
    'SUSPENSION_CHECK',
    'TIRE_CONDITION',
    'VEHICLE_CONDITION',
    'SERVICE_SELECTION',
})

_OPCIONES_FLUIDO = ['Mínimo', 'Bajo', 'Normal', 'Alto', 'Sobre máximo']
_OPCIONES_ESTADO = ['Excelente', 'Bueno', 'Regular', 'Malo', 'Crítico']
_OPCIONES_FLUIDOS_COMPLEMENTARIOS = [
    'Todos correctos',
    'Algunos bajos',
    'Refrigerante bajo',
    'Aceite bajo',
    'Requiere rellenado',
]


def _normalizar_lista(raw: Any) -> list[str] | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        out = [str(x).strip() for x in raw if str(x).strip()]
        return out or None
    if isinstance(raw, str) and raw.strip():
        # A veces viene como texto multilínea
        partes = [p.strip() for p in raw.replace(',', '\n').splitlines() if p.strip()]
        return partes or None
    return None


def opciones_default_para_tipo(tipo_pregunta: str, *, nombre: str = '') -> list[str]:
    tipo = (tipo_pregunta or '').strip().upper()
    nombre_l = (nombre or '').lower()
    if tipo == 'FLUID_LEVEL':
        if any(k in nombre_l for k in ('complement', 'fluidos', 'niveles', 'refriger', 'freno', 'dirección', 'direccion')):
            return list(_OPCIONES_FLUIDOS_COMPLEMENTARIOS)
        return list(_OPCIONES_FLUIDO)
    if tipo in TIPOS_CON_OPCIONES:
        return list(_OPCIONES_ESTADO)
    return list(_OPCIONES_ESTADO)


def opciones_efectivas(
    tipo_pregunta: str,
    opciones: Any,
    *,
    nombre: str = '',
) -> list[str] | None:
    """Devuelve opciones válidas; si el tipo las requiere y faltan, usa defaults."""
    tipo = (tipo_pregunta or '').strip().upper()
    normalizadas = _normalizar_lista(opciones)
    if normalizadas:
        return normalizadas
    if tipo in TIPOS_CON_OPCIONES:
        return opciones_default_para_tipo(tipo, nombre=nombre)
    return None


def asegurar_opciones_en_catalog_item(catalog_item) -> list[str] | None:
    """
    Garantiza opciones en el catálogo. Si faltan y el tipo las requiere,
    persiste defaults (auto-reparación de templates IA rotos).
    """
    if catalog_item is None:
        return None
    tipo = (catalog_item.tipo_pregunta or '').strip().upper()
    efectivas = opciones_efectivas(
        tipo,
        catalog_item.opciones_seleccion,
        nombre=catalog_item.nombre or '',
    )
    if tipo in TIPOS_CON_OPCIONES and efectivas:
        actuales = _normalizar_lista(catalog_item.opciones_seleccion)
        if not actuales:
            catalog_item.opciones_seleccion = efectivas
            catalog_item.save(update_fields=['opciones_seleccion'])
    return efectivas
