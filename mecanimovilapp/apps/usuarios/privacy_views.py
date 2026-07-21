"""Endpoints de privacidad / Ley 21.719 (ARCOP, baja de cuenta, portabilidad)."""
from __future__ import annotations

import logging

from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from mecanimovilapp.apps.usuarios.legal_constants import LEGAL_DOCS_VERSION
from mecanimovilapp.apps.usuarios.models import PreferenciasNotificacion
from mecanimovilapp.apps.usuarios.services.account_deletion import (
    eliminar_cuenta_usuario,
    verificar_puede_eliminar_cuenta,
)
from mecanimovilapp.apps.usuarios.services.consent import (
    registrar_consentimiento,
    registrar_consentimiento_registro,
    requiere_consentimiento_legal,
)
from mecanimovilapp.apps.usuarios.services.data_export import exportar_datos_usuario

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def exportar_mis_datos(request):
    payload = exportar_datos_usuario(request.user)
    return Response(payload)


@api_view(['GET', 'PATCH'])
@permission_classes([permissions.IsAuthenticated])
def preferencias_notificacion(request):
    prefs, _ = PreferenciasNotificacion.objects.get_or_create(usuario=request.user)
    if request.method == 'GET':
        return Response({
            'push_operativo': prefs.push_operativo,
            'push_marketing': prefs.push_marketing,
            'email_marketing': prefs.email_marketing,
            'actualizado_en': prefs.actualizado_en.isoformat() if prefs.actualizado_en else None,
        })

    update_fields = ['actualizado_en']
    for field in ('push_operativo', 'push_marketing', 'email_marketing'):
        if field in request.data:
            setattr(prefs, field, bool(request.data[field]))
            update_fields.append(field)
    prefs.save(update_fields=update_fields)
    return Response({
        'push_operativo': prefs.push_operativo,
        'push_marketing': prefs.push_marketing,
        'email_marketing': prefs.email_marketing,
        'actualizado_en': prefs.actualizado_en.isoformat(),
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def estado_eliminacion_cuenta(request):
    bloqueo = verificar_puede_eliminar_cuenta(request.user)
    if bloqueo is not None:
        return Response({
            'puede_eliminar': False,
            'codigo': bloqueo.code,
            'mensaje': bloqueo.message,
        })
    return Response({'puede_eliminar': True})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def eliminar_cuenta(request):
    password = request.data.get('password') or request.data.get('current_password')
    confirmacion = request.data.get('confirmacion') or request.data.get('confirm')

    if confirmacion not in ('ELIMINAR', 'eliminar', True):
        return Response(
            {'error': 'Debes confirmar escribiendo ELIMINAR'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not password:
        return Response(
            {'error': 'Se requiere tu contraseña para eliminar la cuenta'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        eliminar_cuenta_usuario(request.user, password=password)
    except ValueError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as exc:
        logger.error('Error eliminando cuenta %s: %s', request.user.pk, exc, exc_info=True)
        return Response(
            {'error': 'No se pudo eliminar la cuenta. Intenta más tarde.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return Response({'message': 'Tu cuenta fue eliminada y tus datos personales anonimizados.'})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def registrar_consentimiento_legal(request):
    canal = request.data.get('canal') or 'app_usuarios'
    acepta_terminos = request.data.get('acepta_terminos', False)
    acepta_privacidad = request.data.get('acepta_privacidad', False)

    if not (acepta_terminos and acepta_privacidad):
        return Response(
            {'error': 'Debes aceptar los términos y la política de privacidad'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    registrar_consentimiento_registro(request.user, canal=canal, request=request)
    return Response({
        'message': 'Consentimiento registrado',
        'version_documento': LEGAL_DOCS_VERSION,
        'requiere_consentimiento': False,
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def estado_consentimiento_legal(request):
    return Response({
        'requiere_consentimiento': requiere_consentimiento_legal(request.user),
        'version_documento': LEGAL_DOCS_VERSION,
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def registrar_consentimiento_ubicacion_view(request):
    from mecanimovilapp.apps.usuarios.services.consent import (
        registrar_consentimiento_ubicacion,
        usuario_tiene_consentimiento_ubicacion,
    )

    canal = request.data.get('canal') or 'app_prov'
    acepta = request.data.get('acepta_ubicacion', False)
    if not acepta:
        return Response(
            {'error': 'Debes aceptar el uso de geolocalización'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not usuario_tiene_consentimiento_ubicacion(request.user):
        registrar_consentimiento_ubicacion(request.user, canal=canal, request=request)

    return Response({
        'message': 'Consentimiento de ubicación registrado',
        'version_documento': LEGAL_DOCS_VERSION,
        'tiene_consentimiento_ubicacion': True,
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def estado_consentimiento_ubicacion_view(request):
    from mecanimovilapp.apps.usuarios.services.consent import (
        usuario_tiene_consentimiento_ubicacion,
    )

    return Response({
        'tiene_consentimiento_ubicacion': usuario_tiene_consentimiento_ubicacion(request.user),
        'version_documento': LEGAL_DOCS_VERSION,
    })
