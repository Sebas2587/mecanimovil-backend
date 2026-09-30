"""Cotización pedida en el chat del dueño: el mismo borrador que Cotizar, no un alta de catálogo."""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_HINT_SIN_CANAL = (
    'Este cliente no está en un canal. '
    'Al enviar podrás copiar el link o abrirlo en WhatsApp si registras el teléfono.'
)
_CANAL_LABEL = {
    'MESSENGER': 'Facebook',
    'INSTAGRAM': 'Instagram',
    'WHATSAPP': 'WhatsApp',
}
_MENORES = {'de', 'del', 'la', 'el', 'y', 'e', 'a', 'en'}
_PATENTE_RE = re.compile(
    r'\b([a-z]{4}[\s.\-]*\d{2}|[a-z]{2}[\s.\-]*\d{4})\b',
    re.IGNORECASE,
)
_SERVICIO_RE = re.compile(
    r'\b((?:cambio|reparacion|mantencion|revision|alineacion|balanceo|diagnostico|'
    r'instalacion|rectificacion|ajuste|limpieza)\s+de\s+[a-z0-9]+'
    r'(?:\s+(?!para\b|patente\b|domicilio\b|cliente\b|con\b|sin\b|a\b)[a-z0-9]+){0,4})',
)
_ANIO_RE = re.compile(r'\b((?:19|20)\d{2})\b')


def es_pedido_cotizacion_cliente(texto: str) -> bool:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    p = plano(texto)
    if re.search(r'se cotiza|cotiza mas|mas cotiz|cuantas cotiz|que se pide', p):
        return False
    if re.search(r'servicio del taller|dar de alta|da de alta|en el catalogo|como servicio\b', p):
        if not re.search(r'\b(cotizacion|presupuesto)\b', p):
            return False
    return bool(re.search(r'\b(cotizacion|cotizar|cotizale|cotizame|cotiza|presupuesto)\b', p))


def intentar_cotizacion_desde_chat(taller, hilo, texto: str, user, correcciones: list[dict]) -> dict | None:
    del correcciones
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    pendiente = hilo.accion_pendiente if isinstance(hilo.accion_pendiente, dict) else {}
    tipo = str(pendiente.get('tipo') or '')
    p = plano(texto)
    if tipo == 'enviar_cotizacion':
        return None
    if tipo.startswith('cotizacion_'):
        if _es_otro_pedido(p) and not es_pedido_cotizacion_cliente(texto):
            return None
        return _continuar(taller, hilo, texto, user, pendiente)
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_cotizacion_actualizar import (
        aplicar_cambio,
        documento_del_hilo,
        pide_sumar,
        pide_quitar,
    )

    documento = documento_del_hilo(taller, hilo)
    slots = dict(pendiente.get('slots') or {})
    if documento is not None and (pide_sumar(texto) or pide_quitar(texto)):
        return aplicar_cambio(taller, user, documento, texto, slots)
    cotizacion = _borrador_chat(taller, hilo)
    if cotizacion is not None and not _trabajo_distinto(texto, slots, cotizacion):
        return _seguir_borrador(taller, cotizacion, texto, slots)
    if es_pedido_cotizacion_cliente(texto):
        return _empezar(taller, texto, user, pendiente)
    return None


def _continuar(taller, hilo, texto, user, pendiente) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    tipo = pendiente.get('tipo')
    p = plano(texto)
    slots = dict(pendiente.get('slots') or {})
    if tipo == 'cotizacion_datos':
        return _empezar(taller, texto, user, pendiente)
    if tipo == 'cotizacion_vehiculo':
        return _resolver_vehiculo(taller, texto, user, pendiente)
    if tipo == 'cotizacion_destinatario':
        return _resolver_destinatario(taller, texto, pendiente)
    if tipo == 'cotizacion_calle':
        return _resolver_calle(taller, texto, pendiente)
    if tipo == 'cotizacion_lista':
        from mecanimovilapp.apps.agente_ia.services.agente_dueno_cotizacion_actualizar import (
            aplicar_cambio,
            documento_del_hilo,
            pide_sumar,
            pide_quitar,
        )

        documento = documento_del_hilo(taller, hilo)
        if documento is not None and (pide_sumar(texto) or pide_quitar(texto)):
            return aplicar_cambio(taller, user, documento, texto, slots)
        cotizacion = _borrador_chat(taller, hilo)
        if cotizacion is None:
            return _empezar(taller, texto, user, {})
        if _trabajo_distinto(texto, slots, cotizacion):
            return _empezar(taller, texto, user, {})
        return _seguir_borrador(taller, cotizacion, texto, slots)
    return _empezar(taller, texto, user, pendiente)


def _empezar(taller, texto, user, pendiente) -> dict:
    prev = dict(pendiente.get('slots') or {})
    if es_pedido_cotizacion_cliente(texto) and pendiente.get('tipo') != 'cotizacion_datos':
        prev = {}
    slots = _fusionar(prev, _extraer(texto))
    if _es_precio_solo(texto) and not slots.get('precio'):
        monto = _precio_en(texto, slots.get('anio'))
        if monto:
            slots['precio'] = monto
    falta = _falta_para_armar(slots)
    if falta:
        return _turno(
            haciendo='Reviso qué falta para la cotización',
            titulo='Cotización',
            resumen=falta,
            ancla='keep',
            accion_pendiente={'tipo': 'cotizacion_datos', 'slots': _slots_publicos(slots), 'cotizacion_id': None},
        )
    if slots.get('patente') and not slots.get('conflicto_visto'):
        consulta = _consultar_patente(slots['patente'], user)
        if consulta.get('ok'):
            choque = _choque_vehiculo(slots, consulta['vehiculo'])
            if choque:
                slots['api'] = consulta['vehiculo']
                slots['conflicto_visto'] = True
                return _turno(
                    haciendo=f"Buscando la patente {slots['patente']}",
                    titulo='La patente no coincide',
                    resumen=choque,
                    ancla='keep',
                    accion_pendiente={'tipo': 'cotizacion_vehiculo', 'slots': _slots_con_api(slots)},
                )
            slots['vehiculo'] = _completar_vehiculo(consulta['vehiculo'], slots)
            slots['aviso_patente'] = ''
        else:
            slots['vehiculo'] = _vehiculo_dicho(slots)
            slots['aviso_patente'] = consulta.get('aviso') or (
                f"No pude consultar la patente {slots['patente']}. "
                'Armé el borrador con lo que me dijiste.'
            )
    elif not slots.get('vehiculo'):
        slots['vehiculo'] = _vehiculo_dicho(slots)
    return _armar(taller, user, slots)


def _resolver_vehiculo(taller, texto, user, pendiente) -> dict:
    slots = _fusionar(dict(pendiente.get('slots') or {}), _extraer(texto))
    api = slots.get('api') or {}
    dueno = _vehiculo_dicho(slots)
    lado = _elegir_lado(texto, api, dueno)
    if lado is None:
        slots['vehiculo'] = dueno
        slots['aviso_patente'] = (
            f"La dejo como me la dijiste ({_frase_vehiculo(dueno)}). "
            f"El registro de la patente dice {_frase_vehiculo(api)}."
        )
    else:
        base = api if lado == 'api' else dueno
        slots['vehiculo'] = _completar_vehiculo(base, slots)
        slots['aviso_patente'] = ''
    slots['conflicto_visto'] = True
    return _armar(taller, user, slots)


