"""Texto de catálogo (repuestos + garantía) para ficha operativa y RAG."""
from __future__ import annotations

from typing import Any


def _item_repuesto_txt(item: dict[str, Any]) -> str:
    if not isinstance(item, dict):
        return ''
    nombre = (item.get('nombre') or '').strip()
    if not nombre:
        return ''
    partes = [nombre]
    cantidad = item.get('cantidad') or item.get('cantidad_estimada')
    if cantidad:
        try:
            cant = int(cantidad)
            if cant > 1:
                partes[0] = f'{nombre} x{cant}'
        except (TypeError, ValueError):
            pass
    marca = (item.get('marca_repuesto') or item.get('marca') or '').strip()
    calidad = (item.get('calidad_repuesto_label') or item.get('calidad_repuesto') or '').strip()
    if marca and calidad:
        partes.append(f'marca {marca} ({calidad})')
    elif marca:
        partes.append(f'marca {marca}')
    elif calidad:
        partes.append(calidad)
    return ' '.join(partes)


def resumen_repuestos_garantia_oferta(
    oferta,
    *,
    repuestos: list | None = None,
) -> str:
    """Fragmento de texto con repuestos configurados y garantía de una OfertaServicio."""
    partes: list[str] = []
    items = repuestos if repuestos is not None else (oferta.repuestos_seleccionados or [])
    repuestos_txt: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        linea = _item_repuesto_txt(item)
        if linea:
            repuestos_txt.append(linea)
    if repuestos_txt:
        partes.append('repuestos: ' + '; '.join(repuestos_txt))

    if getattr(oferta, 'incluye_garantia', False):
        dias = int(getattr(oferta, 'duracion_garantia', 0) or 0)
        if dias:
            partes.append(f'garantía {dias} días')
        else:
            partes.append('incluye garantía')
    return ' · '.join(partes)
