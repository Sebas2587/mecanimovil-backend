"""Sincroniza estado de sesión del agente con el ciclo de vida de CotizacionCanal."""
from __future__ import annotations

from mecanimovilapp.apps.agente_ia.models import AgenteConversacionSesion
from mecanimovilapp.apps.ordenes.models import CotizacionCanal


def liberar_sesiones_tras_cerrar_borrador(cotizacion: CotizacionCanal) -> int:
    """Si el borrador ya no está pendiente, saca sesiones de 'esperando revisión'."""
    if cotizacion.estado == 'borrador':
        return 0
    return AgenteConversacionSesion.objects.filter(
        cotizacion_borrador=cotizacion,
        estado=AgenteConversacionSesion.ESTADO_ESPERANDO_REVISION,
    ).update(estado=AgenteConversacionSesion.ESTADO_CAPTURANDO)
