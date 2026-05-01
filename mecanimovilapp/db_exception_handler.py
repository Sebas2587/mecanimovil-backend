"""
Return JSON 503 for DB connectivity errors so mobile clients can retry instead of a generic 500.
"""
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler
from django.db import Error as DjangoDBError


def custom_exception_handler(exc, context):
    if isinstance(exc, DjangoDBError):
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
    return drf_exception_handler(exc, context)
