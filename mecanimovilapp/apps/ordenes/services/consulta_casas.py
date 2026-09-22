"""Consulta de una pieza a las casas de repuestos del taller."""
from __future__ import annotations

import logging
import re
from typing import Any

from django.db import transaction
from django.utils import timezone

from mecanimovilapp.apps.omnichannel.models import ExternalContact
from mecanimovilapp.apps.ordenes.models import ConsultaRepuesto, CotizacionCanal, ProveedorRepuestos
from mecanimovilapp.apps.ordenes.services.horario_habil import sumar_horas_habiles

logger = logging.getLogger(__name__)

MAX_CASAS_POR_PIEZA = 5
MAX_PIEZAS_ABIERTAS = 3
CONFIANZA_ALTA = 0.8
_SIN_STOCK_RE = re.compile(
    r'\b(?:no\s+tenemos|no\s+hay|sin\s+stock|no\s+la\s+tengo|no\s+lo\s+tengo|agotad[oa]s?)\b',
    re.I,
)
_PRECIO_RE = re.compile(
    r'(?:\$\s*)?(\d{1,3}(?:\.\d{3})+|\d{4,7})',
)
_CALIDAD_RE = re.compile(r'\b(original|oem|alternativ[oa])\b', re.I)


def texto_consulta(*, pieza: str, vehiculo: dict) -> str:
    """Plantilla fija. No incluye datos del cliente ni prosa del modelo."""
    auto = _auto_txt(vehiculo)
    lineas = [f'Hola, ¿tienen {pieza} para {auto}?']
    calidad = (vehiculo.get('calidad') or '').strip()
    codigo = (vehiculo.get('codigo') or '').strip()
    if calidad:
        lineas.append(f'Calidad: {calidad}.')
    if codigo:
        lineas.append(f'Código: {codigo}.')
    lineas.append('Quedo atento al precio, stock y plazo.')
    return ' '.join(lineas)


def texto_recordatorio(*, pieza: str, vehiculo: dict) -> str:
    auto = _auto_txt(vehiculo)
    return (
        f'Hola, les recuerdo la consulta de {pieza} para {auto}. '
        '¿Tienen precio y stock?'
    )


def _auto_txt(vehiculo: dict) -> str:
    partes = [
        str(vehiculo.get('marca') or '').strip(),
        str(vehiculo.get('modelo') or '').strip(),
        str(vehiculo.get('anio') or '').strip(),
        str(vehiculo.get('motor') or '').strip(),
    ]
    auto = ' '.join(p for p in partes if p) or 'el vehículo'
    patente = str(vehiculo.get('patente') or '').strip()
    if patente:
        auto = f'{auto}, patente {patente}'
    return auto


def vehiculo_desde_cotizacion(cotizacion: CotizacionCanal, repuesto: dict) -> dict:
    motor = (cotizacion.tipo_motor_label or cotizacion.tipo_motor or cotizacion.vehiculo_cilindraje or '').strip()
    return {
        'marca': cotizacion.vehiculo_marca or '',
        'modelo': cotizacion.vehiculo_modelo or '',
        'anio': cotizacion.vehiculo_anio or '',
        'motor': motor,
        'patente': cotizacion.vehiculo_patente or '',
        'calidad': str(repuesto.get('calidad') or '').strip(),
        'codigo': str(repuesto.get('codigo_parte') or '').strip(),
    }


def extraer_respuesta(texto: str) -> dict[str, Any]:
    """Lee precio, stock y calidad desde el texto. Varios montos quedan por revisar."""
    crudo = (texto or '').strip()
    precios = [_a_clp(m.group(1)) for m in _PRECIO_RE.finditer(crudo)]
    precios = [p for p in precios if 1000 <= p <= 5_000_000]
    calidad = ''
    cal = _CALIDAD_RE.search(crudo)
    if cal:
        token = cal.group(1).lower()
        calidad = 'alternativo' if token.startswith('alternativ') else token
    if _SIN_STOCK_RE.search(crudo) and not precios:
        return {
            'estado': ConsultaRepuesto.ESTADO_SIN_STOCK,
            'precio_clp': 0,
            'confianza': 0.9,
            'calidad': calidad,
        }
    unicos = list(dict.fromkeys(precios))
    if len(unicos) == 1:
        return {
            'estado': ConsultaRepuesto.ESTADO_RESPONDIDA,
            'precio_clp': unicos[0],
            'confianza': 0.9,
            'calidad': calidad,
        }
    if crudo or unicos:
        return {
            'estado': ConsultaRepuesto.ESTADO_POR_REVISAR,
            'precio_clp': 0,
            'confianza': 0.4,
            'calidad': calidad,
        }
    return {
        'estado': ConsultaRepuesto.ESTADO_POR_REVISAR,
        'precio_clp': 0,
        'confianza': 0.2,
        'calidad': '',
    }


