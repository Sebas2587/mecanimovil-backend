"""Asistente del dueño: un hilo por taller, con el contexto vivo de ese taller."""
from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

from django.core.cache import cache
from django.db import transaction

logger = logging.getLogger(__name__)

_CACHE_TTL = 60 * 60 * 24 * 30
_MAX_TURNOS = 16


def _clave(taller_id: int) -> str:
    return f'agente-dueno-hilo:{taller_id}'


def _historial(taller_id: int, entrante: list[dict]) -> list[dict]:
    guardado = cache.get(_clave(taller_id)) or []
    if not isinstance(guardado, list):
        guardado = []
    limpio = []
    for item in list(guardado) + list(entrante or []):
        if not isinstance(item, dict):
            continue
        rol = item.get('rol')
        texto = (item.get('texto') or '').strip()
        if rol in ('dueno', 'agente') and texto:
            limpio.append({'rol': rol, 'texto': texto[:2000]})
    return limpio[-_MAX_TURNOS:]


def _guardar(taller_id: int, historial: list[dict], respuesta: str) -> None:
    copia = list(historial)
    if respuesta.strip():
        copia.append({'rol': 'agente', 'texto': respuesta.strip()[:2000]})
    cache.set(_clave(taller_id), copia[-_MAX_TURNOS:], _CACHE_TTL)


def _contexto(taller) -> dict[str, Any]:
    from django.db.models import Count

    from django.utils import timezone

    from mecanimovilapp.apps.ordenes.models import CotizacionCanal
    from mecanimovilapp.apps.servicios.models import OfertaServicio
    from mecanimovilapp.apps.usuarios.models import MiembroTaller

    hoy = timezone.localdate()
    ofertas_qs = (
        OfertaServicio.objects.filter(taller=taller)
        .select_related('servicio', 'marca_vehiculo_seleccionada', 'modelo_vehiculo_seleccionado')
        .order_by('servicio__nombre', 'marca_vehiculo_seleccionada__nombre')
    )
    servicios = []
    for oferta in ofertas_qs[:80]:
        marca = getattr(oferta.marca_vehiculo_seleccionada, 'nombre', '') or 'Todas las marcas'
        modelo = getattr(oferta.modelo_vehiculo_seleccionado, 'nombre', '') or 'Todos los modelos'
        servicios.append({
            'oferta_id': oferta.id,
            'servicio_id': oferta.servicio_id,
            'nombre': getattr(oferta.servicio, 'nombre', '') or '',
            'marca': marca,
            'modelo': modelo,
            'disponible': bool(oferta.disponible),
            'con_repuestos': oferta.tipo_servicio == 'con_repuestos',
            'mano_obra_clp': int(oferta.costo_mano_de_obra_sin_iva or 0),
            'repuestos_clp': int(oferta.costo_repuestos_sin_iva or 0),
            'precio_publico_clp': int(oferta.precio_publicado_cliente or 0),
        })
    nombres = {fila['nombre'] for fila in servicios if fila['nombre']}

    mecanicos = []
    for miembro in MiembroTaller.objects.filter(taller=taller).exclude(rol='mandante')[:20]:
        mecanicos.append({
            'id': miembro.id,
            'nombre': (miembro.nombre or '').strip(),
            'rol': miembro.rol,
            'activo': bool(miembro.activo),
        })

    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import (
        agenda_del_dia,
        correcciones_para_prompt,
    )

    agenda = agenda_del_dia(taller, hoy)

    demanda = list(
        CotizacionCanal.objects.filter(taller=taller)
        .exclude(servicio_nombre='')
        .values('servicio_nombre', 'vehiculo_marca')
        .annotate(cotizaciones=Count('id'))
        .order_by('-cotizaciones')[:12]
    )
    return {
        'taller': getattr(taller, 'nombre', '') or '',
        'fecha': hoy.isoformat(),
        'servicios_distintos': len(nombres),
        'ofertas_precio': len(servicios),
        'servicios': servicios,
        'demanda_cotizaciones': [
            {
                'servicio': fila['servicio_nombre'],
                'marca': fila['vehiculo_marca'] or 'Sin marca',
                'cotizaciones': fila['cotizaciones'],
            }
            for fila in demanda
        ],
        'mecanicos': mecanicos,
        'agenda_hoy': agenda,
        'correcciones_dueno': correcciones_para_prompt(taller),
    }


