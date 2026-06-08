"""
Selección del servicio de catálogo más adecuado para un componente de salud.
Evita sugerir servicios genéricos (p. ej. «Mantenimiento por kilometraje») en
componentes específicos como neumáticos o filtros.
"""
import re
import unicodedata

from mecanimovilapp.apps.servicios.tipos_motor_utils import servicio_compatible_con_tipo_motor

# Palabras clave por slug → servicio con nombre relacionado
SLUG_SERVICE_KEYWORDS = {
    'tires': ['neumatico', 'neumático', 'goma', 'llanta', 'rotacion', 'alineacion', 'balanceo'],
    'brakes': ['pastilla', 'freno'],
    'brake-discs': ['disco', 'rectificado', 'pastilla', 'freno'],
    'brake-fluid': ['liquido de freno', 'líquido de freno', 'liquido frenos'],
    'oil': ['aceite motor', 'cambio de aceite', 'aceite y filtro'],
    'oil-filter': ['filtro de aceite', 'filtro aceite', 'aceite motor y filtro'],
    'air-filter': ['filtro de aire', 'filtro aire'],
    'cabin-filter': ['filtro habitaculo', 'filtro habitáculo', 'filtro cabina', 'habitaculo'],
    'spark-plug': ['bujia', 'bujía'],
    'battery': ['bateria', 'batería'],
    'coolant': ['refrigerante'],
    'shocks': ['amortiguador'],
    'timing-belt': ['correa', 'distribucion', 'distribución'],
    'exhaust': ['dpf', 'particula', 'partícula', 'filtro de part', 'escape'],
    'adblue': ['adblue', 'urea'],
}

GENERIC_SERVICE_PATTERNS = (
    re.compile(r'^mantenimiento por kilometraje$', re.I),
    re.compile(r'^diagn[oó]stico mec[aá]nico$', re.I),
    re.compile(r'^diagn[oó]stico electromec[aá]nico$', re.I),
)

# Servicios combo que no deben priorizarse en filtros individuales
COMBO_PENALTY_SLUGS = {
    'air-filter': ('aceite motor y filtro', -25),
    'cabin-filter': ('aceite motor y filtro', -25),
    'oil-filter': ('filtro de aire', -15),
    'oil': ('filtro de aire', -15),
}


def _normalize_text(value):
    if not value:
        return ''
    text = unicodedata.normalize('NFD', str(value).lower())
    return ''.join(c for c in text if unicodedata.category(c) != 'Mn')


def _is_generic_service_name(nombre):
    nombre = (nombre or '').strip()
    return any(pat.match(nombre) for pat in GENERIC_SERVICE_PATTERNS)


def score_servicio_para_componente(slug, servicio):
    """Puntúa qué tan adecuado es un servicio para el slug del componente."""
    slug = (slug or '').strip()
    nombre_norm = _normalize_text(getattr(servicio, 'nombre', '') or '')
    score = 0

    for kw in SLUG_SERVICE_KEYWORDS.get(slug, []):
        if _normalize_text(kw) in nombre_norm:
            score += 12

    if _is_generic_service_name(getattr(servicio, 'nombre', '')):
        score -= 60

    combo_rule = COMBO_PENALTY_SLUGS.get(slug)
    if combo_rule:
        needle, penalty = combo_rule
        if _normalize_text(needle) in nombre_norm:
            score += penalty

    return score


def resolver_servicio_sugerido(slug, servicios_qs, tipo_motor=None):
    """
    Devuelve dict ligero {id, nombre, descripcion, precio_referencia} o None.
    """
    best = None
    best_score = -999

    for servicio in servicios_qs:
        if not servicio_compatible_con_tipo_motor(servicio, tipo_motor):
            continue
        score = score_servicio_para_componente(slug, servicio)
        if score > best_score:
            best_score = score
            best = servicio

    if best is None or best_score < 1:
        return None

    return {
        'id': best.id,
        'nombre': best.nombre,
        'descripcion': (best.descripcion or '')[:300],
        'precio_referencia': float(best.precio_referencia) if best.precio_referencia is not None else None,
        'score': best_score,
    }


def ordenar_servicios_asociados(slug, servicios_qs, tipo_motor=None):
    """Lista de dicts ordenada por relevancia para el componente."""
    items = []
    for servicio in servicios_qs:
        if not servicio_compatible_con_tipo_motor(servicio, tipo_motor):
            continue
        score = score_servicio_para_componente(slug, servicio)
        items.append({
            'id': servicio.id,
            'nombre': servicio.nombre,
            'descripcion': (servicio.descripcion or '')[:300],
            'precio_referencia': float(servicio.precio_referencia) if servicio.precio_referencia is not None else None,
            '_score': score,
        })
    items.sort(key=lambda x: x['_score'], reverse=True)
    for row in items:
        row.pop('_score', None)
    return items
