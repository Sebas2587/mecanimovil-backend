"""Sincroniza estado de sesión del agente con el ciclo de vida de CotizacionCanal."""
from __future__ import annotations

from mecanimovilapp.apps.agente_ia.models import AgenteConversacionSesion
from mecanimovilapp.apps.ordenes.models import CotizacionCanal

_ESTADOS_NO_PISAR_AL_ENVIAR = (
    AgenteConversacionSesion.ESTADO_AGENDANDO,
    AgenteConversacionSesion.ESTADO_PAUSADO,
    AgenteConversacionSesion.ESTADO_CERRADO,
    AgenteConversacionSesion.ESTADO_COORDINACION_TERRENO,
)


def liberar_sesiones_tras_cerrar_borrador(cotizacion: CotizacionCanal) -> int:
    """Tras un cambio de estado de la cotización, alinea las sesiones ligadas.

    - `enviada` + hay chat → `esperando_aceptacion` (ya no vuelve a capturando).
    - cancelada / rechazada / otro cierre → `capturando`.
    - `borrador` → no toca.
    """
    if cotizacion.estado == 'borrador':
        return 0

    qs = AgenteConversacionSesion.objects.filter(cotizacion_borrador=cotizacion)
    if cotizacion.estado == 'enviada' and cotizacion.conversation_id:
        return qs.exclude(estado__in=_ESTADOS_NO_PISAR_AL_ENVIAR).update(
            estado=AgenteConversacionSesion.ESTADO_ESPERANDO_ACEPTACION,
        )
    return qs.filter(
        estado__in=(
            AgenteConversacionSesion.ESTADO_ESPERANDO_REVISION,
            AgenteConversacionSesion.ESTADO_ESPERANDO_ACEPTACION,
        ),
    ).update(estado=AgenteConversacionSesion.ESTADO_CAPTURANDO)


def promover_sesion_si_cotizacion_enviada(sesion: AgenteConversacionSesion) -> AgenteConversacionSesion:
    """Sesiones viejas en capturando con coti ya enviada: subir a esperando_aceptacion."""
    if sesion.estado in (
        AgenteConversacionSesion.ESTADO_ESPERANDO_ACEPTACION,
        AgenteConversacionSesion.ESTADO_AGENDANDO,
        AgenteConversacionSesion.ESTADO_PAUSADO,
        AgenteConversacionSesion.ESTADO_CERRADO,
        AgenteConversacionSesion.ESTADO_COORDINACION_TERRENO,
        AgenteConversacionSesion.ESTADO_ELIGIENDO_REPUESTOS,
    ):
        return sesion

    cot = getattr(sesion, 'cotizacion_borrador', None)
    if cot is None or cot.estado != 'enviada':
        conv_id = getattr(sesion, 'conversation_id', None)
        cot = None
        if conv_id:
            cot = (
                CotizacionCanal.objects.filter(
                    conversation_id=conv_id,
                    estado='enviada',
                    es_cotizacion_adicional=False,
                )
                .order_by('-enviada_en', '-id')
                .first()
            )
    if cot is None:
        return sesion
    sesion.estado = AgenteConversacionSesion.ESTADO_ESPERANDO_ACEPTACION
    datos = dict(sesion.datos_capturados or {})
    datos['cotizacion_enviada_id'] = cot.id
    sesion.datos_capturados = datos
    sesion.save(update_fields=['estado', 'datos_capturados', 'actualizado_en'])
    return sesion