def _prompt(taller_nombre: str, contexto: dict, historial: list[dict], texto: str) -> str:
    return (
        'Eres el asistente personal del dueño de un taller mecánico en Chile. '
        'Este hilo es solo de este taller. Hablas breve, en español, como un colega. '
        'No inventes clientes, horas, precios ni servicios que no estén en el contexto. '
        'servicios_distintos es la cantidad de servicios. ofertas_precio es cuántas configuraciones '
        'hay por marca y modelo: no las presentes como si fueran servicios distintos. '
        'Si preguntan cuántos servicios, di ambos números y lista marca, modelo, si lleva repuestos y el precio. '
        'Si preguntan lo más pedido, usa demanda_cotizaciones. '
        'agenda_hoy es la cita del cliente, no el catálogo. '
        'auto_marca, auto_modelo y auto_patente son el vehículo de ESA cita. '
        'servicio_marca y servicio_modelo son la marca para la que está configurado el servicio, no el auto del cliente. '
        'Si preguntan de qué auto o cliente es una cita ya mostrada, responde con esos campos. '
        'No digas que el vehículo no está si auto_marca, auto_modelo o auto_patente tienen valor. '
        'Si el auto del cliente viene vacío y el servicio sí tiene marca, dilo aparte: el auto no está anotado en la cita y el servicio está configurado para esa marca. '
        'agenda_hoy incluye citas personales confirmadas y órdenes de la app con hora ese día. '
        'Si agenda_hoy está vacía, di que hoy no hay nada agendado. '
        'correcciones_dueno son datos que el dueño ya descartó: no los presentes otra vez. '
        'Cada respuesta habla de un solo caso: cliente, vehículo de la cita y documento. '
        'Si hay dos casos posibles, pregunta y no elijas uno. '
        'No marques como listo enviar, aceptar, agendar, empezar ni anotar cobro: esos pasos se confirman en una tarjeta. '
        'Si falta un dato para crear o cambiar algo, haz una sola pregunta y no marques la acción como lista.\n\n'
        f'Taller: {taller_nombre}\n'
        f'Contexto vivo:\n{json.dumps(contexto, ensure_ascii=False)}\n\n'
        f'Historial:\n{json.dumps(historial, ensure_ascii=False)}\n\n'
        f'Mensaje del dueño:\n{texto}\n\n'
        'Responde SOLO JSON con esta forma:\n'
        '{'
        '"haciendo":"qué estás haciendo, en una frase",'
        '"decir":"respuesta al dueño",'
        '"vista":{"titulo":"","resumen":"","filas":[{"id":"","titulo":"","detalle":"","meta":""}]} o null,'
        '"accion":null o {'
        '"tipo":"crear_servicio|pausar_servicio|activar_servicio|habilitar_mecanico|pausar_mecanico",'
        '"listo":false,'
        '"nombre":"",'
        '"marca":"",'
        '"modelo":"",'
        '"precio_mano_obra_clp":0,'
        '"con_repuestos":false,'
        '"duracion_minutos":60,'
        '"id":0'
        '}'
        '}\n'
        'Para agendamientos de hoy usa contexto.agenda_hoy en vista.filas. '
        'crear_servicio solo con listo true si el dueño ya confirmó nombre y precio. '
        'Si pide registrar un servicio y falta el precio o el nombre, pregunta y listo false.'
    )


