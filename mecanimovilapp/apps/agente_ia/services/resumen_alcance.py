"""Resumen de alcance: una vez por cotización, sin montos, escape por urgencia."""
from __future__ import annotations

import logging
import re
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

_URGENCIA_RE = re.compile(
    r'(?:m[aá]ndame\s+el\s+precio\s+ya|el\s+precio\s+ya|urgente|'
    r'lo\s+necesito\s+(?:ya|ahora)|ahora\s+mismo|ya\s+mismo)',
    re.I,
)
_CONFIRMA_RE = re.compile(
    r'^(?:s[ií]|ok|dale|listo|perfecto|confirmo|de\s+una|'
    r'as[ií]\s+est[aá]\s+bien|as[ií]\s+nomas|as[ií]\s+nomas|'
    r'd[eé]jalo\s+as[ií]|queda\s+as[ií])\b',
    re.I,
)
_MODIFICA_RE = re.compile(
    r'\b(?:agrega|agregar|suma|sumar|quita|quitar|saca|sacar|'
    r'tambi[eé]n|adem[aá]s|sin\s+el|en\s+vez)\b',
    re.I,
)


def urgencia_explicita(texto: str, datos: dict[str, Any] | None = None) -> bool:
    if _URGENCIA_RE.search(texto or ''):
        return True
    urg = str((datos or {}).get('urgencia') or '').strip().lower()
    return urg in ('alta', 'urgente', 'inmediata', 'ya')


def debe_enviar_resumen(sesion, decision: dict[str, Any] | None = None, texto_cliente: str = '') -> bool:
    if not getattr(settings, 'AGENTE_IA_ALCANCE_REPUESTOS_ENABLED', False):
        return False
    datos = dict(getattr(sesion, 'datos_capturados', None) or {})
    if datos.get('resumen_alcance_enviado'):
        return False
    if urgencia_explicita(texto_cliente, datos):
        return False
    listo = bool((decision or {}).get('listo_para_cotizar'))
    if not listo and not datos.get('pregunta_calidad_enviada'):
        return False
    servs = list(datos.get('servicios') or [])
    if datos.get('servicio_nombre'):
        servs.append(datos.get('servicio_nombre'))
    return bool(any(str(s or '').strip() for s in servs))


def cliente_confirma_resumen(texto: str) -> bool:
    t = (texto or '').strip()
    if not t:
        return False
    if _MODIFICA_RE.search(t):
        return False
    return bool(_CONFIRMA_RE.search(t) or len(t.split()) <= 4 and _CONFIRMA_RE.search(t))


def cliente_modifica_alcance(texto: str) -> bool:
    return bool(_MODIFICA_RE.search(texto or ''))


def construir_resumen_alcance(datos: dict[str, Any]) -> list[str]:
    """Máx 3 burbujas, sin montos."""
    servs = []
    for s in list(datos.get('servicios') or []):
        n = str(s or '').strip()
        if n and n not in servs:
            servs.append(n)
    if datos.get('servicio_nombre'):
        n = str(datos.get('servicio_nombre') or '').strip()
        if n and n not in servs:
            servs.insert(0, n)
    piezas = [str(p).strip() for p in (datos.get('piezas_mencionadas') or []) if str(p or '').strip()]
    calidad = str(datos.get('calidad_preferida') or '').strip()
    calidad_txt = {
        'original': 'original',
        'oem': 'equivalente OEM',
        'alternativo': 'alternativo',
    }.get(calidad, '')

    bullets = [f'• {s}' for s in servs[:6]]
    for p in piezas[:4]:
        line = f'• {p}'
        if line.lower() not in {b.lower() for b in bullets}:
            bullets.append(line)
    if not bullets:
        bullets = ['• el trabajo que pediste']

    b1 = 'Te resumo lo que va:\n' + '\n'.join(bullets[:6])
    burbujas = [b1]
    if calidad_txt:
        burbujas.append(f'Calidad de las piezas: {calidad_txt}.')
    burbujas.append(
        '¿Sumamos algo más o lo dejo así para que el taller te confirme el valor?'
    )
    logger.info('agente_ia[resumen_alcance] items_n=%s', len(bullets))
    return burbujas[:3]


def marcar_resumen_enviado(sesion) -> None:
    datos = dict(sesion.datos_capturados or {})
    datos['resumen_alcance_enviado'] = True
    sesion.datos_capturados = datos
    sesion.save(update_fields=['datos_capturados', 'actualizado_en'])
