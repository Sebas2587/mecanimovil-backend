"""Registro de consentimiento acreditado (Ley 21.719 art. 12)."""
from __future__ import annotations

from django.utils import timezone

from mecanimovilapp.apps.usuarios.legal_constants import (
    LEGAL_DOCS_VERSION,
    PRIVACIDAD_DOC_VERSION,
    TERMINOS_DOC_VERSION,
)
from mecanimovilapp.apps.usuarios.models import ConsentimientoUsuario, Usuario


def _client_meta(request) -> tuple[str | None, str]:
    if request is None:
        return None, ''
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        ip = xff.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    ua = (request.META.get('HTTP_USER_AGENT') or '')[:500]
    return ip, ua


def registrar_consentimiento(
    usuario: Usuario,
    *,
    tipo: str,
    canal: str,
    version_documento: str | None = None,
    request=None,
) -> ConsentimientoUsuario:
    if version_documento is None:
        if tipo == 'terminos':
            version_documento = TERMINOS_DOC_VERSION
        elif tipo == 'privacidad':
            version_documento = PRIVACIDAD_DOC_VERSION
        else:
            version_documento = LEGAL_DOCS_VERSION

    ip, ua = _client_meta(request)
    return ConsentimientoUsuario.objects.create(
        usuario=usuario,
        tipo=tipo,
        version_documento=version_documento,
        canal=canal,
        ip_address=ip,
        user_agent=ua,
    )


def registrar_consentimiento_registro(
    usuario: Usuario,
    *,
    canal: str,
    request=None,
) -> None:
    registrar_consentimiento(usuario, tipo='terminos', canal=canal, request=request)
    registrar_consentimiento(usuario, tipo='privacidad', canal=canal, request=request)


def usuario_tiene_consentimiento_legal(usuario: Usuario) -> bool:
    tipos = ConsentimientoUsuario.objects.filter(
        usuario=usuario,
        tipo__in=('terminos', 'privacidad'),
        version_documento=LEGAL_DOCS_VERSION,
    ).values_list('tipo', flat=True)
    return 'terminos' in tipos and 'privacidad' in tipos


def requiere_consentimiento_legal(usuario: Usuario) -> bool:
    if usuario.deleted_at is not None:
        return False
    return not usuario_tiene_consentimiento_legal(usuario)


def usuario_tiene_consentimiento_ubicacion(usuario: Usuario) -> bool:
    return ConsentimientoUsuario.objects.filter(
        usuario=usuario,
        tipo='ubicacion',
        version_documento=LEGAL_DOCS_VERSION,
    ).exists()


def registrar_consentimiento_ubicacion(
    usuario: Usuario,
    *,
    canal: str = 'app_prov',
    request=None,
) -> ConsentimientoUsuario:
    return registrar_consentimiento(
        usuario,
        tipo='ubicacion',
        canal=canal,
        request=request,
    )
