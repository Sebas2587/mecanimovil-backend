"""El teléfono de una casa de repuestos marca el contacto y el chat."""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework.exceptions import APIException

from mecanimovilapp.apps.omnichannel.models import ExternalContact
from mecanimovilapp.apps.ordenes.models import CotizacionCanal, ProveedorRepuestos
from mecanimovilapp.apps.ordenes.services.telefono_cl import normalizar_telefono, telefonos_coinciden


class RequiereConfirmacionCliente(APIException):
    status_code = 409
    default_detail = 'Este número ya es cliente.'
    default_code = 'requiere_confirmacion_cliente'


def _contactos_del_taller(taller):
    usuario_id = getattr(taller, 'usuario_id', None)
    if not usuario_id:
        return ExternalContact.objects.none()
    return ExternalContact.objects.filter(connection__usuario_id=usuario_id).select_related('connection')


def contactos_por_telefono(taller, telefono: str):
    objetivo = normalizar_telefono(telefono)
    if not objetivo:
        return []
    encontrados = []
    for contact in _contactos_del_taller(taller):
        candidatos = (
            contact.phone or '',
            contact.telefono_efectivo() or '',
            contact.external_id or '',
        )
        if any(telefonos_coinciden(objetivo, raw) for raw in candidatos):
            encontrados.append(contact)
    return encontrados


def servicios_concretados(contact: ExternalContact) -> int:
    return CotizacionCanal.objects.filter(
        conversation__external_contact=contact,
        estado='aceptada',
    ).count()


def assert_puede_marcar_telefono(taller, telefono: str, *, confirmar: bool, excluir_id: int | None = None) -> None:
    norm = normalizar_telefono(telefono)
    if not norm:
        return
    otras = ProveedorRepuestos.objects.filter(taller=taller, activo=True, telefono_norm=norm)
    if excluir_id:
        otras = otras.exclude(pk=excluir_id)
    if otras.exists():
        from rest_framework.exceptions import ValidationError
        raise ValidationError({'telefono': 'Ya hay una casa activa con este teléfono.'})
    if confirmar:
        return
    for contact in contactos_por_telefono(taller, norm):
        concretados = servicios_concretados(contact)
        if concretados >= 1 or contact.rol in (
            ExternalContact.ROL_CLIENTE_NUEVO,
            ExternalContact.ROL_CLIENTE_RECURRENTE,
        ):
            raise RequiereConfirmacionCliente(detail={
                'code': 'requiere_confirmacion_cliente',
                'detail': (
                    'Este número ya es cliente'
                    + (f' ({concretados} servicio{"s" if concretados != 1 else ""} concretado{"s" if concretados != 1 else ""}).' if concretados else '.')
                    + ' Confirma para marcarlo como casa de repuestos. El historial del chat se conserva.'
                ),
                'servicios': concretados,
            })


def aplicar_marca_casa(proveedor: ProveedorRepuestos) -> int:
    """Marca los chats de ese teléfono como casa de repuestos. Devuelve cuántos contactos."""
    if not proveedor.activo or not proveedor.telefono_norm:
        return 0
    marcados = 0
    primero = None
    for contact in contactos_por_telefono(proveedor.taller, proveedor.telefono_norm):
        contact.rol = ExternalContact.ROL_CASA_REPUESTOS
        contact.rol_manual = True
        contact.rol_sugerido = ''
        contact.save(update_fields=['rol', 'rol_manual', 'rol_sugerido', 'updated_at'])
        marcados += 1
        primero = primero or contact
    if primero is not None and proveedor.external_contact_id != primero.id:
        proveedor.external_contact = primero
        proveedor.save(update_fields=['external_contact', 'actualizado_en'])
    return marcados


def soltar_telefono(taller, telefono_norm: str, *, excepto_proveedor_id: int | None = None) -> None:
    norm = normalizar_telefono(telefono_norm)
    if not norm:
        return
    otras = ProveedorRepuestos.objects.filter(taller=taller, activo=True, telefono_norm=norm)
    if excepto_proveedor_id:
        otras = otras.exclude(pk=excepto_proveedor_id)
    if otras.exists():
        return
    for contact in contactos_por_telefono(taller, norm):
        if contact.rol != ExternalContact.ROL_CASA_REPUESTOS:
            continue
        contact.rol = ExternalContact.ROL_SIN_CLASIFICAR
        contact.rol_manual = False
        contact.rol_sugerido = ''
        contact.save(update_fields=['rol', 'rol_manual', 'rol_sugerido', 'updated_at'])
    ProveedorRepuestos.objects.filter(taller=taller, telefono_norm=norm).update(external_contact=None)


