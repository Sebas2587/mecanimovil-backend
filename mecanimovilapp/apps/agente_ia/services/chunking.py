"""Utilidades de fragmentación de texto para RAG."""
from __future__ import annotations

import re

_CHUNK_SIZE = 600
_CHUNK_OVERLAP = 80


def _normalizar_espacios(texto: str) -> str:
    return re.sub(r'\s+', ' ', (texto or '').strip())


def fragmentar_texto(
    texto: str,
    *,
    chunk_size: int = _CHUNK_SIZE,
    overlap: int = _CHUNK_OVERLAP,
) -> list[str]:
    """Divide texto en fragmentos con solapamiento."""
    texto = _normalizar_espacios(texto)
    if not texto:
        return []
    if len(texto) <= chunk_size:
        return [texto]

    chunks: list[str] = []
    start = 0
    while start < len(texto):
        end = min(len(texto), start + chunk_size)
        chunk = texto[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(texto):
            break
        start = max(0, end - overlap)
    return chunks


def extraer_texto_pdf(archivo) -> str:
    """Extrae texto de un archivo PDF."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return ''

    try:
        reader = PdfReader(archivo)
        partes = []
        for page in reader.pages:
            partes.append(page.extract_text() or '')
        return _normalizar_espacios('\n'.join(partes))
    except Exception:
        return ''
