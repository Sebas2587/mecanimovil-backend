"""El pedido se cotiza. Lo demás queda como sugerencia hasta que el taller decida.

Sirve al agente que habla con el cliente, a la cotización IA del taller y a la
edición manual asistida. Una sugerencia pendiente o descartada no se cobra.
"""
from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any

ORIGEN_PEDIDO = 'pedido'
ORIGEN_SUGERENCIA = 'sugerencia'
ESTADO_PENDIENTE = 'pendiente'
ESTADO_ACEPTADA = 'aceptada'
ESTADO_DESCARTADA = 'descartada'

_SUGERENCIAS_CAJA = (
    (
        'Rodamiento de volante',
        'No viene en el kit (disco, prensa y collarín de empuje). '
        'Al bajar la caja conviene cambiar el rodamiento piloto.',
    ),
    (
        'Aceite de caja de cambios',
        'Al bajar la caja se pierde la valvulina. Es el llenado, no un tambor ni la caja.',
    ),
    (
        'Retén trasero de cigüeñal',
        'Queda a la vista al sacar la caja. Solo si el retén de este motor se cambia en el mismo trabajo.',
    ),
)


def linea_cuenta_en_total(rep: dict | None) -> bool:
    """Pendiente, descartada o sin clasificar no entra al cobro ni a la ganancia."""
    if not isinstance(rep, dict):
        return False
    if str(rep.get('identidad') or '') in ('sin_clasificar', 'otra'):
        return False
    if str(rep.get('rol') or '') in ('duda', 'sistema', 'mano_obra'):
        return False
    origen = str(rep.get('origen') or ORIGEN_PEDIDO)
    estado = str(rep.get('estado_sugerencia') or '')
    if origen == ORIGEN_SUGERENCIA and estado != ESTADO_ACEPTADA:
        return False
    return True


def monto_para_agente(cotizacion) -> str:
    """Solo esta cotización. Una duda de otra no le esconde el monto."""
    if cotizacion is None:
        return ''
    if _hay_precio_no_firme(cotizacion) or _hay_duda_abierta(cotizacion):
        return 'por confirmar'
    monto = getattr(cotizacion, 'total_clp', None)
    try:
        if monto:
            return f'${int(monto)}'
    except (TypeError, ValueError):
        return ''
    return ''


def linea_visible_cliente(rep: dict | None) -> bool:
    return linea_cuenta_en_total(rep)


def aplicar_pedido_y_sugerencias(
    contenido: dict[str, Any] | None,
    servicio_nombre: str = '',
    vehiculo: dict | None = None,
) -> dict[str, Any]:
    """Reescribe el borrador de la IA: lo pedido entra; el complemento queda pendiente."""
    data = dict(contenido or {})
    pedido = _texto_pedido(
        servicio_nombre,
        str(data.get('servicio_nombre') or ''),
        str(data.get('descripcion_problema') or ''),
    )
    reps = [dict(rep) for rep in (data.get('repuestos') or []) if isinstance(rep, dict)]
    if not _toca_embrague(pedido) and not _toca_embrague(_nombres(reps)):
        for rep in reps:
            _marcar_pedido(rep)
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
            piezas_del_pedido,
        )

        dudas_sueltas = []
        for item in _items_a_cotizar(pedido, data):
            if item.get('identidad') in ('sin_clasificar', 'otra') or item.get('rol') in ('duda', 'sistema'):
                dudas_sueltas.append({
                    'id': f"pieza-{_norm(item.get('nombre') or '').replace(' ', '-')}"[:48],
                    'texto': (
                        f"No clasifiqué «{item.get('nombre')}». Quedó como duda: "
                        'no se cobra y no se unió con otra pieza.'
                    ),
                    'confirmada': False,
                })
                continue
            nombre = item['nombre']
            if _ya(reps, nombre):
                continue
            reps.append(_linea(
                nombre,
                origen=ORIGEN_PEDIDO,
                motivo='',
                estado=ESTADO_ACEPTADA,
                identidad=str(item.get('identidad') or ''),
            ))
        data['repuestos'] = reps
        sueltas = _dudas_pieza_suelta(reps) + dudas_sueltas
        if sueltas:
            data['dudas'] = sueltas
        return data

    pedidos = _pedidos_con_llm(pedido, data)
    reps = _quedarse_con_pedidas(reps, pedidos)
    for nombre in pedidos:
        if _ya(reps, nombre):
            continue
        reps.append(_linea(nombre, origen=ORIGEN_PEDIDO, motivo='', estado=ESTADO_ACEPTADA))
    reps = _aplicar_composicion_kit(reps, pedidos, quitar_no_pedidos=True)
    reps = _sellar_lineas(reps, vehiculo or data.get('vehiculo'))
    data['repuestos'] = reps
    data['servicios_lineas'] = _faenas(data, pedido, pedidos)
    data['mano_obra_clp'] = sum(
        int(lin.get('monto_clp') or 0)
        for lin in data['servicios_lineas']
        if linea_cuenta_en_total(lin)
    )
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
        separar_precios_copiados,
    )

    copiadas = separar_precios_copiados(reps)
    data['dudas'] = _dudas(reps, pedido, kit_visto=_linea_kit(reps)) + copiadas
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
        recalcular_totales,
    )

    costo, mo, total = recalcular_totales(reps, int(data['mano_obra_clp'] or 0))
    data['costo_repuestos_clp'] = costo
    data['mano_obra_clp'] = mo
    data['total_clp'] = total
    return data


