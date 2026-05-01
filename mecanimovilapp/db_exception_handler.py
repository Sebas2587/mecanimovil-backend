"""
Return JSON 503 only for *transient* DB connectivity issues so clients can retry.

Previously any django.db.DatabaseError (including ProgrammingError for missing
columns after a deploy) became 503, which masked schema bugs and looked like
the database was down on every endpoint.
"""
import logging

from django.db import DatabaseError, InterfaceError, OperationalError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)

# OperationalError: connection refused, SSL, timeouts, "too many connections", etc.
# InterfaceError: connection already closed (psycopg / async edge cases)
_RETRYABLE_DB = (OperationalError, InterfaceError)


def custom_exception_handler(exc, context):
    if isinstance(exc, _RETRYABLE_DB):
        logger.warning(
            "Base de datos no disponible (transitorio): %s: %s",
            exc.__class__.__name__,
            exc,
            exc_info=True,
        )
        return Response(
            {
                'error': (
                    'La base de datos no está disponible en este momento. '
                    'Espera unos segundos e intenta de nuevo.'
                ),
                'code': 'database_unavailable',
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if isinstance(exc, DatabaseError):
        logger.exception(
            "Error de base de datos no transitorio (%s); delegando a DRF",
            exc.__class__.__name__,
        )
    return drf_exception_handler(exc, context)
