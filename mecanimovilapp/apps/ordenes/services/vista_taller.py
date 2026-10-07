"""Saca fichas cerradas de las listas del taller.

Los agentes siguen leyendo las cotizaciones, los chats y la memoria.
Esta tabla solo dice qué dejó de mostrarse en Cotizaciones y Servicios.
"""
from __future__ import annotations

from django.db.models import QuerySet

from mecanimovilapp.apps.ordenes.models import (
    CitaAgendaPersonal,
    CotizacionCanal,
    OfertaProveedor,
    SolicitudServicio,
    VistaTallerOculta,
)

AMBITOS = (
    'cotizaciones_rechazadas',
    'cotizaciones_terminadas',
    'servicios_completados',
    'servicios_rechazados',
)

ESTADOS_COTIZACION_RECHAZADA = ('rechazada', 'expirada', 'cancelada')
ESTADOS_ORDEN_CERRADA = ('completado',)
ESTADOS_ORDEN_RECHAZADA = ('cancelado', 'rechazada_por_proveedor', 'devuelto')
ESTADOS_OFERTA_CERRADA = ('completada',)
ESTADOS_OFERTA_RECHAZADA = ('rechazada', 'retirada', 'expirada')


def ids_ocultos(taller_id: int, tipo: str) -> set[str]:
    return set(
        VistaTallerOculta.objects.filter(taller_id=taller_id, tipo=tipo)
        .values_list('objeto_id', flat=True)
    )


def excluir_ocultos(qs: QuerySet, taller_id: int | None, tipo: str) -> QuerySet:
    if not taller_id:
        return qs
    ids = ids_ocultos(taller_id, tipo)
    if not ids:
        return qs
    if tipo == VistaTallerOculta.TIPO_OFERTA:
        return qs.exclude(pk__in=list(ids))
    numeros = []
    for valor in ids:
        try:
            numeros.append(int(valor))
        except (TypeError, ValueError):
            continue
    if not numeros:
        return qs
    return qs.exclude(pk__in=numeros)


def cotizacion_se_puede_ocultar(cotizacion: CotizacionCanal) -> bool:
    if cotizacion.estado in ESTADOS_COTIZACION_RECHAZADA:
        return True
    if cotizacion.estado != 'aceptada':
        return False
    from mecanimovilapp.apps.ordenes.services.cotizacion_canal import cita_activa_de_cotizacion

    if cita_activa_de_cotizacion(cotizacion) is not None:
        return False
    return cotizacion.citas_generadas.filter(estado='cerrada').exists()


def cita_se_puede_ocultar(cita: CitaAgendaPersonal) -> bool:
    return cita.estado in ('cerrada', 'cancelada')


def orden_se_puede_ocultar(orden: SolicitudServicio) -> bool:
    return orden.estado in ESTADOS_ORDEN_CERRADA or orden.estado in ESTADOS_ORDEN_RECHAZADA


def oferta_se_puede_ocultar(oferta: OfertaProveedor) -> bool:
    return oferta.estado in ESTADOS_OFERTA_CERRADA or oferta.estado in ESTADOS_OFERTA_RECHAZADA


def _registrar(taller, tipo: str, objeto_id) -> bool:
    _, creado = VistaTallerOculta.objects.get_or_create(
        taller=taller,
        tipo=tipo,
        objeto_id=str(objeto_id),
    )
    return creado


def _ocultar_citas_cerradas_de(cotizacion: CotizacionCanal, taller) -> int:
    total = 0
    citas = CitaAgendaPersonal.objects.filter(
        cotizacion_canal_origen_id=cotizacion.id,
        estado__in=('cerrada', 'cancelada'),
    )
    for cita in citas:
        if _registrar(taller, VistaTallerOculta.TIPO_CITA, cita.id):
            total += 1
    return total


def ocultar_cotizacion(taller, cotizacion: CotizacionCanal) -> int:
    if cotizacion.taller_id != taller.id:
        raise ValueError('Esta cotización es de otro taller.')
    if not cotizacion_se_puede_ocultar(cotizacion):
        raise ValueError('Solo puedes quitar cotizaciones rechazadas o ya terminadas.')
    total = 1 if _registrar(taller, VistaTallerOculta.TIPO_COTIZACION, cotizacion.id) else 0
    total += _ocultar_citas_cerradas_de(cotizacion, taller)
    return total