def _armar(taller, user, slots: dict) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import _caso_cotizacion, clp

    try:
        cotizacion, buscando = _crear_borrador(taller, user, slots)
    except _CuotaCotizacion as exc:
        return _turno(
            haciendo='Reviso la cuota de cotización',
            titulo='Cuota de cotización',
            resumen=exc.mensaje,
            ancla='keep',
            accion_pendiente={},
        )
    except _GeneracionFallida as exc:
        return _turno(
            haciendo='Armo la cotización',
            titulo='No quedó la cotización',
            resumen=exc.mensaje,
            ancla='keep',
            accion_pendiente={'tipo': 'cotizacion_datos', 'slots': _slots_publicos(slots)},
        )
    pendientes = _pendientes_precio(cotizacion)
    _guardar_listo(cotizacion, pendientes)
    cotizacion.save(update_fields=['metadata', 'actualizado_en'])
    auto = _frase_auto_cotizacion(cotizacion)
    frases = []
    if slots.get('aviso_patente'):
        frases.append(str(slots['aviso_patente']))
    patente = (cotizacion.vehiculo_patente or '').strip()
    frases.append(
        f"Dejé el borrador de {cotizacion.servicio_nombre} para {auto}."
        + (f" Patente {patente}." if patente else '')
    )
    if slots.get('precio'):
        frases.append(f"La mano de obra quedó en ${clp(int(slots['precio']))}.")
    frases.append(_frase_desglose(cotizacion, buscando))
    frases.append('Ábrelo para revisarlo y enviarlo. El cliente todavía no lo recibe.')
    return _turno(
        haciendo=_haciendo_armado(slots, buscando),
        titulo=cotizacion.numero_publico or 'Borrador',
        resumen=' '.join(frases),
        filas=_filas_desglose(cotizacion, buscando),
        enlace=_enlace(cotizacion, buscando),
        pasos=_pasos_armado(cotizacion, slots, buscando),
        siguiente=(
            'Cuando aparezcan los precios, abre el borrador y envíalo.'
            if buscando
            else 'Abre el borrador, revisa las líneas y envíalo al cliente.'
        ),
        caso_anclado=_caso_cotizacion(cotizacion, _hoy()),
        ancla='set',
        accion_pendiente={
            'tipo': 'cotizacion_lista',
            'cotizacion_id': cotizacion.id,
            'slots': _slots_publicos(slots),
        },
    )


def _crear_borrador(taller, user, slots: dict):
    from django.core.cache import cache
    from django.utils import timezone

    from mecanimovilapp.apps.ordenes.models import CotizacionCanal
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.disparar_busqueda_web import (
        disparar_busqueda_web_cotizacion,
        marcar_busqueda_web_pendiente,
    )
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
        linea_necesita_busqueda_web,
    )
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.generador import generar_cotizacion_ia
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.mano_obra_lineas import (
        persistir_mano_obra_lineas,
        resolver_mano_obra_lineas,
    )
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
        aplicar_totales_cotizacion,
    )
    from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
        asegurar_numero_publico,
        asegurar_token_cotizacion,
        resolver_politicas_cotizacion,
        snapshot_dias_validez,
    )
    from mecanimovilapp.apps.suscripciones.cuotas_services import (
        CuotaAgotadaError,
        SinSuscripcionError,
        verificar_y_consumir_cuota,
    )
    from mecanimovilapp.apps.suscripciones.models import ConsumoFeatureMensual
    from mecanimovilapp.apps.vehiculos.cilindraje_texto import cilindraje_efectivo

    veh = slots.get('vehiculo') or _vehiculo_dicho(slots)
    servicio = (slots.get('servicio') or '').strip()
    modalidad = slots.get('modalidad') or 'taller'
    direccion = (slots.get('direccion') or '').strip() if modalidad == 'domicilio' else ''
    lock_user = getattr(user, 'id', None) or getattr(taller, 'usuario_id', None) or 0
    lock_key = f'generar_ia:{taller.id}:{lock_user}'
    if not cache.add(lock_key, '1', timeout=90):
        raise _GeneracionFallida(
            'Ya hay una cotización IA en curso. Espera a que termine antes de volver a intentar.'
        )
    try:
        resultado = generar_cotizacion_ia(
            conversation=None,
            servicio_nombre=servicio,
            descripcion_problema='',
            modalidad=modalidad,
            vehiculo={
                'marca': veh.get('marca') or '',
                'modelo': veh.get('modelo') or '',
                'anio': veh.get('anio'),
                'patente': veh.get('patente') or slots.get('patente') or '',
                'cilindraje': veh.get('cilindraje') or '',
                'vin': veh.get('vin') or '',
            },
            taller=taller,
            enriquecer_ml=False,
        )
    except Exception:
        cache.delete(lock_key)
        logger.exception('generar_cotizacion_ia falló desde el chat del dueño')
        raise _GeneracionFallida('No pude armar la cotización. El servicio no quedó registrado.')
    if not resultado.get('disponible'):
        cache.delete(lock_key)
        raise _GeneracionFallida(
            resultado.get('error') or 'No pude armar la cotización. El servicio no quedó registrado.'
        )
    if user is not None and getattr(user, 'is_authenticated', False):
        try:
            verificar_y_consumir_cuota(user, ConsumoFeatureMensual.FEATURE_COTIZACION_IA)
        except (CuotaAgotadaError, SinSuscripcionError) as exc:
            cache.delete(lock_key)
            raise _CuotaCotizacion(exc.to_dict().get('error') or str(exc))
    contenido = resultado.get('contenido') or {}
    ctx = resultado.get('contexto') or {}
    marca = veh.get('marca') or ctx.get('vehiculo_marca') or ''
    modelo = veh.get('modelo') or ctx.get('vehiculo_modelo') or ''
    anio = veh.get('anio') or ctx.get('vehiculo_anio')
    try:
        anio_int = int(anio) if anio else None
    except (TypeError, ValueError):
        anio_int = None
    cilindraje = cilindraje_efectivo(
        veh.get('cilindraje') or ctx.get('vehiculo_cilindraje') or '',
        marca,
        modelo,
    )
    repuestos = list(contenido.get('repuestos') or [])
    if slots.get('con_repuestos') is False:
        repuestos = []
    cotizacion = CotizacionCanal.objects.create(
        conversation=None,
        es_libre=True,
        cliente_nombre='',
        cliente_telefono='',
        taller=taller,
        creado_por=user if getattr(user, 'is_authenticated', False) else None,
        estado='borrador',
        modalidad=modalidad,
        direccion_servicio=direccion[:500],
        vehiculo_marca=str(marca)[:100],
        vehiculo_modelo=str(modelo)[:100],
        vehiculo_anio=anio_int,
        vehiculo_patente=str(veh.get('patente') or slots.get('patente') or ctx.get('vehiculo_patente') or '')[:20],
        vehiculo_cilindraje=str(cilindraje or '')[:50],
        vehiculo_vin=str(veh.get('vin') or '')[:50],
        tipo_motor=str(veh.get('tipo_motor') or contenido.get('tipo_motor') or ctx.get('tipo_motor') or '')[:20],
        tipo_motor_label=str(
            veh.get('tipo_motor_label') or contenido.get('tipo_motor_label') or ctx.get('tipo_motor_label') or ''
        )[:80],
        servicio_nombre=servicio[:255],
        descripcion_problema=str(contenido.get('descripcion_problema') or ''),
        repuestos=repuestos,
        mano_obra_clp=contenido.get('mano_obra_clp') or 0,
        costo_repuestos_clp=0 if slots.get('con_repuestos') is False else (contenido.get('costo_repuestos_clp') or 0),
        total_clp=contenido.get('total_clp') or 0,
        duracion_minutos_estimada=contenido.get('duracion_minutos_estimada'),
        advertencias=contenido.get('advertencias') or [],
        politicas_cotizacion=resolver_politicas_cotizacion(taller=taller),
        dias_validez=snapshot_dias_validez(taller),
        contenido_ia=resultado.get('contenido_ia') or {},
        tokens_entrada=resultado.get('tokens_entrada') or 0,
        tokens_salida=resultado.get('tokens_salida') or 0,
        modelo_ia=str(resultado.get('modelo') or '')[:80],
        metadata={
            'origen': 'respaldo' if resultado.get('respaldo_sin_gemini') else 'ia',
            'origen_chat_dueno': True,
            'respaldo_sin_gemini': bool(resultado.get('respaldo_sin_gemini')),
            'vehiculo_color': str(veh.get('color') or '')[:40],
            'vehiculo_motor': str(veh.get('motor') or '')[:80],
            'servicios_lineas': contenido.get('servicios_lineas') or [],
        },
    )
    if slots.get('precio'):
        lineas = resolver_mano_obra_lineas(cotizacion)
        lineas = [{
            'id': (lineas[0]['id'] if lineas else 'mo-1'),
            'nombre': servicio or 'Mano de obra',
            'monto_clp': int(slots['precio']),
        }]
        persistir_mano_obra_lineas(cotizacion, lineas)
    aplicar_totales_cotizacion(cotizacion)
    meta = dict(cotizacion.metadata or {})
    necesita_web = slots.get('con_repuestos') is not False and any(
        linea_necesita_busqueda_web(rep) for rep in (cotizacion.repuestos or []) if isinstance(rep, dict)
    )
    if necesita_web:
        meta = marcar_busqueda_web_pendiente(meta, repuestos=cotizacion.repuestos)
    else:
        meta['busqueda_web_estado'] = 'ok'
        meta['busqueda_web_en'] = timezone.now().isoformat()
    meta['origen_chat_dueno'] = True
    meta['vehiculo_color'] = str(veh.get('color') or '')[:40]
    cotizacion.metadata = meta
    cotizacion.save()
    cache.delete(lock_key)
    asegurar_token_cotizacion(cotizacion)
    asegurar_numero_publico(cotizacion)
    buscando = bool(necesita_web and (cotizacion.metadata or {}).get('busqueda_web_estado') == 'pendiente')
    if buscando:
        disparar_busqueda_web_cotizacion(cotizacion.id, sync=False)
    cotizacion.refresh_from_db()
    return cotizacion, buscando