def proponer_complementos(
    repuestos: list,
    pedido: str,
    *,
    descartadas: list[str] | None = None,
    vehiculo: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    """En una edición, no reescribe lo que el taller ya puso.

    Lo que el pedido nombra entra como línea cobrable. Si todavía no tiene
    precio, la duda lo dice. Solo el complemento no pedido queda pendiente.
    """
    reps = [dict(rep) if isinstance(rep, dict) else rep for rep in (repuestos or [])]
    for rep in reps:
        if isinstance(rep, dict) and not rep.get('origen'):
            _marcar_pedido(rep)
    if not _toca_embrague(pedido):
        dudas_sueltas = []
        for item in _items_a_cotizar(pedido, {'comprension_llm': {}}):
            if item.get('identidad') in ('sin_clasificar', 'otra') or item.get('rol') in ('duda', 'sistema'):
                dudas_sueltas.append({
                    'id': f"pieza-{_norm(item.get('nombre') or '').replace(' ', '-')}"[:48],
                    'texto': (
                        f"No clasifiqué «{item.get('nombre')}». Quedó como duda: "
                        'no se cobra y no se unió con otra pieza.'
                    ),
                    'confirmada': False,
                })
                continue
            nombre = item['nombre']
            if _ya(reps, nombre):
                _forzar_pedido(reps, nombre)
                continue
            reps.append(_linea(
                nombre,
                origen=ORIGEN_PEDIDO,
                motivo='',
                estado=ESTADO_ACEPTADA,
                identidad=str(item.get('identidad') or ''),
            ))
        return reps, _dudas_pieza_suelta(reps) + dudas_sueltas
    pedidos = _piezas_pedidas(pedido)
    bloqueadas = {_norm(n) for n in (descartadas or [])}
    for nombre in pedidos:
        if _ya(reps, nombre):
            _forzar_pedido(reps, nombre)
            continue
        reps.append(_linea(nombre, origen=ORIGEN_PEDIDO, motivo='', estado=ESTADO_ACEPTADA))
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
        es_sistema,
    )

    reps = [
        rep for rep in reps
        if not (isinstance(rep, dict) and es_sistema(str(rep.get('nombre') or '')))
    ]
    reps = _aplicar_composicion_kit(reps, pedidos, bloqueadas=bloqueadas)
    reps = _sellar_lineas(reps, vehiculo)
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
        separar_precios_copiados,
    )

    dudas = separar_precios_copiados(reps)
    dudas = _dudas(reps, pedido, kit_visto=_linea_kit(reps)) + dudas
    return reps, dudas


def piezas_para_busqueda(texto: str, auto: str) -> dict[str, Any]:
    """Plan de búsqueda: lo pedido y, aparte, las sugerencias marcadas."""
    pedidos = _piezas_pedidas(texto)
    piezas = []
    for nombre in pedidos:
        piezas.append({
            'nombre': nombre,
            'consulta': _consulta(nombre, auto),
            'porque': f'El pedido nombra {nombre}.',
            'escasa': _escasa(nombre),
            'sugerida': False,
        })
    return {
        'trabajo': 'cambio_embrague' if _toca_embrague(texto) else 'pedido_taller',
        'faena': 'Cambio de embrague' if _baja_la_caja(texto, pedidos) else (pedidos[0] if pedidos else 'Mano de obra'),
        'razonamiento': (
            f'{auto}: se cotiza lo pedido ({", ".join(pedidos) or "el trabajo"}). '
            'Lo que no pidieron queda como sugerencia pendiente, no como línea cobrada.'
        ),
        'piezas': piezas,
    }


def resumen_para_cliente(cotizacion) -> str:
    """Texto que el agente puede decir. No nombra sugerencias pendientes."""
    partes = []
    for rep in getattr(cotizacion, 'repuestos', None) or []:
        if not linea_visible_cliente(rep):
            continue
        nombre = str(rep.get('nombre') or '').strip()
        if nombre:
            partes.append(nombre)
    pendientes = [
        str(rep.get('nombre') or '').strip()
        for rep in (getattr(cotizacion, 'repuestos', None) or [])
        if isinstance(rep, dict)
        and rep.get('origen') == ORIGEN_SUGERENCIA
        and rep.get('estado_sugerencia') == ESTADO_PENDIENTE
    ]
    pedido = ', '.join(partes) or (getattr(cotizacion, 'servicio_nombre', '') or 'el trabajo pedido')
    texto = f'Al cliente solo se le confirma: {pedido}.'
    if pendientes:
        texto += (
            ' Hay sugerencias en revisión del taller: no las menciones, '
            'no las prometas y no las sumes al precio.'
        )
    if _hay_precio_no_firme(cotizacion) or _hay_duda_abierta(cotizacion):
        texto += (
            ' No des un precio cerrado. Hay un precio estimado o una duda sin confirmar: '
            'no lo presentes como firme y no comentes la duda al cliente.'
        )
    return texto


def decision_taller_para_agente(cotizacion) -> str:
    eventos = list((getattr(cotizacion, 'metadata', None) or {}).get('eventos_revision') or [])
    frases = []
    for evento in eventos[-8:]:
        if not isinstance(evento, dict):
            continue
        tipo = evento.get('tipo')
        nombre = evento.get('nombre') or ''
        if tipo == 'sugerencia_aceptada' and nombre:
            frases.append(f'El taller aceptó {nombre}.')
        elif tipo == 'sugerencia_descartada' and nombre:
            frases.append(f'El taller descartó {nombre}.')
        elif tipo == 'duda_confirmada':
            frases.append('El taller confirmó una duda.')
    if not frases:
        return ''
    return 'Decisiones del taller: ' + ' '.join(frases)


