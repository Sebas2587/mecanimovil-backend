"""Creación de cotizaciones adicionales sobre un trabajo de canal en curso."""
from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth import get_user_model

from mecanimovilapp.apps.agente_ia.services.cotizacion_borrador import evaluar_listo_para_enviar
from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, CotizacionCanal
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador import generar_cotizacion_ia
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import recalcular_totales
from mecanimovilapp.apps.ordenes.services.catalogo_pricing import (
    buscar_oferta_por_id,
    linea_desde_oferta_catalogo,
    precio_publico_oferta,
)
from mecanimovilapp.apps.ordenes.services.notificaciones_pipeline import (
    notificar_cotizacion_adicional_borrador,
)
from mecanimovilapp.apps.usuarios.models import Taller
from mecanimovilapp.apps.vehiculos.cilindraje_texto import cilindraje_efectivo

logger = logging.getLogger(__name__)
User = get_user_model()

ADVERTENCIA_ADICIONAL = 'Cotización adicional sobre un trabajo en curso del mismo cliente'


def _titulo_servicios(lineas: list[dict[str, Any]]) -> str:
    nombres = [str(l.get('nombre') or '').strip() for l in lineas if l.get('nombre')]
    nombres = [n for n in nombres if n]
    if not nombres:
        return 'Servicio adicional'
    if len(nombres) == 1:
        return nombres[0]
    if len(nombres) == 2:
        return f'{nombres[0]} + {nombres[1]}'
    return f'{nombres[0]} + {nombres[1]} (+{len(nombres) - 2} más)'


def _checklist_en_ejecucion(cita: CitaAgendaPersonal) -> bool:
    inst = getattr(cita, 'checklist_instance', None)
    if inst is None:
        return False
    return inst.estado in ('EN_PROGRESO', 'PAUSADO', 'PENDIENTE_FIRMA_CLIENTE')


def cita_permite_cotizacion_adicional(cita: CitaAgendaPersonal) -> bool:
    """Trabajo agendado (horario confirmado) o en ejecución vía checklist."""
    if cita.estado != 'activa':
        return False
    if not cita.cotizacion_canal_origen_id:
        return False
    origen = cita.cotizacion_canal_origen
    if origen is None or origen.estado != 'aceptada':
        return False
    if _checklist_en_ejecucion(cita):
        return True
    return not bool(getattr(cita, 'horario_por_confirmar', False))


def validar_cotizacion_original(
    *,
    cotizacion_original: CotizacionCanal,
    taller: Taller,
) -> None:
    if cotizacion_original.taller_id != taller.id:
        raise ValueError('La cotización original no pertenece a este taller.')
    if cotizacion_original.estado != 'aceptada':
        raise ValueError('La cotización original debe estar aceptada.')


def _datos_cliente_desde_original(original: CotizacionCanal) -> dict[str, str]:
    return {
        'cliente_nombre': (original.cliente_nombre or '')[:200],
        'cliente_telefono': (original.cliente_telefono or '')[:20],
        'vehiculo_marca': original.vehiculo_marca or '',
        'vehiculo_modelo': original.vehiculo_modelo or '',
        'vehiculo_anio': original.vehiculo_anio,
        'vehiculo_patente': original.vehiculo_patente or '',
        'vehiculo_cilindraje': original.vehiculo_cilindraje or '',
        'vehiculo_vin': original.vehiculo_vin or '',
        'tipo_motor': original.tipo_motor or '',
        'tipo_motor_label': original.tipo_motor_label or '',
        'modalidad': original.modalidad or 'taller',
        'direccion_servicio': original.direccion_servicio or '',
    }


def _armar_lineas_catalogo(
    *,
    taller: Taller,
    servicios_catalogo: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], int]:
    lineas: list[dict[str, Any]] = []
    advertencias: list[str] = [ADVERTENCIA_ADICIONAL]
    mano_obra = 0
    faltan_precio = False

    for item in servicios_catalogo:
        oferta_id = item.get('oferta_servicio_id')
        if not oferta_id:
            raise ValueError('Cada servicio debe incluir oferta_servicio_id.')
        cantidad = max(1, int(item.get('cantidad') or 1))
        oferta = buscar_oferta_por_id(taller=taller, oferta_servicio_id=int(oferta_id))
        if oferta is None:
            raise ValueError(f'Oferta de catálogo {oferta_id} no encontrada o no disponible.')
        linea = linea_desde_oferta_catalogo(oferta, cantidad=cantidad)
        precio_linea = int(linea.get('precio_clp') or 0) * cantidad
        if precio_linea <= 0:
            faltan_precio = True
        mano_obra += precio_linea
        lineas.append(linea)

    if faltan_precio:
        advertencias.append(
            'Uno o más servicios no tienen precio publicado en catálogo — completa antes de enviar.'
        )
    return lineas, advertencias, mano_obra


