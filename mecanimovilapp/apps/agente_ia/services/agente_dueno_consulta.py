"""El dueño pregunta por los casos del taller. Eso no abre el formulario de cotizar."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime

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
    if re.search(r'\b(agrega|suma|incluye|quita|saca|esa cotizacion|el borrador)\b', p):
        return False
    menciona_personas = bool(re.search(
        r'\b(cliente|clientes|quien|quienes|solicitud|solicitudes|chat|chats)\b',
        p,
    ))
    if menciona_personas and re.search(r'\b(potencial|escrib)', p):
        return True
    menciona_cotizacion = bool(re.search(r'\b(cotiz|presupuesto|precio)\b', p))
    pide_mirar = bool(re.search(
        r'\b(saber|revisa|revisar|hay|existen|existe|dime|muestra|muestrame|lista|'
        r'cuant|cual|primero|esper|faltan|pendiente|necesitan|necesita|'
        r'hablaron|hablo|escribieron|escribio|mensaje|mensajes)\b|\?',
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
    quien = user or getattr(taller, 'usuario', None)
    chats_ok = True
    try:
        hablaron = _chats_de_hoy(quien)
    except Exception:
        logger.exception('No pude leer los chats de hoy del taller %s', getattr(taller, 'id', None))
        hablaron = []
        chats_ok = False
    ya_dichos = {caso['cliente'].casefold() for caso in hablaron}
    pipeline_ok = True
    try:
        filas = _filas_pipeline(taller, quien)
    except Exception:
        logger.exception('No pude leer el pipeline del taller %s', getattr(taller, 'id', None))
        filas = []
        pipeline_ok = False
    if not chats_ok and not pipeline_ok:
        raise RuntimeError('no pude leer chats ni pipeline')
    hoy = timezone.localdate().isoformat()
    esperan_hoy = []
    esperan_antes = []
    enviadas_hoy = []
    for fila in filas:
        estado = fila.get('estado_normalizado') or ''
        if estado in _CERRADOS:
            continue
        publico = _publico(fila)
        if publico['cliente'].casefold() in ya_dichos:
            continue
        de_hoy = _es_de_hoy(fila, hoy)
        if estado == 'nuevo':
            (esperan_hoy if de_hoy else esperan_antes).append(fila)
        elif de_hoy and estado in _YA_ENVIADA:
            enviadas_hoy.append(fila)
    return {
        'hablaron_hoy': hablaron,
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
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_tareas import (
        turno_clientes_esperando,
    )

    try:
        return turno_clientes_esperando(taller, user or getattr(taller, 'usuario', None))
    except Exception:
        logger.exception('No pude revisar quién espera cotización en el taller %s', getattr(taller, 'id', None))
        return _turno(
            haciendo='Reviso quién necesita cotización',
            titulo='Clientes de hoy',
            resumen='No pude revisar los chats del taller. Intenta de nuevo en un momento.',
            ancla='keep',
            accion_pendiente={},
        )


def _es_orden_de_armar(p: str) -> bool:
    return bool(re.search(
        r'\b(cotiza|cotizar|cotizame|cotizale)\b'
        r'|realiza una cotizacion|arma(?:r|me)? una cotizacion|haz(?:me)? una cotizacion'
        r'|presupuesto para',
        p,
    ))


_CANAL = {
    'whatsapp': 'WhatsApp',
    'messenger': 'Facebook',
    'instagram': 'Instagram',
    'app': 'la app',
}
_NO_PIDE_COTIZACION = {'casa_repuestos', 'solo_consulta', 'otro'}


def _chats_de_hoy(user) -> list[dict]:
    """Solo mensajes de hoy. No recorre el historial de la bandeja."""
    if user is None:
        return []
    inicio = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    casos = _chats_omnicanal_de_hoy(user, inicio)
    casos.extend(_chats_app_de_hoy(user, inicio))
    casos.sort(key=lambda caso: caso.get('cuando') or '', reverse=True)
    for caso in casos:
        caso.pop('cuando', None)
    return casos


def _chats_omnicanal_de_hoy(user, inicio) -> list[dict]:
    from mecanimovilapp.apps.chat.inbox import _cotizaciones_por_conversacion
    from mecanimovilapp.apps.chat.models import Message
    from mecanimovilapp.apps.omnichannel.services.omnichannel_service import (
        corte_bandeja,
        mensaje_visible_en_bandeja,
    )
    from mecanimovilapp.apps.omnichannel.utils import channel_to_api_slug

    mensajes = (
        Message.objects.filter(
            conversation__participants=user,
            conversation__source_channel__in=('WHATSAPP', 'MESSENGER', 'INSTAGRAM'),
            timestamp__gte=inicio,
        )
        .select_related(
            'conversation',
            'conversation__external_contact',
            'conversation__external_contact__connection',
        )
        .order_by('conversation_id', '-timestamp', '-id')
    )
    ultimos = {}
    for mensaje in mensajes:
        conv = mensaje.conversation
        contacto = conv.external_contact
        conexion = contacto.connection if contacto else None
        if not mensaje_visible_en_bandeja(mensaje, corte_bandeja(conexion)):
            continue
        if conv.id not in ultimos:
            ultimos[conv.id] = mensaje
    cotizaciones = _cotizaciones_por_conversacion(list(ultimos))
    casos = []
    for conv_id, mensaje in ultimos.items():
        contacto = mensaje.conversation.external_contact
        cot = cotizaciones.get(conv_id)
        estado = cot.estado if cot else ''
        rol = contacto.rol if contacto else ''
        canal = channel_to_api_slug(mensaje.conversation.source_channel)
        casos.append(_caso_chat(
            nombre=(contacto.display_name if contacto else '') or 'Cliente sin nombre',
            canal=_CANAL.get(canal, canal),
            texto=mensaje.content or '',
            lo_dijo_el_taller=mensaje.direction == 'outbound',
            servicio=(cot.servicio_nombre if cot else '') or '',
            estado=estado,
            rol=rol,
            cuando=mensaje.timestamp,
        ))
    return casos


def _chats_app_de_hoy(user, inicio) -> list[dict]:
    from mecanimovilapp.apps.ordenes.models import ChatSolicitud

    mensajes = (
        ChatSolicitud.objects.filter(
            oferta__proveedor=user,
            fecha_envio__gte=inicio,
        )
        .select_related(
            'oferta__solicitud__cliente__usuario',
        )
        .order_by('oferta_id', '-fecha_envio')
    )
    ultimos = {}
    for mensaje in mensajes:
        if mensaje.oferta_id not in ultimos:
            ultimos[mensaje.oferta_id] = mensaje
    casos = []
    for mensaje in ultimos.values():
        cliente = mensaje.oferta.solicitud.cliente
        usuario = getattr(cliente, 'usuario', None)
        nombre = ''
        if usuario is not None:
            nombre = (usuario.get_full_name() or usuario.username or '').strip()
        casos.append(_caso_chat(
            nombre=nombre or 'Cliente sin nombre',
            canal='la app',
            texto=mensaje.mensaje or '',
            lo_dijo_el_taller=bool(mensaje.es_proveedor),
            servicio='',
            estado='',
            rol='',
            cuando=mensaje.fecha_envio,
        ))
    return casos


def _caso_chat(*, nombre, canal, texto, lo_dijo_el_taller, servicio, estado, rol, cuando) -> dict:
    limpio = ' '.join(str(texto or '').split())
    if len(limpio) > 90:
        limpio = limpio[:87].rstrip() + '…'
    return {
        'cliente': nombre,
        'canal': canal,
        'dijo': limpio,
        'lo_dijo_el_taller': lo_dijo_el_taller,
        'servicio': servicio,
        'estado_cotizacion': estado,
        'necesita_cotizacion': rol not in _NO_PIDE_COTIZACION and estado in ('', 'borrador'),
        'cuando': cuando.isoformat() if hasattr(cuando, 'isoformat') else '',
    }


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
    if isinstance(valor, datetime):
        if timezone.is_aware(valor):
            valor = timezone.localtime(valor)
        return valor.date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
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
    hablaron = panorama['hablaron_hoy']
    esperan_hoy = panorama['esperan_hoy_total']
    antes = panorama['esperan_antes_total']
    enviadas = panorama['enviadas_hoy_total']
    if not hablaron and not esperan_hoy and not antes and not enviadas:
        return (
            'Hoy no hay clientes que hayan escrito ni que esperen cotización. '
            'Tampoco hay cotizaciones enviadas hoy.'
        )
    partes = []
    if hablaron:
        necesitan = [caso for caso in hablaron if caso['necesita_cotizacion']]
        ya = [caso for caso in hablaron if not caso['necesita_cotizacion']]
        if necesitan:
            partes.append(_frase_chats(
                f'Hoy escribieron {len(hablaron)}. Sin cotización enviada',
                necesitan,
            ))
        elif ya:
            partes.append(_frase_chats(f'Hoy escribieron {len(hablaron)}', ya))
        if necesitan and ya:
            partes.append(_frase_chats('Hoy escribieron y ya tienen cotización', ya))
    else:
        partes.append('Hoy nadie escribió por WhatsApp, Instagram, Facebook ni la app.')
    if esperan_hoy:
        partes.append(_frase(
            'Sin chat de hoy, y sin cotización enviada',
            panorama['esperan_hoy'],
            esperan_hoy,
        ))
    if enviadas:
        partes.append(_frase('Hoy ya tienen cotización enviada', panorama['enviadas_hoy'], enviadas))
    if antes:
        partes.append(
            f'Además hay {antes} de días anteriores que siguen sin cotización enviada.'
            if esperan_hoy or hablaron
            else _frase('Siguen sin cotización enviada, de antes', panorama['esperan_antes'], antes)
        )
    return ' '.join(partes)


def _frase_chats(titulo: str, casos: list[dict]) -> str:
    dichos = []
    for caso in casos[:5]:
        quien = caso['cliente']
        if caso.get('canal'):
            quien = f"{quien} por {caso['canal']}"
        if caso.get('dijo'):
            verbo = 'el taller respondió' if caso.get('lo_dijo_el_taller') else 'dijo'
            quien = f'{quien}, {verbo} «{caso["dijo"]}»'
        dichos.append(quien)
    resto = len(casos) - len(dichos)
    cola = f' y {resto} más' if resto > 0 else ''
    return f"{titulo}: {'; '.join(dichos)}{cola}."


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
    for caso in panorama['hablaron_hoy']:
        if len(filas) >= 8:
            return filas
        filas.append({
            'id': f"caso:{len(filas)}",
            'titulo': caso['cliente'][:120],
            'detalle': (caso.get('dijo') or caso.get('servicio') or '')[:180],
            'meta': 'sin cotización' if caso['necesita_cotizacion'] else 'ya cotizado',
        })
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