def _a_clp(token: str) -> int:
    return int(token.replace('.', ''))


def casas_elegibles(taller_id: int, *, excluir_ids: set[int] | None = None) -> list[ProveedorRepuestos]:
    qs = ProveedorRepuestos.objects.filter(taller_id=taller_id, activo=True).exclude(telefono_norm='')
    if excluir_ids:
        qs = qs.exclude(pk__in=excluir_ids)
    preferidas = list(qs.filter(es_preferido=True).order_by('nombre')[:MAX_CASAS_POR_PIEZA])
    if len(preferidas) >= MAX_CASAS_POR_PIEZA:
        return preferidas
    resto = list(
        qs.filter(es_preferido=False).order_by('nombre')[: MAX_CASAS_POR_PIEZA - len(preferidas)]
    )
    return preferidas + resto


def consultar_lineas_sin_precio_si_automatico(cotizacion: CotizacionCanal) -> dict:
    from mecanimovilapp.apps.agente_ia.models import TallerAgenteConfig

    config = TallerAgenteConfig.objects.filter(taller_id=cotizacion.taller_id).first()
    if config is None or not config.consulta_casas_automatica:
        return {'omitido': True, 'motivo': 'automatico_apagado'}
    if cotizacion.estado != 'borrador':
        return {'omitido': True, 'motivo': 'no_borrador'}
    abiertas = set(
        ConsultaRepuesto.objects.filter(
            cotizacion=cotizacion,
            estado__in=ConsultaRepuesto.ESTADOS_ABIERTOS,
        ).values_list('repuesto_id', flat=True)
    )
    if len(abiertas) >= MAX_PIEZAS_ABIERTAS:
        return {'omitido': True, 'motivo': 'tope_piezas'}
    lanzadas = []
    for rep in cotizacion.repuestos or []:
        if not isinstance(rep, dict):
            continue
        if str(rep.get('certeza') or '') != 'sin_precio':
            continue
        if int(rep.get('precio_unitario_clp') or 0) > 0:
            continue
        rid = str(rep.get('id') or '')
        if not rid or rid in abiertas:
            continue
        if len(abiertas) >= MAX_PIEZAS_ABIERTAS:
            break
        resultado = abrir_consultas(cotizacion, rid, origen='automatico')
        lanzadas.append(resultado)
        if resultado.get('enviadas'):
            abiertas.add(rid)
    return {'lanzadas': lanzadas}


