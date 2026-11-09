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
    """Pendiente o descartada no entra al cobro ni a la ganancia."""
    if not isinstance(rep, dict):
        return False
    origen = str(rep.get('origen') or ORIGEN_PEDIDO)
    estado = str(rep.get('estado_sugerencia') or '')
    if origen == ORIGEN_SUGERENCIA and estado != ESTADO_ACEPTADA:
        return False
    return True


def linea_visible_cliente(rep: dict | None) -> bool:
    return linea_cuenta_en_total(rep)


def aplicar_pedido_y_sugerencias(
    contenido: dict[str, Any] | None,
    servicio_nombre: str = '',
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
        data['repuestos'] = reps
        return data

    pedidos = _piezas_pedidas(pedido)
    descartadas = set(_norm(n) for n in (data.get('sugerencias_descartadas') or []))
    reps = _quedarse_con_pedidas(reps, pedidos)
    for nombre in pedidos:
        if _ya(reps, nombre):
            continue
        reps.append(_linea(nombre, origen=ORIGEN_PEDIDO, motivo='', estado=ESTADO_ACEPTADA))
    if _baja_la_caja(pedido, pedidos):
        kit = _linea_kit(reps)
        incluye_piloto = _kit_declara_piloto(kit)
        for nombre, motivo in _SUGERENCIAS_CAJA:
            if nombre == 'Rodamiento de volante' and incluye_piloto:
                continue
            if _norm(nombre) in descartadas or _pedida(nombre, pedidos):
                continue
            if _ya(reps, nombre):
                _retag_si_no_pedida(reps, nombre, motivo)
                continue
            reps.append(_linea(
                nombre,
                origen=ORIGEN_SUGERENCIA,
                motivo=motivo,
                estado=ESTADO_PENDIENTE,
            ))
    data['repuestos'] = reps
    data['servicios_lineas'] = _faenas(data, pedido, pedidos)
    data['mano_obra_clp'] = sum(
        int(lin.get('monto_clp') or 0)
        for lin in data['servicios_lineas']
        if linea_cuenta_en_total(lin)
    )
    data['dudas'] = _dudas(reps, pedido, kit_visto=_linea_kit(reps))
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
) -> tuple[list[dict], list[dict]]:
    """En una edición, no reescribe lo que el taller ya puso. Solo agrega pendientes."""
    reps = [dict(rep) if isinstance(rep, dict) else rep for rep in (repuestos or [])]
    for rep in reps:
        if isinstance(rep, dict) and not rep.get('origen'):
            _marcar_pedido(rep)
    if not _toca_embrague(pedido):
        return reps, []
    pedidos = _piezas_pedidas(pedido)
    bloqueadas = {_norm(n) for n in (descartadas or [])}
    for nombre in pedidos:
        if nombre in {n for n, _m in _SUGERENCIAS_CAJA}:
            continue
        if _norm(nombre) in bloqueadas or _ya(reps, nombre):
            continue
        reps.append(_linea(
            nombre,
            origen=ORIGEN_SUGERENCIA,
            motivo=f'El pedido nombra {nombre} y todavía no está entre las líneas confirmadas.',
            estado=ESTADO_PENDIENTE,
        ))
    if _baja_la_caja(pedido, pedidos):
        kit = _linea_kit(reps)
        if _kit_declara_piloto(kit):
            bloqueadas.add(_norm('Rodamiento de volante'))
        for nombre, motivo in _SUGERENCIAS_CAJA:
            if _norm(nombre) in bloqueadas or _ya(reps, nombre) or _pedida(nombre, pedidos):
                continue
            reps.append(_linea(
                nombre,
                origen=ORIGEN_SUGERENCIA,
                motivo=motivo,
                estado=ESTADO_PENDIENTE,
            ))
    dudas = _dudas(reps, pedido, kit_visto=_linea_kit(reps))
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
    if _baja_la_caja(texto, pedidos):
        for nombre, motivo in _SUGERENCIAS_CAJA:
            if _pedida(nombre, pedidos):
                continue
            piezas.append({
                'nombre': nombre,
                'consulta': _consulta(nombre, auto),
                'porque': motivo,
                'escasa': _escasa(nombre),
                'sugerida': True,
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


def _piezas_pedidas(pedido: str) -> list[str]:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.separar_pedido_taller import (
        interpretar_pedido_taller,
    )

    interp = interpretar_pedido_taller(pedido or '')
    crudos = list(interp.get('repuestos') or [])
    if not crudos:
        for faena in interp.get('mano_obra') or []:
            crudos.append(faena)
    canonicos: list[str] = []
    for nombre in crudos:
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
    return salida or previas


def _titulos_faena(manos: list[str], pedidos: list[str]) -> list[str]:
    titulos = []
    for mano in manos:
        titulo = 'Cambio de embrague' if _es_faena_kit(mano) else mano
        if titulo not in titulos:
            titulos.append(titulo)
    for nombre in pedidos:
        if nombre in ('Rodamiento de volante', 'Aceite de caja de cambios', 'Retén trasero de cigüeñal'):
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
    if nombre == 'Piola de embrague':
        return 'Cambio de piola de embrague'
    return f'Cambio de {nombre[:1].lower() + nombre[1:]}' if nombre else 'Mano de obra'


def _es_faena_kit(mano: str) -> bool:
    n = _norm(mano)
    if any(k in n for k in ('bomba', 'liquido', 'piola', 'guaya', 'cable')):
        return False
    return 'embrague' in n or 'clutch' in n or 'kit' in n


def _solo_faena_de_embrague(manos: list[str], pedidos: list[str]) -> bool:
    extras = [p for p in pedidos if p not in ('Kit de embrague',)]
    if extras:
        return False
    return all(_es_faena_kit(m) or _norm(m) in ('kit de embrague', 'embrague', 'embrague completo') for m in manos)


def _dudas(reps: list, pedido: str, *, kit_visto: dict | None) -> list[dict]:
    dudas = []
    if _baja_la_caja(pedido, _piezas_pedidas(pedido)) and not _kit_declara_piloto(kit_visto):
        dudas.append({
            'id': 'kit-composicion',
            'texto': (
                'No confirmé la composición del kit en una ficha. '
                'El rodamiento de empuje suele venir dentro; el piloto no, y quedó como sugerencia.'
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
    kit_pedido = 'Kit de embrague' in pedidos
    salida = []
    for rep in reps:
        nombre = str(rep.get('nombre') or '')
        if kit_pedido and _es_suelta_del_kit(nombre):
            continue
        if _es_vago(nombre):
            continue
        canon = _canon(nombre)
        if _pedida(canon, pedidos) or _pedida(nombre, pedidos):
            _marcar_pedido(rep)
            if canon in ('Kit de embrague', 'Bomba de embrague', 'Líquido de frenos', 'Piola de embrague'):
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


def _linea(nombre: str, *, origen: str, motivo: str, estado: str) -> dict:
    fila = {
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


def _canon(nombre: str) -> str:
    n = _norm(nombre)
    if not n:
        return ''
    if 'piola' in n or 'guaya' in n or ('cable' in n and ('embrague' in n or 'clutch' in n)):
        return 'Piola de embrague'
    if 'bomba' in n or 'bombin' in n:
        return 'Bomba de embrague'
    if 'liquido' in n and ('freno' in n or 'embrague' in n):
        return 'Líquido de frenos'
    if 'aceite' in n and ('caja' in n or 'transmision' in n):
        return 'Aceite de caja de cambios'
    if 'piloto' in n or ('rodamiento' in n and 'volante' in n) or 'ruleman' in n:
        return 'Rodamiento de volante'
    if 'reten' in n or 'ciguenal' in n:
        return 'Retén trasero de cigüeñal'
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