def ocultar_cita(taller, cita: CitaAgendaPersonal) -> int:
    if cita.taller_id != taller.id:
        raise ValueError('Esta cita es de otro taller.')
    if not cita_se_puede_ocultar(cita):
        raise ValueError('Solo puedes quitar citas cerradas o canceladas.')
    return 1 if _registrar(taller, VistaTallerOculta.TIPO_CITA, cita.id) else 0


def ocultar_orden(taller, orden: SolicitudServicio) -> int:
    if orden.taller_id != taller.id:
        raise ValueError('Esta orden es de otro taller.')
    if not orden_se_puede_ocultar(orden):
        raise ValueError('Solo puedes quitar servicios completados o rechazados.')
    return 1 if _registrar(taller, VistaTallerOculta.TIPO_ORDEN, orden.id) else 0


def ocultar_oferta(taller, oferta: OfertaProveedor) -> int:
    if not oferta_se_puede_ocultar(oferta):
        raise ValueError('Solo puedes quitar ofertas completadas o rechazadas.')
    return 1 if _registrar(taller, VistaTallerOculta.TIPO_OFERTA, oferta.id) else 0


def _limpiar_ids(taller, tipo: str, ids) -> int:
    total = 0
    for objeto_id in ids:
        if _registrar(taller, tipo, objeto_id):
            total += 1
    return total


def limpiar_vista(taller, ambito: str) -> int:
    if ambito not in AMBITOS:
        raise ValueError('Esa lista no se puede limpiar.')
    if ambito == 'cotizaciones_rechazadas':
        qs = CotizacionCanal.objects.filter(
            taller=taller,
            estado__in=ESTADOS_COTIZACION_RECHAZADA,
        )
        total = 0
        for cotizacion in qs.iterator():
            total += ocultar_cotizacion(taller, cotizacion)
        return total
    if ambito == 'cotizaciones_terminadas':
        qs = CotizacionCanal.objects.filter(taller=taller, estado='aceptada')
        total = 0
        for cotizacion in qs.iterator():
            if not cotizacion_se_puede_ocultar(cotizacion):
                continue
            total += ocultar_cotizacion(taller, cotizacion)
        return total
    if ambito == 'servicios_completados':
        total = _limpiar_ids(
            taller,
            VistaTallerOculta.TIPO_CITA,
            CitaAgendaPersonal.objects.filter(taller=taller, estado='cerrada').values_list('id', flat=True),
        )
        total += _limpiar_ids(
            taller,
            VistaTallerOculta.TIPO_ORDEN,
            SolicitudServicio.objects.filter(taller=taller, estado__in=ESTADOS_ORDEN_CERRADA).values_list('id', flat=True),
        )
        total += _limpiar_ids(
            taller,
            VistaTallerOculta.TIPO_OFERTA,
            OfertaProveedor.objects.filter(
                proveedor_id=taller.usuario_id,
                estado__in=ESTADOS_OFERTA_CERRADA,
            ).values_list('id', flat=True),
        )
        return total
    total = _limpiar_ids(
        taller,
        VistaTallerOculta.TIPO_CITA,
        CitaAgendaPersonal.objects.filter(taller=taller, estado='cancelada').values_list('id', flat=True),
    )
    total += _limpiar_ids(
        taller,
        VistaTallerOculta.TIPO_ORDEN,
        SolicitudServicio.objects.filter(taller=taller, estado__in=ESTADOS_ORDEN_RECHAZADA).values_list('id', flat=True),
    )
    total += _limpiar_ids(
        taller,
        VistaTallerOculta.TIPO_OFERTA,
        OfertaProveedor.objects.filter(
            proveedor_id=taller.usuario_id,
            estado__in=ESTADOS_OFERTA_RECHAZADA,
        ).values_list('id', flat=True),
    )
    return total
