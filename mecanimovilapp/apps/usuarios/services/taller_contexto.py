"""
Resolución de contexto de taller y permisos para sesiones de proveedor.

Unifica cómo un endpoint sabe sobre qué taller opera el usuario autenticado y
qué puede hacer:

- Mandante (dueño que registró el taller): acceso total.
- Supervisor (MiembroTaller con login propio): opera sobre el taller del
  mandante, limitado por su mapa de `permisos`.
- Mecánico (MiembroTaller con login propio): opera sobre el taller del
  mandante, limitado a órdenes/checklists/agenda asignados a él.

Esto permite que un supervisor inicie sesión y gestione el taller sin ser dueño,
mientras el backend valida cada permiso (no solo la UI).
"""

from rest_framework.permissions import BasePermission, SAFE_METHODS


def resolver_contexto_taller(user):
    """
    Devuelve (taller, miembro, rol) para el usuario autenticado.

    - Dueño directo del taller -> (taller, miembro_mandante|None, 'mandante')
    - Supervisor con login activo -> (taller_supervisado, miembro, 'supervisor')
    - Mecánico con login activo -> (taller, miembro, 'mecanico')
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

    miembro = (
        MiembroTaller.objects
        .filter(usuario=user, rol='mecanico', activo=True)
        .select_related('taller')
        .first()
    )
    if miembro is not None:
        return miembro.taller, miembro, 'mecanico'

    return None, None, None


def usuario_puede(user, recurso):
    """True si el usuario puede gestionar (crear/editar/eliminar) el recurso."""
    taller, miembro, rol = resolver_contexto_taller(user)
    if taller is None:
        return False
    if rol == 'mandante':
        return True
    if rol == 'mecanico':
        return False
    return bool(miembro and miembro.tiene_permiso(recurso))


def exigir_no_mecanico_equipo(user, accion='realizar esta acción'):
    """Lanza PermissionDenied si el usuario es mecánico del equipo."""
    from rest_framework.exceptions import PermissionDenied

    _taller, _miembro, rol = resolver_contexto_taller(user)
    if rol == 'mecanico':
        raise PermissionDenied(f'Los mecánicos no pueden {accion}.')


def puede_ejecutar_servicio(user, *, miembro_asignado_id=None) -> bool:
    """
    Quién puede iniciar/avanzar/finalizar un servicio operativo:

    - Mecánico de equipo: sí solo si está asignado a esa orden/cita.
    - Mandante / supervisor: sí (cualquier orden/cita del taller).
    - Proveedor sin rol de equipo (dueño legacy o mecánico a domicilio): sí;
      la autorización de pertenencia la hacen las vistas (get_object / queryset).
    """
    _taller, miembro, rol = resolver_contexto_taller(user)
    if rol == 'mecanico':
        if miembro is None or miembro_asignado_id is None:
            return False
        try:
            return int(miembro_asignado_id) == int(miembro.id)
        except (TypeError, ValueError):
            return False
    return True


def exigir_puede_ejecutar_servicio(user, *, miembro_asignado_id=None, accion='ejecutar este servicio'):
    """Lanza PermissionDenied si el usuario no puede operar el servicio."""
    from rest_framework.exceptions import PermissionDenied

    if not puede_ejecutar_servicio(user, miembro_asignado_id=miembro_asignado_id):
        raise PermissionDenied(
            f'No tienes permiso para {accion}. '
            'Solo el taller/supervisor o el técnico asignado pueden hacerlo.'
        )


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