def anotar_revision_metadata(metadata: dict | None, repuestos: list, dudas: list | None) -> dict:
    meta = dict(metadata or {})
    previas = {
        str(d.get('id')): d
        for d in (meta.get('dudas') or [])
        if isinstance(d, dict) and d.get('id')
    }
    fusion = []
    for duda in dudas or []:
        if not isinstance(duda, dict):
            continue
        anterior = previas.get(str(duda.get('id')))
        if anterior and anterior.get('confirmada'):
            duda = {**duda, 'confirmada': True}
        fusion.append(duda)
    meta['dudas'] = fusion
    pendientes = _contar_pendientes(repuestos)
    if pendientes:
        estado = 'pendiente'
    elif any(isinstance(r, dict) and r.get('origen') == ORIGEN_SUGERENCIA for r in repuestos or []):
        estado = 'resuelta'
    else:
        estado = 'sin_sugerencias'
    meta['revision_sugerencias'] = {
        'estado': estado,
        'pendientes': pendientes,
    }
    return meta


def registrar_evento(metadata: dict, tipo: str, *, nombre: str = '', linea_id: str = '') -> dict:
    from django.utils import timezone

    meta = dict(metadata or {})
    eventos = list(meta.get('eventos_revision') or [])
    eventos.append({
        'tipo': tipo,
        'nombre': nombre,
        'linea_id': linea_id,
        'en': timezone.now().isoformat(),
    })
    meta['eventos_revision'] = eventos[-30:]
    return meta


def notificar_revision_al_taller(cotizacion) -> None:
    """Aviso interno al taller. No abre WhatsApp ni Meta."""
    pendientes = _contar_pendientes(cotizacion.repuestos or [])
    if pendientes <= 0:
        return
    usuario = getattr(cotizacion, 'creado_por', None)
    if usuario is None:
        taller = getattr(cotizacion, 'taller', None)
        usuario = getattr(taller, 'usuario', None) if taller is not None else None
    if usuario is None:
        return
    from mecanimovilapp.apps.usuarios.models import Notificacion

    nombres = [
        str(rep.get('nombre') or '').strip()
        for rep in (cotizacion.repuestos or [])
        if isinstance(rep, dict)
        and rep.get('origen') == ORIGEN_SUGERENCIA
        and rep.get('estado_sugerencia') == ESTADO_PENDIENTE
    ]
    titulo = 'Revisa sugerencias de la cotización'
    mensaje = (
        f'La cotización "{cotizacion.servicio_nombre or "servicio"}" tiene '
        f'{pendientes} sugerencia(s) pendiente(s): {", ".join(nombres[:4])}. '
        'No se cobran ni se le prometen al cliente hasta que las aceptes o las descartes.'
    )
    data = {
        'type': 'revision_sugerencias_pendiente',
        'cotizacion_id': cotizacion.id,
        'conversation_id': cotizacion.conversation_id,
        'pendientes': pendientes,
    }
    Notificacion.crear_unica(
        usuario,
        tipo='system',
        titulo=titulo,
        mensaje=mensaje,
        data=data,
        ventana_horas=6,
        dedup_key={'type': 'revision_sugerencias_pendiente', 'cotizacion_id': cotizacion.id},
    )
    try:
        from mecanimovilapp.apps.agente_ia.services.notificaciones import _emitir_ws_agente

        if getattr(usuario, 'id', None):
            _emitir_ws_agente(usuario.id, 'revision_sugerencias_pendiente', **data)
    except Exception:
        pass


def decidir_sugerencia(cotizacion, *, linea_id: str, accion: str):
    accion = (accion or '').strip().lower()
    if accion not in ('aceptar', 'descartar'):
        raise ValueError('La acción es aceptar o descartar.')
    reps = [dict(rep) if isinstance(rep, dict) else rep for rep in (cotizacion.repuestos or [])]
    objetivo = None
    for rep in reps:
        if isinstance(rep, dict) and str(rep.get('id') or '') == str(linea_id):
            objetivo = rep
            break
    if objetivo is None:
        raise ValueError('No está esa línea en la cotización.')
    if objetivo.get('origen') != ORIGEN_SUGERENCIA:
        raise ValueError('Esa línea la pidió el taller: no es una sugerencia.')
    estado = ESTADO_ACEPTADA if accion == 'aceptar' else ESTADO_DESCARTADA
    objetivo['estado_sugerencia'] = estado
    meta = dict(cotizacion.metadata or {})
    if estado == ESTADO_DESCARTADA:
        bloqueadas = list(meta.get('sugerencias_descartadas') or [])
        nombre = str(objetivo.get('nombre') or '')
        if nombre and nombre not in bloqueadas:
            bloqueadas.append(nombre)
        meta['sugerencias_descartadas'] = bloqueadas
    meta = anotar_revision_metadata(meta, reps, meta.get('dudas') or [])
    meta = registrar_evento(
        meta,
        'sugerencia_aceptada' if estado == ESTADO_ACEPTADA else 'sugerencia_descartada',
        nombre=str(objetivo.get('nombre') or ''),
        linea_id=str(linea_id),
    )
    cotizacion.repuestos = reps
    cotizacion.metadata = meta
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
        aplicar_totales_cotizacion,
    )

    aplicar_totales_cotizacion(cotizacion)
    cotizacion.save(update_fields=[
        'repuestos', 'metadata', 'costo_repuestos_clp', 'mano_obra_clp',
        'descuento_clp', 'total_clp', 'actualizado_en',
    ])
    return cotizacion


def confirmar_duda(cotizacion, duda_id: str):
    meta = dict(cotizacion.metadata or {})
    dudas = []
    encontrada = False
    for duda in meta.get('dudas') or []:
        if not isinstance(duda, dict):
            continue
        if str(duda.get('id') or '') == str(duda_id):
            duda = {**duda, 'confirmada': True}
            encontrada = True
        dudas.append(duda)
    if not encontrada:
        raise ValueError('No está esa duda.')
    meta['dudas'] = dudas
    meta = registrar_evento(meta, 'duda_confirmada', linea_id=str(duda_id))
    cotizacion.metadata = meta
    cotizacion.save(update_fields=['metadata', 'actualizado_en'])
    return cotizacion