def asegurar_rol_reservado(contact: ExternalContact) -> ExternalContact:
    """Si el teléfono ya es una casa guardada, el hilo nace marcado."""
    if contact.rol_manual and contact.rol not in ('', ExternalContact.ROL_SIN_CLASIFICAR):
        return contact
    usuario_id = contact.connection.usuario_id
    if not usuario_id:
        return contact
    candidatos = (
        contact.phone or '',
        contact.telefono_efectivo() or '',
        contact.external_id or '',
    )
    casas = ProveedorRepuestos.objects.filter(
        activo=True,
        taller__usuario_id=usuario_id,
    ).exclude(telefono_norm='')
    for casa in casas:
        if any(telefonos_coinciden(casa.telefono_norm, raw) for raw in candidatos):
            contact.rol = ExternalContact.ROL_CASA_REPUESTOS
            contact.rol_manual = True
            contact.rol_sugerido = ''
            contact.save(update_fields=['rol', 'rol_manual', 'rol_sugerido', 'updated_at'])
            if casa.external_contact_id is None:
                casa.external_contact = contact
                casa.save(update_fields=['external_contact', 'actualizado_en'])
            break
    return contact


def refrescar_rol_por_historial(contact: ExternalContact | None) -> None:
    """Cliente nuevo, recurrente o sugerencia de solo consulta. No pisa un rol manual."""
    if contact is None or contact.rol_manual:
        return
    if contact.rol == ExternalContact.ROL_CASA_REPUESTOS:
        return
    concretados = servicios_concretados(contact)
    if concretados >= 2:
        contact.rol = ExternalContact.ROL_CLIENTE_RECURRENTE
        contact.rol_sugerido = ''
        contact.save(update_fields=['rol', 'rol_sugerido', 'updated_at'])
        return
    if concretados == 1:
        contact.rol = ExternalContact.ROL_CLIENTE_NUEVO
        contact.rol_sugerido = ''
        contact.save(update_fields=['rol', 'rol_sugerido', 'updated_at'])
        return
    desde = timezone.now() - timedelta(days=30)
    conversaciones = contact.conversations.filter(updated_at__gte=desde).count()
    if (
        conversaciones >= 2
        and contact.rol in ('', ExternalContact.ROL_SIN_CLASIFICAR)
        and contact.rol_sugerido != ExternalContact.ROL_CASA_REPUESTOS
    ):
        contact.rol_sugerido = ExternalContact.ROL_SOLO_CONSULTA
        contact.save(update_fields=['rol_sugerido', 'updated_at'])


_FRASES_PROVEEDOR = (
    'sin stock',
    'no hay stock',
    'tenemos en stock',
    'tenemos stock',
    'precio neto',
    'valor neto',
    'neto + iva',
    'neto mas iva',
    'neto más iva',
    'lista de precios',
    'despachamos',
    'retiro en mostrador',
    'retirar en mostrador',
    'adjunto cotizacion',
    'adjunto cotización',
    'cotizacion adjunta',
    'cotización adjunta',
    'te cotizo',
    'les cotizo',
)


def parece_texto_de_proveedor(texto: str) -> bool:
    """True si el mensaje suena a una casa de repuestos, no a un cliente."""
    plano = (texto or '').casefold()
    if len(plano.strip()) < 12:
        return False
    return any(frase in plano for frase in _FRASES_PROVEEDOR)


def marcar_sugerencia_casa(contact: ExternalContact, usuario_id: int) -> None:
    """Pide al taller etiquetar. No cambia el rol ni le escribe al contacto."""
    if contact.rol_manual or contact.rol not in ('', ExternalContact.ROL_SIN_CLASIFICAR):
        return
    if contact.rol_sugerido != ExternalContact.ROL_CASA_REPUESTOS:
        contact.rol_sugerido = ExternalContact.ROL_CASA_REPUESTOS
        contact.save(update_fields=['rol_sugerido', 'updated_at'])
    if not usuario_id:
        return
    from django.contrib.auth import get_user_model

    from mecanimovilapp.apps.usuarios.models import Notificacion
    from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification

    usuario = get_user_model().objects.filter(pk=usuario_id).first()
    if usuario is None:
        return
    nombre = (contact.display_name or contact.phone or 'Este número').strip()
    titulo = 'Parece una casa de repuestos'
    mensaje = (
        f'{nombre} escribió como proveedor. '
        'Márcalo en el chat para que el agente no le venda un servicio.'
    )
    data = {'type': 'rol_casa_sugerida', 'contact_id': str(contact.id)}
    Notificacion.crear_unica(
        usuario,
        tipo='system',
        titulo=titulo,
        mensaje=mensaje,
        data=data,
        ventana_horas=24,
        dedup_key={'type': 'rol_casa_sugerida', 'contact_id': str(contact.id)},
    )
    try:
        send_expo_push_notification.delay(usuario_id, titulo, mensaje, data)
    except Exception:
        pass