def crear_cotizacion_adicional_desde_catalogo(
    *,
    cotizacion_original: CotizacionCanal,
    cita: CitaAgendaPersonal,
    taller: Taller,
    creado_por: User,
    motivo_servicio_adicional: str,
    servicios_catalogo: list[dict[str, Any]],
) -> CotizacionCanal:
    validar_cotizacion_original(cotizacion_original=cotizacion_original, taller=taller)
    if not cita_permite_cotizacion_adicional(cita):
        raise ValueError('Este trabajo aún no permite cotizaciones adicionales.')

    base = _datos_cliente_desde_original(cotizacion_original)
    lineas, advertencias, mano_obra = _armar_lineas_catalogo(
        taller=taller,
        servicios_catalogo=servicios_catalogo,
    )
    motivo = (motivo_servicio_adicional or '').strip()
    descripcion = motivo
    if cotizacion_original.servicio_nombre:
        descripcion = f'{motivo}\n\nServicio original: {cotizacion_original.servicio_nombre}'.strip()

    listo, pendientes = evaluar_listo_para_enviar(
        lineas=lineas,
        modalidad=base['modalidad'],
        direccion_servicio=base['direccion_servicio'],
        cliente_telefono=base['cliente_telefono'],
        vehiculo_patente=base['vehiculo_patente'],
    )
    totales = recalcular_totales(mano_obra_clp=mano_obra, repuestos=[])
    costo_rep, mano_final, total = totales

    cotizacion = CotizacionCanal.objects.create(
        conversation=cotizacion_original.conversation,
        es_libre=False,
        taller=taller,
        creado_por=creado_por,
        estado='borrador',
        cotizacion_original=cotizacion_original,
        es_cotizacion_adicional=True,
        motivo_servicio_adicional=motivo[:2000],
        cliente_nombre=base['cliente_nombre'],
        cliente_telefono=base['cliente_telefono'],
        modalidad=base['modalidad'],
        direccion_servicio=base['direccion_servicio'][:500],
        vehiculo_marca=base['vehiculo_marca'],
        vehiculo_modelo=base['vehiculo_modelo'],
        vehiculo_anio=base['vehiculo_anio'],
        vehiculo_patente=base['vehiculo_patente'],
        vehiculo_cilindraje=base['vehiculo_cilindraje'],
        vehiculo_vin=base['vehiculo_vin'][:50],
        tipo_motor=base['tipo_motor'],
        tipo_motor_label=base['tipo_motor_label'],
        servicio_nombre=_titulo_servicios(lineas),
        descripcion_problema=descripcion[:5000],
        repuestos=[],
        mano_obra_clp=mano_final,
        costo_repuestos_clp=costo_rep,
        total_clp=total,
        advertencias=advertencias,
        metadata={
            'origen': 'cotizacion_adicional',
            'cotizacion_original_id': cotizacion_original.id,
            'cita_personal_id': cita.id,
            'servicios_lineas': lineas,
            'listo_para_enviar': listo,
            'pendientes_revision': pendientes,
            'precio_desde_catalogo': listo,
        },
    )
    notificar_cotizacion_adicional_borrador(
        proveedor_user_id=creado_por.id,
        cotizacion=cotizacion,
        conversation_id=cotizacion.conversation_id,
    )
    return cotizacion