def abrir_consultas(
    cotizacion: CotizacionCanal,
    repuesto_id: str,
    *,
    origen: str,
    proveedor_id: int | None = None,
    solo_restantes: bool = False,
) -> dict[str, Any]:
    repuesto = _linea(cotizacion, repuesto_id)
    if repuesto is None:
        return {'ok': False, 'motivo': 'linea_no_encontrada'}
    ya = set(
        ConsultaRepuesto.objects.filter(
            cotizacion=cotizacion,
            repuesto_id=repuesto_id,
        ).exclude(
            estado__in=(ConsultaRepuesto.ESTADO_CANCELADA,),
        ).values_list('proveedor_id', flat=True)
    )
    if proveedor_id:
        casas = list(
            ProveedorRepuestos.objects.filter(
                pk=proveedor_id,
                taller_id=cotizacion.taller_id,
                activo=True,
            ).exclude(telefono_norm='')
        )
    elif solo_restantes:
        casas = casas_elegibles(cotizacion.taller_id, excluir_ids=ya)
    else:
        casas = casas_elegibles(cotizacion.taller_id)
        casas = [c for c in casas if c.id not in ya]
    piezas_abiertas = ConsultaRepuesto.objects.filter(
        cotizacion=cotizacion,
        estado__in=ConsultaRepuesto.ESTADOS_ABIERTOS,
    ).values('repuesto_id').distinct().count()
    if repuesto_id not in set(
        ConsultaRepuesto.objects.filter(
            cotizacion=cotizacion,
            estado__in=ConsultaRepuesto.ESTADOS_ABIERTOS,
        ).values_list('repuesto_id', flat=True)
    ) and piezas_abiertas >= MAX_PIEZAS_ABIERTAS:
        return {'ok': False, 'motivo': 'tope_piezas'}
    if not casas:
        return {'ok': False, 'motivo': 'sin_casas', 'enviadas': 0}
    unica = len(casas) == 1 and not solo_restantes
    vehiculo = vehiculo_desde_cotizacion(cotizacion, repuesto)
    pieza = str(repuesto.get('nombre') or 'la pieza').strip()
    _avisar(
        cotizacion,
        titulo='Consulta a casas de repuestos',
        mensaje=(
            f'Voy a consultar {pieza} ({_auto_txt(vehiculo)}) '
            f'a {", ".join(c.nombre for c in casas)}.'
        ),
        dedup=f'consulta-inicio-{cotizacion.id}-{repuesto_id}-{origen}',
        data={
            'type': 'consulta_repuesto_inicio',
            'cotizacion_id': cotizacion.id,
            'repuesto_id': repuesto_id,
        },
    )
    enviadas = 0
    fallidas = 0
    for casa in casas:
        consulta = _crear_consulta(
            cotizacion=cotizacion,
            casa=casa,
            repuesto_id=repuesto_id,
            pieza=pieza,
            vehiculo=vehiculo,
            origen=origen,
            unica=unica and len(casas) == 1,
        )
        if consulta is None:
            continue
        if _enviar(consulta, texto_consulta(pieza=pieza, vehiculo=vehiculo)):
            enviadas += 1
        else:
            fallidas += 1
    return {'ok': enviadas > 0, 'enviadas': enviadas, 'fallidas': fallidas, 'casas': [c.nombre for c in casas]}


def _linea(cotizacion: CotizacionCanal, repuesto_id: str) -> dict | None:
    for rep in cotizacion.repuestos or []:
        if isinstance(rep, dict) and str(rep.get('id') or '') == str(repuesto_id):
            return rep
    return None


def _crear_consulta(**kwargs) -> ConsultaRepuesto | None:
    abierta = ConsultaRepuesto.objects.filter(
        cotizacion=kwargs['cotizacion'],
        repuesto_id=kwargs['repuesto_id'],
        proveedor=kwargs['casa'],
        estado__in=ConsultaRepuesto.ESTADOS_ABIERTOS,
    ).first()
    if abierta:
        return None
    ahora = timezone.now()
    conversacion = _conversacion_casa(kwargs['casa'])
    if _hilo_pausado(conversacion):
        return None
    return ConsultaRepuesto.objects.create(
        taller=kwargs['cotizacion'].taller,
        proveedor=kwargs['casa'],
        cotizacion=kwargs['cotizacion'],
        conversation=conversacion,
        repuesto_id=kwargs['repuesto_id'],
        pieza_nombre=kwargs['pieza'][:200],
        vehiculo_snapshot=kwargs['vehiculo'],
        origen=kwargs['origen'],
        unica=kwargs['unica'],
        estado=ConsultaRepuesto.ESTADO_ESPERANDO,
        recordatorio_en=sumar_horas_habiles(ahora, 2),
        cierra_en=sumar_horas_habiles(ahora, 4),
    )


def _conversacion_casa(casa: ProveedorRepuestos):
    from mecanimovilapp.apps.chat.models import Conversation

    contact = casa.external_contact
    if contact is None:
        from mecanimovilapp.apps.ordenes.services.rol_contacto import contactos_por_telefono
        hallados = contactos_por_telefono(casa.taller, casa.telefono_norm)
        contact = hallados[0] if hallados else None
        if contact is not None:
            casa.external_contact = contact
            casa.save(update_fields=['external_contact', 'actualizado_en'])
    if contact is None:
        return None
    return (
        Conversation.objects.filter(external_contact=contact)
        .order_by('-updated_at')
        .first()
    )


