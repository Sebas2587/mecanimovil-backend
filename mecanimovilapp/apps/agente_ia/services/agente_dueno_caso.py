"""Un turno del dueño resuelve un caso y, con un sí, llama la herramienta que ya existe."""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Q
from django.utils import timezone

logger = logging.getLogger(__name__)

_ESTADOS_ORDEN_FUERA = {
    'cancelado',
    'rechazada_por_proveedor',
    'devuelto',
    'pendiente_devolucion',
}
_VERBOS = {
    'enviar': 'Enviar',
    'revisar_precios': 'Revisar precios',
    'marcar_aceptada': 'Marcar aceptada',
    'agendar': 'Agendar',
    'empezar': 'Empezar',
    'anotar_cobro': 'Anotar cobro',
    'contestar': 'Contestar',
    'confirmar': 'Confirmar',
}
_MEDIOS = {
    'efectivo': 'Efectivo',
    'transferencia': 'Transferencia',
    'debito': 'Débito',
    'credito': 'Crédito',
    'mercadopago': 'Mercado Pago',
}


def plano(value: str) -> str:
    texto = unicodedata.normalize('NFD', value or '')
    texto = ''.join(ch for ch in texto if unicodedata.category(ch) != 'Mn')
    return texto.lower().strip()


def clp(valor: int) -> str:
    return f'{int(valor):,}'.replace(',', '.')


def correcciones_para_prompt(taller) -> list[dict]:
    return [
        {
            'caso_id': item['caso_id'],
            'descarta': item['descarta'],
            'valor': item['valor'],
            'texto': item['texto'],
        }
        for item in _leer_correcciones(taller)
    ]


def agenda_del_dia(taller, fecha: date | None = None) -> list[dict]:
    """Citas confirmadas y órdenes de la app con hora ese día. La misma lista que Agenda."""
    dia = fecha or timezone.localdate()
    correcciones = _leer_correcciones(taller)
    salida = []
    for caso in casos_abiertos(taller, dia):
        if caso['fecha'] != dia.isoformat() or caso['tipo'] not in ('cita', 'orden'):
            continue
        if caso['tipo'] == 'cita' and not caso['confirmado']:
            continue
        copia = dict(caso)
        if _cliente_descartado(caso, correcciones):
            copia['cliente'] = ''
            copia['cliente_descartado'] = True
        salida.append(copia)
    salida.sort(key=lambda item: (item['hora'], item['id']))
    return salida


def casos_abiertos(taller, hoy: date | None = None) -> list[dict]:
    from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, CotizacionCanal, SolicitudServicio

    dia = hoy or timezone.localdate()
    desde = dia - timedelta(days=1)
    hasta = dia + timedelta(days=21)
    citas = list(
        CitaAgendaPersonal.objects.filter(taller=taller, estado='activa')
        .filter(Q(horario_por_confirmar=True) | Q(fecha_servicio__gte=desde, fecha_servicio__lte=hasta))
        .select_related(
            'detalle',
            'detalle__oferta_servicio',
            'detalle__oferta_servicio__servicio',
            'detalle__oferta_servicio__marca_vehiculo_seleccionada',
            'detalle__oferta_servicio__modelo_vehiculo_seleccionado',
            'cotizacion_canal_origen',
            'miembro_taller',
        )
        .order_by('fecha_servicio', 'hora_servicio')[:40]
    )
    iniciadas: set[int] = set()
    if citas:
        try:
            from mecanimovilapp.apps.checklists.models import ChecklistInstance
            iniciadas = set(
                ChecklistInstance.objects.filter(cita_personal_id__in=[cita.id for cita in citas])
                .values_list('cita_personal_id', flat=True)
            )
        except Exception:
            logger.exception('No pude leer checklists de citas del taller %s', taller.id)

    casos = [_caso_cita(cita, cita.id in iniciadas, dia) for cita in citas]
    cotizacion_con_cita = {
        caso['cotizacion_id'] for caso in casos if caso.get('cotizacion_id')
    }
    ordenes = (
        SolicitudServicio.objects.filter(
            taller=taller,
            fecha_servicio__gte=desde,
            fecha_servicio__lte=hasta,
        )
        .exclude(estado__in=_ESTADOS_ORDEN_FUERA)
        .select_related('cliente', 'vehiculo', 'vehiculo__marca', 'vehiculo__modelo')
        .prefetch_related('lineas__oferta_servicio__servicio')
        .order_by('fecha_servicio', 'hora_servicio')[:40]
    )
    casos.extend(_caso_orden(orden, dia) for orden in ordenes)
    cotizaciones = (
        CotizacionCanal.objects.filter(taller=taller, estado__in=('borrador', 'enviada'))
        .order_by('-actualizado_en')[:30]
    )
    for cotizacion in cotizaciones:
        if cotizacion.id in cotizacion_con_cita:
            continue
        casos.append(_caso_cotizacion(cotizacion, dia))
    return casos


def resolver_turno(taller, hilo, texto: str, user) -> dict | None:
    texto = (texto or '').strip()
    if not texto:
        return None
    p = plano(texto)
    correcciones = _leer_correcciones(taller)
    pendiente = hilo.accion_pendiente if isinstance(hilo.accion_pendiente, dict) else {}
    if _es_correccion_cliente(p):
        return _corregir_cliente(taller, hilo, texto, correcciones)
    if _es_correccion_servicio(p):
        return _corregir_servicio(taller, hilo, texto)
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_cotizacion import (
        intentar_cotizacion_desde_chat,
    )

    turno_cotizacion = intentar_cotizacion_desde_chat(taller, hilo, texto, user, correcciones)
    if turno_cotizacion is not None:
        return turno_cotizacion
    from mecanimovilapp.apps.agente_ia.services.agente_dueno_agente import atender_tarea

    tarea = atender_tarea(taller, hilo, texto, user)
    if tarea is not None:
        return tarea
    if pendiente.get('tipo') and _es_si(p):
        return _confirmar(taller, hilo, pendiente, user, correcciones)
    if pendiente.get('tipo') and _es_no(p):
        return _turno(
            haciendo='Dejo el caso como está',
            titulo='Sin cambios',
            resumen='No escribí el cambio.',
            ancla='keep',
            accion_pendiente={},
        )
    turno = _intentar(taller, hilo, texto, user, correcciones)
    if turno is None:
        return None
    turno.setdefault('accion_pendiente', {})
    return turno


def _intentar(taller, hilo, texto: str, user, correcciones: list[dict]) -> dict | None:
    p = plano(texto)
    hoy = timezone.localdate()
    if _pide_vehiculo(p):
        return _responder_vehiculo(taller, hilo, texto, hoy, correcciones)
    if _pide_servicios(p):
        return _responder_servicios(taller)
    if _pide_demanda(p):
        return _responder_demanda(taller)
    if _pide_rendimiento(p):
        return _responder_rendimiento(taller, user)
    if _pide_hoy(p):
        return _responder_hoy(taller, hoy, correcciones)
    casos = casos_abiertos(taller, hoy)
    if _pide_enviar(p):
        return _proponer_enviar(hilo, texto, casos, correcciones)
    if _pide_aceptar(p):
        return _proponer_aceptar(hilo, texto, casos, correcciones)
    if _pide_agendar(p, texto):
        return _proponer_agendar(taller, hilo, texto, hoy, casos, correcciones)
    if _pide_mensaje(p):
        return _proponer_mensaje(hilo, texto, casos, correcciones)
    if _pide_empezar(p):
        return _empezar(taller, hilo, texto, user, casos, correcciones)
    if _pide_cobro(p):
        return _proponer_cobro(taller, hilo, texto, casos, correcciones)
    if _pide_estado(p):
        return _responder_estado(hilo, texto, casos, correcciones)
    return None


def _es_respuesta(valor) -> bool:
    return isinstance(valor, dict) and 'ancla' in valor


