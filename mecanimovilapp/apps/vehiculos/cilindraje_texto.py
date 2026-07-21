"""Inferencia de cilindraje desde textos de marca/modelo."""
from __future__ import annotations

import re
from typing import Any

_CIL_LITROS_RE = re.compile(r'(?:^|[^\d.])(\d\.\d{1,2})(?![0-9])\s*[LlTt]?')
_CIL_CC_RE = re.compile(r'\b(\d{3,4})\s*[Cc][Cc]\b')


def extraer_cilindraje_desde_texto(*partes: Any) -> str:
    """
    Infieren cilindraje desde marca/modelo (ej. "3008 GT LINE 1.6 AUT" → "1.6").
    No usa códigos de modelo tipo 3008/208 como cc.
    """
    texto = ' '.join(str(p or '').strip() for p in partes if p is not None).strip()
    if not texto:
        return ''
    m = _CIL_LITROS_RE.search(texto)
    if m:
        return m.group(1)
    m = _CIL_CC_RE.search(texto)
    if m:
        return m.group(1)
    return ''


def cilindraje_efectivo(cilindraje: Any = '', *marca_modelo: Any) -> str:
    directo = str(cilindraje or '').strip()
    if directo:
        return directo
    return extraer_cilindraje_desde_texto(*marca_modelo)