def _hilo_pausado(conversation) -> bool:
    if conversation is None:
        return False
    from mecanimovilapp.apps.agente_ia.models import AgenteConversacionSesion

    sesion = AgenteConversacionSesion.objects.filter(conversation=conversation).first()
    if sesion is None:
        return False
    return bool(sesion.pausado_por_taller) or not bool(sesion.habilitado_en_chat)


def _enviar(consulta: ConsultaRepuesto, texto: str) -> bool:
    conversation = consulta.conversation
    if conversation is None:
        _marcar_fallida(consulta, 'sin_hilo')
        return False
    from mecanimovilapp.apps.omnichannel.services.outbound_guard import (
        OutboundBlockedError,
        validate_omnichannel_outbound,
    )
    try:
        validate_omnichannel_outbound(conversation)
    except OutboundBlockedError:
        _marcar_fallida(consulta, 'fuera_de_ventana')
        return False
    proveedor_user_id = conversation.participants.order_by('id').values_list('id', flat=True).first()
    taller_user = getattr(consulta.taller, 'usuario_id', None)
    if taller_user:
        proveedor_user_id = taller_user
    if not proveedor_user_id:
        _marcar_fallida(consulta, 'sin_remitente')
        return False
    from mecanimovilapp.apps.agente_ia.services.orquestador import enviar_respuesta_agente

    mensaje = enviar_respuesta_agente(
        conversation=conversation,
        proveedor_user_id=proveedor_user_id,
        texto=texto,
        extra_metadata={
            'tipo': 'consulta_repuesto',
            'consulta_id': consulta.id,
            'cotizacion_id': consulta.cotizacion_id,
        },
    )
    if mensaje is None:
        _marcar_fallida(consulta, 'envio_bloqueado')
        return False
    consulta.mensaje_saliente = mensaje
    consulta.estado = ConsultaRepuesto.ESTADO_ESPERANDO
    consulta.save(update_fields=['mensaje_saliente', 'estado', 'actualizado_en'])
    _programar(consulta)
    return True


def _marcar_fallida(consulta: ConsultaRepuesto, motivo: str) -> None:
    consulta.estado = ConsultaRepuesto.ESTADO_FALLIDA
    consulta.extraccion = {'motivo': motivo}
    consulta.save(update_fields=['estado', 'extraccion', 'actualizado_en'])
    _avisar(
        consulta.cotizacion,
        titulo='No se escribió a la casa',
        mensaje=(
            f'No pude escribir a {consulta.proveedor.nombre} por {consulta.pieza_nombre}. '
            'WhatsApp no dejó el mensaje (sin conversación reciente o fuera de 24 horas).'
        ),
        dedup=f'consulta-fallida-{consulta.id}',
        data={'type': 'consulta_repuesto_fallida', 'consulta_id': consulta.id, 'cotizacion_id': consulta.cotizacion_id},
    )


def _programar(consulta: ConsultaRepuesto) -> None:
    from mecanimovilapp.apps.agente_ia.tasks import (
        cierre_consulta_repuesto_task,
        recordatorio_consulta_repuesto_task,
    )
    if consulta.recordatorio_en:
        recordatorio_consulta_repuesto_task.apply_async(args=[consulta.id], eta=consulta.recordatorio_en)
    if consulta.cierra_en:
        cierre_consulta_repuesto_task.apply_async(args=[consulta.id], eta=consulta.cierra_en)