def _turno(**kwargs) -> dict:
    base = {
        'haciendo': '',
        'titulo': 'Agente del taller',
        'resumen': '',
        'filas': [],
        'confirmacion': None,
        'abrir_whatsapp': None,
        'caso_anclado': {},
        'accion_pendiente': {},
        'ancla': 'keep',
    }
    base.update(kwargs)
    return base


def _fila_caso(caso: dict, correcciones: list[dict]) -> dict:
    cliente = _cliente_visible(caso, correcciones)
    auto = _frase_auto(caso)
    if not auto:
        auto = 'Auto no anotado en la cita'
        config = _frase_config(caso)
        if config:
            auto = f'{auto}. {config}'
    titulo = ' '.join(parte for parte in [caso.get('hora') or '', cliente or 'Cliente sin confirmar'] if parte)
    return {
        'id': caso['id'],
        'titulo': titulo,
        'detalle': auto,
        'meta': _VERBOS.get(caso.get('verbo') or '', ''),
    }


def _responder_hoy(taller, hoy: date, correcciones: list[dict]) -> dict:
    casos = [
        caso for caso in agenda_del_dia(taller, hoy)
    ]
    if not casos:
        return _turno(
            haciendo='Miro el día',
            titulo='Hoy en el taller',
            resumen='Hoy no hay nada agendado.',
            ancla='clear',
        )
    if len(casos) == 1:
        caso = casos[0]
        cliente = _cliente_visible(caso, correcciones) or 'sin confirmar'
        auto = _frase_auto(caso) or 'no está anotado en la cita'
        hora_txt = 'Ya está agendado.' if caso['confirmado'] else 'La hora todavía no está confirmada.'
        resumen = (
            f"Sí. {caso['hora']}, {caso['servicio'] or 'servicio'}. "
            f"Cliente: {cliente}. Auto: {auto}. {hora_txt}"
        )
        extra = _aviso_auto(caso, correcciones)
        if extra:
            resumen = f'{resumen} {extra}'
        return _turno(
            haciendo='Miro el día',
            titulo='Hoy en el taller',
            resumen=resumen,
            filas=[_fila_caso(caso, correcciones)],
            caso_anclado=caso,
            ancla='set',
        )
    return _turno(
        haciendo='Miro el día',
        titulo='Hoy en el taller',
        resumen=f'Hay {len(casos)} en el día.',
        filas=[_fila_caso(caso, correcciones) for caso in casos],
        ancla='clear',
    )


def _responder_vehiculo(taller, hilo, texto: str, hoy: date, correcciones: list[dict]) -> dict:
    casos = casos_abiertos(taller, hoy)
    hora = _hora_mencionada(texto)
    if hora:
        elegidos = [caso for caso in casos if caso['hora'] == hora]
    else:
        elegidos = _coincidencias(texto, casos, hilo, por_hora=False)
    if len(elegidos) > 1:
        return _pregunta(elegidos[:8], correcciones, 'Hay más de un caso a esa hora.')
    if len(elegidos) == 0:
        return _turno(
            haciendo='Busco el auto de la cita',
            titulo='Auto de la cita',
            resumen='No hay una cita a esa hora.' if hora else 'Dime la hora o el cliente.',
            ancla='keep',
        )
    caso = elegidos[0]
    auto = _frase_auto(caso)
    if auto:
        resumen = f'{auto}.'
        if caso.get('auto_anio'):
            resumen = f'{auto}, {caso["auto_anio"]}.'
    else:
        resumen = f"La cita de las {caso['hora'] or 'esa hora'} no tiene marca, modelo ni patente."
        config = _frase_config(caso)
        if config:
            resumen = f'{resumen} {config}'
    extra = _aviso_correccion_servicio(caso, correcciones)
    if extra:
        resumen = f'{resumen} {extra}'
    return _turno(
        haciendo='Busco el auto de la cita',
        titulo='Auto de la cita',
        resumen=resumen,
        filas=[_fila_caso(caso, correcciones)],
        caso_anclado=caso,
        ancla='set',
    )


def _responder_servicios(taller) -> dict:
    from mecanimovilapp.apps.servicios.models import OfertaServicio

    qs = (
        OfertaServicio.objects.filter(taller=taller)
        .select_related('servicio', 'marca_vehiculo_seleccionada', 'modelo_vehiculo_seleccionado')
        .order_by('servicio__nombre')
    )
    servicios = qs.values('servicio_id').distinct().count()
    ofertas = qs.count()
    filas = []
    for oferta in qs[:30]:
        marca = getattr(oferta.marca_vehiculo_seleccionada, 'nombre', '') or 'Todas las marcas'
        modelo = getattr(oferta.modelo_vehiculo_seleccionado, 'nombre', '') or 'Todos los modelos'
        repuestos = 'Con repuestos' if oferta.tipo_servicio == 'con_repuestos' else 'Sin repuestos'
        precio = int(oferta.precio_publicado_cliente or 0)
        filas.append({
            'id': f'oferta:{oferta.id}',
            'titulo': getattr(oferta.servicio, 'nombre', '') or 'Servicio',
            'detalle': f'{marca} {modelo} · {repuestos}',
            'meta': f'${clp(precio)}',
        })
    return _turno(
        haciendo='Cuento servicios y ofertas',
        titulo='Servicios del taller',
        resumen=f'{servicios} servicios, {ofertas} ofertas.',
        filas=filas,
        ancla='keep',
    )


def _responder_demanda(taller) -> dict:
    from mecanimovilapp.apps.ordenes.models import CotizacionCanal

    filas_qs = list(
        CotizacionCanal.objects.filter(taller=taller)
        .exclude(servicio_nombre='')
        .values('servicio_nombre', 'vehiculo_marca')
        .annotate(cotizaciones=Count('id'))
        .order_by('-cotizaciones')[:8]
    )
    if not filas_qs:
        return _turno(
            haciendo='Miro las cotizaciones',
            titulo='Lo más cotizado',
            resumen='Todavía no hay cotizaciones para contar.',
            ancla='keep',
        )
    filas = [
        {
            'id': f"demanda:{index}",
            'titulo': fila['servicio_nombre'],
            'detalle': fila['vehiculo_marca'] or 'Sin marca',
            'meta': str(fila['cotizaciones']),
        }
        for index, fila in enumerate(filas_qs)
    ]
    primera = filas_qs[0]
    return _turno(
        haciendo='Miro las cotizaciones',
        titulo='Lo más cotizado',
        resumen=(
            f"{primera['servicio_nombre']} "
            f"({primera['vehiculo_marca'] or 'sin marca'}) "
            f"aparece en {primera['cotizaciones']} cotizaciones."
        ),
        filas=filas,
        ancla='keep',
    )


def _responder_rendimiento(taller, user) -> dict:
    usuario = user or getattr(taller, 'usuario', None)
    if usuario is None:
        return _turno(
            haciendo='Miro el rendimiento',
            titulo='Rendimiento del taller',
            resumen='No pude leer el rendimiento de este taller.',
            ancla='keep',
        )
    try:
        from mecanimovilapp.apps.ordenes.services.proveedor_kpis import compute_proveedor_kpis_resumen
        data = compute_proveedor_kpis_resumen(usuario, 30)
    except Exception:
        logger.exception('Rendimiento del taller %s', getattr(taller, 'id', None))
        return _turno(
            haciendo='Miro el rendimiento',
            titulo='Rendimiento del taller',
            resumen='No pude leer el rendimiento ahora.',
            ancla='keep',
        )
    score = data.get('score_rendimiento')
    dias = data.get('ventana_dias') or 30
    completadas = data.get('ordenes_mercado_completadas')
    return _turno(
        haciendo='Miro el rendimiento',
        titulo='Rendimiento del taller',
        resumen=f'Score {score}% en los últimos {dias} días. Órdenes completadas: {completadas}.',
        ancla='keep',
    )


