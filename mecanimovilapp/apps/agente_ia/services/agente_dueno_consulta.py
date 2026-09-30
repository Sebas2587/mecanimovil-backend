"""El dueño pregunta por los casos del taller. Eso no abre el formulario de cotizar."""
from __future__ import annotations

import logging
import re

from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

_CERRADOS = {'rechazado_perdido', 'completado'}
_YA_ENVIADA = {'cotizacion_enviada', 'en_negociacion'}


def busca_casos_de_cotizacion(texto: str) -> bool:
    """Pregunta por clientes o cotizaciones del taller, no pide armar una."""
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import plano

    p = plano(texto)
    if _es_orden_de_armar(p) and not re.search(r'\b(primero|antes|revisa|revisar|saber)\b', p):
        return False
    menciona_personas = bool(re.search(
        r'\b(cliente|clientes|quien|quienes|solicitud|solicitudes)\b',
        p,
    ))
    menciona_cotizacion = bool(re.search(r'\b(cotiz|presupuesto|precio)\b', p))
    pide_mirar = bool(re.search(
        r'\b(saber|revisa|revisar|hay|existen|existe|dime|muestra|muestrame|lista|'
        r'cuant|cual|primero|esper|faltan|pendiente)\b|\?',
        p,
    ))
    if not pide_mirar:
        return False
    if menciona_personas and (menciona_cotizacion or re.search(r'\b(hoy|dia)\b', p)):
        return True
    return bool(
        menciona_cotizacion
        and re.search(r'\b(hoy|dia|pendiente|faltan|sin enviar)\b', p)
    )


def panorama_comercial(taller, user) -> dict:
    filas = _filas_pipeline(taller, user)
    hoy = timezone.localdate().isoformat()
    esperan_hoy = []
    esperan_antes = []
    enviadas_hoy = []
    for fila in filas:
        estado = fila.get('estado_normalizado') or ''
        if estado in _CERRADOS:
            continue
        de_hoy = _es_de_hoy(fila, hoy)
        if estado == 'nuevo':
            (esperan_hoy if de_hoy else esperan_antes).append(fila)
        elif de_hoy and estado in _YA_ENVIADA:
            enviadas_hoy.append(fila)
    return {
        'esperan_hoy': [_publico(fila) for fila in esperan_hoy[:8]],
        'esperan_antes': [_publico(fila) for fila in esperan_antes[:5]],
        'enviadas_hoy': [_publico(fila) for fila in enviadas_hoy[:8]],
        'esperan_hoy_total': len(esperan_hoy),
        'esperan_antes_total': len(esperan_antes),
        'enviadas_hoy_total': len(enviadas_hoy),
    }


def responder_casos_cotizacion(taller, user, texto: str) -> dict:
    del texto
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_caso import _turno

    try:
        panorama = panorama_comercial(taller, user or getattr(taller, 'usuario', None))
    except Exception:
        logger.exception('No pude armar el panorama comercial del taller %s', getattr(taller, 'id', None))
        return _turno(
            haciendo='Reviso quién necesita cotización',
            titulo='Cotizaciones de hoy',
            resumen='No pude revisar los casos del taller. Intenta de nuevo en un momento.',
            ancla='keep',
            accion_pendiente={},
        )
    return _turno(
        haciendo='Reviso quién necesita cotización',
        titulo='Cotizaciones de hoy',
        resumen=_redactar(panorama),
        filas=_filas_chat(panorama),
        ancla='keep',
        accion_pendiente={},
        pasos=[
            {'texto': 'Revisé solicitudes, chats y cotizaciones del taller', 'estado': 'hecho'},
            {'texto': 'Te muestro quién espera cotización y quién ya tiene una hoy', 'estado': 'ahora'},
        ],
        siguiente='Puedes pedirme que cotice uno de estos casos, o preguntar por otro cliente.',
    )