def _preguntar_destinatario(taller, cotizacion, slots: dict) -> dict:
    nombre = (slots.get('cliente') or '').strip()
    canal = slots.get('canal') or ''
    if nombre and canal:
        contactos = _contactos_canal(taller, nombre, canal)
        if len(contactos) == 1:
            return _proponer_uno(cotizacion, contactos[0], slots, 'canal')
        if len(contactos) > 1:
            return _proponer_varios(cotizacion, contactos, slots, 'canal', nombre)
    personas = _personas_patente(taller, cotizacion)
    if len(personas) == 1:
        return _proponer_uno(cotizacion, personas[0], slots, 'patente')
    if len(personas) > 1:
        return _proponer_varios(
            cotizacion,
            personas,
            slots,
            'patente',
            cotizacion.vehiculo_patente or 'esa patente',
        )
    auto = _frase_auto_cotizacion(cotizacion)
    return _turno(
        haciendo='Busco a quién va la cotización',
        titulo='Cliente nuevo',
        resumen=f'{auto}. ¿A nombre de quién la dejo? El teléfono es opcional. {_HINT_SIN_CANAL}',
        enlace=_enlace(cotizacion, False),
        caso_anclado=_caso_anclado(cotizacion),
        ancla='set',
        accion_pendiente={
            'tipo': 'cotizacion_destinatario',
            'cotizacion_id': cotizacion.id,
            'paso': 'nuevo',
            'opciones': [],
            'slots': _slots_publicos(slots),
        },
    )


def _proponer_uno(cotizacion, opcion: dict, slots: dict, paso: str) -> dict:
    auto = _frase_auto_cotizacion(cotizacion)
    canal = opcion.get('canal_label') or ''
    titulo = ' · '.join(parte for parte in [auto, opcion.get('nombre') or 'Cliente', canal] if parte)
    return _turno(
        haciendo='Busco a quién va la cotización',
        titulo='¿Se la dejo a esta persona?',
        resumen=f'{titulo}. Confirma y la dejo en el borrador. Todavía no se envía.',
        filas=[{
            'id': opcion['id'],
            'titulo': titulo,
            'detalle': opcion.get('detalle') or '',
            'meta': canal or 'Cliente',
        }],
        confirmacion={'etiqueta': 'Sí, es el destinatario', 'tipo': 'accion'},
        enlace=_enlace(cotizacion, False),
        caso_anclado=_caso_anclado(cotizacion),
        ancla='set',
        accion_pendiente={
            'tipo': 'cotizacion_destinatario',
            'cotizacion_id': cotizacion.id,
            'paso': paso,
            'opciones': [opcion],
            'slots': _slots_publicos(slots),
        },
    )


def _proponer_varios(cotizacion, opciones: list[dict], slots: dict, paso: str, quien: str) -> dict:
    return _turno(
        haciendo='Busco a quién va la cotización',
        titulo='Hay más de uno',
        resumen=f'Hay más de un {quien}. Toca la tarjeta que corresponde. No elijo solo.',
        filas=[{
            'id': opcion['id'],
            'titulo': ' · '.join(
                parte for parte in [opcion.get('nombre') or 'Cliente', opcion.get('canal_label') or ''] if parte
            ),
            'detalle': opcion.get('detalle') or '',
            'meta': opcion.get('canal_label') or '',
        } for opcion in opciones[:6]],
        enlace=_enlace(cotizacion, False),
        caso_anclado=_caso_anclado(cotizacion),
        ancla='set',
        accion_pendiente={
            'tipo': 'cotizacion_destinatario',
            'cotizacion_id': cotizacion.id,
            'paso': paso,
            'opciones': opciones[:6],
            'slots': _slots_publicos(slots),
        },
    )


def _resolver_destinatario(taller, texto: str, pendiente: dict) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano
    from mecanimovilapp.apps.ordenes.models import CotizacionCanal

    cotizacion = CotizacionCanal.objects.filter(
        taller=taller,
        id=pendiente.get('cotizacion_id'),
        estado='borrador',
    ).first()
    if cotizacion is None:
        return _turno(
            haciendo='Busco la cotización',
            titulo='Cotización',
            resumen='Ese borrador ya no está.',
            ancla='keep',
            accion_pendiente={},
        )
    p = plano(texto)
    opciones = list(pendiente.get('opciones') or [])
    if pendiente.get('paso') == 'nuevo' or not opciones:
        return _guardar_cliente_nuevo(cotizacion, texto, pendiente)
    if _es_no(p):
        slots = dict(pendiente.get('slots') or {})
        slots['cliente'] = ''
        slots['canal'] = ''
        return _preguntar_destinatario_sin_dicho(taller, cotizacion, slots)
    elegido = None
    match = re.search(r'\belijo\s+(\S+)', p)
    if match:
        elegido = next((op for op in opciones if str(op.get('id')) == match.group(1)), None)
    if elegido is None and len(opciones) == 1 and _es_si(p):
        elegido = opciones[0]
    if elegido is None and len(opciones) > 1:
        elegidos = [op for op in opciones if op.get('nombre') and plano(op['nombre']) in p]
        if len(elegidos) == 1:
            elegido = elegidos[0]
    if elegido is None:
        return _turno(
            haciendo='Espero el destinatario',
            titulo='¿A quién?',
            resumen='Toca una tarjeta o dime el nombre. No elijo solo.',
            filas=[{
                'id': op['id'],
                'titulo': op.get('nombre') or 'Cliente',
                'detalle': op.get('detalle') or '',
                'meta': op.get('canal_label') or '',
            } for op in opciones],
            enlace=_enlace(cotizacion, False),
            ancla='keep',
            accion_pendiente=pendiente,
        )
    return _escribir_destinatario(cotizacion, elegido, pendiente)


