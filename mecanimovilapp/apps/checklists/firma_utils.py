"""Normalización de firmas (canvas suele mandar data URI; guardamos solo el payload base64)."""


def firma_a_payload_base64(firma: str) -> str:
    """
    Devuelve solo el tramo base64, sin prefijo data:image/...;base64,
    para almacenar de forma uniforme (misma convención que la app proveedor).
    """
    if not firma or not isinstance(firma, str):
        return firma
    s = firma.strip()
    if not s:
        return s
    marker = 'base64,'
    if s.startswith('data:') and marker in s:
        return s.split(marker, 1)[1]
    return s