def recordar_consulta(consulta_id: int) -> dict:
    consulta = ConsultaRepuesto.objects.select_related('proveedor', 'cotizacion', 'conversation', 'taller').filter(pk=consulta_id).first()
    if consulta is None or consulta.estado != ConsultaRepuesto.ESTADO_ESPERANDO or consulta.recordatorio_enviado:
        return {'omitido': True}
    if consulta.conversation is None:
        return {'omitido': True}
    from mecanimovilapp.apps.agente_ia.services.orquestador import enviar_respuesta_agente
    from mecanimovilapp.apps.omnichannel.services.outbound_guard import (
        OutboundBlockedError,
        validate_omnichannel_outbound,
    )
    try:
        validate_omnichannel_outbound(consulta.conversation)
    except OutboundBlockedError:
        return {'omitido': True, 'motivo': 'fuera_de_ventana'}
    user_id = consulta.taller.usuario_id
    if not user_id:
        return {'omitido': True}
    mensaje = enviar_respuesta_agente(
        conversation=consulta.conversation,
        proveedor_user_id=user_id,
        texto=texto_recordatorio(pieza=consulta.pieza_nombre, vehiculo=consulta.vehiculo_snapshot or {}),
        extra_metadata={'tipo': 'consulta_repuesto_recordatorio', 'consulta_id': consulta.id},
    )
    if mensaje is None:
        return {'omitido': True, 'motivo': 'no_enviado'}
    consulta.estado = ConsultaRepuesto.ESTADO_RECORDADA
    consulta.recordatorio_enviado = True
    consulta.save(update_fields=['estado', 'recordatorio_enviado', 'actualizado_en'])
    _avisar(
        consulta.cotizacion,
        titulo='Recordatorio a la casa',
        mensaje=f'Le recordé a {consulta.proveedor.nombre} la consulta de {consulta.pieza_nombre}. Sigo esperando.',
        dedup=f'consulta-recordatorio-{consulta.id}',
        data={'type': 'consulta_repuesto_recordatorio', 'consulta_id': consulta.id, 'cotizacion_id': consulta.cotizacion_id},
    )
    return {'ok': True}


def cerrar_por_silencio(consulta_id: int) -> dict:
    consulta = ConsultaRepuesto.objects.select_related('proveedor', 'cotizacion', 'taller').filter(pk=consulta_id).first()
    if consulta is None or consulta.estado not in ConsultaRepuesto.ESTADOS_ABIERTOS:
        return {'omitido': True}
    consulta.estado = ConsultaRepuesto.ESTADO_SIN_RESPUESTA
    consulta.save(update_fields=['estado', 'actualizado_en'])
    _anotar_linea(consulta, estado_linea='sin_respuesta')
    otras = _quedan_otras(consulta)
    if otras and consulta.unica:
        mensaje = (
            f'{consulta.proveedor.nombre} no respondió por {consulta.pieza_nombre} '
            f'({_auto_txt(consulta.vehiculo_snapshot or {})}). '
            'La cotización sigue en espera. Puedes consultar las otras casas.'
        )
    else:
        mensaje = (
            f'{consulta.proveedor.nombre} no respondió por {consulta.pieza_nombre} '
            f'({_auto_txt(consulta.vehiculo_snapshot or {})}).'
        )
    _avisar(
        consulta.cotizacion,
        titulo='Casa sin respuesta',
        mensaje=mensaje,
        dedup=f'consulta-silencio-{consulta.cotizacion_id}-{consulta.repuesto_id}',
        data={
            'type': 'consulta_repuesto_sin_respuesta',
            'consulta_id': consulta.id,
            'cotizacion_id': consulta.cotizacion_id,
            'repuesto_id': consulta.repuesto_id,
            'puede_consultar_otras': bool(otras and consulta.unica),
        },
    )
    return {'ok': True, 'puede_consultar_otras': bool(otras and consulta.unica)}


def _quedan_otras(consulta: ConsultaRepuesto) -> bool:
    usadas = set(
        ConsultaRepuesto.objects.filter(
            cotizacion_id=consulta.cotizacion_id,
            repuesto_id=consulta.repuesto_id,
        ).values_list('proveedor_id', flat=True)
    )
    return ProveedorRepuestos.objects.filter(
        taller_id=consulta.taller_id,
        activo=True,
    ).exclude(telefono_norm='').exclude(pk__in=usadas).exists()