def _responder_estado(hilo, texto: str, casos: list[dict], correcciones: list[dict]) -> dict:
    elegidos = _coincidencias(texto, casos, hilo, por_hora=True)
    if len(elegidos) > 1:
        return _pregunta(elegidos[:8], correcciones, 'Hay más de un caso. Nombra a la persona o di el primero.')
    if len(elegidos) != 1:
        return _turno(
            haciendo='Busco el caso',
            titulo='Falta el caso',
            resumen='Dime el cliente, la patente o el folio.',
            ancla='keep',
        )
    caso = elegidos[0]
    return _turno(
        haciendo='Busco el caso',
        titulo=_VERBOS.get(caso['verbo'], 'Caso'),
        resumen=_detalle_persona(caso, correcciones),
        filas=[_fila_caso(caso, correcciones)],
        caso_anclado=caso,
        ancla='set',
    )


def _proponer_agendar(taller, hilo, texto, hoy, casos, correcciones) -> dict:
    fecha = _fecha_pedida(texto, hoy)
    hora = _hora_mencionada(texto)
    if fecha is None or not hora:
        return _turno(
            haciendo='Armo el cupo',
            titulo='Agendar',
            resumen='Dime el día y la hora. Por ejemplo: mañana a las 8.',
            ancla='keep',
        )
    elegidos = _coincidencias(texto, casos, hilo, por_hora=False)
    if len(elegidos) != 1:
        por_confirmar = [caso for caso in casos if caso['tipo'] == 'cita' and not caso['confirmado']]
        if len(elegidos) > 1:
            return _pregunta(elegidos[:8], correcciones, 'Hay más de un caso. No agendé ninguno.')
        if len(por_confirmar) == 1:
            elegidos = por_confirmar
        elif len(por_confirmar) > 1:
            return _pregunta(por_confirmar[:8], correcciones, 'Hay más de una cita sin hora. Di cuál.')
        else:
            return _turno(
                haciendo='Armo el cupo',
                titulo='Agendar',
                resumen='No encuentro la cita que hay que agendar.',
                ancla='keep',
            )
    caso = elegidos[0]
    if caso['tipo'] != 'cita':
        return _turno(
            haciendo='Armo el cupo',
            titulo='Agendar',
            resumen='Ese caso no es una cita del taller. La hora de una orden de la app ya está en la agenda.',
            filas=[_fila_caso(caso, correcciones)],
            caso_anclado=caso,
            ancla='set',
        )
    cita = _cita_de(taller, caso['documento_id'])
    if cita is None:
        return _turno(
            haciendo='Armo el cupo',
            titulo='Agendar',
            resumen='Esa cita ya no está en el taller.',
            ancla='keep',
        )
    hora_t = datetime.strptime(hora, '%H:%M').time()
    try:
        from mecanimovilapp.apps.ordenes.services.cita_agenda_personal import (
            _categorias_de_oferta,
            validar_cita_personal_slot,
        )
        oferta = getattr(getattr(cita, 'detalle', None), 'oferta_servicio', None)
        miembro = validar_cita_personal_slot(
            taller=taller,
            mecanico=cita.mecanico,
            tipo_servicio=cita.tipo_servicio,
            fecha=fecha,
            hora=hora_t,
            duracion_minutos=cita.duracion_minutos or 60,
            miembro_id=None,
            categorias_requeridas=_categorias_de_oferta(oferta),
            excluir_cita_id=cita.pk,
        )
    except DjangoValidationError as exc:
        return _turno(
            haciendo='Armo el cupo',
            titulo='Agendar',
            resumen=_msg_validacion(exc),
            filas=[_fila_caso(caso, correcciones)],
            caso_anclado=caso,
            ancla='set',
        )
    nombre = (miembro.nombre or '').strip() if miembro is not None else 'Tú'
    con_quien = 'contigo' if miembro is None else f'con {nombre}'
    auto = _frase_auto(caso) or 'el auto no está anotado en la cita'
    cuando = _fecha_humana(fecha, hoy)
    return _turno(
        haciendo='Armo el cupo',
        titulo='Agendar',
        resumen=f'Puedo dejarla {cuando} a las {hora} {con_quien}. Auto: {auto}.',
        filas=[{
            'id': caso['id'],
            'titulo': f'{cuando} {hora} · {nombre}',
            'detalle': _detalle_persona(caso, correcciones),
            'meta': 'Agendar',
        }],
        confirmacion={'etiqueta': 'Sí, agendar', 'tipo': 'accion'},
        caso_anclado=caso,
        ancla='set',
        accion_pendiente={
            'tipo': 'agendar',
            'caso_id': caso['id'],
            'cita_id': caso['documento_id'],
            'fecha': fecha.isoformat(),
            'hora': hora,
            'miembro_id': miembro.id if miembro is not None else None,
            'duracion_minutos': cita.duracion_minutos or 60,
        },
    )


def _proponer_mensaje(hilo, texto, casos, correcciones) -> dict:
    elegidos = _uno_o_pregunta(hilo, texto, casos, correcciones, '¿A quién le escribo?')
    if _es_respuesta(elegidos):
        return elegidos
    caso = elegidos
    if not (caso.get('telefono') or '').strip():
        return _turno(
            haciendo='Armo el mensaje',
            titulo='Mensaje al cliente',
            resumen=f"{_cliente_visible(caso, correcciones) or 'Ese caso'} no tiene teléfono.",
            filas=[_fila_caso(caso, correcciones)],
            caso_anclado=caso,
            ancla='set',
        )
    cuerpo = _cuerpo_mensaje(texto)
    if not cuerpo:
        return _turno(
            haciendo='Armo el mensaje',
            titulo='Mensaje al cliente',
            resumen='Dime qué le escribo.',
            filas=[_fila_caso(caso, correcciones)],
            caso_anclado=caso,
            ancla='set',
        )
    destinatario = _cliente_visible(caso, correcciones) or (caso.get('cliente') or 'cliente')
    mensaje = _texto_whatsapp(destinatario, cuerpo, caso.get('folio') or '', caso.get('url_publica') or '')
    return _turno(
        haciendo='Armo el mensaje',
        titulo=f'Mensaje a {destinatario}',
        resumen=f'{mensaje}\nTeléfono: {caso["telefono"]}',
        filas=[_fila_caso(caso, correcciones)],
        confirmacion={'etiqueta': 'Sí, abrir WhatsApp', 'tipo': 'whatsapp'},
        caso_anclado=caso,
        ancla='set',
        accion_pendiente={
            'tipo': 'contestar',
            'caso_id': caso['id'],
            'telefono': caso['telefono'],
            'texto': mensaje,
            'destinatario': destinatario,
        },
    )


def _proponer_enviar(hilo, texto, casos, correcciones) -> dict:
    elegidos = _uno_o_pregunta(hilo, texto, casos, correcciones, '¿Qué cotización envío?')
    if _es_respuesta(elegidos):
        return elegidos
    caso = _caso_cotizacion_de(elegidos, casos)
    if caso is None or caso['tipo'] != 'cotizacion':
        return _turno(
            haciendo='Reviso la cotización',
            titulo='Enviar',
            resumen='No encuentro una cotización en borrador para ese caso.',
            ancla='keep',
        )
    if caso['estado_doc'] != 'borrador':
        return _turno(
            haciendo='Reviso la cotización',
            titulo='Enviar',
            resumen='Esa cotización ya no está en borrador.',
            filas=[_fila_caso(caso, correcciones)],
            caso_anclado=caso,
            ancla='set',
        )
    return _turno(
        haciendo='Reviso la cotización',
        titulo='Enviar cotización',
        resumen=f"Total ${clp(caso['total_clp'])}. La envío cuando confirmes.",
        filas=[_fila_caso(caso, correcciones)],
        confirmacion={'etiqueta': 'Sí, enviar', 'tipo': 'accion'},
        caso_anclado=caso,
        ancla='set',
        accion_pendiente={
            'tipo': 'enviar_cotizacion',
            'caso_id': caso['id'],
            'cotizacion_id': caso['documento_id'],
        },
    )


