"""
Helpers compartidos para adjudicación pública y carrito (evita imports circulares con views).
"""
import logging

from mecanimovilapp.apps.ordenes.models import CarritoAgendamiento, ChatSolicitud

logger = logging.getLogger(__name__)


def obtener_o_crear_carrito(cliente, vehiculo):
    """
    Obtiene o crea un carrito activo para el cliente y vehículo.
    Si ya existe un carrito activo para ese vehículo, lo retorna.
    Si no existe, crea uno nuevo.
    """
    carrito = CarritoAgendamiento.objects.filter(
        cliente=cliente,
        vehiculo=vehiculo,
        activo=True
    ).first()

    if carrito:
        logger.info(f"Carrito existente encontrado: {carrito.id}")
        return carrito

    CarritoAgendamiento.objects.filter(
        cliente=cliente,
        activo=True
    ).update(activo=False)

    carrito = CarritoAgendamiento.objects.create(
        cliente=cliente,
        vehiculo=vehiculo,
        activo=True
    )
    logger.info(f"Carrito nuevo creado: {carrito.id}")

    return carrito


def crear_chat_inicial_oferta(oferta, solicitud):
    """
    Crea un mensaje inicial en el chat mostrando la solicitud original.
    Este mensaje se envía automáticamente cuando se acepta una oferta.
    """
    servicios_nombres = list(solicitud.servicios_solicitados.values_list('nombre', flat=True))
    servicios_texto = ", ".join(servicios_nombres) if servicios_nombres else "Servicios varios"

    mensaje_parts = [
        "¡Hola! He aceptado tu oferta para mi solicitud de servicio.",
        "",
        "📋 **Detalles de la solicitud original:**",
        f"• Descripción: {solicitud.descripcion_problema or 'Sin descripción adicional'}",
        f"• Servicios: {servicios_texto}",
        f"• Ubicación: {solicitud.direccion_servicio_texto or 'Ubicación no especificada'}",
        f"• Fecha preferida: {solicitud.fecha_preferida.strftime('%d/%m/%Y') if solicitud.fecha_preferida else 'No especificada'}",
    ]

    if solicitud.hora_preferida:
        mensaje_parts.append(f"• Hora preferida: {solicitud.hora_preferida.strftime('%H:%M')}")

    if solicitud.detalles_ubicacion:
        mensaje_parts.append(f"• Detalles adicionales: {solicitud.detalles_ubicacion}")

    mensaje_parts.extend([
        "",
        "Puedes contactarme a través de este chat para coordinar los detalles del servicio.",
    ])

    mensaje = "\n".join(mensaje_parts)

    chat_mensaje = ChatSolicitud.objects.create(
        oferta=oferta,
        mensaje=mensaje,
        enviado_por=solicitud.cliente.usuario,
        es_proveedor=False
    )

    logger.info(f"Mensaje inicial del chat creado: {chat_mensaje.id} para oferta: {oferta.id}")
    return chat_mensaje
