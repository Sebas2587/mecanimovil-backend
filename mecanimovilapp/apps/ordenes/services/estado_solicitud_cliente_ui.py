"""
Estado efectivo de SolicitudServicioPublica para la app del cliente.

Centraliza la lógica que antes solo existía en el frontend: pago parcial,
servicio en curso con saldo pendiente y pendiente de firma del cliente (orden
en `pendiente_firma_cliente` con pago completo).
"""
from __future__ import annotations

from typing import Optional

# Estados derivados solo para UI (no se persisten en SolicitudServicioPublica.estado).
ESTADOS_DERIVADOS_UI = frozenset({
    'pagada_parcialmente',
    'en_ejecucion_pago_pendiente',
    'pendiente_firma_cliente',
    'ofertas_adicionales_pendientes',
})

DISPLAY_EFECTIVO = {
    'ofertas_adicionales_pendientes': 'Ofertas adicionales por revisar',
    'pagada_parcialmente': 'Pago parcial',
    'en_ejecucion_pago_pendiente': 'En curso · saldo pendiente',
    'pendiente_firma_cliente': 'Pendiente de tu firma',
    'creada': 'Creada',
    'seleccionando_servicios': 'Seleccionando Servicios',
    'publicada': 'Publicada',
    'con_ofertas': 'Con Ofertas',
    'pendiente_confirmacion': 'Pendiente confirmación del proveedor',
    'esperando_creditos_proveedor': 'Esperando confirmación del proveedor (créditos)',
    'adjudicada': 'Adjudicada',
    'pendiente_pago': 'Pendiente de Pago',
    'pagada': 'Pagada',
    'en_ejecucion': 'Servicio en curso',
    'completada': 'Completada',
    'expirada': 'Expirada',
    'cancelada': 'Cancelada',
}


def tiene_pago_parcial(oferta) -> bool:
    if not oferta:
        return False
    repuestos_pagados = getattr(oferta, 'estado_pago_repuestos', None) == 'pagado'
    servicio_pendiente = (getattr(oferta, 'estado_pago_servicio', None) or 'pendiente') == 'pendiente'
    return repuestos_pagados and servicio_pendiente


def _orden_de_oferta(oferta):
    if not oferta:
        return None
    cache = getattr(oferta, '_prefetched_objects_cache', None) or {}
    if 'solicitudes_servicio' in cache:
        ordenes = cache['solicitudes_servicio']
        if not ordenes:
            return None
        return max(ordenes, key=lambda o: o.id)
    return oferta.solicitudes_servicio.order_by('-id').first()


def _checklist_orden(orden):
    if not orden:
        return None
    cache = getattr(orden, '_prefetched_objects_cache', None) or {}
    if 'checklistinstance_set' in cache:
        items = cache['checklistinstance_set']
        return items[0] if items else None
    try:
        from mecanimovilapp.apps.checklists.models import ChecklistInstance
        return ChecklistInstance.objects.filter(orden=orden).order_by('-id').first()
    except Exception:
        return None


def compute_estado_efectivo_cliente(
    solicitud,
    *,
    tiene_ofertas_secundarias_pendientes: bool = False,
) -> str:
    """Clave de estado para badges/listas en la app del cliente."""
    if tiene_ofertas_secundarias_pendientes:
        return 'ofertas_adicionales_pendientes'

    estado = solicitud.estado
    oferta = getattr(solicitud, 'oferta_seleccionada', None)
    parcial = tiene_pago_parcial(oferta)
    orden = _orden_de_oferta(oferta)
    checklist = _checklist_orden(orden)

    # La orden marketplace manda sobre solicitud/oferta desfasadas en BD.
    if orden and orden.estado == 'completado':
        return 'completada'
    if checklist and checklist.estado == 'COMPLETADO':
        return 'completada'
    if oferta and getattr(oferta, 'estado', None) == 'completada':
        return 'completada'
    if estado == 'completada':
        return 'completada'

    if parcial and estado == 'pagada':
        return 'pagada_parcialmente'

    if (
        orden
        and orden.estado == 'pendiente_firma_cliente'
        and not parcial
        and (getattr(oferta, 'estado_pago_servicio', None) or 'pendiente') == 'pagado'
    ):
        return 'pendiente_firma_cliente'

    if checklist and checklist.estado == 'PENDIENTE_FIRMA_CLIENTE':
        return 'pendiente_firma_cliente'

    if parcial and (estado == 'en_ejecucion' or getattr(oferta, 'estado', None) == 'en_ejecucion'):
        return 'en_ejecucion_pago_pendiente'

    return estado


def compute_estado_display_efectivo_cliente(
    solicitud,
    estado_efectivo: Optional[str] = None,
) -> str:
    """Texto legible del estado efectivo."""
    efectivo = estado_efectivo or compute_estado_efectivo_cliente(solicitud)
    if efectivo in DISPLAY_EFECTIVO:
        return DISPLAY_EFECTIVO[efectivo]
    return str(efectivo).replace('_', ' ').title()