def _proponer_aceptar(hilo, texto, casos, correcciones) -> dict:
    elegidos = _uno_o_pregunta(hilo, texto, casos, correcciones, '¿Qué cotización marco aceptada?')
    if _es_respuesta(elegidos):
        return elegidos
    caso = _caso_cotizacion_de(elegidos, casos)
    if caso is None:
        return _turno(
            haciendo='Reviso la cotización',
            titulo='Marcar aceptada',
            resumen='No encuentro la cotización enviada de ese caso.',
            ancla='keep',
        )
    if caso['estado_doc'] != 'enviada':
        return _turno(
            haciendo='Reviso la cotización',
            titulo='Marcar aceptada',
            resumen='Solo una cotización enviada se puede marcar aceptada.',
            filas=[_fila_caso(caso, correcciones)],
            caso_anclado=caso,
            ancla='set',
        )
    return _turno(
        haciendo='Reviso la cotización',
        titulo='Marcar aceptada',
        resumen=(
            f"{_cliente_visible(caso, correcciones) or 'El cliente'} "
            f"· ${clp(caso['total_clp'])}. La dejo aceptada cuando confirmes."
        ),
        filas=[_fila_caso(caso, correcciones)],
        confirmacion={'etiqueta': 'Sí, marcar aceptada', 'tipo': 'accion'},
        caso_anclado=caso,
        ancla='set',
        accion_pendiente={
            'tipo': 'marcar_aceptada',
            'caso_id': caso['id'],
            'cotizacion_id': caso['documento_id'],
        },
    )


def _proponer_cobro(taller, hilo, texto, casos, correcciones) -> dict:
    elegidos = _uno_o_pregunta(hilo, texto, casos, correcciones, '¿En qué caso anoto el cobro?')
    if _es_respuesta(elegidos):
        return elegidos
    caso = elegidos
    if caso['tipo'] == 'cotizacion':
        return _turno(
            haciendo='Reviso el cobro',
            titulo='Anotar cobro',
            resumen='El cobro se anota en la cita o en la orden, no en la cotización.',
            filas=[_fila_caso(caso, correcciones)],
            caso_anclado=caso,
            ancla='set',
        )
    medio = _medio_dicho(plano(texto))
    monto = _monto_dicho(texto)
    total = int(caso.get('total_clp') or 0)
    if monto is None:
        monto = total
    if not medio:
        return _turno(
            haciendo='Reviso el cobro',
            titulo='Anotar cobro',
            resumen='¿En qué medio? Efectivo, transferencia, débito o crédito.',
            filas=[_fila_caso(caso, correcciones)],
            caso_anclado=caso,
            ancla='set',
        )
    if monto <= 0:
        return _turno(
            haciendo='Reviso el cobro',
            titulo='Anotar cobro',
            resumen='¿Qué monto anoto?',
            filas=[_fila_caso(caso, correcciones)],
            caso_anclado=caso,
            ancla='set',
        )
    nota = ''
    if total and monto != total:
        nota = f' El total del documento es ${clp(total)}.'
    return _turno(
        haciendo='Reviso el cobro',
        titulo='Anotar cobro',
        resumen=f"Anoto ${clp(monto)} por {_MEDIOS.get(medio, medio)}.{nota}",
        filas=[_fila_caso(caso, correcciones)],
        confirmacion={'etiqueta': 'Sí, anotar cobro', 'tipo': 'accion'},
        caso_anclado=caso,
        ancla='set',
        accion_pendiente={
            'tipo': 'anotar_cobro',
            'caso_id': caso['id'],
            'documento_tipo': caso['tipo'],
            'documento_id': caso['documento_id'],
            'monto': monto,
            'medio': medio,
        },
    )


def _empezar(taller, hilo, texto, user, casos, correcciones) -> dict:
    elegidos = _uno_o_pregunta(hilo, texto, casos, correcciones, '¿Qué caso empiezo?')
    if _es_respuesta(elegidos):
        return elegidos
    caso = elegidos
    if caso['verbo'] != 'empezar':
        return _turno(
            haciendo='Reviso si se puede empezar',
            titulo='Empezar',
            resumen=_porque_no_empieza(caso),
            filas=[_fila_caso(caso, correcciones)],
            caso_anclado=caso,
            ancla='set',
        )
    try:
        from rest_framework.exceptions import PermissionDenied
        from mecanimovilapp.apps.usuarios.services.taller_contexto import exigir_puede_ejecutar_servicio
        if user is not None:
            exigir_puede_ejecutar_servicio(user, accion='empezar este servicio')
    except PermissionDenied as exc:
        return _turno(
            haciendo='Reviso si se puede empezar',
            titulo='Empezar',
            resumen=str(exc.detail if hasattr(exc, 'detail') else exc),
            filas=[_fila_caso(caso, correcciones)],
            caso_anclado=caso,
            ancla='set',
        )
    if caso['tipo'] == 'cita':
        resumen = _empezar_cita(taller, caso['documento_id'])
    elif caso['tipo'] == 'orden':
        resumen = _empezar_orden(taller, caso['documento_id'])
    else:
        resumen = 'Ese documento no se empieza desde el hilo.'
    fresco = _caso_por_id(taller, caso['id']) or caso
    return _turno(
        haciendo='Empiezo el servicio',
        titulo='Empezar',
        resumen=resumen,
        filas=[_fila_caso(fresco, correcciones)],
        caso_anclado=fresco,
        ancla='set',
    )


def _confirmar(taller, hilo, pendiente: dict, user, correcciones: list[dict]) -> dict:
    tipo = pendiente.get('tipo')
    try:
        if tipo == 'agendar':
            return _confirmar_agendar(taller, pendiente, correcciones)
        if tipo == 'contestar':
            return _confirmar_mensaje(taller, hilo, pendiente, correcciones)
        if tipo == 'enviar_cotizacion':
            return _confirmar_enviar(taller, pendiente, user, correcciones)
        if tipo == 'marcar_aceptada':
            return _confirmar_aceptar(taller, pendiente, correcciones)
        if tipo == 'anotar_cobro':
            return _confirmar_cobro(taller, pendiente, correcciones)
    except DjangoValidationError as exc:
        return _turno(
            haciendo='Guardo el caso',
            titulo='No quedó escrito',
            resumen=_msg_validacion(exc),
            ancla='keep',
            accion_pendiente={},
        )
    except ValueError as exc:
        return _turno(
            haciendo='Guardo el caso',
            titulo='No quedó escrito',
            resumen=str(exc),
            ancla='keep',
            accion_pendiente={},
        )
    except Exception:
        logger.exception('Agente dueño no pudo confirmar %s', tipo)
        return _turno(
            haciendo='Guardo el caso',
            titulo='No quedó escrito',
            resumen='No pude guardar el cambio. El caso sigue como estaba.',
            ancla='keep',
            accion_pendiente={},
        )
    return _turno(
        haciendo='Guardo el caso',
        titulo='Sin cambios',
        resumen='No había un paso esperando confirmación.',
        ancla='keep',
        accion_pendiente={},
    )


def _confirmar_agendar(taller, pendiente, correcciones) -> dict:
    from mecanimovilapp.apps.ordenes.services.cita_agenda_personal import actualizar_cita_personal

    cita = _cita_de(taller, pendiente.get('cita_id'))
    if cita is None:
        raise ValueError('Esa cita ya no está en el taller.')
    actualizar_cita_personal(
        cita,
        cabecera={
            'fecha_servicio': date.fromisoformat(pendiente['fecha']),
            'hora_servicio': datetime.strptime(pendiente['hora'], '%H:%M').time(),
            'duracion_minutos': pendiente.get('duracion_minutos') or cita.duracion_minutos,
            'miembro_taller': pendiente.get('miembro_id'),
        },
    )
    cita.refresh_from_db()
    caso = _caso_por_id(taller, f"cita:{cita.id}") or {}
    con_quien = cita.miembro_taller.nombre if cita.miembro_taller_id else ''
    con_quien = f'con {con_quien}' if con_quien else 'contigo'
    auto = _frase_auto(caso) or 'el auto no está anotado en la cita'
    return _turno(
        haciendo='Dejo la cita en la agenda',
        titulo='Agendada',
        resumen=(
            f"Quedó en la agenda el {cita.fecha_servicio.strftime('%d/%m')} "
            f"a las {cita.hora_servicio.strftime('%H:%M')}, {con_quien}. Auto: {auto}."
        ),
        filas=[_fila_caso(caso, correcciones)] if caso else [],
        caso_anclado=caso,
        ancla='set',
        accion_pendiente={},
    )