class EliminacionBloqueada(ValueError):
    def __init__(self, mensaje: str, codigo: str = 'cotizacion_con_caja'):
        super().__init__(mensaje)
        self.codigo = codigo


def motivo_bloqueo_eliminacion(cotizacion) -> str:
    citas = list(cotizacion.citas_generadas.all())
    if any(getattr(c, 'estado', '') == 'activa' for c in citas):
        return (
            'Esta cotización tiene una cita activa. '
            'Ciérrala o cancélala antes de quitarla, para no dejar el caso a medias.'
        )
    if any(
        getattr(c, 'cobro_estado', '') == 'anotado' or int(getattr(c, 'cobro_monto_clp', 0) or 0) > 0
        for c in citas
    ):
        return 'Esta cotización tiene un cobro anotado. No se elimina para no romper la caja.'
    ids = [str(c.id) for c in citas]
    if not ids:
        return ''
    from mecanimovilapp.apps.ordenes.models import CobroTaller

    if CobroTaller.objects.filter(
        taller_id=cotizacion.taller_id,
        ancla_tipo=CobroTaller.ANCLA_CITA,
        ancla_id__in=ids,
    ).exists():
        return 'Esta cotización tiene movimientos de caja. No se elimina para no romper la caja.'
    return ''


def eliminar_cotizacion_taller(cotizacion) -> dict[str, Any]:
    """Una acción: la saca de las listas del taller. No borra la fila ni la caja."""
    motivo = motivo_bloqueo_eliminacion(cotizacion)
    if motivo:
        raise EliminacionBloqueada(motivo)
    from mecanimovilapp.apps.ordenes.models import VistaTallerOculta

    if cotizacion.estado in ('borrador', 'enviada'):
        cotizacion.estado = 'cancelada'
        cotizacion.save(update_fields=['estado', 'actualizado_en'])
    VistaTallerOculta.objects.get_or_create(
        taller_id=cotizacion.taller_id,
        tipo=VistaTallerOculta.TIPO_COTIZACION,
        objeto_id=str(cotizacion.id),
    )
    return {
        'eliminada': True,
        'id': cotizacion.id,
        'estado': cotizacion.estado,
        'modo': 'oculta',
    }


def _contar_pendientes(repuestos) -> int:
    return sum(
        1
        for rep in repuestos or []
        if isinstance(rep, dict)
        and rep.get('origen') == ORIGEN_SUGERENCIA
        and rep.get('estado_sugerencia') == ESTADO_PENDIENTE
    )


def _texto_pedido(*partes: str) -> str:
    """Junta servicio y detalle sin repetir la misma frase dos veces."""
    texto = ''
    for parte in partes:
        parte = (parte or '').strip()
        if not parte:
            continue
        if _norm(parte) and _norm(parte) in _norm(texto):
            continue
        if _norm(parte) in (
            'cambio de embrague', 'cambio embrague', 'embrague', 'embrague completo', 'clutch',
        ) and ('embrague' in _norm(texto) or 'clutch' in _norm(texto)):
            continue
        texto = f'{texto} {parte}'.strip()
    return texto


def _hay_precio_no_firme(cotizacion) -> bool:
    for rep in getattr(cotizacion, 'repuestos', None) or []:
        if not isinstance(rep, dict) or not linea_visible_cliente(rep):
            continue
        if int(rep.get('precio_unitario_clp') or 0) <= 0:
            continue
        if _precio_es_estimado(rep):
            return True
    return False


def _hay_duda_abierta(cotizacion) -> bool:
    meta = getattr(cotizacion, 'metadata', None) or {}
    for duda in meta.get('dudas') or []:
        if isinstance(duda, dict) and not duda.get('confirmada'):
            return True
    return False


def _dudas_pieza_suelta(reps: list) -> list[dict]:
    dudas = []
    for rep in reps:
        if not isinstance(rep, dict) or rep.get('identidad') != 'sin_clasificar':
            continue
        nombre = str(rep.get('nombre') or '')
        dudas.append({
            'id': f'pieza-{_norm(nombre).replace(" ", "-")}'[:48],
            'texto': (
                f'No clasifiqué «{nombre}». Quedó como pieza aparte: '
                'no se descartó ni se unió con otra.'
            ),
            'confirmada': False,
        })
    return dudas


def _items_a_cotizar(pedido: str, data: dict | None) -> list[dict]:
    """Taxonomía del texto, más una «otra» con confianza que el modelo sí nombró."""
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
        identidad_de,
        piezas_del_pedido,
    )

    items = list(piezas_del_pedido(pedido or ''))
    comp = (data or {}).get('comprension_llm') if isinstance(data, dict) else None
    dinamicos = [
        item for item in (comp or {}).get('items') or []
        if isinstance(item, dict) and str(item.get('identidad') or '').startswith('otra:')
        and item.get('rol') not in ('duda', 'sistema', 'mano_obra')
    ]
    citados = {
        _norm(str(item.get('texto_original') or item.get('nombre') or ''))
        for item in dinamicos
    }
    if citados:
        items = [
            item for item in items
            if not (
                item.get('identidad') == 'sin_clasificar'
                and _norm(str(item.get('texto_original') or item.get('nombre') or '')) in citados
            )
        ]
    conocidas = {
        identidad_de(str(item.get('nombre') or ''))
        for item in items
        if item.get('identidad') not in ('sin_clasificar', 'otra', '')
    }
    ya = {_norm(str(item.get('nombre') or '')) for item in items}
    for item in dinamicos:
        nombre = str(item.get('nombre') or '').strip()
        if not nombre or _norm(nombre) in ya:
            continue
        conocida = identidad_de(nombre)
        if conocida and conocida in conocidas:
            continue
        ya.add(_norm(nombre))
        items.append(item)
    return items


