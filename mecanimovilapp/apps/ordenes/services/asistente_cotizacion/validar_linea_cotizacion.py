"""Revisa cada repuesto antes de devolver la cotización al taller.

La unidad sale del título de la ficha (pack, juego, kit, set, bidón).
La ficha se descarta si nombra otro año, otro motor u otro modelo.
El costo de una ficha válida es ese precio por unidad, no un monto asumido.
"""
from __future__ import annotations

import re
from typing import Any

_INCOMPATIBLE = frozenset({
    'anio_incompatible',
    'motor_incompatible',
    'modelo_incompatible',
    'sin_modelo',
    'listado',
})
_FRASE = {
    'anio_incompatible': 'La ficha es de otros años.',
    'motor_incompatible': 'La ficha es de otro motor.',
    'modelo_incompatible': 'La ficha es de otro modelo.',
    'sin_modelo': 'La ficha no nombra este modelo.',
    'listado': 'La ficha es un listado, no el producto.',
    'precio_alto_banda': 'El precio de la ficha queda por encima del rango de esta pieza.',
    'precio_bajo_banda': 'El precio de la ficha queda por debajo del rango de esta pieza.',
}


def _entero(valor: Any) -> int:
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


def _cantidad(rep: dict) -> int:
    cant = _entero(rep.get('cantidad') or 1)
    return cant if cant > 0 else 1


def _pack_de(nombre: str, titulo: str, cantidad: int) -> int:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
        _norm,
        unidades_pack,
    )

    n = unidades_pack(titulo)
    if n >= 2:
        return n
    if 'bujia' not in _norm(f'{nombre} {titulo}'):
        return 0
    if re.search(r'\b(juego|set|pack|kit)\b', _norm(f'{nombre} {titulo}')):
        if 2 <= cantidad <= 12:
            return cantidad
    return 0


def _estantes(rep: dict) -> list[int]:
    montos = [
        _entero(rep.get('precio_referencia_clp')),
        _entero(rep.get('precio_marketplace_clp')),
        _entero(rep.get('precio_verificado_clp')),
    ]
    for fuente in rep.get('fuentes_detalle') or []:
        if isinstance(fuente, dict):
            montos.append(_entero(fuente.get('precio_clp')))
    return [m for m in montos if m > 0]


def _precio_en_unidad(rep: dict, monto: int, titulo: str) -> tuple[int, str]:
    """Precio por unidad de la línea. Un pack no se vuelve a partir si ya es la unidad."""
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
        _norm,
        precio_unitario_desde_envase,
        precio_unitario_desde_pack,
    )

    monto = _entero(monto)
    if monto <= 0:
        return 0, ''
    nombre = str(rep.get('nombre') or '')
    cant = _cantidad(rep)
    pack = _pack_de(nombre, titulo, cant)
    if pack >= 2:
        for crudo in _estantes(rep):
            unidad = max(1, round(crudo / pack))
            if crudo > monto and abs(unidad - monto) <= max(2, int(monto * 0.08)):
                return monto, ''
    if 'bujia' in _norm(nombre) and pack >= 2 and cant >= pack:
        unit, nota = precio_unitario_desde_pack(nombre, monto, titulo, cant)
        if nota and unit > 0:
            return unit, nota
        unit = max(1, round(monto / pack))
        if unit < monto:
            nota = (
                f'La ficha es un juego de {pack} bujías a ${monto:,} CLP. '
                f'Se cotiza ${unit:,} por unidad.'
            ).replace(',', '.')
            return unit, nota
    unit, nota = precio_unitario_desde_envase(nombre, monto, titulo)
    if nota and unit > 0:
        return unit, nota
    return monto, ''


def _titulo_linea(rep: dict) -> str:
    partes = [
        str(rep.get('nombre_producto') or ''),
        str(rep.get('nombre') or ''),
        str(rep.get('especificacion') or ''),
    ]
    for fuente in rep.get('fuentes_detalle') or []:
        if isinstance(fuente, dict):
            partes.append(str(fuente.get('nombre') or ''))
            partes.append(str(fuente.get('url') or ''))
    return ' '.join(p for p in partes if p).strip()


def _casa_sugerida(rep: dict, marca: str) -> str:
    from mecanimovilapp.apps.ordenes.casas_especialistas import (
        es_etiqueta_historial,
        especialistas_de_marca,
    )
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
        nombre_tienda_visible,
    )

    casa = nombre_tienda_visible(str(rep.get('casa_repuesto_nombre') or ''))
    if casa and not es_etiqueta_historial(casa):
        return casa
    casas = especialistas_de_marca(marca)
    if casas:
        return str(casas[0].get('nombre') or '')
    return ''