def _preguntar_destinatario_sin_dicho(taller, cotizacion, slots: dict) -> dict:
    personas = _personas_patente(taller, cotizacion)
    if len(personas) == 1:
        return _proponer_uno(cotizacion, personas[0], slots, 'patente')
    if len(personas) > 1:
        return _proponer_varios(cotizacion, personas, slots, 'patente', cotizacion.vehiculo_patente or 'esa patente')
    return _preguntar_destinatario(taller, cotizacion, slots)


def _guardar_cliente_nuevo(cotizacion, texto: str, pendiente: dict) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    nombre, telefono, invalido = _partir_nombre_telefono(texto)
    if invalido:
        return _turno(
            haciendo='Reviso el teléfono',
            titulo='Teléfono',
            resumen='El teléfono es opcional. Si lo escribes, tiene que ser +56 y 9 dígitos que empiezan en 9.',
            enlace=_enlace(cotizacion, False),
            ancla='keep',
            accion_pendiente=pendiente,
        )
    if not nombre or plano(nombre) in ('si', 'no', 'ok', 'dale'):
        return _turno(
            haciendo='Espero el nombre',
            titulo='Cliente nuevo',
            resumen=f'¿A nombre de quién la dejo? {_HINT_SIN_CANAL}',
            enlace=_enlace(cotizacion, False),
            ancla='keep',
            accion_pendiente=pendiente,
        )
    return _escribir_destinatario(cotizacion, {
        'nombre': nombre,
        'telefono': telefono,
        'conversation_id': None,
        'canal_label': '',
    }, pendiente)


def _escribir_destinatario(cotizacion, elegido: dict, pendiente: dict) -> dict:
    from mecanimovilapp.apps.chat.models import Conversation

    nombre = (elegido.get('nombre') or '').strip()[:200]
    telefono = (elegido.get('telefono') or '').strip()[:20]
    conversation = None
    conv_id = elegido.get('conversation_id')
    if conv_id:
        conversation = Conversation.objects.filter(id=conv_id).first()
    cotizacion.cliente_nombre = nombre
    cotizacion.cliente_telefono = telefono
    campos = ['cliente_nombre', 'cliente_telefono', 'actualizado_en']
    if conversation is not None:
        cotizacion.conversation = conversation
        cotizacion.es_libre = False
        campos.extend(['conversation', 'es_libre'])
    cotizacion.save(update_fields=campos)
    cotizacion.refresh_from_db()
    canal = elegido.get('canal_label') or ''
    donde = f', {canal}' if canal else ''
    aviso = '' if conversation is not None else f' {_HINT_SIN_CANAL}'
    slots = dict(pendiente.get('slots') or {})
    slots['cliente'] = nombre
    return _turno(
        haciendo='Dejo el destinatario en el borrador',
        titulo='Destinatario',
        resumen=(
            f'Quedó a nombre de {nombre}{donde}. '
            f'El borrador sigue sin enviarse.{aviso} '
            'Cuando quieras enviarla, dímelo.'
        ),
        enlace=_enlace(cotizacion, False),
        caso_anclado=_caso_anclado(cotizacion),
        ancla='set',
        accion_pendiente={
            'tipo': 'cotizacion_lista',
            'cotizacion_id': cotizacion.id,
            'slots': _slots_publicos(slots),
        },
    )


def _preparar_envio(taller, cotizacion, slots: dict) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import clp

    if not (cotizacion.cliente_nombre or '').strip():
        return _preguntar_destinatario(taller, cotizacion, slots)
    if cotizacion.modalidad == 'domicilio' and _direccion_sin_calle(cotizacion.direccion_servicio):
        lugar = (cotizacion.direccion_servicio or 'el domicilio').strip()
        return _turno(
            haciendo='Reviso la dirección',
            titulo='Calle',
            resumen=(
                f'¿En qué calle de {lugar}? Con la comuna bastó para armar. '
                'Para enviarla a domicilio falta la calle.'
            ),
            enlace=_enlace(cotizacion, False),
            caso_anclado=_caso_anclado(cotizacion),
            ancla='set',
            accion_pendiente={
                'tipo': 'cotizacion_calle',
                'cotizacion_id': cotizacion.id,
                'slots': _slots_publicos(slots),
            },
        )
    caso = _caso_anclado(cotizacion)
    return _turno(
        haciendo='Reviso la cotización',
        titulo='Enviar cotización',
        resumen=f"Total ${clp(int(cotizacion.total_clp or 0))}. La envío cuando confirmes.",
        confirmacion={'etiqueta': 'Sí, enviar', 'tipo': 'accion'},
        enlace=_enlace(cotizacion, False),
        caso_anclado=caso,
        ancla='set',
        accion_pendiente={
            'tipo': 'enviar_cotizacion',
            'caso_id': caso.get('id'),
            'cotizacion_id': cotizacion.id,
        },
    )


def _resolver_calle(taller, texto, pendiente) -> dict:
    from mecanimovilapp.apps.ordenes.models import CotizacionCanal

    cotizacion = CotizacionCanal.objects.filter(
        taller=taller,
        id=pendiente.get('cotizacion_id'),
        estado='borrador',
    ).first()
    if cotizacion is None:
        return _turno(
            haciendo='Reviso la dirección',
            titulo='Cotización',
            resumen='Ese borrador ya no está.',
            accion_pendiente={},
            ancla='keep',
        )
    calle = (texto or '').strip()
    if len(calle) < 4:
        return _turno(
            haciendo='Reviso la dirección',
            titulo='Calle',
            resumen='Dime la calle y el número.',
            enlace=_enlace(cotizacion, False),
            ancla='keep',
            accion_pendiente=pendiente,
        )
    comuna = (cotizacion.direccion_servicio or '').strip()
    if comuna and comuna.lower() not in calle.lower():
        cotizacion.direccion_servicio = f'{calle}, {comuna}'[:500]
    else:
        cotizacion.direccion_servicio = calle[:500]
    cotizacion.save(update_fields=['direccion_servicio', 'actualizado_en'])
    return _preparar_envio(taller, cotizacion, dict(pendiente.get('slots') or {}))


def _aplicar_precio_dicho(taller, cotizacion, texto: str, slots: dict) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import clp
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.mano_obra_lineas import (
        persistir_mano_obra_lineas,
        resolver_mano_obra_lineas,
    )
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
        aplicar_totales_cotizacion,
    )
    from mecanimovilapp.apps.servicios.models import OfertaServicio

    monto = _precio_en(texto, cotizacion.vehiculo_anio)
    if not monto:
        return _turno_doc(cotizacion, slots, 'No reconocí el monto de la mano de obra.')
    antes = OfertaServicio.objects.filter(taller=taller).count()
    lineas = resolver_mano_obra_lineas(cotizacion)
    persistir_mano_obra_lineas(cotizacion, [{
        'id': (lineas[0]['id'] if lineas else 'mo-1'),
        'nombre': cotizacion.servicio_nombre or 'Mano de obra',
        'monto_clp': monto,
    }])
    aplicar_totales_cotizacion(cotizacion)
    _guardar_listo(cotizacion, _pendientes_precio(cotizacion))
    cotizacion.save()
    if OfertaServicio.objects.filter(taller=taller).count() != antes:
        logger.error('El precio del chat del dueño tocó una oferta del taller %s', taller.id)
    slots = dict(slots)
    slots['precio'] = monto
    return _turno(
        haciendo='Escribo la mano de obra de esta cotización',
        titulo=cotizacion.numero_publico or 'Cotización',
        resumen=(
            f"La mano de obra de este borrador quedó en ${clp(monto)}. "
            'No cambié los servicios del taller.'
        ),
        enlace=_enlace(cotizacion, False),
        caso_anclado=_caso_anclado(cotizacion),
        ancla='set',
        accion_pendiente={
            'tipo': 'cotizacion_lista',
            'cotizacion_id': cotizacion.id,
            'slots': _slots_publicos(slots),
        },
    )


