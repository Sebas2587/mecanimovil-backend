"""Tareas del dueño: leen el taller, dejan el trabajo hecho y muestran el paso."""
from __future__ import annotations

import logging
import re
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

_CANAL = {
    'whatsapp': 'WhatsApp',
    'messenger': 'Facebook',
    'instagram': 'Instagram',
    'app': 'la app',
}
_NECESIDAD = re.compile(
    r'\b(embrague|pastillas|aceite|frenos|bujias|distribucion|amortiguador|bateria|correa|filtro)\b',
)
_NOMBRE_CASA = re.compile(
    r'ltda|eirl|\bspa\b|motors|motores|baterias|automotriz|repuestos|electromec|vulca|chinauto|portal',
    re.IGNORECASE,
)
_TOPE_BORRADORES = 5


def turno_clientes_esperando(taller, user) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import _turno

    clientes = clientes_esperando(taller, user)
    if not clientes:
        return _turno(
            haciendo='Reviso quién espera cotización',
            titulo='Clientes de hoy',
            resumen=(
                'Entre hoy y ayer no hay clientes esperando cotización. '
                'Miré quién escribió, dejé fuera casas de repuestos, saludos e imágenes, '
                'y a quien ya tiene una cotización enviada.'
            ),
            ancla='keep',
            accion_pendiente={},
            pasos=[
                {'texto': 'Leí los mensajes de hoy y de ayer', 'estado': 'hecho'},
                {'texto': 'Ninguno pide un servicio y manda la patente sin cotización enviada', 'estado': 'ahora'},
            ],
            siguiente='Cuando escriba un cliente, pregúntame de nuevo.',
        )
    return _turno(
        haciendo='Reviso quién espera cotización',
        titulo='Clientes de hoy',
        resumen=_resumen_esperando(clientes),
        filas=_filas_esperando(clientes),
        ancla='keep',
        accion_pendiente={
            'tipo': 'tarea_agente',
            'herramienta': 'clientes_esperando',
            'clientes': [_memoria(cliente) for cliente in clientes],
        },
        pasos=[
            {'texto': 'Leí quién escribió hoy o ayer y descarté casas de repuestos', 'estado': 'hecho'},
            {'texto': 'Dejé a quien pidió un servicio, mandó la patente y no tiene cotización enviada', 'estado': 'ahora'},
        ],
        siguiente='Elige un cliente para ver el servicio, el vehículo y el siguiente paso.',
    )