def _listados(rep: dict) -> list[dict[str, Any]]:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
        _tienda_del_enlace,
        _url_ficha,
    )

    vistos: set[str] = set()
    out: list[dict[str, Any]] = []

    def agregar(url: str, tienda: str, precio: Any, titulo: str) -> None:
        ficha = _url_ficha(url)
        if not ficha or ficha in vistos:
            return
        monto = _entero(precio)
        if monto <= 0:
            return
        nombre = _tienda_del_enlace(ficha, tienda)
        if not nombre:
            return
        vistos.add(ficha)
        out.append({
            'url': ficha,
            'tienda': nombre,
            'precio': monto,
            'titulo': titulo or ficha,
        })

    for fuente in rep.get('fuentes_detalle') or []:
        if not isinstance(fuente, dict):
            continue
        agregar(
            str(fuente.get('url') or ''),
            str(fuente.get('tienda') or fuente.get('dominio') or ''),
            fuente.get('precio_clp'),
            str(fuente.get('nombre') or rep.get('nombre_producto') or ''),
        )
    url_producto = str(rep.get('url_producto') or '')
    if _url_ficha(url_producto) not in vistos:
        agregar(
            url_producto,
            str(rep.get('referencia_tienda') or rep.get('proveedor_nombre') or ''),
            _entero(rep.get('precio_referencia_clp')) or _entero(rep.get('precio_marketplace_clp')) or _entero(rep.get('precio_unitario_clp')),
            str(rep.get('nombre_producto') or ''),
        )
    return out


def _codigo_rechazo(
    rep: dict,
    item: dict[str, Any],
    unit: int,
    *,
    modelo: str,
    anio: Any,
    tipo_motor: str,
    cilindraje: Any,
) -> str:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
        _RE_PACK,
        _anio_fuera_de_rango,
        _compat_pastilla_candidato,
        _holgura_anio_titulo,
        _es_pastillas_freno,
        _monto_banda_por_unidad,
        _motivo_calidad_pastilla,
        _titulo_contradice_motor,
    )

    titulo = str(item.get('titulo') or '')
    nombre = str(rep.get('nombre') or '')
    if _titulo_contradice_motor(titulo, modelo, tipo_motor, cilindraje):
        return 'motor_incompatible'
    cand_anio = {'title': titulo, 'url': item.get('url') or '', 'content': titulo}
    if _anio_fuera_de_rango(
        cand_anio,
        anio,
        holgura=_holgura_anio_titulo(nombre, cand_anio, modelo, tipo_motor, cilindraje),
    ):
        return 'anio_incompatible'
    if _compat_pastilla_candidato(cand_anio, modelo, tipo_motor) is False:
        return 'modelo_incompatible'
    limpio = _RE_PACK.sub(' ', titulo)
    cand = {
        'title': limpio,
        'url': item.get('url') or '',
        'content': '',
        'precio_snippet': unit,
        'ficha_leida': True,
    }
    cant = _cantidad(rep)
    piso = _monto_banda_por_unidad(nombre, _entero(rep.get('precio_min_clp')), cant)
    techo = _monto_banda_por_unidad(nombre, _entero(rep.get('precio_max_clp')), cant)
    motivo = _motivo_calidad_pastilla(
        cand,
        nombre=nombre,
        modelo=modelo,
        tipo_motor=tipo_motor,
        banda_min=piso,
        banda_max=techo,
        anio=anio,
        cilindraje=cilindraje,
    ) or ''
    if motivo in ('sin_modelo', 'listado') and not _es_pastillas_freno(nombre):
        return ''
    if motivo == 'precio_alto_banda' and techo > 0 and unit <= int(techo * 1.03) + 1:
        return ''
    return motivo


def _base(casa: str) -> dict[str, Any]:
    return {
        'url_referencia': '',
        'tienda_referencia': '',
        'precio_verificado_clp': None,
        'casa_sugerida': casa,
        'precio_verificado_en_casa': False,
        'nota_referencia': '',
        'costo_unitario_clp': None,
        'validacion_estado': 'ok',
        'validacion_motivo': '',
        'alertas': [],
    }