def _dejar_sin_repuestos(cotizacion, slots: dict) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import clp
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
        aplicar_totales_cotizacion,
    )

    cotizacion.repuestos = []
    aplicar_totales_cotizacion(cotizacion)
    meta = dict(cotizacion.metadata or {})
    meta['busqueda_web_estado'] = 'ok'
    cotizacion.metadata = meta
    _guardar_listo(cotizacion, _pendientes_precio(cotizacion))
    cotizacion.save()
    return _turno(
        haciendo='Dejo solo la mano de obra',
        titulo=cotizacion.numero_publico or 'Cotización',
        resumen=f"Quedó solo la mano de obra. Total ${clp(int(cotizacion.total_clp or 0))}.",
        enlace=_enlace(cotizacion, False),
        caso_anclado=_caso_anclado(cotizacion),
        ancla='set',
        accion_pendiente={
            'tipo': 'cotizacion_lista',
            'cotizacion_id': cotizacion.id,
            'slots': _slots_publicos(slots),
        },
    )


def _consultar_patente(patente: str, user) -> dict:
    from mecanimovilapp.apps.suscripciones.cuotas_services import (
        CuotaAgotadaError,
        SinSuscripcionError,
        verificar_y_consumir_cuota,
    )
    from mecanimovilapp.apps.suscripciones.models import ConsumoFeatureMensual
    from mecanimovilapp.apps.vehiculos.services.guest_patente_lookup import fetch_patente_normalized

    if user is not None and getattr(user, 'is_authenticated', False):
        try:
            verificar_y_consumir_cuota(user, ConsumoFeatureMensual.FEATURE_CONSULTA_PATENTE)
        except (CuotaAgotadaError, SinSuscripcionError) as exc:
            return {
                'ok': False,
                'aviso': exc.to_dict().get('error') or f'No pude consultar la patente {patente}.',
            }
    try:
        payload, _status, error = fetch_patente_normalized(patente, include_private_fields=True)
    except Exception:
        logger.exception('consultar patente %s desde el chat del dueño', patente)
        payload, error = None, 'servicio_externo'
    if not payload:
        if error == 'patente_no_encontrada':
            aviso = (
                f'La patente {patente} no está en el registro. '
                'Armé el borrador con lo que me dijiste.'
            )
        else:
            aviso = f'No pude consultar la patente {patente}. Armé el borrador con lo que me dijiste.'
        return {'ok': False, 'aviso': aviso}
    anio = payload.get('year')
    try:
        anio_int = int(anio) if anio else None
    except (TypeError, ValueError):
        anio_int = None
    combustible = str(payload.get('tipo_motor') or '').strip()
    return {
        'ok': True,
        'vehiculo': {
            'marca': str(payload.get('marca_nombre') or '').strip(),
            'modelo': str(payload.get('modelo_nombre') or '').strip(),
            'anio': anio_int,
            'patente': patente,
            'color': str(payload.get('color') or '').strip(),
            'motor': str(payload.get('motor') or '').strip(),
            'cilindraje': str(payload.get('cilindraje') or '').strip(),
            'vin': str(payload.get('vin') or '').strip(),
            'tipo_motor': combustible[:20],
            'tipo_motor_label': combustible[:80],
        },
    }


def _leer_patente(texto: str) -> str:
    match = _PATENTE_RE.search(texto or '')
    if not match:
        return ''
    compacta = re.sub(r'[^a-z0-9]', '', match.group(1), flags=re.IGNORECASE).upper()
    if not re.search(r'[A-Z]', compacta) or not re.search(r'\d', compacta):
        return ''
    if not (5 <= len(compacta) <= 6):
        return ''
    return compacta


def _sin_patente(texto: str, patente: str) -> str:
    limpio = _PATENTE_RE.sub(' ', texto or '')
    if patente:
        limpio = re.sub(re.escape(patente), ' ', limpio, flags=re.IGNORECASE)
        letras = patente[:4] if len(patente) >= 6 else ''
        if len(letras) == 4:
            limpio = re.sub(rf'\b{letras}\b', ' ', limpio, flags=re.IGNORECASE)
    return limpio


def _extraer(texto: str) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    patente = _leer_patente(texto)
    p = plano(_sin_patente(texto, patente))
    out: dict = {}
    if patente:
        out['patente'] = patente
    cliente = re.search(r'\bcliente\s+([a-zñ]+(?:\s+[a-zñ]+)?)\b', p)
    if cliente:
        nombre = re.split(r'\b(del|de|chat|por)\b', cliente.group(1))[0].strip()
        if nombre and nombre not in ('del', 'de', 'chat'):
            out['cliente'] = _titulo(nombre)
    if re.search(r'\b(facebook|messenger)\b', p):
        out['canal'] = 'MESSENGER'
    elif re.search(r'\binstagram\b', p):
        out['canal'] = 'INSTAGRAM'
    elif re.search(r'\b(whatsapp|wsp)\b', p):
        out['canal'] = 'WHATSAPP'
    if re.search(r'\ba domicilio\b|\bdomicilio\b', p):
        out['modalidad'] = 'domicilio'
    elif re.search(r'\ben el taller\b|\ben taller\b', p):
        out['modalidad'] = 'taller'
    comuna = re.search(r'comuna de\s+([a-zñ ]+)', p)
    if not comuna:
        comuna = re.search(r'a domicilio en\s+(?:la comuna de\s+)?([a-zñ ]+)', p)
    if comuna:
        lugar = re.split(r'\b(patente|cliente|para|cambio)\b', comuna.group(1))[0].strip(' .,) ')
        if lugar:
            out['direccion'] = _titulo(lugar)
    if re.search(r'\bsin repuestos\b|\bsolo mano de obra\b|\bsin piezas\b', p):
        out['con_repuestos'] = False
    elif re.search(r'\bcon repuestos\b|\bincluye repuestos\b|\bcon piezas\b', p):
        out['con_repuestos'] = True
    servicio = _SERVICIO_RE.search(p)
    if servicio:
        nombre = _limpiar_servicio(servicio.group(1))
        if nombre:
            out['servicio'] = nombre[:1].upper() + nombre[1:]
    anio = _ANIO_RE.search(p)
    if anio:
        out['anio'] = int(anio.group(1))
    out.update(_extraer_marca_modelo(p, out.get('anio')))
    precio = _precio_en(texto, out.get('anio'))
    if precio and not _es_telefono(texto):
        out['precio'] = precio
    return out


def _extraer_marca_modelo(p: str, anio) -> dict:
    resto = _SERVICIO_RE.sub(' ', p)
    resto = re.sub(r'\bcliente\s+[a-zñ]+(?:\s+[a-zñ]+)?', ' ', resto)
    ruido = {'de', 'del', 'la', 'el', 'para', 'un', 'una', 'los', 'las'}
    for match in re.finditer(
        r'\bpara\s+([a-zñ]+(?:\s+[a-zñ]+){0,3})(?:\s+((?:19|20)\d{2}))?',
        resto,
    ):
        tokens = [tok for tok in match.group(1).split() if tok not in ruido]
        if len(tokens) < 2 or tokens[0] in ('cliente', 'chat', 'domicilio', 'comuna'):
            continue
        data = {'marca': _titulo(tokens[0]), 'modelo': _titulo(' '.join(tokens[1:3]))}
        if match.group(2):
            data['anio'] = int(match.group(2))
        return data
    if anio:
        match = re.search(rf'\b([a-zñ]+(?:\s+[a-zñ]+){{1,2}})\s+{anio}\b', resto)
        if match:
            tokens = [tok for tok in match.group(1).split() if tok not in ruido and tok != 'ano']
            if len(tokens) >= 2 and tokens[0] not in ('patente', 'comuna', 'cliente', 'cambio', 'chat'):
                return {'marca': _titulo(tokens[0]), 'modelo': _titulo(' '.join(tokens[1:]))}
    return {}


