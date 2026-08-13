"""Creación de cotizaciones adicionales sobre un trabajo de canal en curso."""
from __future__ import annotations

import logging
from datetime import date, datetime, time as dt_time
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
EJECUCION_MISMA_VISITA = 'misma_visita'
EJECUCION_NUEVA_FECHA = 'nueva_fecha'


def parse_fecha_propuesta(val) -> date | None:
    if val in (None, ''):
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    return datetime.strptime(str(val)[:10], '%Y-%m-%d').date()


def parse_hora_propuesta(val) -> dt_time | None:
    if val in (None, ''):
        return None
    if isinstance(val, dt_time):
        return val
    raw = str(val).strip()
    parts = raw[:8].split(':')
    hora = int(parts[0])
    minuto = int(parts[1]) if len(parts) > 1 else 0
    return dt_time(hora, minuto)


def normalizar_plan_ejecucion(
    *,
    ejecucion_adicional: str | None = None,
    fecha_propuesta=None,
    hora_propuesta=None,
) -> tuple[str, date | None, dt_time | None]:
    modo = (ejecucion_adicional or EJECUCION_MISMA_VISITA).strip() or EJECUCION_MISMA_VISITA
    if modo not in (EJECUCION_MISMA_VISITA, EJECUCION_NUEVA_FECHA):
        raise ValueError('La ejecución del adicional debe ser misma visita o nueva fecha.')
    if modo == EJECUCION_MISMA_VISITA:
        return modo, None, None
    return modo, parse_fecha_propuesta(fecha_propuesta), parse_hora_propuesta(hora_propuesta)


def es_adicional_nueva_fecha(cotizacion: CotizacionCanal) -> bool:
    return bool(
        cotizacion.es_cotizacion_adicional
        and (cotizacion.ejecucion_adicional or '') == EJECUCION_NUEVA_FECHA
    )


def formatear_slot_propuesto(cotizacion: CotizacionCanal) -> str:
    if not cotizacion.fecha_propuesta:
        return ''
    fecha = cotizacion.fecha_propuesta.strftime('%d/%m/%Y')
    if cotizacion.hora_propuesta:
        return f'{fecha} a las {cotizacion.hora_propuesta.strftime("%H:%M")}'
    return fecha


def validar_adicional_listo_para_enviar(cotizacion: CotizacionCanal) -> None:
    if not es_adicional_nueva_fecha(cotizacion):
        return
    if not cotizacion.fecha_propuesta or not cotizacion.hora_propuesta:
        raise ValueError(
            'Indica fecha y hora para el trabajo adicional en una visita posterior.'
        )


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
    ejecucion_adicional: str = EJECUCION_MISMA_VISITA,
    fecha_propuesta=None,
    hora_propuesta=None,
) -> CotizacionCanal:
    validar_cotizacion_original(cotizacion_original=cotizacion_original, taller=taller)
    if cotizacion_original.es_cotizacion_adicional:
        raise ValueError('No se puede crear un trabajo adicional sobre otro adicional.')
    if not cita_permite_cotizacion_adicional(cita):
        raise ValueError('Este trabajo aún no permite cotizaciones adicionales.')

    ejecucion, fecha_p, hora_p = normalizar_plan_ejecucion(
        ejecucion_adicional=ejecucion_adicional,
        fecha_propuesta=fecha_propuesta,
        hora_propuesta=hora_propuesta,
    )

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
        cita_origen=cita,
        es_cotizacion_adicional=True,
        ejecucion_adicional=ejecucion,
        fecha_propuesta=fecha_p,
        hora_propuesta=hora_p,
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
    ejecucion_adicional: str = EJECUCION_MISMA_VISITA,
    fecha_propuesta=None,
    hora_propuesta=None,
) -> CotizacionCanal:
    from mecanimovilapp.apps.suscripciones.cuotas_services import (
        CuotaAgotadaError,
        SinSuscripcionError,
        verificar_y_consumir_cuota,
    )
    from mecanimovilapp.apps.suscripciones.models import ConsumoFeatureMensual

    validar_cotizacion_original(cotizacion_original=cotizacion_original, taller=taller)
    if cotizacion_original.es_cotizacion_adicional:
        raise ValueError('No se puede crear un trabajo adicional sobre otro adicional.')
    if not cita_permite_cotizacion_adicional(cita):
        raise ValueError('Este trabajo aún no permite cotizaciones adicionales.')

    ejecucion, fecha_p, hora_p = normalizar_plan_ejecucion(
        ejecucion_adicional=ejecucion_adicional,
        fecha_propuesta=fecha_propuesta,
        hora_propuesta=hora_propuesta,
    )

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
        taller=taller,
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
        cita_origen=cita,
        es_cotizacion_adicional=True,
        ejecucion_adicional=ejecucion,
        fecha_propuesta=fecha_p,
        hora_propuesta=hora_p,
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
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.disparar_busqueda_web import (
        disparar_y_refrescar_cotizacion,
        marcar_busqueda_web_pendiente,
    )

    cotizacion.metadata = marcar_busqueda_web_pendiente(cotizacion.metadata)
    if cotizacion.metadata.get('busqueda_web_estado') == 'pendiente':
        cotizacion.save(update_fields=['metadata', 'actualizado_en'])
        cotizacion = disparar_y_refrescar_cotizacion(cotizacion)
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


def cotizacion_es_trabajo_adicional(cotizacion: CotizacionCanal) -> bool:
    return bool(cotizacion.es_cotizacion_adicional)


