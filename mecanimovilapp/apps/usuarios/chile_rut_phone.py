"""
Normalización y validación de RUT chileno y teléfono móvil (+56 9XXXXXXXX).
"""
from __future__ import annotations

import re
from itertools import cycle


def normalizar_rut_chile(valor: str) -> str | None:
    """
    Devuelve RUT en forma '12345678-9' o '1234567-K' en mayúsculas, o None si no es recuperable.
    """
    if not valor or not str(valor).strip():
        return None
    s = str(valor).strip().upper().replace(' ', '')
    s = re.sub(r'[^0-9K\-]', '', s.replace('.', ''))
    if '-' in s:
        body, dv = s.split('-', 1)
    else:
        if len(s) < 2:
            return None
        body, dv = s[:-1], s[-1]
    body = re.sub(r'[^0-9]', '', body)
    dv = dv.strip().upper()
    if not body.isdigit() or len(body) > 8:
        return None
    if dv not in ('0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'K'):
        return None
    return f'{body}-{dv}'


def calcular_dv_rut(body: str) -> str:
    """Módulo 11 estándar Chile."""
    body = body.zfill(8)
    reversed_digits = map(int, reversed(body))
    factors = cycle([2, 3, 4, 5, 6, 7])
    total = sum(d * f for d, f in zip(reversed_digits, factors))
    resto = total % 11
    dv = 11 - resto
    if dv == 11:
        return '0'
    if dv == 10:
        return 'K'
    return str(dv)


def rut_modulo11_valido(normalizado: str) -> bool:
    parts = normalizado.split('-')
    if len(parts) != 2:
        return False
    body, dv = parts[0], parts[1].upper()
    if not body.isdigit() or len(body) < 1 or len(body) > 8:
        return False
    esperado = calcular_dv_rut(body)
    return dv == esperado


def normalizar_telefono_movil_cl(valor: str) -> str | None:
    """
    Canonico '+56912345678' para móvil chileno (9 dígitos empezando en 9).
    """
    if not valor:
        return None
    d = ''.join(c for c in str(valor) if c.isdigit())
    if not d:
        return None
    if d.startswith('56') and len(d) >= 11:
        d = d[2:]
    if len(d) == 9 and d[0] == '9':
        return f'+56{d}'
    if len(d) == 11 and d.startswith('569'):
        return f'+{d}'
    return None