def validar_repuesto(
    rep: dict,
    *,
    marca: str = '',
    modelo: str = '',
    anio: Any = None,
    tipo_motor: str = '',
    cilindraje: Any = None,
) -> dict[str, Any]:
    """Campos que la respuesta del taller debe mostrar para esta línea."""
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
        _linea_es_historial,
        _nota_referencia,
        _url_es_de_casa,
    )

    if not isinstance(rep, dict):
        return _base('')
    casa = _casa_sugerida(rep, marca)
    titulo = _titulo_linea(rep)
    cobrado, nota_cobrado = _precio_en_unidad(rep, _entero(rep.get('precio_unitario_clp')), titulo)
    out = _base(casa)
    alertas: list[str] = []
    if nota_cobrado:
        alertas.append(nota_cobrado)
    if cobrado > 0 and cobrado != _entero(rep.get('precio_unitario_clp')):
        out['precio_unitario_clp'] = cobrado

    if _linea_es_historial(rep):
        out['nota_referencia'] = _nota_referencia(casa, '', en_casa=False, historial=True)
        out['costo_unitario_clp'] = cobrado or None
        if cobrado > 0:
            alertas.append('El monto sale del historial del taller, no de una ficha de tienda.')
        out['alertas'] = alertas
        return _cerrar(out, cobrado, alertas)

    aceptados: list[dict[str, Any]] = []
    rechazos: list[tuple[str, str]] = []
    for item in _listados(rep):
        unit, nota = _precio_en_unidad(rep, item['precio'], item['titulo'])
        codigo = _codigo_rechazo(
            rep,
            item,
            unit,
            modelo=modelo,
            anio=anio,
            tipo_motor=tipo_motor,
            cilindraje=cilindraje,
        )
        if codigo:
            rechazos.append((codigo, item['tienda']))
            continue
        aceptados.append({**item, 'unit': unit, 'nota': nota})

    if casa:
        aceptados.sort(key=lambda item: 0 if _url_es_de_casa(item['url'], casa) else 1)

    if aceptados:
        elegido = aceptados[0]
        en_casa = _url_es_de_casa(elegido['url'], casa)
        out.update({
            'url_referencia': elegido['url'],
            'tienda_referencia': elegido['tienda'],
            'precio_verificado_clp': elegido['unit'],
            'precio_verificado_en_casa': en_casa,
            'nota_referencia': _nota_referencia(
                casa, elegido['tienda'], en_casa=en_casa, historial=False,
            ),
            'costo_unitario_clp': elegido['unit'],
        })
        if elegido['nota']:
            alertas.append(elegido['nota'])
        if _es_asumido(rep):
            alertas.append(
                f"Había un precio asumido. Se usa la ficha de {elegido['tienda']}."
            )
        out['validacion_estado'] = 'ok'
        out['validacion_motivo'] = ''
    else:
        out['costo_unitario_clp'] = cobrado or None
        incompatible = [codigo for codigo, _tienda in rechazos if codigo in _INCOMPATIBLE]
        if incompatible:
            frase = _FRASE.get(incompatible[0], 'La ficha no corresponde a este auto.')
            out['validacion_estado'] = 'sin_referencia_valida'
            out['validacion_motivo'] = f'{frase} No hay otra referencia válida.'
            alertas.append(out['validacion_motivo'])
        elif rechazos:
            frase = _FRASE.get(rechazos[0][0], 'El precio de la ficha no calza con esta pieza.')
            out['validacion_estado'] = 'requiere_revision'
            out['validacion_motivo'] = frase
            alertas.append(frase)
        elif _es_asumido(rep):
            motivo = 'No hay ficha de tienda. El precio se asumió para cotizar.'
            if casa:
                motivo = f'{motivo} Casa sugerida: {casa}.'
            out['validacion_estado'] = 'asumido'
            out['validacion_motivo'] = motivo
            alertas.append(motivo)
        if casa and not out['nota_referencia']:
            out['nota_referencia'] = _nota_referencia(casa, '', en_casa=False, historial=False)

    return _cerrar(out, cobrado, alertas)


def _es_asumido(rep: dict) -> bool:
    certeza = str(rep.get('certeza') or '').strip().lower()
    if certeza == 'asumido':
        return True
    if rep.get('precio_estimado') and str(rep.get('fuente_marketplace') or '').strip().lower() in ('', 'estimado'):
        return True
    comentario = str(rep.get('comentario') or rep.get('motivo_seleccion') or '').lower()
    return comentario.startswith('precio asumido')


def _cerrar(out: dict[str, Any], cobrado: int, alertas: list[str]) -> dict[str, Any]:
    """Si el costo sigue siendo un pack, lo parte. Si no se puede, pide revisión."""
    costo = _entero(out.get('costo_unitario_clp'))
    if cobrado > 0 and costo > cobrado * 2:
        ratio = costo / cobrado
        n = round(ratio)
        if 2 <= n <= 12 and abs(ratio - n) / n <= 0.08:
            costo = max(1, round(costo / n))
            out['costo_unitario_clp'] = costo
            if out.get('precio_verificado_clp'):
                out['precio_verificado_clp'] = costo
            alertas.append(
                f'El costo estaba en {n} unidades. Se dejó en ${costo:,} por unidad.'.replace(',', '.')
            )
    if cobrado > 0 and costo > cobrado * 2:
        pct = (cobrado - costo) / cobrado * 100
        if pct < -100 and out.get('validacion_estado') == 'ok':
            out['validacion_estado'] = 'requiere_revision'
            out['validacion_motivo'] = (
                'El costo queda más del doble del precio cobrado y no se pudo pasar a precio por unidad.'
            )
            alertas.append(out['validacion_motivo'])
    vistos: list[str] = []
    for texto in alertas:
        limpio = str(texto or '').strip()
        if limpio and limpio not in vistos:
            vistos.append(limpio)
    out['alertas'] = vistos
    return out