def _confirmar_mensaje(taller, hilo, pendiente, correcciones) -> dict:
    from mecanimovilapp.apps.agente_ia.models import AgenteDuenoAvisoCliente

    AgenteDuenoAvisoCliente.objects.create(
        taller=taller,
        caso_id=pendiente.get('caso_id') or '',
        destinatario=pendiente.get('destinatario') or '',
        telefono=pendiente.get('telefono') or '',
        texto=pendiente.get('texto') or '',
    )
    caso = _caso_por_id(taller, pendiente.get('caso_id')) or (hilo.caso_anclado or {})
    return _turno(
        haciendo='Anoto el mensaje en el caso',
        titulo='Mensaje al cliente',
        resumen=(
            f"Anoté el mensaje a {pendiente.get('destinatario') or 'el cliente'}. "
            'Abro WhatsApp con ese texto. El caso sigue aquí.'
        ),
        filas=[_fila_caso(caso, correcciones)] if caso.get('id') else [],
        abrir_whatsapp={
            'telefono': pendiente.get('telefono') or '',
            'texto': pendiente.get('texto') or '',
        },
        caso_anclado=caso,
        ancla='set',
        accion_pendiente={},
    )


def _confirmar_enviar(taller, pendiente, user, correcciones) -> dict:
    from mecanimovilapp.apps.ordenes.models import CotizacionCanal
    from mecanimovilapp.apps.ordenes.services.cotizacion_canal import enviar_cotizacion_canal
    from mecanimovilapp.apps.ordenes.services.cotizacion_publica import enviar_cotizacion_libre

    cotizacion = CotizacionCanal.objects.filter(taller=taller, id=pendiente.get('cotizacion_id')).first()
    if cotizacion is None:
        raise ValueError('Esa cotización ya no está en el taller.')
    if cotizacion.es_libre or cotizacion.conversation_id is None:
        enviar_cotizacion_libre(cotizacion)
    else:
        if user is None:
            raise ValueError('Falta el usuario del taller para enviar por el canal.')
        enviar_cotizacion_canal(cotizacion, user)
    cotizacion.refresh_from_db()
    caso = _caso_por_id(taller, f'cotizacion:{cotizacion.id}') or {}
    return _turno(
        haciendo='Envío la cotización',
        titulo='Cotización enviada',
        resumen=f"Quedó enviada. Total ${clp(int(cotizacion.total_clp or 0))}.",
        filas=[_fila_caso(caso, correcciones)] if caso else [],
        caso_anclado=caso or {'id': f'cotizacion:{cotizacion.id}'},
        ancla='set',
        accion_pendiente={},
    )


def _confirmar_aceptar(taller, pendiente, correcciones) -> dict:
    from mecanimovilapp.apps.ordenes.models import CotizacionCanal
    from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
        aceptar_cotizacion_publica,
        on_cotizacion_respondida,
    )

    cotizacion = CotizacionCanal.objects.filter(taller=taller, id=pendiente.get('cotizacion_id')).first()
    if cotizacion is None:
        raise ValueError('Esa cotización ya no está en el taller.')
    cotizacion, cita = aceptar_cotizacion_publica(cotizacion)
    try:
        on_cotizacion_respondida(
            cotizacion,
            'aceptar',
            conversation=cotizacion.conversation,
            cita_id=cita.id if cita else None,
        )
    except Exception:
        logger.exception('Aviso de aceptación no enviado para cotización %s', cotizacion.id)
    caso = _caso_por_id(taller, f'cita:{cita.id}') if cita is not None else {}
    if not caso:
        caso = _caso_por_id(taller, f'cotizacion:{cotizacion.id}') or {}
    return _turno(
        haciendo='Marco la cotización aceptada',
        titulo='Aceptada',
        resumen='Quedó aceptada. El siguiente paso es agendar la hora.',
        filas=[_fila_caso(caso, correcciones)] if caso.get('id') else [],
        caso_anclado=caso,
        ancla='set',
        accion_pendiente={},
    )


def _confirmar_cobro(taller, pendiente, correcciones) -> dict:
    from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal, SolicitudServicio

    documento_id = pendiente.get('documento_id')
    if pendiente.get('documento_tipo') == 'orden':
        obj = SolicitudServicio.objects.filter(taller=taller, id=documento_id).first()
        caso_id = f'orden:{documento_id}'
    else:
        obj = CitaAgendaPersonal.objects.filter(taller=taller, id=documento_id).first()
        caso_id = f'cita:{documento_id}'
    if obj is None:
        raise ValueError('Ese caso ya no está en el taller.')
    obj.cobro_estado = 'anotado'
    obj.cobro_medio = pendiente.get('medio') or ''
    obj.cobro_monto_clp = Decimal(pendiente.get('monto') or 0)
    obj.cobro_anotado_en = timezone.now()
    obj.save(update_fields=['cobro_estado', 'cobro_medio', 'cobro_monto_clp', 'cobro_anotado_en'])
    caso = _caso_por_id(taller, caso_id) or {}
    return _turno(
        haciendo='Anoto el cobro',
        titulo='Cobro anotado',
        resumen=f"Anoté ${clp(pendiente.get('monto') or 0)} por {_MEDIOS.get(pendiente.get('medio'), '')}.",
        filas=[_fila_caso(caso, correcciones)] if caso else [],
        caso_anclado=caso,
        ancla='set',
        accion_pendiente={},
    )


def _empezar_cita(taller, cita_id) -> str:
    from mecanimovilapp.apps.checklists.services import crear_checklist_para_cita_personal
    from mecanimovilapp.apps.ordenes.services.cita_agenda_personal import cita_es_dia_de_servicio

    cita = _cita_de(taller, cita_id)
    if cita is None:
        return 'Esa cita ya no está en el taller.'
    if cita.estado != 'activa':
        return 'Esa cita ya no está activa.'
    if cita.horario_por_confirmar:
        return 'Confirma día, hora y técnico antes de empezar.'
    if not cita_es_dia_de_servicio(cita):
        return f"Solo puedes empezar el día de la cita ({cita.fecha_servicio.strftime('%d/%m/%Y')})."
    instance = crear_checklist_para_cita_personal(cita, generar_template_si_ausente=True)
    if instance is not None and instance.estado == 'PENDIENTE':
        instance.estado = 'EN_PROGRESO'
        instance.fecha_inicio = timezone.now()
        instance.save(update_fields=['estado', 'fecha_inicio'])
    if instance is None:
        return 'El servicio quedó iniciado. Esta cita no tiene checklist.'
    return 'Servicio iniciado. El checklist quedó en el caso.'


def _empezar_orden(taller, orden_id) -> str:
    from mecanimovilapp.apps.checklists.services import crear_checklist_para_orden
    from mecanimovilapp.apps.ordenes.models import SolicitudServicio

    orden = SolicitudServicio.objects.filter(taller=taller, id=orden_id).first()
    if orden is None:
        return 'Esa orden ya no está en el taller.'
    if orden.estado != 'aceptada_por_proveedor':
        return 'Esa orden no está lista para empezar.'
    instance = crear_checklist_para_orden(orden, generar_template_si_ausente=True)
    orden.estado = 'checklist_en_progreso' if instance is not None else 'en_proceso'
    orden.save(update_fields=['estado'])
    if instance is None:
        return 'El servicio quedó iniciado. Esta orden no tiene checklist.'
    return 'Servicio iniciado. El checklist quedó en la orden.'


