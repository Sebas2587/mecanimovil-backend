"""
Resolución de contexto de taller y permisos para sesiones de proveedor.

Unifica cómo un endpoint sabe sobre qué taller opera el usuario autenticado y
qué puede hacer:

- Mandante (dueño que registró el taller): acceso total.
- Supervisor (MiembroTaller con login propio): opera sobre el taller del
  mandante, limitado por su mapa de `permisos`.

Esto permite que un supervisor inicie sesión y gestione el taller sin ser dueño,
mientras el backend valida cada permiso (no solo la UI).
"""

from rest_framework.permissions import BasePermission, SAFE_METHODS


def resolver_contexto_taller(user):
    """
    Devuelve (taller, miembro, rol) para el usuario autenticado.

    - Dueño directo del taller -> (taller, miembro_mandante|None, 'mandante')
    - Supervisor con login activo -> (taller_supervisado, miembro, 'supervisor')
    - Sin contexto de taller -> (None, None, None)
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return None, None, None

    from mecanimovilapp.apps.usuarios.models import Taller, MiembroTaller

    taller = getattr(user, 'taller', None)
    if taller is None:
        taller = Taller.objects.filter(usuario=user).first()
    if taller is not None:
        miembro = MiembroTaller.objects.filter(
            taller=taller, usuario=user, rol='mandante'
        ).first()
        return taller, miembro, 'mandante'

    miembro = (
        MiembroTaller.objects
        .filter(usuario=user, rol='supervisor', activo=True)
        .select_related('taller')
        .first()
    )
    if miembro is not None:
        return miembro.taller, miembro, 'supervisor'

    return None, None, None


def usuario_puede(user, recurso):
    """True si el usuario puede gestionar (crear/editar/eliminar) el recurso."""
    taller, miembro, rol = resolver_contexto_taller(user)
    if taller is None:
        return False
    if rol == 'mandante':
        return True
    return bool(miembro and miembro.tiene_permiso(recurso))


def requiere_permiso(recurso):
    """
    Fabrica una permission class de DRF que exige permiso de gestión sobre
    `recurso` para métodos de escritura. Las lecturas se permiten a cualquier
    miembro del taller (mandante o supervisor).
    """

    class _PermisoTaller(BasePermission):
        message = f'No tienes permiso para gestionar {recurso}.'

        def has_permission(self, request, view):
            taller, miembro, rol = resolver_contexto_taller(request.user)
            if taller is None:
                return False
            if request.method in SAFE_METHODS:
                return True
            if rol == 'mandante':
                return True
            return bool(miembro and miembro.tiene_permiso(recurso))

    return _PermisoTaller


class BloqueadoParaSupervisor(BasePermission):
    """
    Permite el acceso solo al mandante (dueño). Usar en módulos sensibles que un
    supervisor nunca debe tocar: suscripción, MercadoPago y perfil del taller.
    """
    message = 'Solo el dueño del taller puede acceder a este módulo.'

    def has_permission(self, request, view):
        taller, miembro, rol = resolver_contexto_taller(request.user)
        # Dueño directo: permitido. Cualquier otro contexto (supervisor): bloqueado.
        return rol == 'mandante'