def crear_cotizacion_adicional_con_ia(
    *,
    cotizacion_original: CotizacionCanal,
    cita: CitaAgendaPersonal,
    taller: Taller,
    creado_por: User,
    motivo_servicio_adicional: str,
    servicio_nombre: str,
    descripcion_problema: str = '',
) -> CotizacionCanal:
    from mecanimovilapp.apps.suscripciones.cuotas_services import (
        CuotaAgotadaError,
        SinSuscripcionError,
        verificar_y_consumir_cuota,
    )
    from mecanimovilapp.apps.suscripciones.models import ConsumoFeatureMensual

    validar_cotizacion_original(cotizacion_original=cotizacion_original, taller=taller)
    if not cita_permite_cotizacion_adicional(cita):
        raise ValueError('Este trabajo aún no permite cotizaciones adicionales.')

    try:
        verificar_y_consumir_cuota(creado_por, ConsumoFeatureMensual.FEATURE_COTIZACION_IA)
    except (CuotaAgotadaError, SinSuscripcionError) as exc:
        raise ValueError(exc.message) from exc

    base = _datos_cliente_desde_original(cotizacion_original)
    motivo = (motivo_servicio_adicional or '').strip()
    desc_ia = (descripcion_problema or motivo or servicio_nombre).strip()
    if motivo and motivo not in desc_ia:
        desc_ia = f'{motivo}\n{desc_ia}'.strip()

    conversation = cotizacion_original.conversation
    resultado = generar_cotizacion_ia(
        conversation=conversation,
        servicio_nombre=servicio_nombre or 'Servicio adicional',
        descripcion_problema=desc_ia,
        modalidad=base['modalidad'],
        vehiculo={
            'marca': base['vehiculo_marca'],
            'modelo': base['vehiculo_modelo'],
            'anio': base['vehiculo_anio'],
            'patente': base['vehiculo_patente'],
            'cilindraje': base['vehiculo_cilindraje'],
            'vin': base['vehiculo_vin'],
            'tipo_motor': base['tipo_motor'],
        },
    )
    if not resultado.get('disponible'):
        raise ValueError(resultado.get('error') or 'No se pudo generar la cotización con IA.')

    contenido = resultado.get('contenido') or {}
    ctx = resultado.get('contexto') or {}
    marca = ctx.get('vehiculo_marca') or base['vehiculo_marca']
    modelo = ctx.get('vehiculo_modelo') or base['vehiculo_modelo']
    cilindraje = cilindraje_efectivo(
        ctx.get('vehiculo_cilindraje') or base['vehiculo_cilindraje'],
        marca,
        modelo,
    )

    nombre_serv = contenido.get('servicio_nombre') or servicio_nombre or 'Servicio adicional'
    from mecanimovilapp.apps.ordenes.services.catalogo_pricing import buscar_oferta_exacta

    oferta = buscar_oferta_exacta(
        taller=taller,
        servicio_nombre=nombre_serv,
        marca=marca,
        modelo=modelo,
        tipo_motor=base['tipo_motor'],
    )
    mano_obra = int(contenido.get('mano_obra_clp') or 0)
    precio_cat = False
    lineas: list[dict[str, Any]] = []
    if oferta:
        precio, _ = precio_publico_oferta(oferta, con_repuestos=True)
        if precio > 0:
            mano_obra = precio
            precio_cat = True
        lineas = [linea_desde_oferta_catalogo(oferta)]

    repuestos = contenido.get('repuestos') or []
    costo_rep, mano_final, total = recalcular_totales(
        mano_obra_clp=mano_obra,
        repuestos=repuestos,
    )
    advertencias = list(contenido.get('advertencias') or [])
    advertencias.insert(0, ADVERTENCIA_ADICIONAL)
    if not precio_cat:
        advertencias.append(
            'Sin precio publicado en catálogo para este servicio — completa el valor antes de enviar.'
        )

    listo, pendientes = evaluar_listo_para_enviar(
        lineas=lineas or [{'nombre': nombre_serv, 'precio_desde_catalogo': precio_cat}],
        modalidad=base['modalidad'],
        direccion_servicio=base['direccion_servicio'],
        cliente_telefono=base['cliente_telefono'],
        vehiculo_patente=base['vehiculo_patente'],
    )

    cotizacion = CotizacionCanal.objects.create(
        conversation=conversation,
        es_libre=False,
        taller=taller,
        creado_por=creado_por,
        estado='borrador',
        cotizacion_original=cotizacion_original,
        es_cotizacion_adicional=True,
        motivo_servicio_adicional=motivo[:2000],
        cliente_nombre=base['cliente_nombre'],
        cliente_telefono=base['cliente_telefono'],
        modalidad=base['modalidad'],
        direccion_servicio=base['direccion_servicio'][:500],
        vehiculo_marca=marca,
        vehiculo_modelo=modelo,
        vehiculo_anio=base['vehiculo_anio'],
        vehiculo_patente=ctx.get('vehiculo_patente') or base['vehiculo_patente'],
        vehiculo_cilindraje=cilindraje,
        vehiculo_vin=base['vehiculo_vin'][:50],
        tipo_motor=contenido.get('tipo_motor') or base['tipo_motor'],
        tipo_motor_label=contenido.get('tipo_motor_label') or base['tipo_motor_label'],
        aviso_motor=contenido.get('aviso_motor') or '',
        servicio_nombre=nombre_serv,
        descripcion_problema=desc_ia[:5000],
        repuestos=repuestos,
        mano_obra_clp=mano_final,
        costo_repuestos_clp=costo_rep,
        total_clp=total,
        duracion_minutos_estimada=contenido.get('duracion_minutos_estimada'),
        advertencias=advertencias,
        contenido_ia=resultado.get('contenido_ia') or {},
        tokens_entrada=resultado.get('tokens_entrada') or 0,
        tokens_salida=resultado.get('tokens_salida') or 0,
        modelo_ia=resultado.get('modelo') or '',
        metadata={
            'origen': 'cotizacion_adicional',
            'modo': 'ia',
            'cotizacion_original_id': cotizacion_original.id,
            'cita_personal_id': cita.id,
            'servicios_lineas': lineas,
            'listo_para_enviar': listo,
            'pendientes_revision': pendientes,
            'precio_desde_catalogo': precio_cat,
        },
    )
    notificar_cotizacion_adicional_borrador(
        proveedor_user_id=creado_por.id,
        cotizacion=cotizacion,
        conversation_id=cotizacion.conversation_id,
    )
    logger.info(
        'Cotización adicional IA %s creada desde original %s cita %s',
        cotizacion.id,
        cotizacion_original.id,
        cita.id,
    )
    return cotizacion