def _corregir_cliente(taller, hilo, texto, correcciones) -> dict:
    from mecanimovilapp.apps.agente_ia.models import AgenteDuenoCorreccion

    caso = _caso_de_ancla(taller, hilo)
    if not caso:
        return _turno(
            haciendo='Anoto la corrección',
            titulo='Corrección',
            resumen='Dime primero de qué caso hablas.',
            ancla='keep',
            accion_pendiente={},
        )
    valor = (caso.get('cliente') or '').strip()
    AgenteDuenoCorreccion.objects.create(
        taller=taller,
        caso_id=caso['id'],
        descarta=AgenteDuenoCorreccion.DESCARTA_CLIENTE,
        valor=valor[:200],
        texto=texto[:500],
    )
    return _turno(
        haciendo='Anoto la corrección',
        titulo='Corrección',
        resumen=f'Listo. No voy a presentar a {valor or "ese contacto"} como el cliente de ese caso.',
        filas=[_fila_caso(caso, correcciones + [{'caso_id': caso['id'], 'descarta': 'cliente', 'valor': valor}])],
        caso_anclado=caso,
        ancla='set',
        accion_pendiente={},
    )


def _corregir_servicio(taller, hilo, texto) -> dict:
    from mecanimovilapp.apps.agente_ia.models import AgenteDuenoCorreccion

    caso = _caso_de_ancla(taller, hilo) or {}
    AgenteDuenoCorreccion.objects.create(
        taller=taller,
        caso_id=caso.get('id') or '',
        descarta=AgenteDuenoCorreccion.DESCARTA_AUTO_SERVICIO,
        valor=(caso.get('servicio_marca') or caso.get('servicio') or '')[:200],
        texto=texto[:500],
    )
    return _turno(
        haciendo='Anoto la corrección',
        titulo='Corrección',
        resumen='Listo. Esa marca queda como configuración del servicio, no como el auto del cliente.',
        filas=[_fila_caso(caso, [])] if caso.get('id') else [],
        caso_anclado=caso,
        ancla='set' if caso.get('id') else 'keep',
        accion_pendiente={},
    )


def _caso_cita(cita, iniciado: bool, hoy: date) -> dict:
    try:
        detalle = cita.detalle
    except Exception:
        detalle = None
    oferta = getattr(detalle, 'oferta_servicio', None) if detalle else None
    cotizacion = getattr(cita, 'cotizacion_canal_origen', None)
    total = 0
    if detalle is not None and detalle.precio_referencia:
        total = int(detalle.precio_referencia)
    elif cotizacion is not None:
        total = int(cotizacion.total_clp or 0)
    caso = {
        'id': f'cita:{cita.id}',
        'tipo': 'cita',
        'documento_id': cita.id,
        'cotizacion_id': cita.cotizacion_canal_origen_id or 0,
        'cliente': (getattr(detalle, 'cliente_nombre', '') or '').strip(),
        'telefono': (getattr(detalle, 'cliente_telefono', '') or '').strip(),
        'auto_marca': (getattr(detalle, 'vehiculo_marca', '') or '').strip(),
        'auto_modelo': (getattr(detalle, 'vehiculo_modelo', '') or '').strip(),
        'auto_patente': (getattr(detalle, 'vehiculo_patente', '') or '').strip(),
        'auto_anio': getattr(detalle, 'vehiculo_anio', None) if detalle else None,
        'servicio': (getattr(detalle, 'servicio_nombre', '') or '').strip(),
        'servicio_marca': getattr(getattr(oferta, 'marca_vehiculo_seleccionada', None), 'nombre', '') or '',
        'servicio_modelo': getattr(getattr(oferta, 'modelo_vehiculo_seleccionado', None), 'nombre', '') or '',
        'hora': cita.hora_servicio.strftime('%H:%M') if cita.hora_servicio else '',
        'fecha': cita.fecha_servicio.isoformat() if cita.fecha_servicio else '',
        'confirmado': not bool(cita.horario_por_confirmar),
        'estado_doc': 'por_confirmar' if cita.horario_por_confirmar else 'activa',
        'folio': (cita.numero_publico or getattr(cotizacion, 'numero_publico', '') or '').strip(),
        'total_clp': total,
        'url_publica': (getattr(cotizacion, 'url_publica', '') or '').strip(),
        'cobro_estado': cita.cobro_estado or 'pendiente',
        'iniciado': iniciado,
        'origen': 'personal',
        'duracion_minutos': cita.duracion_minutos or 60,
    }
    if not caso['servicio'] and oferta is not None:
        caso['servicio'] = getattr(getattr(oferta, 'servicio', None), 'nombre', '') or ''
    caso['verbo'] = _verbo(caso, hoy)
    return caso


def _caso_orden(orden, hoy: date) -> dict:
    vehiculo = orden.vehiculo
    cliente = orden.cliente
    iniciado = orden.estado in {
        'checklist_en_progreso',
        'checklist_completado',
        'en_proceso',
        'pendiente_firma_cliente',
        'completado',
    }
    caso = {
        'id': f'orden:{orden.id}',
        'tipo': 'orden',
        'documento_id': orden.id,
        'cotizacion_id': 0,
        'cliente': _nombre_persona(cliente),
        'telefono': (getattr(cliente, 'telefono', '') or '').strip(),
        'auto_marca': vehiculo.marca.nombre if vehiculo and vehiculo.marca_id else '',
        'auto_modelo': vehiculo.modelo.nombre if vehiculo and vehiculo.modelo_id else '',
        'auto_patente': (vehiculo.patente or '').strip() if vehiculo else '',
        'auto_anio': vehiculo.year if vehiculo else None,
        'servicio': 'Orden de la app',
        'servicio_marca': '',
        'servicio_modelo': '',
        'hora': orden.hora_servicio.strftime('%H:%M') if orden.hora_servicio else '',
        'fecha': orden.fecha_servicio.isoformat() if orden.fecha_servicio else '',
        'confirmado': True,
        'estado_doc': orden.estado,
        'folio': (orden.numero_publico or '').strip(),
        'total_clp': int(orden.total or 0),
        'url_publica': '',
        'cobro_estado': orden.cobro_estado or 'pendiente',
        'iniciado': iniciado,
        'origen': 'mecanimovil',
        'duracion_minutos': 60,
    }
    linea = orden.lineas.select_related('oferta_servicio__servicio').first() if hasattr(orden, 'lineas') else None
    if linea and linea.oferta_servicio and linea.oferta_servicio.servicio:
        caso['servicio'] = linea.oferta_servicio.servicio.nombre
    caso['verbo'] = _verbo(caso, hoy)
    return caso


def _caso_cotizacion(cotizacion, hoy: date) -> dict:
    caso = {
        'id': f'cotizacion:{cotizacion.id}',
        'tipo': 'cotizacion',
        'documento_id': cotizacion.id,
        'cotizacion_id': cotizacion.id,
        'cliente': (cotizacion.cliente_nombre or '').strip(),
        'telefono': (cotizacion.cliente_telefono or '').strip(),
        'auto_marca': (cotizacion.vehiculo_marca or '').strip(),
        'auto_modelo': (cotizacion.vehiculo_modelo or '').strip(),
        'auto_patente': (cotizacion.vehiculo_patente or '').strip(),
        'auto_anio': cotizacion.vehiculo_anio,
        'servicio': (cotizacion.servicio_nombre or '').strip(),
        'servicio_marca': '',
        'servicio_modelo': '',
        'hora': '',
        'fecha': '',
        'confirmado': False,
        'estado_doc': cotizacion.estado,
        'folio': (cotizacion.numero_publico or '').strip(),
        'total_clp': int(cotizacion.total_clp or 0),
        'url_publica': (cotizacion.url_publica or '').strip(),
        'cobro_estado': 'pendiente',
        'iniciado': False,
        'origen': 'cotizacion',
        'duracion_minutos': cotizacion.duracion_minutos_estimada or 60,
    }
    caso['verbo'] = _verbo(caso, hoy)
    return caso