def _pedidos_con_llm(pedido: str, data: dict | None) -> list[str]:
    """Taxonomía del texto, más lo que la extracción ya validada nombró."""
    pedidos = _piezas_pedidas(pedido)
    comp = (data or {}).get('comprension_llm') if isinstance(data, dict) else None
    for item in (comp or {}).get('items') or []:
        if not isinstance(item, dict):
            continue
        nombre = str(item.get('nombre') or '').strip()
        if not nombre:
            continue
        if item.get('identidad') in ('sin_clasificar', 'otra') or item.get('rol') in ('duda', 'sistema'):
            continue
        if str(item.get('identidad') or '').startswith('otra:'):
            from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
                identidad_de,
            )

            conocida = identidad_de(nombre)
            if conocida and any(identidad_de(pedido_ya) == conocida for pedido_ya in pedidos):
                continue
        canon = _canon(nombre) or nombre
        if not any(_norm(p) == _norm(canon) for p in pedidos):
            pedidos.append(canon)
    return pedidos


def _piezas_pedidas(pedido: str) -> list[str]:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
        es_sistema,
        piezas_del_pedido,
    )
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.separar_pedido_taller import (
        interpretar_pedido_taller,
    )

    comprendidas = [
        item['nombre'] for item in piezas_del_pedido(pedido or '')
        if item.get('identidad') not in ('sin_clasificar', 'otra')
        and item.get('rol') not in ('duda', 'sistema')
    ]
    if comprendidas:
        return comprendidas
    interp = interpretar_pedido_taller(pedido or '')
    crudos = list(interp.get('repuestos') or [])
    if not crudos:
        for faena in interp.get('mano_obra') or []:
            crudos.append(faena)
    canonicos: list[str] = []
    for nombre in crudos:
        if es_sistema(nombre):
            continue
        canon = _canon(nombre)
        if canon and canon not in canonicos:
            canonicos.append(canon)
    if _menciona_piola(pedido) and 'Piola de embrague' not in canonicos:
        canonicos.append('Piola de embrague')
    if not canonicos and _toca_embrague(pedido):
        canonicos.append('Kit de embrague')
    return canonicos


def _faenas(data: dict, pedido: str, pedidos: list[str]) -> list[dict]:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.separar_pedido_taller import (
        interpretar_pedido_taller,
    )

    previas = [lin for lin in (data.get('servicios_lineas') or []) if isinstance(lin, dict)]
    interp = interpretar_pedido_taller(pedido or '')
    manos = [str(n).strip() for n in (interp.get('mano_obra') or []) if str(n).strip()]
    if _solo_faena_de_embrague(manos, pedidos):
        monto = sum(int(lin.get('monto_clp') or 0) for lin in previas) or int(data.get('mano_obra_clp') or 0)
        faena = {'nombre': 'Cambio de embrague', 'monto_clp': monto, 'origen': ORIGEN_PEDIDO, 'estado_sugerencia': ESTADO_ACEPTADA}
        if previas and str(previas[0].get('id') or '').strip():
            faena['id'] = previas[0]['id']
        return [faena]
    salida = []
    usados = set()
    for titulo in _titulos_faena(manos, pedidos):
        match = _linea_parecida(previas, titulo, usados)
        monto = int(match.get('monto_clp') or 0) if match else 0
        if match is not None:
            usados.add(id(match))
        fila = {
            'nombre': titulo,
            'monto_clp': monto,
            'origen': ORIGEN_PEDIDO,
            'estado_sugerencia': ESTADO_ACEPTADA,
            'motivo_sugerencia': '',
        }
        if match and match.get('id'):
            fila['id'] = match['id']
        salida.append(fila)
    if salida and sum(int(f.get('monto_clp') or 0) for f in salida) == 0:
        lump = int(data.get('mano_obra_clp') or 0) or sum(int(lin.get('monto_clp') or 0) for lin in previas)
        if lump:
            salida[0]['monto_clp'] = lump
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
        faenas_de,
    )

    for titulo in faenas_de(pedido, []):
        if titulo not in [fila['nombre'] for fila in salida]:
            salida.append({
                'nombre': titulo,
                'monto_clp': 0,
                'origen': ORIGEN_PEDIDO,
                'estado_sugerencia': ESTADO_ACEPTADA,
                'motivo_sugerencia': '',
            })
    return salida or previas


def _titulos_faena(manos: list[str], pedidos: list[str]) -> list[str]:
    titulos = []
    for mano in manos:
        if 'purg' in _norm(mano) or 'sistema hidraulico' in _norm(mano):
            titulo = 'Purga del sistema hidráulico'
        else:
            titulo = 'Cambio de embrague' if _es_faena_kit(mano) else mano
        if titulo not in titulos:
            titulos.append(titulo)
    for nombre in pedidos:
        if nombre in ('Rodamiento de volante', 'Retén trasero de cigüeñal'):
            continue
        esperado = _faena_de_pieza(nombre)
        if not any(_norm(esperado) in _norm(t) or _norm(nombre) in _norm(t) for t in titulos):
            titulos.append(esperado)
    return titulos


def _faena_de_pieza(nombre: str) -> str:
    if nombre == 'Kit de embrague':
        return 'Cambio de embrague'
    if nombre == 'Bomba de embrague':
        return 'Cambio de bomba de embrague'
    if nombre == 'Líquido de frenos':
        return 'Cambio de líquido de frenos'
    if nombre == 'Cilindro de embrague':
        return 'Cambio de cilindro de embrague'
    if nombre == 'Aceite de caja de cambios':
        return 'Cambio de aceite de caja'
    if nombre == 'Piola de embrague':
        return 'Cambio de piola de embrague'
    return f'Cambio de {nombre[:1].lower() + nombre[1:]}' if nombre else 'Mano de obra'


