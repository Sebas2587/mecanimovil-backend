"""Normalización de teléfonos chilenos para identificar un contacto."""
from __future__ import annotations


def solo_digitos(raw: str | None) -> str:
    return ''.join(c for c in (raw or '') if c.isdigit())


def normalizar_telefono(raw: str | None) -> str:
    """Devuelve dígitos con prefijo 56 cuando el número parece móvil chileno."""
    digits = solo_digitos(raw)
    if not digits:
        return ''
    if digits.startswith('56') and len(digits) >= 11:
        return digits[:15]
    if len(digits) == 9 and digits.startswith('9'):
        return '56' + digits
    if len(digits) == 8:
        return '569' + digits
    return digits[:15]


def telefonos_coinciden(a: str | None, b: str | None) -> bool:
    left = normalizar_telefono(a)
    right = normalizar_telefono(b)
    if not left or not right:
        return False
    if left == right:
        return True
    cola_izq = left[-9:]
    cola_der = right[-9:]
    return len(cola_izq) >= 8 and cola_izq == cola_der