def _fusionar(base: dict, nuevo: dict) -> dict:
    slots = {
        'servicio': '',
        'patente': '',
        'marca': '',
        'modelo': '',
        'anio': None,
        'modalidad': '',
        'direccion': '',
        'cliente': '',
        'canal': '',
        'precio': None,
        'con_repuestos': None,
        'aviso_patente': '',
        'vehiculo': None,
        'api': None,
        'conflicto_visto': False,
    }
    slots.update({clave: valor for clave, valor in (base or {}).items() if clave in slots})
    for clave, valor in nuevo.items():
        if valor is None or valor == '':
            continue
        slots[clave] = valor
    return slots


def _falta_para_armar(slots: dict) -> str:
    sin_servicio = not (slots.get('servicio') or '').strip()
    sin_auto = not (slots.get('patente') or '').strip() and not (
        (slots.get('marca') or '').strip() and (slots.get('modelo') or '').strip()
    )
    if sin_servicio and sin_auto:
        return '¿Qué servicio cotizo, y de qué auto? Con la patente o con marca y modelo alcanza.'
    if sin_servicio:
        return '¿Qué servicio cotizo?'
    if sin_auto:
        return '¿De qué auto? Dime la patente, o la marca y el modelo.'
    return ''


def _choque_vehiculo(slots: dict, api: dict) -> str:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    dicho_marca = plano(slots.get('marca') or '')
    api_marca = plano(api.get('marca') or '')
    dicho_anio = slots.get('anio')
    api_anio = api.get('anio')
    marca_distinta = bool(
        dicho_marca and api_marca and dicho_marca not in api_marca and api_marca not in dicho_marca
    )
    anio_distinto = bool(dicho_anio and api_anio and int(dicho_anio) != int(api_anio))
    if not marca_distinta and not anio_distinto:
        return ''
    return (
        f"Dijiste {_frase_vehiculo(_vehiculo_dicho(slots))}. "
        f"La patente {slots.get('patente')} figura como {_frase_vehiculo(api)}. "
        '¿Cuál dejo en la cotización?'
    )


def _elegir_lado(texto: str, api: dict, dueno: dict) -> str | None:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    p = plano(texto)
    if re.search(r'\b(la que dije|lo que dije|dije yo|mi version|como dije)\b', p):
        return 'dueno'
    if re.search(r'\b(del registro|la patente|el padron|la del registro)\b', p):
        return 'api'
    api_marca = plano(api.get('marca') or '')
    dueno_marca = plano(dueno.get('marca') or '')
    tiene_api = bool(api_marca and api_marca in p)
    tiene_dueno = bool(dueno_marca and dueno_marca in p)
    if tiene_api and not tiene_dueno:
        return 'api'
    if tiene_dueno and not tiene_api:
        return 'dueno'
    return None


def _vehiculo_dicho(slots: dict) -> dict:
    return {
        'marca': slots.get('marca') or '',
        'modelo': slots.get('modelo') or '',
        'anio': slots.get('anio'),
        'patente': slots.get('patente') or '',
        'color': '',
        'motor': '',
        'cilindraje': '',
        'vin': '',
        'tipo_motor': '',
        'tipo_motor_label': '',
    }


def _completar_vehiculo(base: dict | None, slots: dict) -> dict:
    dicho = _vehiculo_dicho(slots)
    fuente = dict(base or {})
    for clave, valor in dicho.items():
        if fuente.get(clave) in (None, '') and valor not in (None, ''):
            fuente[clave] = valor
    if not fuente.get('patente'):
        fuente['patente'] = slots.get('patente') or ''
    return fuente


def _contactos_canal(taller, nombre: str, canal: str) -> list[dict]:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano
    from mecanimovilapp.apps.chat.models import Conversation

    usuario_id = getattr(taller, 'usuario_id', None)
    if not usuario_id or not nombre:
        return []
    qs = (
        Conversation.objects.filter(participants=usuario_id, source_channel=canal)
        .select_related('external_contact')
        .order_by('-updated_at')[:80]
    )
    buscado = plano(nombre)
    vistos = []
    for conv in qs:
        ext = conv.external_contact
        display = (getattr(ext, 'display_name', '') or '').strip()
        if buscado not in plano(display).split():
            continue
        telefono = ''
        if ext is not None and hasattr(ext, 'telefono_efectivo'):
            telefono = ext.telefono_efectivo() or ''
        vistos.append({
            'id': f'dest:{conv.id}',
            'nombre': display,
            'telefono': telefono,
            'conversation_id': conv.id,
            'canal_label': _CANAL_LABEL.get(canal, canal),
            'detalle': telefono,
        })
    return vistos


def _personas_patente(taller, cotizacion) -> list[dict]:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano
    from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, CotizacionCanal

    patente = (cotizacion.vehiculo_patente or '').strip()
    if not patente:
        return []
    vistos: list[dict] = []
    claves = set()

    def agregar(nombre: str, telefono: str, conversation_id, canal: str, detalle: str):
        nombre = (nombre or '').strip()
        telefono = (telefono or '').strip()
        if not nombre and not telefono:
            return
        clave = (plano(nombre), telefono)
        if clave in claves:
            return
        claves.add(clave)
        vistos.append({
            'id': f'persona:{len(vistos)}',
            'nombre': nombre or 'Cliente',
            'telefono': telefono,
            'conversation_id': conversation_id,
            'canal_label': canal,
            'detalle': detalle,
        })

    otras = (
        CotizacionCanal.objects.filter(taller=taller, vehiculo_patente__iexact=patente)
        .exclude(id=cotizacion.id)
        .select_related('conversation')
        .order_by('-actualizado_en')[:12]
    )
    for otra in otras:
        canal = ''
        conv = otra.conversation
        if conv is not None:
            canal = _CANAL_LABEL.get(conv.source_channel, '')
        agregar(
            otra.cliente_nombre,
            otra.cliente_telefono,
            otra.conversation_id,
            canal,
            ' '.join(parte for parte in [otra.cliente_telefono or '', canal] if parte),
        )
    citas = (
        CitaAgendaPersonal.objects.filter(taller=taller, detalle__vehiculo_patente__iexact=patente)
        .select_related('detalle')
        .order_by('-fecha_servicio')[:12]
    )
    for cita in citas:
        det = getattr(cita, 'detalle', None)
        agregar(
            getattr(det, 'cliente_nombre', ''),
            getattr(det, 'cliente_telefono', ''),
            None,
            '',
            getattr(det, 'cliente_telefono', '') or 'Cita del taller',
        )
    return vistos


def _pendientes_precio(cotizacion) -> list[str]:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.resolver_precio import (
        CERTEZA_ASUMIDO,
        CERTEZA_CONFIRMADO,
        backfill_certeza,
    )

    pendientes = []
    if int(cotizacion.mano_obra_clp or 0) <= 0:
        pendientes.append(f"Falta precio de {cotizacion.servicio_nombre or 'la mano de obra'}")
    for rep in cotizacion.repuestos or []:
        if not isinstance(rep, dict):
            continue
        if backfill_certeza(rep) in (CERTEZA_CONFIRMADO, CERTEZA_ASUMIDO):
            continue
        nombre = (rep.get('nombre') or 'un repuesto').strip()
        pendientes.append(f'Falta precio de {nombre}')
    return pendientes