def _es_faena_kit(mano: str) -> bool:
    n = _norm(mano)
    if any(k in n for k in (
        'bomba', 'liquido', 'piola', 'guaya', 'cable', 'cilindro', 'bombin',
        'aceite', 'flexible', 'horquilla', 'manguera',
    )):
        return False
    return 'embrague' in n or 'clutch' in n or 'kit' in n


def _solo_faena_de_embrague(manos: list[str], pedidos: list[str]) -> bool:
    extras = [p for p in pedidos if p not in ('Kit de embrague',)]
    if extras:
        return False
    return all(_es_faena_kit(m) or _norm(m) in ('kit de embrague', 'embrague', 'embrague completo') for m in manos)


def _dudas(reps: list, pedido: str, *, kit_visto: dict | None) -> list[dict]:
    dudas = []
    if _baja_la_caja(pedido, _piezas_pedidas(pedido)) and not _kit_tiene_ficha(kit_visto):
        dudas.append({
            'id': 'kit-composicion',
            'texto': (
                'No confirmé en una ficha si el kit trae disco, prensa y rodamiento. '
                'No agregué el rodamiento de volante aparte.'
            ),
            'confirmada': False,
        })
    for rep in reps:
        if not isinstance(rep, dict) or not linea_cuenta_en_total(rep):
            continue
        nombre = str(rep.get('nombre') or '')
        if int(rep.get('precio_unitario_clp') or 0) <= 0:
            dudas.append({
                'id': f'precio-{_norm(nombre).replace(" ", "-")}'[:48],
                'texto': f'No hay precio de tienda para {nombre}. Confírmalo: no lo inventé.',
                'confirmada': False,
            })
        elif _precio_es_estimado(rep):
            dudas.append({
                'id': f'precio-estimado-{_norm(nombre).replace(" ", "-")}'[:48],
                'texto': (
                    f'El precio de {nombre} es estimado, sin ficha de tienda. '
                    'Confírmalo o ingrésalo antes de enviar.'
                ),
                'confirmada': False,
            })
        if rep.get('identidad') == 'sin_clasificar':
            dudas.append({
                'id': f'pieza-{_norm(nombre).replace(" ", "-")}'[:48],
                'texto': (
                    f'No clasifiqué «{nombre}». Quedó como pieza aparte: '
                    'no se descartó ni se unió con otra.'
                ),
                'confirmada': False,
            })
        if 'liquido' in _norm(nombre) and not str(rep.get('especificacion') or '').strip():
            dudas.append({
                'id': 'liquido-especificacion',
                'texto': 'No confirmé si este auto usa líquido DOT3 o DOT4.',
                'confirmada': False,
            })
    vistos = set()
    unicas = []
    for duda in dudas:
        if duda['id'] in vistos:
            continue
        vistos.add(duda['id'])
        unicas.append(duda)
    return unicas


def _quedarse_con_pedidas(reps: list[dict], pedidos: list[str]) -> list[dict]:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
        es_sistema as _es_sistema,
    )

    kit_pedido = 'Kit de embrague' in pedidos
    salida = []
    for rep in reps:
        nombre = str(rep.get('nombre') or '')
        if kit_pedido and _es_suelta_del_kit(nombre):
            continue
        if _es_vago(nombre) or _es_sistema(nombre):
            continue
        canon = _canon(nombre)
        if _pedida(canon, pedidos) or _pedida(nombre, pedidos):
            _marcar_pedido(rep)
            if canon in (
                'Kit de embrague', 'Bomba de embrague', 'Cilindro de embrague',
                'Líquido de frenos', 'Piola de embrague', 'Aceite de caja de cambios',
            ):
                rep['nombre'] = canon
            salida.append(rep)
            continue
        if rep.get('origen') == ORIGEN_SUGERENCIA:
            salida.append(rep)
            continue
        if _canon(nombre) in {n for n, _m in _SUGERENCIAS_CAJA}:
            rep['nombre'] = _canon(nombre)
            salida.append(rep)
            continue
        _marcar_pedido(rep)
        salida.append(rep)
    return salida


def _retag_si_no_pedida(reps: list[dict], nombre: str, motivo: str) -> None:
    for rep in reps:
        if _ya([rep], nombre) and rep.get('origen') != ORIGEN_PEDIDO:
            rep['origen'] = ORIGEN_SUGERENCIA
            rep['estado_sugerencia'] = rep.get('estado_sugerencia') or ESTADO_PENDIENTE
            rep['motivo_sugerencia'] = motivo
            if rep.get('estado_sugerencia') not in (ESTADO_ACEPTADA, ESTADO_DESCARTADA, ESTADO_PENDIENTE):
                rep['estado_sugerencia'] = ESTADO_PENDIENTE


def _marcada_pedido_explicita(rep: dict) -> bool:
    return rep.get('origen') == ORIGEN_PEDIDO and rep.get('estado_sugerencia') == ESTADO_ACEPTADA


def _linea(nombre: str, *, origen: str, motivo: str, estado: str, identidad: str = '') -> dict:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
        identidad_de,
        rol_de,
    )

    ident = str(identidad or '').strip()
    if not ident or ident in ('sin_clasificar', 'otra'):
        ident = identidad_de(nombre) or ident or 'sin_clasificar'
    rol = 'repuesto' if ident.startswith('otra:') else (rol_de(ident) or 'repuesto')
    fila = {
        'identidad': ident,
        'rol': rol,
        'nombre': nombre,
        'cantidad': 1,
        'precio_unitario_clp': 0,
        'precio_min_clp': 0,
        'precio_max_clp': 0,
        'especificacion': '',
        'marca_repuesto': '',
        'fuente_marketplace': '',
        'tienda_ml': '',
        'comentario': motivo if origen == ORIGEN_SUGERENCIA else (
            'Disco, prensa y rodamiento de empuje. Así lo venden las casas de repuestos.'
            if nombre == 'Kit de embrague' else ''
        ),
        'id': f'rep-{uuid.uuid4().hex[:10]}',
        'origen': origen,
        'motivo_sugerencia': motivo if origen == ORIGEN_SUGERENCIA else '',
        'estado_sugerencia': estado,
    }
    return fila