def procesar_respuesta_casa(message, contact: ExternalContact, taller, proveedor_user_id: int) -> dict:
    """Lee la respuesta de una casa. No vende servicios y no escribe de vuelta."""
    del proveedor_user_id
    casa = ProveedorRepuestos.objects.filter(
        taller=taller,
        activo=True,
        external_contact=contact,
    ).first()
    if casa is None:
        from mecanimovilapp.apps.ordenes.services.rol_contacto import contactos_por_telefono
        casas = ProveedorRepuestos.objects.filter(taller=taller, activo=True).exclude(telefono_norm='')
        for candidata in casas:
            if contact in contactos_por_telefono(taller, candidata.telefono_norm):
                casa = candidata
                break
    if casa is None:
        return {'skipped': True, 'reason': 'casa_sin_ficha', 'handled': True}
    consulta = (
        ConsultaRepuesto.objects.filter(
            proveedor=casa,
            estado__in=ConsultaRepuesto.ESTADOS_ABIERTOS,
        )
        .select_related('cotizacion')
        .order_by('-creado_en')
        .first()
    )
    if consulta is None:
        from datetime import timedelta

        desde = timezone.now() - timedelta(hours=48)
        consulta = (
            ConsultaRepuesto.objects.filter(
                proveedor=casa,
                estado__in=(
                    ConsultaRepuesto.ESTADO_SIN_RESPUESTA,
                    ConsultaRepuesto.ESTADO_SIN_STOCK,
                    ConsultaRepuesto.ESTADO_POR_REVISAR,
                ),
                actualizado_en__gte=desde,
                cotizacion__estado='borrador',
            )
            .select_related('cotizacion')
            .order_by('-actualizado_en')
            .first()
        )
        if consulta is None:
            return {'skipped': True, 'reason': 'casa_sin_consulta', 'handled': True}
    texto = (message.content or '').strip()
    if getattr(message, 'attachment', None):
        texto = _texto_con_adjunto(message, texto)
    parsed = extraer_respuesta(texto)
    consulta.mensaje_respuesta = message
    consulta.extraccion = parsed
    consulta.confianza = float(parsed.get('confianza') or 0)
    consulta.estado = parsed['estado']
    consulta.save(update_fields=['mensaje_respuesta', 'extraccion', 'confianza', 'estado', 'actualizado_en'])
    _aplicar_en_cotizacion(consulta, parsed)
    return {'ok': True, 'handled': True, 'estado': consulta.estado}


def _texto_con_adjunto(message, texto: str) -> str:
    try:
        from mecanimovilapp.apps.agente_ia.services.media_analisis import analizar_adjunto_mensaje
        analisis = analizar_adjunto_mensaje(message, proposito='proveedor') or {}
        resumen = str(analisis.get('resumen_para_chat') or '').strip()
        if resumen and resumen not in texto:
            texto = f'{texto}\n{resumen}'.strip()
    except Exception:
        logger.info('Adjunto de casa sin análisis msg=%s', getattr(message, 'id', None))
    if not texto:
        texto = '[adjunto]'
    return texto


def _aplicar_en_cotizacion(consulta: ConsultaRepuesto, parsed: dict) -> None:
    with transaction.atomic():
        cot = CotizacionCanal.objects.select_for_update().get(pk=consulta.cotizacion_id)
        if cot.estado != 'borrador':
            return
        reps = list(cot.repuestos or [])
        idx = next(
            (i for i, rep in enumerate(reps) if isinstance(rep, dict) and str(rep.get('id') or '') == consulta.repuesto_id),
            None,
        )
        if idx is None:
            return
        rep = dict(reps[idx])
        opcion = {
            'casa': consulta.proveedor.nombre,
            'proveedor_id': consulta.proveedor_id,
            'precio_clp': int(parsed.get('precio_clp') or 0),
            'calidad': parsed.get('calidad') or '',
            'estado': parsed.get('estado'),
            'confianza': parsed.get('confianza') or 0,
            'consulta_id': consulta.id,
            'mensaje_id': consulta.mensaje_respuesta_id,
        }
        opciones = list(rep.get('opciones_casa') or [])
        opciones.append(opcion)
        rep['opciones_casa'] = opciones[-8:]
        precio = int(parsed.get('precio_clp') or 0)
        alta = float(parsed.get('confianza') or 0) >= CONFIANZA_ALTA and precio > 0
        precio_previo = int(rep.get('precio_unitario_clp') or 0)
        if alta and precio_previo <= 0:
            rep['precio_unitario_clp'] = precio
            rep['proveedor_nombre'] = consulta.proveedor.nombre
            rep['proveedor_id'] = consulta.proveedor_id
            rep['fuente_marketplace'] = 'casa_repuestos'
            rep['certeza'] = 'referencial'
            rep['precio_estimado'] = True
            rep['comentario'] = f'Cotizado por {consulta.proveedor.nombre}'
            if parsed.get('calidad'):
                rep['calidad'] = parsed['calidad']
        rep['consulta_casas'] = {
            'estado': parsed.get('estado'),
            'casa': consulta.proveedor.nombre,
            'puede_consultar_otras': parsed.get('estado') in (
                ConsultaRepuesto.ESTADO_SIN_RESPUESTA,
                ConsultaRepuesto.ESTADO_SIN_STOCK,
            ) and consulta.unica and _quedan_otras(consulta),
        }
        reps[idx] = rep
        cot.repuestos = reps
        from mecanimovilapp.apps.ordenes.services.cotizacion_canal import aplicar_totales_cotizacion
        aplicar_totales_cotizacion(cot)
        cot.save(update_fields=['repuestos', 'costo_repuestos_clp', 'mano_obra_clp', 'descuento_clp', 'total_clp', 'actualizado_en'])
    if parsed.get('estado') == ConsultaRepuesto.ESTADO_SIN_STOCK:
        _avisar(
            consulta.cotizacion,
            titulo='La casa no tiene la pieza',
            mensaje=f'{consulta.proveedor.nombre} no tiene {consulta.pieza_nombre}.',
            dedup=f'consulta-sinstock-{consulta.id}',
            data={'type': 'consulta_repuesto_sin_stock', 'cotizacion_id': consulta.cotizacion_id, 'repuesto_id': consulta.repuesto_id},
        )
    elif alta:
        _avisar(
            consulta.cotizacion,
            titulo='Precio de casa de repuestos',
            mensaje=(
                f'{consulta.proveedor.nombre} cotizó {consulta.pieza_nombre} '
                f'a ${precio:,} CLP.'.replace(',', '.')
            ),
            dedup=f'consulta-precio-{consulta.id}',
            data={'type': 'consulta_repuesto_precio', 'cotizacion_id': consulta.cotizacion_id, 'repuesto_id': consulta.repuesto_id},
        )
    else:
        _avisar(
            consulta.cotizacion,
            titulo='Respuesta por revisar',
            mensaje=f'{consulta.proveedor.nombre} respondió por {consulta.pieza_nombre}. Revisa el mensaje antes de usar el precio.',
            dedup=f'consulta-revisar-{consulta.id}',
            data={'type': 'consulta_repuesto_revisar', 'cotizacion_id': consulta.cotizacion_id, 'repuesto_id': consulta.repuesto_id},
        )