def _guardar_listo(cotizacion, pendientes: list[str]) -> None:
    meta = dict(cotizacion.metadata or {})
    meta['origen_chat_dueno'] = True
    meta['listo_para_enviar'] = len(pendientes) == 0
    meta['pendientes_revision'] = pendientes
    cotizacion.metadata = meta


def _enlace(cotizacion, buscando: bool) -> dict:
    auto = _frase_auto_cotizacion(cotizacion)
    folio = cotizacion.numero_publico or 'Borrador'
    servicio = cotizacion.servicio_nombre or 'Servicio'
    titulo = f'{folio}: {servicio}'
    if auto:
        titulo = f'{titulo} · {auto}'
    return {
        'cotizacion_id': cotizacion.id,
        'busqueda_pendiente': bool(buscando),
        'titulo': titulo[:180],
        'descripcion': 'Borrador para revisar y enviar. El cliente todavía no lo recibe.',
        'es_borrador': True,
    }


def _seguir_borrador(taller, cotizacion, texto: str, slots: dict) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    p = plano(texto)
    if _es_precio_solo(texto):
        return _aplicar_precio_dicho(taller, cotizacion, texto, slots)
    if _dijo_sin_repuestos(p):
        return _dejar_sin_repuestos(cotizacion, slots)
    if _es_aprobacion(p):
        return _preguntar_destinatario(taller, cotizacion, slots)
    if _es_envio(p):
        return _preparar_envio(taller, cotizacion, slots)
    return _turno_doc(cotizacion, slots, _respuesta_sobre_borrador(cotizacion, texto))


def _trabajo_distinto(texto: str, slots: dict, cotizacion) -> bool:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    extra = _extraer(texto)
    patente_actual = (slots.get('patente') or cotizacion.vehiculo_patente or '').upper()
    if extra.get('patente') and extra['patente'] != patente_actual:
        return True
    nuevo = plano(extra.get('servicio') or '')
    actual = plano(cotizacion.servicio_nombre or slots.get('servicio') or '')
    if nuevo and actual and nuevo not in actual and actual not in nuevo:
        return True
    return False


def _respuesta_sobre_borrador(cotizacion, texto: str) -> str:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    p = plano(texto)
    auto = _frase_auto_cotizacion(cotizacion)
    patente = (cotizacion.vehiculo_patente or '').strip()
    piezas = [
        str(rep.get('nombre') or '').strip()
        for rep in (cotizacion.repuestos or [])
        if isinstance(rep, dict) and (rep.get('nombre') or '').strip()
    ]
    base = f"Sigo en el borrador de {cotizacion.servicio_nombre} para {auto}."
    if patente:
        base = f"{base} Patente {patente}."
    if piezas and re.search(r'repuesto|pieza|incluye|lleva|kit|aceite|hidraulic|precio|desglose|cotiz', p):
        lista = ', '.join(piezas[:6])
        return (
            f"{base} Las piezas que armé son: {lista}. "
            'El desglose está abajo, con el origen de cada precio. '
            'Ábrelo para revisarlo. El cliente todavía no lo recibe.'
        )
    return (
        f"{base} {_frase_desglose(cotizacion, False)} "
        'Ábrelo para revisarlo y enviarlo. El cliente todavía no lo recibe.'
    )


def _filas_desglose(cotizacion, buscando: bool) -> list[dict]:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import clp
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.mano_obra_lineas import (
        resolver_mano_obra_lineas,
    )

    filas = []
    for linea in resolver_mano_obra_lineas(cotizacion):
        monto = int(linea.get('monto_clp') or 0)
        filas.append({
            'id': f"mo-{linea.get('id') or len(filas)}",
            'titulo': linea.get('nombre') or 'Mano de obra',
            'detalle': 'Mano de obra de este borrador.',
            'meta': f"${clp(monto)}" if monto else 'Sin precio',
        })
    for indice, rep in enumerate(cotizacion.repuestos or []):
        if not isinstance(rep, dict):
            continue
        nombre = (rep.get('nombre') or 'Repuesto').strip()
        detalle = _detalle_repuesto(rep, buscando)
        precio = int(rep.get('precio_unitario_clp') or 0)
        filas.append({
            'id': f"rep-{rep.get('id') or indice}",
            'titulo': nombre[:120],
            'detalle': detalle[:240],
            'meta': f"${clp(precio)}" if precio else 'Sin precio',
        })
    return filas[:20]


def _detalle_repuesto(rep: dict, buscando: bool) -> str:
    partes = []
    especificacion = (rep.get('especificacion') or '').strip()
    if especificacion:
        partes.append(especificacion)
    if rep.get('especificacion_pendiente'):
        partes.append('Falta confirmar la variante de esta pieza.')
    partes.append(_origen_precio(rep, buscando))
    comentario = (rep.get('comentario') or '').strip()
    if comentario:
        partes.append(comentario)
    return '. '.join(parte for parte in partes if parte)


def _origen_precio(rep: dict, buscando: bool) -> str:
    fuente = str(rep.get('fuente_marketplace') or '').strip().lower()
    precio = int(rep.get('precio_unitario_clp') or 0)
    if fuente in ('catalogo', 'catálogo', 'proveedor'):
        return 'Precio del taller.'
    if fuente == 'historial':
        return 'Precio del historial del taller.'
    if fuente in ('web', 'ml', 'mercadolibre'):
        return 'Precio consultado en tiendas.'
    if precio <= 0 and (buscando or rep.get('motivo_sin_precio')):
        return 'Buscando el precio en tiendas.'
    if precio <= 0:
        return 'Todavía sin precio de tienda.'
    if rep.get('precio_estimado') or rep.get('precio_referencia_mercado'):
        return 'Precio de referencia, hay que confirmarlo.'
    return 'Precio de referencia.'


def _frase_desglose(cotizacion, buscando: bool) -> str:
    nombres = [
        str(rep.get('nombre') or '').strip()
        for rep in (cotizacion.repuestos or [])
        if isinstance(rep, dict) and (rep.get('nombre') or '').strip()
    ]
    if not nombres:
        return 'Quedó la mano de obra, sin líneas de repuesto.'
    lista = ', '.join(nombres[:6])
    if buscando:
        return f"Armé los repuestos: {lista}. Estoy consultando esos precios en tiendas."
    sin_precio = [
        nombre for nombre, rep in (
            (str(rep.get('nombre') or '').strip(), rep)
            for rep in (cotizacion.repuestos or [])
            if isinstance(rep, dict)
        )
        if nombre and int(rep.get('precio_unitario_clp') or 0) <= 0
    ]
    if sin_precio:
        return (
            f"Armé los repuestos: {lista}. "
            f"Sin precio de tienda: {', '.join(sin_precio[:4])}."
        )
    return f"Armé los repuestos: {lista}. Cada línea dice de dónde salió el precio."


def _borrador_chat(taller, hilo):
    from mecanimovilapp.apps.ordenes.models import CotizacionCanal

    pendiente = hilo.accion_pendiente if isinstance(hilo.accion_pendiente, dict) else {}
    cid = pendiente.get('cotizacion_id')
    if not cid and isinstance(getattr(hilo, 'caso_anclado', None), dict):
        cid = hilo.caso_anclado.get('cotizacion_id') or hilo.caso_anclado.get('documento_id')
    if not cid:
        return None
    cotizacion = CotizacionCanal.objects.filter(taller=taller, id=cid, estado='borrador').first()
    if cotizacion is None:
        return None
    meta = cotizacion.metadata if isinstance(cotizacion.metadata, dict) else {}
    if not meta.get('origen_chat_dueno'):
        return None
    return cotizacion


