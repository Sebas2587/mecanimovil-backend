"""Soft-delete y anonimización de cuenta (Ley 21.719 art. 7)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone
from rest_framework.authtoken.models import Token

from mecanimovilapp.apps.ordenes.models import SolicitudServicio
from mecanimovilapp.apps.pagos.models import LiquidacionProveedor
from mecanimovilapp.apps.usuarios.models import (
    Cliente,
    DireccionUsuario,
    PushToken,
    Taller,
    Usuario,
    WebPushSubscription,
)


ORDENES_ACTIVAS = {
    'pendiente',
    'pago_validado',
    'confirmado',
    'pendiente_aceptacion_proveedor',
    'aceptada_por_proveedor',
    'checklist_en_progreso',
    'checklist_completado',
    'en_proceso',
    'pendiente_firma_cliente',
    'solicitud_cancelacion',
    'pendiente_devolucion',
}

LIQUIDACIONES_PENDIENTES = {'pendiente', 'procesada'}


@dataclass
class AccountDeletionBlock:
    code: str
    message: str


def _usuario_tiene_taller(usuario: Usuario) -> bool:
    return Taller.objects.filter(usuario=usuario).exists()


def verificar_puede_eliminar_cuenta(usuario: Usuario) -> AccountDeletionBlock | None:
    if usuario.deleted_at is not None:
        return AccountDeletionBlock(
            code='already_deleted',
            message='Esta cuenta ya fue eliminada.',
        )

    if usuario.es_mecanico and _usuario_tiene_taller(usuario):
        return AccountDeletionBlock(
            code='provider_assisted',
            message=(
                'Las cuentas de proveedor con taller activo requieren baja asistida. '
                'Contacta a soporte@mecanimovil.cl para cerrar tu cuenta de forma segura.'
            ),
        )

    cliente = getattr(usuario, 'cliente', None)
    if cliente is not None:
        activas = SolicitudServicio.objects.filter(
            cliente=cliente,
            estado__in=ORDENES_ACTIVAS,
        ).exists()
        if activas:
            return AccountDeletionBlock(
                code='active_orders',
                message=(
                    'Tienes órdenes o servicios en curso. '
                    'Finalízalos o cancélalos antes de eliminar tu cuenta.'
                ),
            )

    liq_pendiente = LiquidacionProveedor.objects.filter(
        usuario=usuario,
        estado__in=LIQUIDACIONES_PENDIENTES,
    ).exists()
    if liq_pendiente:
        return AccountDeletionBlock(
            code='pending_settlement',
            message=(
                'Tienes liquidaciones pendientes. '
                'Espera a que se procesen antes de eliminar tu cuenta.'
            ),
        )

    return None


def _anonimizar_cliente(cliente: Cliente) -> None:
    suffix = uuid.uuid4().hex[:12]
    cliente.nombre = 'Usuario'
    cliente.apellido = 'Eliminado'
    cliente.email = f'deleted-{suffix}@anon.mecanimovil.local'
    cliente.telefono = None
    cliente.direccion = None
    cliente.ubicacion = None
    cliente.save(
        update_fields=['nombre', 'apellido', 'email', 'telefono', 'direccion', 'ubicacion'],
    )


@transaction.atomic
def eliminar_cuenta_usuario(usuario: Usuario, *, password: str | None = None) -> None:
    bloqueo = verificar_puede_eliminar_cuenta(usuario)
    if bloqueo is not None:
        raise ValueError(bloqueo.message)

    if password is not None and not usuario.check_password(password):
        raise ValueError('La contraseña es incorrecta.')

    ahora = timezone.now()
    suffix = uuid.uuid4().hex[:12]

    if usuario.foto_perfil:
        try:
            usuario.foto_perfil.delete(save=False)
        except Exception:
            pass

    usuario.email = f'deleted-{suffix}@anon.mecanimovil.local'
    usuario.first_name = ''
    usuario.last_name = ''
    usuario.telefono = None
    usuario.direccion = None
    usuario.foto_perfil = None
    usuario.expo_push_token = None
    usuario.password_reset_token = None
    usuario.password_reset_token_expires = None
    usuario.username = f'deleted_{usuario.pk}_{suffix}'
    usuario.set_unusable_password()
    usuario.is_active = False
    usuario.deleted_at = ahora
    usuario.anonymized_at = ahora
    usuario.save()

    try:
        cliente = usuario.cliente
    except Cliente.DoesNotExist:
        cliente = None
    if cliente is not None:
        _anonimizar_cliente(cliente)

    DireccionUsuario.objects.filter(usuario=usuario).delete()
    PushToken.objects.filter(usuario=usuario).update(activo=False)
    WebPushSubscription.objects.filter(usuario=usuario).update(activo=False)
    Token.objects.filter(user=usuario).delete()