def _anotar_linea(consulta: ConsultaRepuesto, *, estado_linea: str) -> None:
    cot = consulta.cotizacion
    reps = list(cot.repuestos or [])
    cambio = False
    for i, rep in enumerate(reps):
        if not isinstance(rep, dict) or str(rep.get('id') or '') != consulta.repuesto_id:
            continue
        actual = dict(rep)
        actual['consulta_casas'] = {
            'estado': estado_linea,
            'casa': consulta.proveedor.nombre,
            'puede_consultar_otras': bool(consulta.unica and _quedan_otras(consulta)),
        }
        reps[i] = actual
        cambio = True
        break
    if cambio:
        cot.repuestos = reps
        cot.save(update_fields=['repuestos', 'actualizado_en'])


def _avisar(cotizacion: CotizacionCanal, *, titulo: str, mensaje: str, dedup: str, data: dict) -> None:
    user_id = cotizacion.creado_por_id or getattr(cotizacion.taller, 'usuario_id', None)
    if not user_id:
        return
    from django.contrib.auth import get_user_model
    from mecanimovilapp.apps.usuarios.models import Notificacion
    from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification

    User = get_user_model()
    usuario = User.objects.filter(pk=user_id).first()
    if usuario is None:
        return
    Notificacion.crear_unica(
        usuario,
        tipo='system',
        titulo=titulo,
        mensaje=mensaje,
        data=data,
        ventana_horas=6,
        dedup_key={'type': data.get('type'), 'dedup': dedup},
    )
    try:
        send_expo_push_notification.delay(user_id, titulo, mensaje, data)
    except Exception as exc:
        logger.warning('Push consulta repuesto no encolado: %s', exc)


def nota_para_agente_comercial(conversation_id: int) -> str:
    abiertas = ConsultaRepuesto.objects.filter(
        cotizacion__conversation_id=conversation_id,
        estado__in=ConsultaRepuesto.ESTADOS_ABIERTOS,
        cotizacion__estado='borrador',
    ).exists()
    if not abiertas:
        return ''
    return (
        'Hay una consulta de repuestos en curso con un proveedor del taller. '
        'Si el cliente pregunta por la cotización, di que se está cerrando. '
        'No nombres al proveedor ni des un monto de esa pieza.'
    )