def _marcar_pedido(rep: dict) -> None:
    if rep.get('origen') == ORIGEN_SUGERENCIA:
        return
    rep['origen'] = ORIGEN_PEDIDO
    rep['estado_sugerencia'] = ESTADO_ACEPTADA
    rep.setdefault('motivo_sugerencia', '')


def _forzar_pedido(reps: list, nombre: str) -> None:
    """Lo pedido no puede seguir como sugerencia, aunque antes se haya etiquetado así."""
    clave = _norm(_canon(nombre) or nombre)
    canon = _canon(nombre) or nombre
    for rep in reps:
        if not isinstance(rep, dict):
            continue
        if _norm(_canon(str(rep.get('nombre') or ''))) != clave:
            continue
        rep['origen'] = ORIGEN_PEDIDO
        rep['estado_sugerencia'] = ESTADO_ACEPTADA
        rep['motivo_sugerencia'] = ''
        if canon in (
            'Kit de embrague',
            'Bomba de embrague',
            'Líquido de frenos',
            'Piola de embrague',
            'Aceite de caja de cambios',
            'Rodamiento de volante',
            'Retén trasero de cigüeñal',
        ):
            rep['nombre'] = canon


_COMPLEMENTOS = (
    'Rodamiento de volante',
    'Aceite de caja de cambios',
    'Retén trasero de cigüeñal',
)


def _aplicar_composicion_kit(
    reps: list[dict],
    pedidos: list[str],
    bloqueadas: set[str] | None = None,
    *,
    quitar_no_pedidos: bool = False,
) -> list[dict]:
    """Sin ficha no se agrega el rodamiento. Con ficha, solo lo que ella dice que falta.

    quitar_no_pedidos solo en la generación: ahí el modelo a veces mete el
    piloto, el aceite y el retén sin que nadie los pidiera. En una edición
    se conserva lo que el taller ya puso.
    """
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
        composicion_de_kit,
        kit_pide_piloto_aparte,
    )

    bloqueadas = bloqueadas or set()
    kit = _linea_kit(reps)
    titulo = str((kit or {}).get('nombre_producto') or '')
    salida = []
    for rep in reps:
        nombre = _canon(str(rep.get('nombre') or ''))
        if not quitar_no_pedidos or nombre not in _COMPLEMENTOS or _pedida(nombre, pedidos):
            salida.append(rep)
            continue
        if rep.get('origen') == ORIGEN_SUGERENCIA and rep.get('estado_sugerencia') == ESTADO_ACEPTADA:
            salida.append(rep)
    if kit_pide_piloto_aparte(titulo) and not _pedida('Rodamiento de volante', pedidos):
        if _norm('Rodamiento de volante') not in bloqueadas and not _ya(salida, 'Rodamiento de volante'):
            salida.append(_linea(
                'Rodamiento de volante',
                origen=ORIGEN_SUGERENCIA,
                motivo='La ficha del kit dice que no incluye el rodamiento piloto.',
                estado=ESTADO_PENDIENTE,
            ))
    if kit_pide_piloto_aparte(titulo):
        motivo_aceite = (
            'Al bajar la caja para el rodamiento piloto se pierde el aceite. Conviene reponerlo.'
        )
    else:
        partes = composicion_de_kit(titulo) or {}
        titulo_n = _norm(titulo)
        motivo_aceite = (
            'Al bajar la caja para el kit se pierde el aceite. Conviene reponerlo.'
            if titulo and (
                ('kit' in titulo_n and ('embrague' in titulo_n or 'clutch' in titulo_n))
                or partes.get('disco')
                or partes.get('prensa')
            )
            else ''
        )
    if motivo_aceite and not _pedida('Aceite de caja de cambios', pedidos):
        if _norm('Aceite de caja de cambios') not in bloqueadas and not _ya(salida, 'Aceite de caja de cambios'):
            salida.append(_linea(
                'Aceite de caja de cambios',
                origen=ORIGEN_SUGERENCIA,
                motivo=motivo_aceite,
                estado=ESTADO_PENDIENTE,
            ))
    return salida


def _sellar_lineas(reps: list[dict], vehiculo: dict | None) -> list[dict]:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.comprension_pedido import (
        anotar_especificacion,
    )

    for rep in reps:
        if isinstance(rep, dict):
            anotar_especificacion(rep, vehiculo)
    return reps


def _kit_tiene_ficha(rep: dict | None) -> bool:
    if not isinstance(rep, dict):
        return False
    return bool(str(rep.get('nombre_producto') or '').strip())


def _precio_es_estimado(rep: dict) -> bool:
    if str(rep.get('url_producto') or rep.get('url_referencia') or '').strip():
        return False
    if rep.get('precio_estimado') is True:
        return True
    return str(rep.get('certeza') or '').strip().lower() == 'asumido'


def _otro_sistema(n: str) -> bool:
    return any(pieza in n for pieza in (
        'freno', 'suspension', 'rueda', 'puerta', 'acelerador', 'automatico', 'direccion',
    ))