def _ejecutar(taller, accion: dict | None) -> str:
    if not isinstance(accion, dict) or not accion.get('listo'):
        return ''
    tipo = (accion.get('tipo') or '').strip()
    nombre = (accion.get('nombre') or '').strip()
    try:
        with transaction.atomic():
            if tipo in ('pausar_servicio', 'activar_servicio'):
                return _disponibilidad_servicio(taller, nombre, accion.get('id'), tipo == 'activar_servicio')
            if tipo in ('habilitar_mecanico', 'pausar_mecanico'):
                return _mecanico(taller, nombre, accion.get('id'), tipo == 'habilitar_mecanico')
            if tipo == 'crear_servicio':
                return _crear_servicio(taller, accion)
    except Exception:
        logger.exception('Agente dueño no pudo ejecutar %s', tipo)
        return 'No pude guardar el cambio. Revisa el dato y lo intentamos de nuevo.'
    return ''


def _disponibilidad_servicio(taller, nombre: str, oferta_id, disponible: bool) -> str:
    from mecanimovilapp.apps.servicios.models import OfertaServicio

    qs = OfertaServicio.objects.filter(taller=taller).select_related('servicio')
    oferta = None
    if oferta_id:
        oferta = qs.filter(id=oferta_id).first()
    if oferta is None and nombre:
        oferta = qs.filter(servicio__nombre__icontains=nombre).first()
    if oferta is None:
        return f'No encuentro el servicio "{nombre}".'
    oferta.disponible = disponible
    oferta.save(update_fields=['disponible'])
    verbo = 'activado' if disponible else 'pausado'
    return f'{oferta.servicio.nombre} quedó {verbo}.'


def _mecanico(taller, nombre: str, miembro_id, activo: bool) -> str:
    from mecanimovilapp.apps.usuarios.models import MiembroTaller

    qs = MiembroTaller.objects.filter(taller=taller).exclude(rol='mandante')
    miembro = qs.filter(id=miembro_id).first() if miembro_id else None
    if miembro is None and nombre:
        miembro = qs.filter(nombre__icontains=nombre).first()
    if miembro is None:
        return f'No encuentro al mecánico "{nombre}".'
    miembro.activo = activo
    miembro.save(update_fields=['activo', 'fecha_actualizacion'])
    verbo = 'habilitado' if activo else 'pausado'
    return f'{miembro.nombre} quedó {verbo}.'


def _crear_servicio(taller, accion: dict) -> str:
    from mecanimovilapp.apps.servicios.models import OfertaServicio, Servicio

    nombre = (accion.get('nombre') or '').strip()
    precio = accion.get('precio_mano_obra_clp') or 0
    try:
        precio_num = Decimal(str(precio))
    except Exception:
        precio_num = Decimal('0')
    if not nombre or precio_num <= 0:
        return 'Para dar de alta el servicio necesito el nombre y el precio de mano de obra.'
    servicio = Servicio.objects.filter(nombre__iexact=nombre).first()
    if servicio is None:
        servicio = Servicio.objects.filter(nombre__icontains=nombre).first()
    if servicio is None:
        return (
            f'No hay un servicio de catálogo llamado "{nombre}". '
            'Dime el nombre tal como está en el catálogo, o uno parecido.'
        )
    ya = OfertaServicio.objects.filter(taller=taller, servicio=servicio).first()
    if ya:
        ya.disponible = True
        ya.costo_mano_de_obra_sin_iva = precio_num
        ya.save(update_fields=['disponible', 'costo_mano_de_obra_sin_iva'])
        return f'{servicio.nombre} ya estaba en el taller. Actualicé el precio y lo dejé activo.'
    tipo = 'con_repuestos' if accion.get('con_repuestos') else 'sin_repuestos'
    marca = None
    modelo = None
    marca_nombre = (accion.get('marca') or '').strip()
    modelo_nombre = (accion.get('modelo') or '').strip()
    if marca_nombre:
        from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo, Modelo
        marca = MarcaVehiculo.objects.filter(nombre__icontains=marca_nombre).first()
        if modelo_nombre and marca is not None:
            modelo = Modelo.objects.filter(marca=marca, nombre__icontains=modelo_nombre).first()
    OfertaServicio.objects.create(
        tipo_proveedor='taller',
        taller=taller,
        servicio=servicio,
        disponible=True,
        tipo_servicio=tipo,
        costo_mano_de_obra_sin_iva=precio_num,
        costo_repuestos_sin_iva=0,
        detalles_adicionales='',
        marca_vehiculo_seleccionada=marca,
        modelo_vehiculo_seleccionado=modelo,
    )
    donde = ' '.join(parte for parte in [getattr(marca, 'nombre', ''), getattr(modelo, 'nombre', '')] if parte)
    return f'{servicio.nombre} quedó registrado{(" para " + donde) if donde else ""}.'