def total_visita_cita(cita: CitaAgendaPersonal) -> int:
    """Precio de referencia de la visita: principal + adicionales aceptadas."""
    total = 0
    origen = getattr(cita, 'cotizacion_canal_origen', None)
    if origen is not None:
        total += max(0, int(origen.total_clp or 0))
    adicionales = getattr(cita, 'cotizaciones_adicionales', None)
    if adicionales is None:
        return total
    for ad in adicionales.filter(estado='aceptada'):
        if getattr(ad, 'ejecucion_adicional', EJECUCION_MISMA_VISITA) == EJECUCION_NUEVA_FECHA:
            continue
        total += max(0, int(ad.total_clp or 0))
    return total


def actualizar_precio_referencia_visita(cita: CitaAgendaPersonal) -> None:
    det = getattr(cita, 'detalle', None)
    if det is None:
        return
    det.precio_referencia = total_visita_cita(cita)
    det.save(update_fields=['precio_referencia'])


def aplicar_adicional_aceptada_a_cita(
    cotizacion: CotizacionCanal,
    cita: CitaAgendaPersonal,
) -> CitaAgendaPersonal:
    """Suma duración y precio de referencia a la cita principal. No crea cita nueva."""
    extra = int(cotizacion.duracion_minutos_estimada or 0)
    update_fields: list[str] = []
    if extra > 0:
        cita.duracion_minutos = int(cita.duracion_minutos or 0) + extra
        update_fields.append('duracion_minutos')
    if update_fields:
        cita.save(update_fields=update_fields)
    actualizar_precio_referencia_visita(cita)
    logger.info(
        'Cotización adicional %s aceptada → cita principal %s (sin cita nueva)',
        cotizacion.id,
        cita.id,
    )
    return cita


def crear_cita_desde_adicional_nueva_fecha(
    cotizacion: CotizacionCanal,
    cita_padre: CitaAgendaPersonal,
) -> CitaAgendaPersonal:
    """Cita hija con horario propuesto. Ligada al principal vía cotización.cita_origen."""
    from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonalDetalle
    from mecanimovilapp.apps.ordenes.services.cotizacion_publica import _telefono_desde_cotizacion

    if not cotizacion.fecha_propuesta or not cotizacion.hora_propuesta:
        raise ValueError('Falta fecha y hora para agendar el trabajo adicional.')

    duracion = cotizacion.duracion_minutos_estimada or 60
    tipo_servicio = 'domicilio' if cotizacion.modalidad == 'domicilio' else 'taller'
    direccion = (cotizacion.direccion_servicio or '').strip()[:500]
    tel_efectivo = _telefono_desde_cotizacion(cotizacion)

    cita = CitaAgendaPersonal(
        taller=cotizacion.taller,
        cotizacion_canal_origen=cotizacion,
        conversation_origen=cotizacion.conversation or cita_padre.conversation_origen,
        miembro_taller=cita_padre.miembro_taller,
        fecha_servicio=cotizacion.fecha_propuesta,
        hora_servicio=cotizacion.hora_propuesta,
        duracion_minutos=duracion,
        tipo_servicio=tipo_servicio,
        horario_por_confirmar=False,
        creado_por=cotizacion.creado_por or cita_padre.creado_por,
    )
    if cita.creado_por_id is None and cotizacion.taller and cotizacion.taller.usuario_id:
        cita.creado_por_id = cotizacion.taller.usuario_id
    cita.full_clean()
    cita.save()

    det_padre = getattr(cita_padre, 'detalle', None)
    det = CitaAgendaPersonalDetalle(
        cita=cita,
        cliente_nombre=cotizacion.cliente_nombre or getattr(det_padre, 'cliente_nombre', None) or 'Cliente',
        cliente_telefono=tel_efectivo or (cotizacion.cliente_telefono or '') or getattr(det_padre, 'cliente_telefono', ''),
        direccion=direccion or getattr(det_padre, 'direccion', '') or '',
        vehiculo_marca=cotizacion.vehiculo_marca or getattr(det_padre, 'vehiculo_marca', '') or '',
        vehiculo_modelo=cotizacion.vehiculo_modelo or getattr(det_padre, 'vehiculo_modelo', '') or '',
        vehiculo_patente=cotizacion.vehiculo_patente or getattr(det_padre, 'vehiculo_patente', '') or '',
        vehiculo_vin=(cotizacion.vehiculo_vin or getattr(det_padre, 'vehiculo_vin', '') or '').strip().upper()[:30],
        vehiculo_anio=cotizacion.vehiculo_anio or getattr(det_padre, 'vehiculo_anio', None),
        vehiculo_cilindraje=cilindraje_efectivo(
            cotizacion.vehiculo_cilindraje or getattr(det_padre, 'vehiculo_cilindraje', ''),
            cotizacion.vehiculo_marca,
            cotizacion.vehiculo_modelo,
        ),
        servicio_nombre=cotizacion.servicio_nombre,
        descripcion=cotizacion.descripcion_problema or cotizacion.motivo_servicio_adicional,
        precio_referencia=cotizacion.total_clp,
    )
    det.full_clean()
    det.save()
    logger.info(
        'Cotización adicional %s aceptada → cita hija %s (fecha %s %s, padre %s)',
        cotizacion.id,
        cita.id,
        cotizacion.fecha_propuesta,
        cotizacion.hora_propuesta,
        cita_padre.id,
    )
    return cita
