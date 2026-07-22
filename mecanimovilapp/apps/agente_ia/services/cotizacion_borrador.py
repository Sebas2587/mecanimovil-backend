"""Generación de borrador de cotización desde el agente IA."""
from __future__ import annotations

import logging

from django.contrib.auth import get_user_model

from mecanimovilapp.apps.agente_ia.models import AgenteConversacionSesion
from mecanimovilapp.apps.agente_ia.services.notificaciones import notificar_cotizacion_borrador_agente
from mecanimovilapp.apps.chat.models import Conversation
from mecanimovilapp.apps.ordenes.models import CotizacionCanal
from mecanimovilapp.apps.vehiculos.cilindraje_texto import cilindraje_efectivo
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador import generar_cotizacion_ia
from mecanimovilapp.apps.suscripciones.cuotas_services import CuotaAgotadaError, SinSuscripcionError, verificar_y_consumir_cuota
from mecanimovilapp.apps.suscripciones.models import ConsumoFeatureMensual
from mecanimovilapp.apps.usuarios.models import Taller

logger = logging.getLogger(__name__)
User = get_user_model()


def crear_cotizacion_borrador_desde_agente(
    *,
    sesion: AgenteConversacionSesion,
    conversation: Conversation,
    taller: Taller,
    proveedor_user_id: int,
    datos: dict,
) -> CotizacionCanal | None:
    """Genera CotizacionCanal borrador usando el generador IA existente."""
    proveedor = User.objects.filter(pk=proveedor_user_id).first()
    if not proveedor:
        logger.warning('Proveedor %s no encontrado para cotización agente', proveedor_user_id)
        return None

    try:
        verificar_y_consumir_cuota(proveedor, ConsumoFeatureMensual.FEATURE_COTIZACION_IA)
    except (CuotaAgotadaError, SinSuscripcionError) as exc:
        logger.info('Cuota cotización IA agotada para agente: %s', exc.message)
        return None

    vehiculo = datos.get('vehiculo') or {}
    servicio_nombre = (datos.get('servicio_nombre') or '').strip()
    descripcion = (datos.get('descripcion_problema') or datos.get('sintoma') or '').strip()
    modalidad = datos.get('modalidad') or 'taller'

    resultado = generar_cotizacion_ia(
        conversation=conversation,
        servicio_nombre=servicio_nombre,
        descripcion_problema=descripcion,
        modalidad=modalidad,
        vehiculo=vehiculo,
        contexto_rag_extra=datos.get('contexto_rag') or '',
    )
    if not resultado.get('disponible'):
        logger.info('generar_cotizacion_ia no disponible: %s', resultado.get('error'))
        return None

    contenido = resultado.get('contenido') or {}
    ctx = resultado.get('contexto') or {}
    anio_raw = vehiculo.get('anio') or ctx.get('vehiculo_anio')
    try:
        anio_int = int(anio_raw) if anio_raw else None
    except (TypeError, ValueError):
        anio_int = None

    marca = ctx.get('vehiculo_marca') or vehiculo.get('marca', '')
    modelo = ctx.get('vehiculo_modelo') or vehiculo.get('modelo', '')

    contact = conversation.external_contact
    cliente_nombre = (datos.get('cliente_nombre') or '').strip()
    cliente_telefono = (datos.get('cliente_telefono') or '').strip()
    if contact:
        cliente_nombre = cliente_nombre or (contact.display_name or '')
        cliente_telefono = cliente_telefono or (contact.phone or '')

    cotizacion = CotizacionCanal.objects.create(
        conversation=conversation,
        es_libre=False,
        cliente_nombre=cliente_nombre[:200],
        cliente_telefono=cliente_telefono[:20],
        taller=taller,
        creado_por=proveedor,
        estado='borrador',
        modalidad=modalidad,
        direccion_servicio=str(datos.get('direccion_servicio') or '')[:500],
        vehiculo_marca=marca,
        vehiculo_modelo=modelo,
        vehiculo_anio=anio_int,
        vehiculo_patente=ctx.get('vehiculo_patente') or vehiculo.get('patente', ''),
        vehiculo_cilindraje=cilindraje_efectivo(
            ctx.get('vehiculo_cilindraje') or vehiculo.get('cilindraje', ''),
            marca,
            modelo,
        ),
        tipo_motor=contenido.get('tipo_motor') or ctx.get('tipo_motor', ''),
        tipo_motor_label=contenido.get('tipo_motor_label') or ctx.get('tipo_motor_label', ''),
        aviso_motor=contenido.get('aviso_motor') or ctx.get('aviso_motor', ''),
        servicio_nombre=contenido.get('servicio_nombre') or servicio_nombre,
        descripcion_problema=contenido.get('descripcion_problema') or descripcion,
        repuestos=contenido.get('repuestos') or [],
        mano_obra_clp=contenido.get('mano_obra_clp') or 0,
        costo_repuestos_clp=contenido.get('costo_repuestos_clp') or 0,
        total_clp=contenido.get('total_clp') or 0,
        duracion_minutos_estimada=contenido.get('duracion_minutos_estimada'),
        advertencias=contenido.get('advertencias') or [],
        contenido_ia=resultado.get('contenido_ia') or {},
        metadata={'origen': 'agente_ia', 'sesion_id': sesion.id},
        tokens_entrada=resultado.get('tokens_entrada') or 0,
        tokens_salida=resultado.get('tokens_salida') or 0,
        modelo_ia=resultado.get('modelo') or '',
    )

    sesion.cotizacion_borrador = cotizacion
    sesion.estado = AgenteConversacionSesion.ESTADO_ESPERANDO_REVISION
    sesion.save(update_fields=['cotizacion_borrador', 'estado', 'actualizado_en'])

    notificar_cotizacion_borrador_agente(
        proveedor_user_id=proveedor_user_id,
        cotizacion=cotizacion,
        conversation_id=conversation.id,
    )
    return cotizacion
