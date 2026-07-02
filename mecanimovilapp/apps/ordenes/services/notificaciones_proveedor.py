"""Notificaciones push dirigidas a proveedores (Expo + Web Push)."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

ESTADOS_OFERTA_ACTIVA_PROVEEDOR = (
    'enviada',
    'vista',
    'en_chat',
    'pendiente_confirmacion',
    'pendiente_creditos',
    'aceptada',
)


def resolver_usuario_proveedor_orden(orden) -> int | None:
    """Resuelve el user_id del proveedor responsable de una SolicitudServicio."""
    if getattr(orden, 'oferta_proveedor_id', None) and orden.oferta_proveedor_id:
        return orden.oferta_proveedor.proveedor_id
    if getattr(orden, 'taller_id', None) and orden.taller_id and orden.taller.usuario_id:
        return orden.taller.usuario_id
    if getattr(orden, 'mecanico_id', None) and orden.mecanico_id and orden.mecanico.usuario_id:
        return orden.mecanico.usuario_id
    return None


def _vehiculo_label(orden) -> str:
    vehiculo = getattr(orden, 'vehiculo', None)
    if not vehiculo:
        return 'tu servicio'
    marca = getattr(getattr(vehiculo, 'marca', None), 'nombre', '') or ''
    modelo = getattr(getattr(vehiculo, 'modelo', None), 'nombre', '') or ''
    label = f'{marca} {modelo}'.strip()
    if label:
        return label
    patente = getattr(vehiculo, 'patente', '') or ''
    return patente or 'tu servicio'


def notificar_checklist_pendiente_proveedor(orden, checklist_instance) -> None:
    """Encola push al proveedor cuando hay checklist PENDIENTE por completar."""
    from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification

    user_id = resolver_usuario_proveedor_orden(orden)
    vehiculo_label = _vehiculo_label(orden)
    solicitud_id = ''
    if getattr(orden, 'oferta_proveedor_id', None) and orden.oferta_proveedor_id:
        solicitud_id = str(orden.oferta_proveedor.solicitud_id)

    payload = {
        'type': 'checklist_pendiente',
        'orden_id': str(orden.id),
        'checklist_id': str(checklist_instance.id),
        'solicitud_id': solicitud_id,
    }
    titulo = 'Completa el checklist del servicio'
    cuerpo = (
        f'Tienes un checklist pendiente para {vehiculo_label}. '
        'Ábrelo y complétalo antes de continuar.'
    )

    mecanico_asignado = getattr(orden, 'mecanico_asignado', None)
    mecanico_user_id = None
    if mecanico_asignado is not None and mecanico_asignado.usuario_id:
        mecanico_user_id = mecanico_asignado.usuario_id

    destinatarios: list[int] = []
    if mecanico_user_id:
        destinatarios.append(mecanico_user_id)
    if user_id and user_id not in destinatarios:
        destinatarios.append(user_id)

    if not destinatarios:
        logger.debug('[checklist_pendiente] Sin proveedor para orden %s', getattr(orden, 'id', None))
        return

    for uid in destinatarios:
        try:
            send_expo_push_notification.delay(uid, titulo, cuerpo, payload)
        except Exception as exc:
            logger.error('[checklist_pendiente] Error encolando push orden %s user %s: %s', orden.id, uid, exc)


def notificar_orden_asignada_mecanico(orden, miembro) -> None:
    """Encola push al mecánico cuando se le asigna una orden."""
    from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification

    if miembro is None or not getattr(miembro, 'usuario_id', None):
        return
    if not getattr(miembro, 'activo', True):
        return

    vehiculo_label = _vehiculo_label(orden)
    solicitud_id = ''
    if getattr(orden, 'oferta_proveedor_id', None) and orden.oferta_proveedor_id:
        solicitud_id = str(orden.oferta_proveedor.solicitud_id)

    try:
        send_expo_push_notification.delay(
            miembro.usuario_id,
            'Nueva orden asignada',
            f'Se te asignó un servicio para {vehiculo_label}. Revisa los detalles y el checklist.',
            {
                'type': 'orden_asignada_mecanico',
                'orden_id': str(orden.id),
                'solicitud_id': solicitud_id,
                'miembro_id': str(miembro.id),
            },
        )
    except Exception as exc:
        logger.error(
            '[orden_asignada_mecanico] Error encolando push orden %s mecanico %s: %s',
            getattr(orden, 'id', None),
            getattr(miembro, 'id', None),
            exc,
        )


def obtener_proveedores_elegibles_solicitud(solicitud):
    """
    Proveedores verificados/activos compatibles con marca y servicios de la solicitud.
    Misma lógica que SolicitudServicioPublicaViewSet._obtener_proveedores_para_notificar.
    """
    from mecanimovilapp.apps.servicios.models import OfertaServicio
    from mecanimovilapp.apps.usuarios.models import Usuario

    if not solicitud.vehiculo:
        return Usuario.objects.none()

    marca_vehiculo = solicitud.vehiculo.marca
    if not marca_vehiculo:
        return Usuario.objects.none()

    proveedores_base = Usuario.objects.filter(
        Q(taller__marcas_atendidas=marca_vehiculo)
        | Q(mecanico_domicilio__marcas_atendidas=marca_vehiculo)
    ).filter(
        Q(taller__verificado=True, taller__activo=True)
        | Q(mecanico_domicilio__verificado=True, mecanico_domicilio__activo=True)
    ).select_related('taller', 'mecanico_domicilio').distinct()

    servicios_solicitados = solicitud.servicios_solicitados.all()
    if servicios_solicitados.exists():
        proveedores_con_ofertas = OfertaServicio.objects.filter(
            servicio__in=servicios_solicitados,
            disponible=True,
        ).filter(
            Q(marca_vehiculo_seleccionada=marca_vehiculo)
            | Q(marca_vehiculo_seleccionada__isnull=True)
        ).filter(
            Q(taller__verificado=True, taller__activo=True)
            | Q(mecanico__verificado=True, mecanico__activo=True)
        ).values_list('taller__usuario_id', 'mecanico__usuario_id')

        ids = set()
        for taller_uid, mec_uid in proveedores_con_ofertas:
            if taller_uid:
                ids.add(taller_uid)
            if mec_uid:
                ids.add(mec_uid)
        if ids:
            proveedores_base = proveedores_base.filter(id__in=ids)

    return proveedores_base


def _solicitud_vehiculo_label(solicitud) -> str:
    v = solicitud.vehiculo
    if not v:
        return 'Nueva oportunidad'
    marca = getattr(v.marca, 'nombre', str(v.marca)) if v.marca else ''
    modelo = getattr(v.modelo, 'nombre', str(v.modelo)) if v.modelo else ''
    return f'{marca} {modelo}'.strip() or 'Nueva oportunidad'


def recordar_solicitudes_por_vencer_proveedor() -> dict:
    """
    Alerta a proveedores elegibles cuando una solicitud está por expirar.
    Ventana: entre 30 y 60 minutos antes de fecha_expiracion.
    """
    from mecanimovilapp.apps.ordenes.models import OfertaProveedor, SolicitudServicioPublica
    from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification

    ahora = timezone.now()
    ventana_inicio = ahora + timedelta(minutes=30)
    ventana_fin = ahora + timedelta(minutes=60)

    enviados = 0

    # Caso A: solicitudes abiertas (sin oferta activa del proveedor)
    solicitudes_abiertas = SolicitudServicioPublica.objects.filter(
        estado__in=['publicada', 'con_ofertas'],
        fecha_expiracion__gte=ventana_inicio,
        fecha_expiracion__lte=ventana_fin,
    ).select_related('vehiculo__marca', 'vehiculo__modelo')

    for solicitud in solicitudes_abiertas:
        proveedores = obtener_proveedores_elegibles_solicitud(solicitud)
        if solicitud.tipo_solicitud == 'dirigida':
            proveedores = solicitud.proveedores_dirigidos.filter(
                id__in=proveedores.values_list('id', flat=True)
            )

        vehiculo_label = _solicitud_vehiculo_label(solicitud)
        minutos = max(1, int((solicitud.fecha_expiracion - ahora).total_seconds() / 60))

        for proveedor in proveedores:
            tiene_oferta = OfertaProveedor.objects.filter(
                solicitud=solicitud,
                proveedor=proveedor,
                estado__in=ESTADOS_OFERTA_ACTIVA_PROVEEDOR,
            ).exists()
            if tiene_oferta:
                continue

            try:
                send_expo_push_notification.delay(
                    proveedor.id,
                    'Solicitud por vencer',
                    f'Quedan ~{minutos} min para responder: {vehiculo_label}',
                    {
                        'type': 'solicitud_por_vencer',
                        'solicitud_id': str(solicitud.id),
                        'minutos_restantes': str(minutos),
                    },
                )
                enviados += 1
            except Exception as exc:
                logger.error(
                    '[solicitud_por_vencer] Error push solicitud %s proveedor %s: %s',
                    solicitud.id,
                    proveedor.id,
                    exc,
                )

    # Caso B: catálogo pendiente confirmación del proveedor
    catalogo_pendiente = SolicitudServicioPublica.objects.filter(
        estado='pendiente_confirmacion',
        fecha_expiracion__gte=ventana_inicio,
        fecha_expiracion__lte=ventana_fin,
        oferta_seleccionada__isnull=False,
    ).select_related('oferta_seleccionada__proveedor', 'vehiculo__marca', 'vehiculo__modelo')

    for solicitud in catalogo_pendiente:
        oferta = solicitud.oferta_seleccionada
        if not oferta or not oferta.proveedor_id:
            continue
        minutos = max(1, int((solicitud.fecha_expiracion - ahora).total_seconds() / 60))
        vehiculo_label = _solicitud_vehiculo_label(solicitud)
        try:
            send_expo_push_notification.delay(
                oferta.proveedor_id,
                'Confirma la asignación pronto',
                f'Tienes ~{minutos} min para confirmar: {vehiculo_label}',
                {
                    'type': 'solicitud_por_vencer',
                    'solicitud_id': str(solicitud.id),
                    'oferta_id': str(oferta.id),
                    'minutos_restantes': str(minutos),
                },
            )
            enviados += 1
        except Exception as exc:
            logger.error(
                '[solicitud_por_vencer] Error push catálogo solicitud %s: %s',
                solicitud.id,
                exc,
            )

    return {'enviados': enviados}