def _hilo(taller, hilo_id, texto: str):
    from mecanimovilapp.apps.agente_ia.models import AgenteDuenoHilo, AgenteDuenoMensaje

    hilo = None
    if hilo_id:
        hilo = AgenteDuenoHilo.objects.filter(taller=taller, id=hilo_id).first()
    if hilo is None:
        titulo = texto.strip().replace('\n', ' ')[:80] or 'Nueva conversación'
        hilo = AgenteDuenoHilo.objects.create(taller=taller, titulo=titulo)
    return hilo, AgenteDuenoMensaje


_ACCIONES_SENSIBLES = {
    'enviar_cotizacion',
    'marcar_aceptada',
    'agendar',
    'contestar',
    'empezar',
    'anotar_cobro',
}


def _cerrar_turno(hilo, Mensaje, turno: dict) -> dict[str, Any]:
    filas = []
    for fila in (turno.get('filas') or [])[:30]:
        if not isinstance(fila, dict):
            continue
        filas.append({
            'id': str(fila.get('id') or '')[:80],
            'titulo': str(fila.get('titulo') or '')[:120],
            'detalle': str(fila.get('detalle') or '')[:240],
            'meta': str(fila.get('meta') or '')[:80],
        })
    confirmacion = turno.get('confirmacion') if isinstance(turno.get('confirmacion'), dict) else None
    if confirmacion:
        confirmacion = {
            'etiqueta': str(confirmacion.get('etiqueta') or 'Sí')[:80],
            'tipo': 'whatsapp' if confirmacion.get('tipo') == 'whatsapp' else 'accion',
        }
    abrir = turno.get('abrir_whatsapp') if isinstance(turno.get('abrir_whatsapp'), dict) else None
    if abrir and not (abrir.get('telefono') or '').strip():
        abrir = None
    elif abrir:
        abrir = {
            'telefono': str(abrir.get('telefono') or '')[:30],
            'texto': str(abrir.get('texto') or '')[:1000],
        }
    resumen = (turno.get('resumen') or 'Listo.').strip()
    vista = {
        'titulo': str(turno.get('titulo') or 'Agente del taller')[:80],
        'resumen': resumen,
        'filas': filas,
        'confirmacion': confirmacion,
    }
    Mensaje.objects.create(hilo=hilo, rol='agente', texto=resumen[:4000], vista=vista)
    ancla = turno.get('ancla') or 'keep'
    hilo.ultima_tarjeta = {'filas': filas}
    hilo.accion_pendiente = turno.get('accion_pendiente') or {}
    campos = ['actualizado_en', 'ultima_tarjeta', 'accion_pendiente']
    if ancla == 'set':
        hilo.caso_anclado = turno.get('caso_anclado') or {}
        campos.append('caso_anclado')
    elif ancla == 'clear':
        hilo.caso_anclado = {}
        campos.append('caso_anclado')
    hilo.save(update_fields=campos)
    return {
        'ok': True,
        'hilo_id': hilo.id,
        'hilo_titulo': hilo.titulo,
        'haciendo': (turno.get('haciendo') or '').strip(),
        'titulo': vista['titulo'],
        'resumen': resumen,
        'filas': filas,
        'memoria_ids': [fila['id'] for fila in filas],
        'confirmacion': confirmacion,
        'abrir_whatsapp': abrir,
    }