def _verbo(caso: dict, hoy: date) -> str:
    tipo = caso['tipo']
    if tipo == 'cotizacion':
        if caso['estado_doc'] == 'borrador':
            return 'enviar' if caso['total_clp'] else 'revisar_precios'
        if caso['estado_doc'] == 'enviada':
            return 'marcar_aceptada'
        return 'agendar'
    if tipo == 'orden':
        if caso['estado_doc'] in ('pendiente', 'pendiente_aceptacion_proveedor'):
            return 'confirmar'
        if caso['estado_doc'] == 'aceptada_por_proveedor':
            return 'empezar'
        if caso['cobro_estado'] != 'anotado':
            return 'anotar_cobro'
        return 'contestar'
    if not caso['confirmado']:
        return 'agendar'
    if caso['fecha'] == hoy.isoformat() and not caso['iniciado']:
        return 'empezar'
    if caso['iniciado'] and caso['cobro_estado'] != 'anotado':
        return 'anotar_cobro'
    return 'contestar'


def _pregunta(casos: list[dict], correcciones: list[dict], resumen: str) -> dict:
    return _turno(
        haciendo='Busco el caso',
        titulo='¿Cuál caso?',
        resumen=resumen,
        filas=[_fila_caso(caso, correcciones) for caso in casos],
        ancla='clear',
        accion_pendiente={},
    )


def _uno_o_pregunta(hilo, texto, casos, correcciones, pregunta: str):
    elegidos = _coincidencias(texto, casos, hilo, por_hora=False)
    if len(elegidos) > 1:
        return _pregunta(elegidos[:8], correcciones, pregunta)
    if len(elegidos) == 1:
        return elegidos[0]
    ancla = _caso_de_ancla_en(casos, hilo)
    if ancla is not None:
        return ancla
    return _turno(
        haciendo='Busco el caso',
        titulo='Falta el caso',
        resumen=pregunta,
        ancla='keep',
    )


def _coincidencias(texto: str, casos: list[dict], hilo, *, por_hora: bool) -> list[dict]:
    por_id = {caso['id']: caso for caso in casos}
    p = plano(texto)
    filas = (hilo.ultima_tarjeta or {}).get('filas') or []
    if re.search(r'\b(el primero|la primera)\b', p) and filas:
        caso = por_id.get(str(filas[0].get('id')))
        return [caso] if caso else []
    if re.search(r'\b(el segundo|la segunda)\b', p) and len(filas) > 1:
        caso = por_id.get(str(filas[1].get('id')))
        return [caso] if caso else []
    if por_hora:
        hora = _hora_mencionada(texto)
        if hora:
            return [caso for caso in casos if caso['hora'] == hora]
    hits = []
    vistos = set()
    for caso in casos:
        if caso['id'] in vistos:
            continue
        if _texto_nombra(p, caso):
            hits.append(caso)
            vistos.add(caso['id'])
    if hits:
        return hits
    if _es_pronombre(p):
        ancla = por_id.get((hilo.caso_anclado or {}).get('id'))
        if ancla is not None:
            return [ancla]
        if len(filas) == 1:
            caso = por_id.get(str(filas[0].get('id')))
            return [caso] if caso else []
    return []


def _texto_nombra(p: str, caso: dict) -> bool:
    cliente = plano(caso.get('cliente') or '')
    if len(cliente) > 2 and re.search(rf'\b{re.escape(cliente)}\b', p):
        return True
    primero = cliente.split(' ')[0] if cliente else ''
    if len(primero) > 2 and primero != cliente and re.search(rf'\b{re.escape(primero)}\b', p):
        return True
    patente = plano(caso.get('auto_patente') or '')
    if len(patente) >= 4 and re.search(rf'\b{re.escape(patente)}\b', p):
        return True
    folio = plano(caso.get('folio') or '')
    if len(folio) >= 4 and folio in p:
        return True
    return False


def _es_pronombre(p: str) -> bool:
    return bool(re.search(
        r'\b(agendala|agendalo|enviala|envialo|aceptala|aceptalo|mandale|dile|avisale|escribile|decile|este|esta|esa|eso)\b',
        p,
    ))


def _caso_de_ancla(taller, hilo) -> dict | None:
    ancla = hilo.caso_anclado if isinstance(hilo.caso_anclado, dict) else {}
    if ancla.get('id'):
        fresco = _caso_por_id(taller, ancla['id'])
        return fresco or ancla
    filas = (hilo.ultima_tarjeta or {}).get('filas') or []
    if len(filas) == 1:
        return _caso_por_id(taller, filas[0].get('id'))
    return None


def _caso_de_ancla_en(casos: list[dict], hilo) -> dict | None:
    por_id = {caso['id']: caso for caso in casos}
    ancla_id = (hilo.caso_anclado or {}).get('id')
    if ancla_id and ancla_id in por_id:
        return por_id[ancla_id]
    return None


def _caso_por_id(taller, caso_id: str | None) -> dict | None:
    if not caso_id:
        return None
    for caso in casos_abiertos(taller):
        if caso['id'] == caso_id:
            return caso
    return None


def _caso_cotizacion_de(caso: dict | None, casos: list[dict]) -> dict | None:
    if caso is None:
        return None
    if caso['tipo'] == 'cotizacion':
        return caso
    cotizacion_id = caso.get('cotizacion_id') or 0
    if not cotizacion_id:
        return None
    for item in casos:
        if item['id'] == f'cotizacion:{cotizacion_id}':
            return item
    return None


def _cita_de(taller, cita_id):
    from mecanimovilapp.apps.ordenes.models import CitaAgendaPersonal

    if not cita_id:
        return None
    return (
        CitaAgendaPersonal.objects.filter(taller=taller, id=cita_id)
        .select_related(
            'detalle',
            'detalle__oferta_servicio',
            'detalle__oferta_servicio__servicio',
            'miembro_taller',
        )
        .first()
    )


def _leer_correcciones(taller) -> list[dict]:
    from mecanimovilapp.apps.agente_ia.models import AgenteDuenoCorreccion

    return list(
        AgenteDuenoCorreccion.objects.filter(taller=taller)
        .order_by('-creado_en')
        .values('caso_id', 'descarta', 'valor', 'texto')[:30]
    )


def _cliente_descartado(caso: dict, correcciones: list[dict]) -> bool:
    for item in correcciones:
        if item.get('descarta') != 'cliente':
            continue
        if item.get('caso_id') and item.get('caso_id') == caso.get('id'):
            return True
        valor = plano(item.get('valor') or '')
        if valor and valor == plano(caso.get('cliente') or ''):
            return True
    return False


def _cliente_visible(caso: dict, correcciones: list[dict]) -> str:
    if _cliente_descartado(caso, correcciones):
        return ''
    return (caso.get('cliente') or '').strip()


def _aviso_auto(caso: dict, correcciones: list[dict]) -> str:
    if _frase_auto(caso):
        return _aviso_correccion_servicio(caso, correcciones)
    return ' '.join(parte for parte in [_frase_config(caso), _aviso_correccion_servicio(caso, correcciones)] if parte)


def _aviso_correccion_servicio(caso: dict, correcciones: list[dict]) -> str:
    for item in correcciones:
        if item.get('descarta') != 'auto_desde_servicio':
            continue
        if item.get('caso_id') and item.get('caso_id') not in ('', caso.get('id')):
            continue
        return 'Según lo que corregiste, esa marca es la configuración del servicio, no el auto del cliente.'
    return ''


def _frase_auto(caso: dict) -> str:
    nombre = ' '.join(parte for parte in [caso.get('auto_marca') or '', caso.get('auto_modelo') or ''] if parte)
    patente = (caso.get('auto_patente') or '').strip()
    if nombre and patente:
        return f'{nombre}, patente {patente}'
    if patente:
        return f'patente {patente}'
    return nombre


