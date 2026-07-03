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
        if record.levelno < logging.WARNING:
            return True
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(getattr(record, 'msg', ''))
        if 'Unauthorized' in msg and '/api/' in msg:
            return False
        args = getattr(record, 'args', None)
        if args:
            joined = ' '.join(str(a) for a in args)
            if 'Unauthorized' in joined or '/api/' in joined:
                if getattr(record, 'status_code', None) == 401:
                    return False
        return True