def _canon(nombre: str) -> str:
    n = _norm(nombre)
    if not n:
        return ''
    embrague = 'embrague' in n or 'clutch' in n or 'embrage' in n
    if _otro_sistema(n) and not embrague:
        if 'aceite' in n and ('caja' in n or 'transmision' in n):
            return 'Aceite de caja de cambios'
        return str(nombre or '').strip()
    if embrague and ('piola' in n or 'guaya' in n or 'cable' in n):
        return 'Piola de embrague'
    if 'piola de embrague' in n or 'piola embrague' in n or 'cable de embrague' in n:
        return 'Piola de embrague'
    if (
        (embrague and 'bombin' in n)
        or 'cilindro receptor' in n
        or 'cilindro esclavo' in n
        or ('cilindro' in n and embrague and 'maestro' not in n)
    ):
        return 'Cilindro de embrague'
    if ('bomba' in n and embrague) or (embrague and 'cilindro maestro' in n):
        return 'Bomba de embrague'
    if 'liquido' in n and ('freno' in n or 'embrague' in n):
        return 'Líquido de frenos'
    if 'aceite' in n and ('caja' in n or 'transmision' in n):
        return 'Aceite de caja de cambios'
    if 'flexible' in n or ('manguera' in n and ('embrague' in n or 'clutch' in n)):
        return 'Flexible de embrague'
    if 'horquilla' in n and embrague:
        return 'Horquilla de embrague'
    if 'rodamiento' in n and 'volante' in n:
        return 'Rodamiento de volante'
    if ('piloto' in n or 'ruleman' in n) and embrague:
        return 'Rodamiento de volante'
    if 'ciguenal' in n or (embrague and 'reten' in n) or 'reten trasero' in n:
        return 'Retén trasero de cigüeñal'
    if n in ('collarin', 'crapodina', 'rodamiento de empuje') or 'crapodina' in n:
        return 'Rodamiento de empuje'
    if 'kit' in n or n in ('embrague', 'embrague completo', 'clutch', 'cambio de embrague'):
        return 'Kit de embrague'
    if any(p in n for p in ('disco', 'prensa', 'plato', 'collarin', 'empuje')) and 'piloto' not in n:
        return 'Kit de embrague'
    return str(nombre or '').strip()


def _pedida(nombre: str, pedidos: list[str]) -> bool:
    clave = _norm(_canon(nombre) or nombre)
    return any(_norm(p) == clave or _norm(_canon(p)) == clave for p in pedidos)


def _baja_la_caja(pedido: str, pedidos: list[str] | None = None) -> bool:
    if 'Kit de embrague' in (pedidos or []):
        return True
    n = _norm(pedido)
    if 'embrague' not in n and 'clutch' not in n:
        return False
    if 'kit' in n:
        return True
    if 'bomba' in n or 'liquido' in n or 'piola' in n:
        return 'cambio de embrague' in n or 'cambio embrague' in n
    return True


def _toca_embrague(texto: str) -> bool:
    n = _norm(texto)
    return 'embrague' in n or 'clutch' in n


def _menciona_piola(texto: str) -> bool:
    n = _norm(texto)
    return 'piola' in n or 'guaya' in n or ('cable' in n and ('embrague' in n or 'clutch' in n))


def _es_suelta_del_kit(nombre: str) -> bool:
    n = _norm(nombre)
    if any(k in n for k in ('kit', 'juego', 'set', 'piloto', 'volante', 'piola', 'bomba', 'liquido', 'aceite', 'reten')):
        return False
    return any(p in n for p in ('disco', 'prensa', 'plato', 'collarin', 'empuje'))


def _es_vago(nombre: str) -> bool:
    n = _norm(nombre)
    return n in ('embrague', 'embrague completo', 'clutch')


def _kit_declara_piloto(rep: dict | None) -> bool:
    if not isinstance(rep, dict):
        return False
    texto = _norm(' '.join(
        str(rep.get(k) or '') for k in ('nombre_producto', 'comentario', 'especificacion')
    ))
    return 'piloto' in texto or 'ruleman piloto' in texto


def _linea_kit(reps: list) -> dict | None:
    for rep in reps:
        if isinstance(rep, dict) and _canon(str(rep.get('nombre') or '')) == 'Kit de embrague':
            return rep
    return None


def _ya(reps: list, nombre: str) -> bool:
    clave = _norm(_canon(nombre) or nombre)
    for rep in reps:
        if not isinstance(rep, dict):
            continue
        if _norm(_canon(str(rep.get('nombre') or ''))) == clave:
            return True
    return False


def _linea_parecida(lineas: list[dict], titulo: str, usados: set) -> dict | None:
    nt = _norm(titulo)
    for lin in lineas:
        if id(lin) in usados:
            continue
        nl = _norm(str(lin.get('nombre') or ''))
        if nt in nl or nl in nt:
            return lin
        if 'piola' in nt and 'piola' in nl:
            return lin
        if 'bomba' in nt and 'bomba' in nl:
            return lin
        if 'liquido' in nt and 'liquido' in nl:
            return lin
    return None


def _consulta(nombre: str, auto: str) -> str:
    frase = nombre
    if nombre == 'Rodamiento de volante':
        frase = 'rodamiento piloto'
    elif nombre == 'Kit de embrague':
        frase = 'kit embrague'
    elif nombre == 'Aceite de caja de cambios':
        frase = 'aceite caja cambios'
    elif nombre == 'Retén trasero de cigüeñal':
        frase = 'reten cigueñal'
    elif nombre == 'Piola de embrague':
        frase = 'piola embrague'
    return f'{frase} {auto}'.strip()[:180]


def _escasa(nombre: str) -> bool:
    n = _norm(nombre)
    return any(k in n for k in ('reten', 'ciguenal', 'piloto', 'volante'))


def _nombres(reps: list) -> str:
    return ' '.join(str(rep.get('nombre') or '') for rep in reps if isinstance(rep, dict))


def _norm(texto: str) -> str:
    plano = unicodedata.normalize('NFD', texto or '')
    plano = ''.join(ch for ch in plano if unicodedata.category(ch) != 'Mn')
    plano = re.sub(r'[^a-z0-9]+', ' ', plano.lower())
    return re.sub(r'\s+', ' ', plano).strip()