def clientes_esperando(taller, user) -> list[dict]:
    del taller
    ahora = timezone.localtime()
    inicio = (ahora - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return _desde_chats(user, inicio)


def estudiar_lead(taller, user, conversation_id: int) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import _turno

    cliente = next(
        (
            item for item in clientes_esperando(taller, user)
            if item.get('conversation_id') == conversation_id
        ),
        None,
    )
    if cliente is None:
        return _turno(
            haciendo='Busco ese chat',
            titulo='Cliente',
            resumen='Ese chat ya no está entre los que esperan cotización.',
            ancla='keep',
            accion_pendiente={},
        )
    auto = cliente.get('auto') or cliente.get('patente')
    donde = f" Lo pidió {cliente['donde']}." if cliente.get('donde') else ''
    if cliente.get('cotizacion_id'):
        siguiente = 'El borrador ya está. Revísalo y envíalo cuando esté bien.'
        confirmacion = None
    else:
        siguiente = 'Si está bien, armo el borrador. No lo envío.'
        confirmacion = {'etiqueta': 'Armar borrador', 'tipo': 'accion'}
    return _turno(
        haciendo='Leo el pedido de este cliente',
        titulo=cliente['nombre'],
        resumen=(
            f"{cliente['nombre']} escribió {cliente.get('cuando') or 'en estos días'} por {cliente.get('canal') or 'el chat'}. "
            f"Pide {cliente.get('servicio')} para {auto}.{donde} "
            + (
                'Tiene borrador y falta enviarla.'
                if cliente.get('cotizacion_id')
                else 'Todavía no tiene cotización enviada.'
            )
        ),
        filas=_filas_esperando([cliente]),
        confirmacion=confirmacion,
        ancla='keep',
        accion_pendiente={
            'tipo': 'tarea_agente',
            'herramienta': 'estudiar_lead',
            'conversation_id': conversation_id,
            'clientes': [_memoria(cliente)],
        },
        pasos=[
            {'texto': 'Leí lo que escribió', 'estado': 'hecho'},
            {'texto': f"Servicio: {cliente.get('servicio')}. Vehículo: {auto}", 'estado': 'hecho'},
            {
                'texto': 'Falta enviar el borrador' if cliente.get('cotizacion_id') else 'Falta armar el borrador',
                'estado': 'ahora',
            },
        ],
        siguiente=siguiente,
    )


def cotizar_pendientes(taller, user, clientes: list[dict]) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import _turno
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_cotizacion import (
        _CuotaCotizacion,
        _GeneracionFallida,
        _consultar_patente,
        _crear_borrador,
    )

    if not clientes:
        clientes = [_memoria(cliente) for cliente in clientes_esperando(taller, user)]
    if not clientes:
        return _turno(
            haciendo='Reviso a quién cotizar',
            titulo='Sin pendientes',
            resumen='No hay clientes esperando cotización. No armé borradores.',
            ancla='keep',
            accion_pendiente={},
        )
    pasos = [{
        'texto': 'Voy a dejar un borrador por cliente, para que lo revises y lo envíes',
        'estado': 'hecho',
    }]
    filas = []
    hechos = 0
    for cliente in clientes[:_TOPE_BORRADORES]:
        nombre = cliente.get('nombre') or 'Cliente'
        servicio = (cliente.get('servicio') or '').strip()
        if not servicio:
            pasos.append({
                'texto': f'{nombre}: en el chat no está qué hay que cotizar',
                'estado': 'hecho',
            })
            continue
        patente = (cliente.get('patente') or '').replace(' ', '').upper()
        vehiculo = {
            'marca': cliente.get('marca') or '',
            'modelo': cliente.get('modelo') or '',
            'anio': cliente.get('anio'),
            'patente': patente,
        }
        if patente:
            consulta = _consultar_patente(patente, user)
            if consulta.get('ok'):
                vehiculo.update(consulta.get('vehiculo') or {})
                vehiculo['patente'] = patente
                pasos.append({'texto': f'Consulté la patente {patente} de {nombre}', 'estado': 'hecho'})
            else:
                pasos.append({
                    'texto': consulta.get('aviso') or f'No pude consultar la patente {patente}',
                    'estado': 'hecho',
                })
        try:
            cotizacion, _buscando = _crear_borrador(taller, user, {
                'servicio': servicio,
                'patente': patente,
                'marca': vehiculo.get('marca') or '',
                'modelo': vehiculo.get('modelo') or '',
                'anio': vehiculo.get('anio'),
                'vehiculo': vehiculo,
                'modalidad': 'taller',
            })
        except (_CuotaCotizacion, _GeneracionFallida) as exc:
            pasos.append({'texto': f'{nombre}: {exc}', 'estado': 'hecho'})
            continue
        except Exception:
            logger.exception('No pude cotizar a %s', nombre)
            pasos.append({'texto': f'{nombre}: no pude armar el borrador', 'estado': 'hecho'})
            continue
        _atar_chat(cotizacion, cliente)
        hechos += 1
        pasos.append({
            'texto': f'Borrador de {servicio} para {nombre}',
            'estado': 'hecho',
        })
        filas.append({
            'id': f'cotizacion:{cotizacion.id}',
            'titulo': cotizacion.numero_publico or nombre,
            'detalle': f'{servicio} · {nombre}'[:180],
            'meta': 'borrador',
        })
    if len(clientes) > _TOPE_BORRADORES:
        pasos.append({
            'texto': f'Quedan {len(clientes) - _TOPE_BORRADORES} para el siguiente pedido',
            'estado': 'hecho',
        })
    if pasos:
        pasos[-1]['estado'] = 'ahora'
    if hechos:
        resumen = (
            f'Dejé {hechos} borrador{"es" if hechos != 1 else ""} para que los revises y los envíes. '
            'No los mandé.'
        )
    else:
        resumen = 'No dejé borradores: en esos chats no está el trabajo a cotizar.'
    return _turno(
        haciendo='Armo los borradores pendientes',
        titulo='Borradores',
        resumen=resumen,
        filas=filas,
        ancla='keep',
        accion_pendiente={},
        pasos=pasos,
        siguiente='Abre cada borrador, revísalo y envíalo cuando esté bien.',
    )


def resumen_actividad(taller) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import _turno
    from mecanimovilapp.apps.ordenes.models import CotizacionCanal, SolicitudServicio

    realizados = SolicitudServicio.objects.filter(taller=taller, estado='completado').count()
    enviadas = CotizacionCanal.objects.filter(taller=taller, enviada_en__isnull=False).count()
    return _turno(
        haciendo='Cuento el trabajo del taller',
        titulo='Trabajo del taller',
        resumen=(
            f'El taller ha realizado {realizados} servicio{"s" if realizados != 1 else ""}. '
            f'En todo el tiempo se han enviado {enviadas} cotizacion{"es" if enviadas != 1 else ""}.'
        ),
        ancla='keep',
        accion_pendiente={},
        pasos=[
            {'texto': 'Conté los servicios completados', 'estado': 'hecho'},
            {'texto': 'Conté las cotizaciones que sí se enviaron', 'estado': 'ahora'},
        ],
    )


def resumen_cotizaciones(taller, texto: str) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import _turno, plano
    from mecanimovilapp.apps.ordenes.models import CotizacionCanal

    periodo, inicio = _periodo(texto)
    enviadas = list(
        CotizacionCanal.objects.filter(
            taller=taller,
            estado='enviada',
            enviada_en__gte=inicio,
        ).order_by('-enviada_en')[:30]
    )
    autos = []
    for cot in enviadas:
        auto = ' '.join(
            parte for parte in [cot.vehiculo_marca, cot.vehiculo_modelo] if parte
        ).strip() or cot.vehiculo_patente or cot.servicio_nombre or 'un vehículo'
        if auto not in autos:
            autos.append(auto)
    if enviadas:
        lista = ', '.join(autos[:6])
        resumen = (
            f'{periodo.capitalize()} se han enviado {len(enviadas)} '
            f'cotizacion{"es" if len(enviadas) != 1 else ""}, para {lista}.'
        )
    else:
        resumen = f'{periodo.capitalize()} no se han enviado cotizaciones.'
    return _turno(
        haciendo='Cuento las cotizaciones enviadas',
        titulo='Cotizaciones enviadas',
        resumen=resumen,
        ancla='keep',
        accion_pendiente={
            'tipo': 'tarea_agente',
            'herramienta': 'resumen_cotizaciones',
            'periodo': 'mes' if 'mes' in plano(texto) else 'semana',
        },
        pasos=[
            {'texto': f'Revisé las enviadas de {periodo}', 'estado': 'ahora'},
        ],
        siguiente=(
            '¿Quieres que te diga cuáles fueron aprobadas, cuáles siguen en borrador, '
            'cuáles se rechazaron o cuáles quedaron fuera de plazo?'
        ),
    )


def detalle_cotizaciones(taller, texto: str, periodo: str) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import _turno, plano
    from mecanimovilapp.apps.ordenes.models import CotizacionCanal

    p = plano(texto)
    estado, etiqueta = _estado_pedido(p)
    _, inicio = _periodo('mes' if periodo == 'mes' else 'semana')
    filas_doc = list(
        CotizacionCanal.objects.filter(
            taller=taller,
            estado=estado,
            actualizado_en__gte=inicio,
        ).order_by('-actualizado_en')[:20]
    )
    if not filas_doc:
        resumen = f'En este período no hay cotizaciones {etiqueta}.'
    else:
        nombres = []
        for cot in filas_doc[:6]:
            quien = cot.cliente_nombre or cot.vehiculo_patente or cot.servicio_nombre or 'Sin nombre'
            nombres.append(quien)
        resumen = f'Hay {len(filas_doc)} {etiqueta}: {", ".join(nombres)}.'
    return _turno(
        haciendo='Reviso ese grupo de cotizaciones',
        titulo=etiqueta[:1].upper() + etiqueta[1:],
        resumen=resumen,
        filas=[
            {
                'id': f'cotizacion:{cot.id}',
                'titulo': cot.numero_publico or (cot.cliente_nombre or 'Cotización'),
                'detalle': (cot.servicio_nombre or '')[:180],
                'meta': cot.estado,
            }
            for cot in filas_doc[:8]
        ],
        ancla='keep',
        accion_pendiente={
            'tipo': 'tarea_agente',
            'herramienta': 'resumen_cotizaciones',
            'periodo': periodo or 'semana',
        },
        siguiente='Puedes pedir otro grupo: aprobadas, borrador, rechazadas o fuera de plazo.',
    )


def empezar_servicio(taller, texto: str) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import _turno, plano

    p = plano(texto)
    if _alcance(p):
        return cerrar_servicio(taller, texto, {'nombre': _nombre_servicio(p), 'repuestos': _repuestos(p)})
    nombre = _nombre_servicio(p)
    return _turno(
        haciendo='Preparo el alta del servicio',
        titulo='Nuevo servicio',
        resumen=(
            f'Voy a crear {nombre or "ese servicio"} con sus repuestos y el valor que el taller ya cotizó. '
            '¿Es multimarca o para una marca en especial?'
        ),
        ancla='keep',
        accion_pendiente={
            'tipo': 'tarea_agente',
            'herramienta': 'crear_servicio',
            'nombre': nombre,
            'repuestos': _repuestos(p),
        },
        pasos=[
            {'texto': 'Identifiqué el servicio y los repuestos pedidos', 'estado': 'hecho'},
            {'texto': 'Falta saber si es multimarca o de una marca', 'estado': 'ahora'},
        ],
        siguiente='Responde multimarca o el nombre de la marca.',
    )


def cerrar_servicio(taller, texto: str, pendiente: dict) -> dict:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno import _crear_servicio
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import _turno, plano
    from mecanimovilapp.apps.servicios.models import OfertaServicio

    p = plano(texto)
    alcance = _alcance(p) or ('multimarca' if not (pendiente.get('marca')) else '')
    nombre = (pendiente.get('nombre') or _nombre_servicio(p) or '').strip()
    repuestos = list(pendiente.get('repuestos') or []) or _repuestos(p)
    marca = ''
    if alcance == 'marca':
        marca = _marca_dicha(p)
        if not marca:
            return _turno(
                haciendo='Preparo el alta del servicio',
                titulo='Nuevo servicio',
                resumen='¿Para qué marca?',
                ancla='keep',
                accion_pendiente={
                    'tipo': 'tarea_agente',
                    'herramienta': 'crear_servicio',
                    'nombre': nombre,
                    'repuestos': repuestos,
                },
            )
    mano, precios = _precios_de_mercado(taller, nombre, repuestos)
    if not nombre:
        return _turno(
            haciendo='Preparo el alta del servicio',
            titulo='Nuevo servicio',
            resumen='¿Cómo se llama el servicio?',
            ancla='keep',
            accion_pendiente={'tipo': 'tarea_agente', 'herramienta': 'crear_servicio', 'repuestos': repuestos},
        )
    if mano <= 0:
        return _turno(
            haciendo='Busco el valor de mercado',
            titulo='Nuevo servicio',
            resumen=(
                f'No tengo un valor de mano de obra ya cotizado para {nombre}. '
                'Dime el monto y lo dejo activo.'
            ),
            ancla='keep',
            accion_pendiente={
                'tipo': 'tarea_agente',
                'herramienta': 'crear_servicio',
                'nombre': nombre,
                'repuestos': repuestos,
                'marca': marca,
                'alcance': alcance,
            },
            pasos=[{'texto': 'Revisé cotizaciones anteriores y no hay precio de esa mano de obra', 'estado': 'ahora'}],
        )
    antes = OfertaServicio.objects.filter(taller=taller).count()
    hecho = _crear_servicio(taller, {
        'nombre': nombre,
        'precio_mano_obra_clp': mano,
        'con_repuestos': bool(repuestos),
        'marca': marca,
        'listo': True,
    })
    if OfertaServicio.objects.filter(taller=taller).count() == antes and 'quedó' not in hecho and 'Actualicé' not in hecho:
        return _turno(
            haciendo='Creo el servicio',
            titulo='Nuevo servicio',
            resumen=hecho,
            ancla='keep',
            accion_pendiente={},
        )
    if precios:
        oferta = OfertaServicio.objects.filter(taller=taller, servicio__nombre__icontains=nombre).first()
        if oferta is not None:
            oferta.costo_repuestos_sin_iva = sum(precios.values())
            oferta.save(update_fields=['costo_repuestos_sin_iva'])
    detalle = ', '.join(f'{pieza} ${monto}' for pieza, monto in precios.items()) or 'sin precio de repuesto previo'
    donde = marca or 'multimarca'
    return _turno(
        haciendo='Creo el servicio',
        titulo='Servicio listo',
        resumen=f'{hecho} Alcance: {donde}. Repuestos: {detalle}.',
        ancla='keep',
        accion_pendiente={},
        pasos=[
            {'texto': f'Alcance {donde}', 'estado': 'hecho'},
            {'texto': 'Tomé los valores de cotizaciones anteriores del taller', 'estado': 'hecho'},
            {'texto': 'El servicio quedó activo', 'estado': 'ahora'},
        ],
        siguiente='Ya puedes usarlo al cotizar.',
    )


def _resumen_esperando(clientes: list[dict]) -> str:
    n = len(clientes)
    frase = 'cliente' if n == 1 else 'clientes'
    lineas = []
    for cliente in clientes[:8]:
        auto = cliente.get('auto') or cliente.get('patente') or 'el auto que indicó'
        donde = f", {cliente['donde']}" if cliente.get('donde') else ''
        estado = (
            'Tiene borrador y falta enviarla.'
            if cliente.get('cotizacion_id')
            else 'Todavía no tiene cotización enviada.'
        )
        lineas.append(
            f"{cliente['nombre']} por {cliente.get('canal') or 'el chat'}: "
            f"{cliente.get('servicio') or 'un servicio'} para {auto}{donde}. {estado}"
        )
    resto = n - len(lineas)
    cola = f' Y {resto} más con patente y servicio.' if resto else ''
    return (
        f'Entre hoy y ayer hay {n} {frase} esperando cotización. '
        f'Pidieron un trabajo y mandaron la patente. '
        + ' '.join(lineas)
        + cola
    )


def _filas_esperando(clientes: list[dict]) -> list[dict]:
    filas = []
    for cliente in clientes[:8]:
        if cliente.get('conversation_id'):
            fila_id = f"lead:{cliente['conversation_id']}"
        elif cliente.get('cotizacion_id'):
            fila_id = f"cotizacion:{cliente['cotizacion_id']}"
        else:
            fila_id = f"caso:{len(filas)}"
        detalle = ' · '.join(
            parte for parte in (
                cliente.get('servicio'),
                cliente.get('patente'),
                cliente.get('donde'),
            ) if parte
        )
        filas.append({
            'id': fila_id,
            'titulo': cliente['nombre'][:120],
            'detalle': detalle[:180],
            'meta': cliente.get('cuando') or ('falta enviar' if cliente.get('cotizacion_id') else 'falta cotizar'),
        })
    return filas


def _memoria(cliente: dict) -> dict:
    return {
        'conversation_id': cliente.get('conversation_id'),
        'cotizacion_id': cliente.get('cotizacion_id'),
        'nombre': cliente.get('nombre') or '',
        'servicio': cliente.get('servicio') or '',
        'patente': cliente.get('patente') or '',
        'marca': cliente.get('marca') or '',
        'modelo': cliente.get('modelo') or '',
        'anio': cliente.get('anio'),
        'canal': cliente.get('canal') or '',
        'donde': cliente.get('donde') or '',
    }


def _desde_chats(user, desde) -> list[dict]:
    if user is None:
        return []
    from mecanimovilapp.apps.chat.inbox import _cotizaciones_por_conversacion
    from mecanimovilapp.apps.chat.models import Message
    from mecanimovilapp.apps.omnichannel.utils import channel_to_api_slug

    mensajes = (
        Message.objects.filter(
            conversation__participants=user,
            conversation__source_channel__in=('WHATSAPP', 'MESSENGER', 'INSTAGRAM'),
            timestamp__gte=desde,
        )
        .select_related('conversation', 'conversation__external_contact')
        .order_by('conversation_id', 'timestamp', 'id')
    )
    grupos: dict[int, list] = {}
    for mensaje in mensajes:
        grupos.setdefault(mensaje.conversation_id, []).append(mensaje)
    cotizaciones = _cotizaciones_por_conversacion(list(grupos))
    clientes = []
    for conv_id, hilo in grupos.items():
        entrantes = [mensaje for mensaje in hilo if mensaje.direction == 'inbound']
        if not entrantes:
            continue
        cot = cotizaciones.get(conv_id)
        if cot is not None and cot.estado in ('enviada', 'aceptada', 'rechazada', 'expirada'):
            continue
        contacto = hilo[-1].conversation.external_contact
        texto = ' '.join((mensaje.content or '') for mensaje in entrantes)
        ultimo = entrantes[-1].timestamp
        if timezone.is_aware(ultimo):
            ultimo = timezone.localtime(ultimo)
        cuando = 'hoy' if ultimo.date() == timezone.localdate() else 'ayer'
        nombre = (contacto.display_name if contacto else '') or 'Cliente sin nombre'
        if _es_casa(contacto, texto, nombre):
            continue
        patente, marca, modelo, anio = _auto_en(texto)
        servicio = _servicio_en(texto)
        if not servicio or not patente:
            continue
        canal = channel_to_api_slug(hilo[-1].conversation.source_channel)
        auto = ' '.join(parte for parte in [marca, modelo, str(anio or '') if anio else '', patente] if parte)
        clientes.append({
            'conversation_id': conv_id,
            'cotizacion_id': cot.id if cot is not None else None,
            'nombre': nombre,
            'canal': _CANAL.get(canal, canal),
            'servicio': servicio,
            'patente': patente,
            'marca': marca,
            'modelo': modelo,
            'anio': anio,
            'auto': auto,
            'donde': _donde(texto),
            'cuando': cuando,
        })
    return clientes


def _es_casa(contacto, texto: str, nombre: str) -> bool:
    from mecanimovilapp.apps.ordenes.services.rol_contacto import parece_texto_de_proveedor

    if contacto is not None:
        if contacto.rol in ('casa_repuestos', 'solo_consulta', 'otro'):
            return True
        if contacto.rol_sugerido == 'casa_repuestos':
            return True
    if _NOMBRE_CASA.search(nombre or ''):
        return True
    return parece_texto_de_proveedor(texto)


def _donde(texto: str) -> str:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    p = plano(texto)
    if 'domicilio' in p:
        return 'a domicilio'
    if re.search(r'\b(en el taller|al taller|en taller)\b', p):
        return 'en el taller'
    return ''


def _auto_en(texto: str) -> tuple[str, str, str, int | None]:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_cotizacion import (
        _PATENTE_RE,
        _extraer_marca_modelo,
    )
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    p = plano(texto)
    patente = ''
    hallada = _PATENTE_RE.search(p)
    if hallada:
        patente = re.sub(r'[^a-z0-9]', '', hallada.group(1)).upper()
    marca_modelo = _extraer_marca_modelo(p, None)
    anio = marca_modelo.get('anio')
    return patente, marca_modelo.get('marca') or '', marca_modelo.get('modelo') or '', anio


def _servicio_en(texto: str) -> str:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_cotizacion import _SERVICIO_RE

    p = plano(texto)
    hallado = _SERVICIO_RE.search(p)
    if hallado:
        nombre = hallado.group(1).strip()
        return nombre[:1].upper() + nombre[1:]
    pieza = _NECESIDAD.search(p)
    if pieza:
        return f'Cambio de {pieza.group(1)}'
    return ''


def _atar_chat(cotizacion, cliente: dict) -> None:
    conv = cliente.get('conversation_id')
    if not conv:
        return
    cotizacion.conversation_id = conv
    cotizacion.es_libre = False
    if cliente.get('nombre'):
        cotizacion.cliente_nombre = str(cliente['nombre'])[:200]
    cotizacion.save(update_fields=['conversation', 'es_libre', 'cliente_nombre'])


def _periodo(texto: str) -> tuple[str, object]:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    ahora = timezone.localtime()
    if 'mes' in plano(texto):
        inicio = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return 'este mes', inicio
    inicio = (ahora - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    return 'esta semana', inicio


def _estado_pedido(p: str) -> tuple[str, str]:
    if 'rechaz' in p:
        return 'rechazada', 'rechazadas'
    if 'borrador' in p or 'pendiente' in p:
        return 'borrador', 'en borrador'
    if 'plazo' in p or 'vencid' in p or 'expir' in p:
        return 'expirada', 'fuera de plazo'
    return 'aceptada', 'aprobadas'


def _alcance(p: str) -> str:
    if 'multimarca' in p or 'todas las marcas' in p:
        return 'multimarca'
    if re.search(r'\bmarca\b', p) and not re.search(r'\bmultimarca\b', p):
        return 'marca'
    return ''


def _nombre_servicio(p: str) -> str:
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_cotizacion import _SERVICIO_RE

    hallado = _SERVICIO_RE.search(p)
    if hallado:
        nombre = hallado.group(1).strip()
        return nombre[:1].upper() + nombre[1:]
    return ''


def _repuestos(p: str) -> list[str]:
    hallado = re.search(r'\brepuestos?\s+(.+)', p)
    if not hallado:
        return []
    vistos = []
    for pieza in _NECESIDAD.findall(hallado.group(1)):
        if pieza not in vistos:
            vistos.append(pieza)
    return vistos


def _marca_dicha(p: str) -> str:
    salto = {'para', 'una', 'la', 'el', 'marca', 'especial', 'multimarca', 'de'}
    match = re.search(r'\bmarca\s+([a-z0-9]+)', p)
    if match and match.group(1) not in salto:
        return match.group(1)[:1].upper() + match.group(1)[1:]
    return ''


def _precios_de_mercado(taller, servicio: str, repuestos: list[str]) -> tuple[int, dict]:
    from mecanimovilapp.apps.ordenes.models import CotizacionCanal

    mano = 0
    precios: dict[str, int] = {}
    recientes = CotizacionCanal.objects.filter(taller=taller).exclude(estado='cancelada').order_by('-actualizado_en')[:40]
    for cot in recientes:
        if servicio and servicio.lower() in (cot.servicio_nombre or '').lower() and int(cot.mano_obra_clp or 0) > 0:
            mano = int(cot.mano_obra_clp)
        for rep in cot.repuestos or []:
            if not isinstance(rep, dict):
                continue
            nombre = str(rep.get('nombre') or '').lower()
            monto = int(rep.get('precio_unitario_clp') or 0)
            if monto <= 0:
                continue
            for pieza in repuestos:
                if pieza in nombre and pieza not in precios:
                    precios[pieza] = monto
        if mano and len(precios) >= len(repuestos):
            break
    return mano, precios
