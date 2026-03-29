"""
Extracción del odómetro declarado en un checklist completado.
Centralizado para evitar importar módulos de Celery desde serializadores/API.
"""

# Subcadenas para detectar ítems NUMBER que en la práctica son odómetro
_KM_CATALOG_HINTS = (
    'kilomet', 'kilometraje', 'odomet', 'odómetro', 'cuenta kilómetro', 'cuenta kilometros',
)


def extraer_kilometraje_desde_checklist_instance(checklist):
    """
    Lee el km declarado en el checklist. Además de KILOMETER_INPUT, acepta NUMBER si el ítem
    del catálogo indica odómetro (muchos templates usan solo NUMBER).
    """
    qs = checklist.respuestas.select_related('item_template__catalog_item')
    for respuesta in qs.all():
        cat = respuesta.item_template.catalog_item
        if not cat or respuesta.respuesta_numero is None:
            continue
        tipo = (cat.tipo_pregunta or '').strip()
        if tipo == 'KILOMETER_INPUT':
            pass
        elif tipo == 'NUMBER':
            nombre = (cat.nombre or '').lower()
            texto = (cat.pregunta_texto or '').lower()
            if not any((h in nombre) or (h in texto) for h in _KM_CATALOG_HINTS):
                continue
        else:
            continue
        try:
            return int(float(respuesta.respuesta_numero))
        except (TypeError, ValueError):
            continue
    return None