def responder_agente_dueno(taller, texto: str, historial_cliente: list[dict] | None, hilo_id=None, user=None) -> dict[str, Any]:
    from mecanimovilapp.apps.agente_ia.services.orquestador import _llamar_gemini_agente

    texto = (texto or '').strip()
    hilo, Mensaje = _hilo(taller, hilo_id, texto)
    previos = [
        {'rol': mensaje.rol, 'texto': mensaje.texto}
        for mensaje in hilo.mensajes.order_by('creado_en')[:_MAX_TURNOS]
    ]
    historial = previos or _historial(taller.id, historial_cliente or [])
    Mensaje.objects.create(hilo=hilo, rol='dueno', texto=texto[:4000])
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import resolver_turno

    turno = resolver_turno(taller, hilo, texto, user)
    if turno is not None:
        respuesta = _cerrar_turno(hilo, Mensaje, turno)
        _guardar(taller.id, historial, respuesta['resumen'])
        return respuesta
    if hilo.accion_pendiente:
        hilo.accion_pendiente = {}
        hilo.save(update_fields=['accion_pendiente'])
    contexto = _contexto(taller)
    decision, error = _llamar_gemini_agente(_prompt(
        getattr(taller, 'nombre', '') or 'Taller',
        contexto,
        historial,
        texto,
    ))
    if not decision:
        return {
            'ok': False,
            'error': error or 'El agente no respondió.',
            'haciendo': '',
            'titulo': 'Agente del taller',
            'resumen': error or 'No pude consultar al agente. Intenta de nuevo.',
            'filas': [],
            'memoria_ids': [],
            'confirmacion': None,
            'abrir_whatsapp': None,
        }

    accion = decision.get('accion') if isinstance(decision.get('accion'), dict) else None
    if isinstance(accion, dict) and accion.get('tipo') in _ACCIONES_SENSIBLES:
        accion = None
    hecho = _ejecutar(taller, accion)
    decir = (decision.get('decir') or '').strip()
    if hecho:
        decir = f'{decir} {hecho}'.strip()
    vista = decision.get('vista') if isinstance(decision.get('vista'), dict) else {}
    filas = vista.get('filas') if isinstance(vista.get('filas'), list) else []
    filas_limpias = []
    for fila in filas[:30]:
        if not isinstance(fila, dict):
            continue
        filas_limpias.append({
            'id': str(fila.get('id') or fila.get('titulo') or len(filas_limpias)),
            'titulo': str(fila.get('titulo') or '')[:120],
            'detalle': str(fila.get('detalle') or '')[:180],
            'meta': str(fila.get('meta') or '')[:80],
        })
    pregunta = (decision.get('pregunta') or '').strip()
    if pregunta and pregunta not in decir:
        decir = f'{decir} {pregunta}'.strip()
    vista_guardar = {
        'titulo': str(vista.get('titulo') or 'Agente del taller')[:80],
        'resumen': decir or 'Listo.',
        'filas': filas_limpias,
        'confirmacion': None,
    }
    Mensaje.objects.create(hilo=hilo, rol='agente', texto=vista_guardar['resumen'], vista=vista_guardar)
    hilo.ultima_tarjeta = {'filas': filas_limpias}
    hilo.save(update_fields=['actualizado_en', 'ultima_tarjeta'])
    _guardar(taller.id, historial, decir)
    return {
        'ok': True,
        'hilo_id': hilo.id,
        'hilo_titulo': hilo.titulo,
        'haciendo': (decision.get('haciendo') or '').strip(),
        'titulo': vista_guardar['titulo'],
        'resumen': vista_guardar['resumen'],
        'filas': filas_limpias,
        'memoria_ids': [fila['id'] for fila in filas_limpias],
        'confirmacion': None,
        'abrir_whatsapp': None,
    }