def _es_orden_de_armar(p: str) -> bool:
    return bool(re.search(
        r'\b(cotiza|cotizar|cotizame|cotizale)\b'
        r'|realiza una cotizacion|arma(?:r|me)? una cotizacion|haz(?:me)? una cotizacion'
        r'|presupuesto para',
        p,
    ))


def _filas_pipeline(taller, user) -> list[dict]:
    from mecanimovilapp.apps.ordenes.services.pipeline_comercial import (
        construir_pipeline_comercial,
    )

    quien = user or getattr(taller, 'usuario', None)
    data = construir_pipeline_comercial(
        user=quien,
        taller=taller,
        incluir_borradores=True,
        limite=80,
    )
    return list(data.get('results') or [])


def _es_de_hoy(fila: dict, hoy: str) -> bool:
    if (fila.get('fecha_agendada') or '') == hoy:
        return True
    return _dia_local(fila.get('fecha_referencia')) == hoy


def _dia_local(valor) -> str:
    texto = str(valor or '').strip()
    if not texto:
        return ''
    if len(texto) == 10 and texto[4] == '-':
        return texto
    momento = parse_datetime(texto)
    if momento is None:
        return texto[:10]
    if timezone.is_aware(momento):
        momento = timezone.localtime(momento)
    return momento.date().isoformat()


def _publico(fila: dict) -> dict:
    cliente = (fila.get('cliente_nombre') or '').strip() or 'Cliente sin nombre'
    return {
        'cliente': cliente,
        'servicio': (fila.get('servicio_resumen') or '').strip(),
        'auto': (fila.get('vehiculo_resumen') or '').strip(),
        'origen': (fila.get('origen') or '').strip(),
        'estado': 'sin enviar' if fila.get('estado_normalizado') == 'nuevo' else 'enviada',
    }


def _redactar(panorama: dict) -> str:
    esperan_hoy = panorama['esperan_hoy_total']
    antes = panorama['esperan_antes_total']
    enviadas = panorama['enviadas_hoy_total']
    if not esperan_hoy and not antes and not enviadas:
        return (
            'Hoy no hay clientes esperando cotización ni solicitudes nuevas. '
            'Tampoco hay cotizaciones enviadas hoy.'
        )
    partes = ['Revisé solicitudes, chats y cotizaciones del taller.']
    if esperan_hoy:
        partes.append(_frase('Hoy todavía no tienen cotización enviada', panorama['esperan_hoy'], esperan_hoy))
    else:
        partes.append('Hoy no entró nadie nuevo sin cotización.')
    if enviadas:
        partes.append(_frase('Hoy ya tienen cotización enviada', panorama['enviadas_hoy'], enviadas))
    if antes:
        if esperan_hoy:
            partes.append(
                f'Además hay {antes} de días anteriores que siguen sin cotización enviada.'
            )
        else:
            partes.append(_frase('Siguen sin cotización enviada, de antes', panorama['esperan_antes'], antes))
    return ' '.join(partes)


def _frase(titulo: str, casos: list[dict], total: int) -> str:
    dichos = []
    for caso in casos[:5]:
        partes = [caso['cliente']]
        if caso.get('servicio'):
            partes.append(caso['servicio'])
        if caso.get('auto'):
            partes.append(caso['auto'])
        dichos.append(', '.join(partes))
    resto = total - len(dichos)
    cola = f' y {resto} más' if resto > 0 else ''
    return f"{titulo}: {'; '.join(dichos)}{cola}."


def _filas_chat(panorama: dict) -> list[dict]:
    filas = []
    grupos = (
        ('sin enviar', panorama['esperan_hoy'] + panorama['esperan_antes']),
        ('enviada hoy', panorama['enviadas_hoy']),
    )
    for meta, casos in grupos:
        for caso in casos:
            if len(filas) >= 8:
                return filas
            detalle = ', '.join(parte for parte in (caso.get('servicio'), caso.get('auto')) if parte)
            filas.append({
                'id': f"caso:{len(filas)}",
                'titulo': caso['cliente'][:120],
                'detalle': detalle[:180],
                'meta': meta,
            })
    return filas
