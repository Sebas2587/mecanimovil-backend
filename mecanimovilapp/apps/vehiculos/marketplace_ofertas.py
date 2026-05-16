"""
Reglas de negocio para OfertaVehiculo (marketplace entre usuarios).
"""
from .models import OfertaVehiculo

# Estados que bloquean enviar otra oferta del mismo comprador al mismo vendedor.
ESTADOS_OFERTA_BLOQUEANTES = ('pendiente', 'contraoferta', 'aceptada')

MENSAJE_OFERTA_ACTIVA_MISMO_VENDEDOR = (
    'No puedes enviar más ofertas a este vendedor hasta que acepte o rechace tu oferta activa.'
)


def comprador_tiene_oferta_activa_con_vendedor(comprador_id, vendedor_usuario_id, excluir_oferta_id=None):
    """True si el comprador ya tiene una oferta bloqueante hacia ese vendedor."""
    if not comprador_id or not vendedor_usuario_id:
        return False
    qs = OfertaVehiculo.objects.filter(
        comprador_id=comprador_id,
        vehiculo__cliente__usuario_id=vendedor_usuario_id,
        estado__in=ESTADOS_OFERTA_BLOQUEANTES,
    )
    if excluir_oferta_id:
        qs = qs.exclude(pk=excluir_oferta_id)
    return qs.exists()


def vendedor_id_desde_vehiculo(vehiculo):
    if vehiculo is None:
        return None
    cliente = getattr(vehiculo, 'cliente', None)
    if cliente is None:
        return None
    usuario = getattr(cliente, 'usuario', None)
    return getattr(usuario, 'id', None) if usuario else None
