from django.conf import settings
from rest_framework import permissions
from rest_framework.permissions import BasePermission
import logging

logger = logging.getLogger(__name__)


def _taller_supervisado(user):
    """Devuelve el taller que un supervisor con login activo opera, o None."""
    try:
        from mecanimovilapp.apps.usuarios.models import MiembroTaller
        miembro = (
            MiembroTaller.objects
            .filter(usuario=user, rol='supervisor', activo=True)
            .select_related('taller')
            .first()
        )
        return miembro.taller if miembro else None
    except Exception:
        return None


class IsProveedor(BasePermission):
    """
    Permiso que permite acceso solo a usuarios que sean talleres o mecánicos
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            logger.warning(
                "Usuario no autenticado intentando acceder a %s",
                view.__class__.__name__,
            )
            return False

        if settings.DEBUG:
            logger.debug(
                "Permiso proveedor: user=%s id=%s",
                getattr(request.user, "username", None),
                request.user.id,
            )

        tiene_taller = hasattr(request.user, "taller")
        tiene_mecanico = hasattr(request.user, "mecanico_domicilio")

        if tiene_taller:
            try:
                taller = request.user.taller
                if settings.DEBUG:
                    logger.debug(
                        "Proveedor taller: %s (verificado=%s)",
                        taller.nombre,
                        taller.verificado,
                    )
                return True
            except Exception as e:
                logger.error("Error accediendo a taller vía relación: %s", e)

        elif tiene_mecanico:
            try:
                mecanico = request.user.mecanico_domicilio
                if settings.DEBUG:
                    logger.debug(
                        "Proveedor mecánico: %s (verificado=%s)",
                        mecanico.nombre,
                        mecanico.verificado,
                    )
                return True
            except Exception as e:
                logger.error("Error accediendo a mecánico vía relación: %s", e)

        # Supervisor con login propio: opera sobre el taller del mandante.
        if _taller_supervisado(request.user) is not None:
            return True

        else:
            logger.warning(
                "Usuario %s no tiene perfil de taller ni mecánico",
                getattr(request.user, "username", request.user.pk),
            )
            if settings.DEBUG:
                related = [
                    a
                    for a in ("taller", "mecanico_domicilio", "cliente")
                    if hasattr(request.user, a)
                ]
                logger.debug("Atributos relacionados presentes: %s", related)

        return False


class IsOrderOwnerForProvider(BasePermission):
    """
    Permiso que permite a un proveedor acceder solo a sus propias órdenes
    """

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        # Verificar si el usuario es el proveedor asignado a la orden
        if hasattr(request.user, "taller"):
            return obj.taller == request.user.taller
        elif hasattr(request.user, "mecanico_domicilio"):
            return obj.mecanico == request.user.mecanico_domicilio

        taller_sup = _taller_supervisado(request.user)
        if taller_sup is not None:
            return obj.taller_id == taller_sup.id

        return False


class IsProveedorOrCliente(BasePermission):
    """
    Permiso que permite acceso a proveedores o clientes
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        return (
            hasattr(request.user, "cliente")
            or hasattr(request.user, "taller")
            or hasattr(request.user, "mecanico_domicilio")
        )


class CanManageOrder(BasePermission):
    """
    Permiso que permite gestionar órdenes según el rol del usuario
    """

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        # Los clientes pueden ver y gestionar sus propias órdenes
        if hasattr(request.user, "cliente"):
            return obj.cliente == request.user.cliente

        # Los proveedores pueden ver y gestionar órdenes asignadas a ellos
        if hasattr(request.user, "taller"):
            return obj.taller == request.user.taller
        elif hasattr(request.user, "mecanico_domicilio"):
            return obj.mecanico == request.user.mecanico_domicilio

        taller_sup = _taller_supervisado(request.user)
        if taller_sup is not None:
            return obj.taller_id == taller_sup.id

        # Los administradores pueden gestionar todas las órdenes
        return request.user.is_staff


class IsProveedorConMP(IsProveedor):
    """
    Permiso que exige: usuario autenticado + perfil de proveedor + cuenta MercadoPago conectada.
    Usado para bloquear acciones que requieren poder recibir/realizar pagos (crear ofertas,
    suscribirse a planes, etc.) si el proveedor no ha vinculado su cuenta de Mercado Pago.
    """

    message = (
        "Debes conectar tu cuenta de Mercado Pago antes de realizar esta acción. "
        "Ve a Configuración → Mercado Pago para vincularla."
    )

    def has_permission(self, request, view):
        # Primero verificar que sea un proveedor válido
        if not super().has_permission(request, view):
            return False

        # Luego verificar que tenga cuenta MP conectada
        try:
            cuenta_mp = request.user.cuenta_mercadopago
            if not cuenta_mp or cuenta_mp.estado != "conectada":
                logger.warning(
                    "Proveedor %s sin cuenta MP conectada (estado: %s)",
                    request.user.id,
                    cuenta_mp.estado if cuenta_mp else "sin cuenta",
                )
                return False
        except Exception:
            logger.warning(
                "Proveedor %s sin cuenta_mercadopago configurada",
                request.user.id,
            )
            return False

        return True
