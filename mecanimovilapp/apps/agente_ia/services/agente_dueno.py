"""Asistente del dueño: un hilo por taller, con el contexto vivo de ese taller."""
from __future__ import annotations

import json
import logging
from datetime import date
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
    from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal
    from mecanimovilapp.apps.servicios.models import OfertaServicio
    from mecanimovilapp.apps.usuarios.models import MiembroTaller

    hoy = date.today()
    servicios = []
    ofertas = (
        OfertaServicio.objects.filter(taller=taller)
        .select_related('servicio')
        .order_by('servicio__nombre')[:40]
    )
    for oferta in ofertas:
        servicios.append({
            'id': oferta.id,
            'nombre': getattr(oferta.servicio, 'nombre', '') or '',
            'disponible': bool(oferta.disponible),
            'mano_obra_clp': int(oferta.costo_mano_de_obra_sin_iva or 0),
        })

    mecanicos = []
    for miembro in MiembroTaller.objects.filter(taller=taller).exclude(rol='mandante')[:20]:
        mecanicos.append({
            'id': miembro.id,
            'nombre': (miembro.nombre or '').strip(),
            'rol': miembro.rol,
            'activo': bool(miembro.activo),
        })

    agenda = []
    citas = (
        CitaAgendaPersonal.objects.filter(
            taller=taller,
            fecha_servicio=hoy,
            estado='activa',
        )
        .select_related('detalle')
        .order_by('hora_servicio')[:20]
    )
    for cita in citas:
        try:
            detalle = cita.detalle
        except Exception:
            detalle = None
        cliente = getattr(detalle, 'cliente_nombre', '') if detalle else ''
        servicio = getattr(detalle, 'servicio_nombre', '') if detalle else ''
        agenda.append({
            'id': cita.id,
            'hora': cita.hora_servicio.strftime('%H:%M') if cita.hora_servicio else '',
            'cliente': cliente or '',
            'servicio': servicio or '',
            'horario_por_confirmar': bool(cita.horario_por_confirmar),
        })

    return {
        'taller': getattr(taller, 'nombre', '') or '',
        'fecha': hoy.isoformat(),
        'servicios': servicios,
        'mecanicos': mecanicos,
        'agenda_hoy': agenda,
    }


def _prompt(taller_nombre: str, contexto: dict, historial: list[dict], texto: str) -> str:
    return (
        'Eres el asistente personal del dueño de un taller mecánico en Chile. '
        'Este hilo es solo de este taller. Hablas breve, en español, como un colega. '
        'No inventes clientes, horas, precios ni servicios que no estén en el contexto. '
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
    OfertaServicio.objects.create(
        tipo_proveedor='taller',
        taller=taller,
        servicio=servicio,
        disponible=True,
        tipo_servicio=tipo,
        costo_mano_de_obra_sin_iva=precio_num,
        costo_repuestos_sin_iva=0,
        detalles_adicionales='',
    )
    return f'{servicio.nombre} quedó registrado en el taller.'


def responder_agente_dueno(taller, texto: str, historial_cliente: list[dict] | None) -> dict[str, Any]:
    from mecanimovilapp.apps.agente_ia.services.orquestador import _llamar_gemini_agente

    texto = (texto or '').strip()
    historial = _historial(taller.id, historial_cliente or [])
    historial.append({'rol': 'dueno', 'texto': texto[:2000]})
    contexto = _contexto(taller)
    decision, error = _llamar_gemini_agente(_prompt(
        getattr(taller, 'nombre', '') or 'Taller',
        contexto,
        historial[:-1],
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
        }

    hecho = _ejecutar(taller, decision.get('accion') if isinstance(decision.get('accion'), dict) else None)
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
    _guardar(taller.id, historial, decir)
    return {
        'ok': True,
        'haciendo': (decision.get('haciendo') or '').strip(),
        'titulo': str(vista.get('titulo') or 'Agente del taller')[:80],
        'resumen': decir or 'Listo.',
        'filas': filas_limpias,
        'memoria_ids': [fila['id'] for fila in filas_limpias],
    }
