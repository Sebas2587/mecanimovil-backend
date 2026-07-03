"""Filtros de logging para reducir ruido operacional en producción."""
from __future__ import annotations

import logging


class SuppressRoutineHttp401Filter(logging.Filter):
    """
    Suprime WARNING de django.request por 401 en /api/.

    Un 401 sin token es esperable (app web en dev, sesión expirada, pestaña abierta).
    Las peticiones siguen registrándose en access logs de Render (tipo request).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING and 'Unauthorized: /api/' in record.getMessage():
            return False
        return True