def _precio_en(texto: str, anio) -> int | None:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    mil = re.search(r'\b(\d{2,3})\s*mil\b', plano(texto))
    if mil:
        return int(mil.group(1)) * 1000
    limpio = _PATENTE_RE.sub(' ', texto)
    for match in re.finditer(r'(\d{1,3}(?:\.\d{3})+|\d{5,8})', limpio):
        numero = int(match.group(1).replace('.', ''))
        if anio and numero == int(anio):
            continue
        if 1000 <= numero <= 20000000:
            return numero
    return None


def _es_precio_solo(texto: str) -> bool:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    if re.search(r'[a-zñ]{3,}', plano(texto)):
        return False
    return _precio_en(texto, None) is not None


def _es_telefono(texto: str) -> bool:
    digitos = ''.join(ch for ch in texto if ch.isdigit())
    return digitos.startswith('569') and len(digitos) >= 11


def _partir_nombre_telefono(texto: str) -> tuple[str, str, bool]:
    crudo = (texto or '').strip()
    digitos = ''.join(ch for ch in crudo if ch.isdigit())
    telefono = ''
    invalido = False
    if len(digitos) >= 8:
        nacional = digitos[2:] if digitos.startswith('56') else digitos
        if len(nacional) == 9 and nacional.startswith('9'):
            telefono = f'+56{nacional}'
        else:
            invalido = True
    nombre = ' '.join(re.sub(r'\+?\d[\d\s-]{6,}', ' ', crudo).split())
    return nombre[:200], telefono, invalido and bool(digitos)


def _direccion_sin_calle(direccion: str) -> bool:
    texto = (direccion or '').strip()
    if not texto:
        return True
    return re.search(r'\d', texto) is None


def _limpiar_servicio(nombre: str) -> str:
    corte = re.split(
        r'\b(para|patente|domicilio|cliente|con repuestos|sin repuestos|a domicilio)\b',
        nombre,
        maxsplit=1,
    )[0]
    return ' '.join(corte.split()).strip(' ,.')


def _titulo(texto: str) -> str:
    partes = []
    for i, parte in enumerate((texto or '').split()):
        if i and parte in _MENORES:
            partes.append(parte)
        else:
            partes.append(parte[:1].upper() + parte[1:])
    return ' '.join(partes)


def _frase_vehiculo(veh: dict | None) -> str:
    if not veh:
        return 'el auto'
    base = ' '.join(parte for parte in [str(veh.get('marca') or ''), str(veh.get('modelo') or '')] if parte).strip()
    if veh.get('anio'):
        base = f"{base} {veh.get('anio')}".strip()
    patente = str(veh.get('patente') or '').strip()
    if patente:
        base = f'{base}, patente {patente}'.strip(', ')
    return base or 'el auto'


def _frase_auto_cotizacion(cotizacion) -> str:
    base = ' '.join(
        parte for parte in [cotizacion.vehiculo_marca, cotizacion.vehiculo_modelo] if parte
    ).strip()
    if cotizacion.vehiculo_anio:
        base = f'{base} {cotizacion.vehiculo_anio}'.strip()
    if cotizacion.vehiculo_patente:
        base = f'{base} patente {cotizacion.vehiculo_patente}'.strip()
    return base


def _caso_anclado(cotizacion) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import _caso_cotizacion

    return _caso_cotizacion(cotizacion, _hoy())


def _slots_publicos(slots: dict) -> dict:
    return {
        'servicio': slots.get('servicio') or '',
        'patente': slots.get('patente') or '',
        'marca': slots.get('marca') or '',
        'modelo': slots.get('modelo') or '',
        'anio': slots.get('anio'),
        'modalidad': slots.get('modalidad') or '',
        'direccion': slots.get('direccion') or '',
        'cliente': slots.get('cliente') or '',
        'canal': slots.get('canal') or '',
        'precio': slots.get('precio'),
        'con_repuestos': slots.get('con_repuestos'),
        'aviso_patente': slots.get('aviso_patente') or '',
        'conflicto_visto': bool(slots.get('conflicto_visto')),
        'api': slots.get('api'),
        'vehiculo': slots.get('vehiculo'),
    }


def _slots_con_api(slots: dict) -> dict:
    data = _slots_publicos(slots)
    data['api'] = slots.get('api')
    data['conflicto_visto'] = True
    return data


def _pasos_armado(cotizacion, slots: dict, buscando: bool) -> list[dict]:
    patente = (cotizacion.vehiculo_patente or slots.get('patente') or '').strip()
    pasos = []
    if patente:
        if slots.get('aviso_patente'):
            pasos.append({'texto': str(slots['aviso_patente'])[:180], 'estado': 'hecho'})
        else:
            pasos.append({'texto': f'Consulté la patente {patente}', 'estado': 'hecho'})
    else:
        pasos.append({'texto': 'Usé el auto que me dijiste', 'estado': 'hecho'})
    pasos.append({
        'texto': f"Armé {cotizacion.servicio_nombre or 'la cotización'} con mano de obra y repuestos",
        'estado': 'hecho',
    })
    if buscando:
        pasos.append({'texto': 'Buscando los precios en tiendas', 'estado': 'ahora'})
    else:
        pasos.append({'texto': 'El borrador está listo para revisarlo', 'estado': 'ahora'})
    return pasos


def _haciendo_armado(slots: dict, buscando: bool) -> str:
    if buscando:
        return 'Buscando repuestos…'
    servicio = slots.get('servicio') or 'la cotización'
    veh = slots.get('vehiculo') or {}
    auto = ' '.join(
        parte for parte in [
            str(veh.get('marca') or slots.get('marca') or ''),
            str(veh.get('modelo') or slots.get('modelo') or ''),
        ] if parte
    ).strip()
    anio = veh.get('anio') or slots.get('anio')
    if anio:
        auto = f'{auto} {anio}'.strip()
    if auto:
        return f'Armando {servicio} para {auto}…'
    return f'Armando {servicio}…'


def _turno_doc(cotizacion, slots: dict, resumen: str) -> dict:
    return _turno(
        haciendo='Sigo con la cotización',
        titulo=cotizacion.numero_publico or 'Borrador',
        resumen=resumen,
        filas=_filas_desglose(cotizacion, False),
        enlace=_enlace(cotizacion, False),
        caso_anclado=_caso_anclado(cotizacion),
        ancla='set',
        accion_pendiente={
            'tipo': 'cotizacion_lista',
            'cotizacion_id': cotizacion.id,
            'slots': _slots_publicos(slots),
        },
    )


def _turno(**kwargs) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import _turno as base

    return base(**kwargs)


def _hoy():
    from django.utils import timezone

    return timezone.localdate()


def _es_aprobacion(p: str) -> bool:
    return bool(re.search(
        r'\b(esta bien|estan bien|apruebo|aprobada|asi dejala|dejala asi|queda bien|me sirve|asi esta)\b',
        p,
    ))


def _es_envio(p: str) -> bool:
    return bool(re.search(
        r'\b(enviasela|enviala|mandasela|mandala|enviamela|envia la cotizacion|enviar la cotizacion)\b',
        p,
    ))


def _dijo_sin_repuestos(p: str) -> bool:
    return bool(re.search(r'\bsin repuestos\b|\bsolo mano de obra\b|\bsin piezas\b', p))


def _es_otro_pedido(p: str) -> bool:
    return bool(re.search(r'que tengo|cuantos servicios|rendimient|agendamient|que hay hoy', p))


def _es_si(p: str) -> bool:
    return bool(re.match(r'^(si|dale|confirmo|ok|okay|de acuerdo|hazlo|adelante|claro)\b', p))


def _es_no(p: str) -> bool:
    return bool(re.match(r'^(no|nop|otro|otra)\b', p))


class _CuotaCotizacion(Exception):
    def __init__(self, mensaje: str):
        super().__init__(mensaje)
        self.mensaje = mensaje


class _GeneracionFallida(Exception):
    def __init__(self, mensaje: str):
        super().__init__(mensaje)
        self.mensaje = mensaje
