"""
Consultas de solicitudes públicas activas (anti-duplicado vehículo + servicio).
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence

from mecanimovilapp.apps.ordenes.models import SolicitudServicioPublica

# Pipeline donde el cliente ya tiene un pedido "en curso" para el mismo servicio/auto
ESTADOS_SOLICITUD_ACTIVA_DUPLICADO: tuple[str, ...] = (
    'creada',
    'seleccionando_servicios',
    'publicada',
    'con_ofertas',
    'pendiente_confirmacion',
    'esperando_creditos_proveedor',
    'adjudicada',
    'pendiente_pago',
    'pagada',
    'en_ejecucion',
)

MENSAJE_DUPLICADO_DEFAULT = (
    'Ya tienes una solicitud activa con este servicio para este vehículo. '
    'Revisa Mis solicitudes o espera a que finalice.'
)


def normalizar_servicio_ids(servicios: Iterable) -> list[int]:
    ids: list[int] = []
    for s in servicios:
        if s is None:
            continue
        if isinstance(s, int):
            ids.append(s)
            continue
        pk = getattr(s, 'pk', None) or getattr(s, 'id', None)
        if pk is not None:
            ids.append(int(pk))
    return list(dict.fromkeys(ids))


def buscar_solicitud_activa_mismo_servicio(
    cliente,
    vehiculo_id: int,
    servicio_ids: Sequence[int],
    *,
    exclude_pk=None,
) -> Optional[SolicitudServicioPublica]:
    """
    Primera solicitud del cliente con mismo vehículo y al menos un servicio en común,
    en estado de pipeline activo.
    """
    if not cliente or not vehiculo_id or not servicio_ids:
        return None

    qs = SolicitudServicioPublica.objects.filter(
        cliente=cliente,
        vehiculo_id=vehiculo_id,
        estado__in=ESTADOS_SOLICITUD_ACTIVA_DUPLICADO,
        servicios_solicitados__id__in=list(servicio_ids),
    ).distinct()

    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)

    return qs.order_by('-fecha_creacion').first()


def verificar_servicio_activo_duplicado(
    cliente,
    vehiculo_id: int,
    servicio_ids: Sequence[int],
    *,
    exclude_pk=None,
) -> dict:
    """
    Payload para API y validación de serializer.
    """
    ids = list(servicio_ids) if servicio_ids else []
    if not vehiculo_id or not ids:
        return {
            'bloqueado': False,
            'solicitud_id': None,
            'servicios_en_conflicto': [],
            'mensaje': None,
        }

    solicitud = buscar_solicitud_activa_mismo_servicio(
        cliente,
        vehiculo_id,
        ids,
        exclude_pk=exclude_pk,
    )
    if not solicitud:
        return {
            'bloqueado': False,
            'solicitud_id': None,
            'servicios_en_conflicto': [],
            'mensaje': None,
        }

    conflict_ids = list(
        solicitud.servicios_solicitados.filter(id__in=ids).values_list('id', flat=True)
    )
    return {
        'bloqueado': True,
        'solicitud_id': str(solicitud.pk),
        'estado': solicitud.estado,
        'servicios_en_conflicto': conflict_ids,
        'mensaje': MENSAJE_DUPLICADO_DEFAULT,
    }