def _frase_config(caso: dict) -> str:
    donde = ' '.join(parte for parte in [caso.get('servicio_marca') or '', caso.get('servicio_modelo') or ''] if parte)
    if not donde:
        return ''
    return f'El servicio está configurado para {donde}.'


def _detalle_persona(caso: dict, correcciones: list[dict]) -> str:
    partes = [_cliente_visible(caso, correcciones) or 'Cliente sin confirmar']
    auto = _frase_auto(caso)
    partes.append(auto or 'Auto no anotado en la cita')
    if not auto and caso.get('servicio_marca'):
        partes.append(_frase_config(caso))
    if caso.get('servicio'):
        partes.append(caso['servicio'])
    return ' · '.join(parte for parte in partes if parte)


def _porque_no_empieza(caso: dict) -> str:
    if caso['tipo'] == 'cita' and not caso['confirmado']:
        return 'Primero confirma la hora y el mecánico.'
    if caso['tipo'] == 'cita' and caso.get('fecha'):
        return f"Solo puedes empezar el día de la cita ({caso['fecha']})."
    if caso['verbo'] == 'anotar_cobro':
        return 'Ese trabajo ya empezó. El paso que sigue es anotar el cobro.'
    return 'Ese caso no está listo para empezar.'


def _texto_whatsapp(destinatario: str, cuerpo: str, folio: str, url: str) -> str:
    primero = (destinatario or '').split(' ')[0]
    saludo = f'Hola {primero}.' if primero and primero.lower() not in ('cliente', 'sin') else 'Hola.'
    frase = cuerpo[:1].upper() + cuerpo[1:] if cuerpo else ''
    if frase and not frase.endswith('.'):
        frase = f'{frase}.'
    partes = [saludo, frase]
    if folio:
        partes.append(f'Folio {folio}.')
    if url:
        partes.append(url)
    return ' '.join(parte for parte in partes if parte)


def _cuerpo_mensaje(texto: str) -> str:
    match = re.search(
        r'(?:dile(?:\s+a\s+\w+)?\s+que|m[aá]ndale(?:\s+a\s+\w+)?\s+que|av[ií]sale(?:\s+a\s+\w+)?\s+que|'
        r'escr[ií]bele(?:\s+a\s+\w+)?\s+que|decile(?:\s+a\s+\w+)?\s+que)\s+(.+)',
        texto,
        re.IGNORECASE,
    )
    return (match.group(1) if match else '').strip().rstrip('.')


def _hora_mencionada(texto: str) -> str | None:
    match = re.search(r'(?:a\s+las|las|a\s+la)\s+(\d{1,2})(?::(\d{2}))?', texto, re.IGNORECASE)
    if match is None:
        match = re.search(r'\b(\d{1,2}):(\d{2})\b', texto)
    if match is None:
        return None
    hora = int(match.group(1))
    minuto = int(match.group(2) or 0)
    if 'tarde' in plano(texto) and hora < 12:
        hora += 12
    if hora > 23 or minuto > 59:
        return None
    return f'{hora:02d}:{minuto:02d}'


def _fecha_pedida(texto: str, hoy: date) -> date | None:
    p = plano(texto)
    if 'pasado manana' in p:
        return hoy + timedelta(days=2)
    if re.search(r'\bmanana\b', p):
        return hoy + timedelta(days=1)
    if re.search(r'\bhoy\b', p):
        return hoy
    dias = {
        'lunes': 0,
        'martes': 1,
        'miercoles': 2,
        'jueves': 3,
        'viernes': 4,
        'sabado': 5,
        'domingo': 6,
    }
    for nombre, indice in dias.items():
        if re.search(rf'\b{nombre}\b', p):
            delta = (indice - hoy.weekday()) % 7
            return hoy + timedelta(days=delta or 7)
    return None


def _medio_dicho(p: str) -> str:
    if 'transfer' in p:
        return 'transferencia'
    if 'efectivo' in p:
        return 'efectivo'
    if 'debito' in p:
        return 'debito'
    if 'credito' in p or 'tarjeta' in p:
        return 'credito'
    if 'mercado pago' in p or 'mercadopago' in p:
        return 'mercadopago'
    return ''


def _monto_dicho(texto: str) -> int | None:
    match = re.search(r'(\d{1,3}(?:\.\d{3})+|\d{4,7})', texto)
    if match is None:
        return None
    return int(match.group(1).replace('.', ''))


def _nombre_persona(persona) -> str:
    if persona is None:
        return ''
    return ' '.join(
        parte for parte in [
            (getattr(persona, 'nombre', '') or '').strip(),
            (getattr(persona, 'apellido', '') or '').strip(),
        ] if parte
    )


def _msg_validacion(exc: DjangoValidationError) -> str:
    if hasattr(exc, 'message_dict'):
        partes = []
        for valor in exc.message_dict.values():
            if isinstance(valor, list):
                partes.extend(str(item) for item in valor)
            else:
                partes.append(str(valor))
        if partes:
            return ' '.join(partes)
    if hasattr(exc, 'messages'):
        return ' '.join(str(item) for item in exc.messages)
    return str(exc)


def _es_si(p: str) -> bool:
    return bool(re.match(r'^(si|dale|confirmo|ok|okay|de acuerdo|hazlo|adelante|claro|listo)\b', p))


def _es_no(p: str) -> bool:
    return bool(re.match(r'^(no|nop|cancela|cancelar|mejor no)\b', p))


def _es_correccion_cliente(p: str) -> bool:
    return bool(re.search(r'no es el cliente|ese no es el cliente|no es ese cliente|ese contacto no', p))


def _es_correccion_servicio(p: str) -> bool:
    return bool(re.search(r'solo para este modelo|solo para esa marca|el servicio es solo|no es el auto', p))


def _pide_vehiculo(p: str) -> bool:
    return bool(re.search(r'vehiculo|que auto|el auto|de que auto|patente del|que patente', p))


def _pide_servicios(p: str) -> bool:
    return bool(re.search(r'cuantos servicios|cuantas ofertas|servicios tengo|ofertas tengo', p))


def _pide_demanda(p: str) -> bool:
    return bool(re.search(r'cotiza mas|se cotiza|mas pedido|mas cotiz|que se pide', p))


def _pide_rendimiento(p: str) -> bool:
    return bool(re.search(r'rendimient|como voy|score del taller|\bkpi\b', p))


def _pide_hoy(p: str) -> bool:
    if re.search(r'\bagend(ar|ala|alo)\b', p):
        return False
    return bool(re.search(r'que tengo|tengo algo|agendamient|ordenes de hoy|mi dia|que hay hoy', p))


def _pide_enviar(p: str) -> bool:
    return 'cotizacion' in p and bool(re.search(r'\b(envia|enviar|mandala|mandale)\b', p))


def _pide_aceptar(p: str) -> bool:
    return bool(re.search(
        r'\b(aceptala|aceptalo|marcar aceptada|marcala aceptada|marcalo aceptado|cliente acepto|ya acepto)\b',
        p,
    ))


def _pide_agendar(p: str, texto: str) -> bool:
    if re.search(r'\b(agendar|agendala|agendalo|ponle hora|poner hora)\b', p):
        return True
    return bool(_hora_mencionada(texto) and re.search(r'\b(manana|hoy)\b', p) and _es_pronombre(p))


def _pide_mensaje(p: str) -> bool:
    return bool(re.search(r'\b(dile|mandale que|avisale|escribile|decile|whatsapp)\b', p))


def _pide_empezar(p: str) -> bool:
    return bool(re.search(r'\b(empieza|empezar|inicia el servicio|iniciar el servicio|inicia el trabajo)\b', p))


def _pide_cobro(p: str) -> bool:
    return bool(re.search(r'\b(cobro|cobrar|anota el pago|anotar el pago|ya pago|me pago)\b', p))


def _pide_estado(p: str) -> bool:
    return bool(re.search(r'en que va|como va|como esta|estado de|que paso con', p))
