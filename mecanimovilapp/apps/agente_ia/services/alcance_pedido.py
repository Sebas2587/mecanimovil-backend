"""Alcance del pedido de cotización: mención ≠ ítem; suma solo explícita.

El historial clínico de patente (`historial_red`) informa recomendaciones.
NO es lista de servicios a cotizar: solo entra al pedido si el cliente lo pide ahora.
"""
from __future__ import annotations

import re
import unicodedata

from mecanimovilapp.apps.ordenes.services.catalogo_pricing import normalizar_nombre_servicio

_SERVICIO_PAREN_RE = re.compile(
    r'\s*\([^)]*(?:repuesto|sin repuesto|con repuesto|incluye|no incluye)[^)]*\)\s*',
    re.IGNORECASE,
)

_AGREGAR_A_COTIZACION_RE = re.compile(
    r'\b(?:'
    r'agrega(?:r|me|lo|la|s)?|'
    r'suma(?:r|me|le)?|'
    r'a[nñ]ade(?:r|me)?|'
    r'incluye(?:me)?|'
    r'tambi[eé]n\s+(?:quiero|necesito|pido|el|la|un|una)|'
    r'adem[aá]s\s+(?:quiero|necesito|el|la|un|una)|'
    r'actualiza(?:r)?\s+(?:la\s+)?cotizaci[oó]n|'
    r'agregar\s+a\s+(?:la\s+)?cotizaci[oó]n|'
    r'suma(?:r)?\s+(?:a\s+)?(?:la\s+)?cotizaci[oó]n'
    r')\b',
    re.IGNORECASE,
)

_QUITAR_DE_COTIZACION_RE = re.compile(
    r'\b(?:'
    r'quita(?:r|me|le|lo|la)?|'
    r'saca(?:r|me|le|lo|la)?|'
    r'elimina(?:r|me)?|'
    r'no\s+(?:quiero|incluyas?|agregues?|pidas?)'
    r')\b',
    re.IGNORECASE,
)

_SOLO_SERVICIO_RE = re.compile(
    r'\b(?:solo|solamente|[úu]nicamente)\s+(?:quiero\s+)?(?:el|la|un|una)?\s*(.+)',
    re.IGNORECASE,
)

_SERVICIO_MENCION_RE = re.compile(
    r'\b('
    r'cambio\s+de\s+filtro\s+de\s+aire|'
    r'cambio\s+de\s+filtro\s+de\s+(?:polen|habit[aá]culo|cabina)|'
    r'cambio\s+de\s+filtro\s+de\s+(?:aceite|combustible|gasolina|bencina)|'
    r'filtro\s+de\s+(?:aire|polen|habit[aá]culo|cabina|aceite|combustible)|'
    r'cambio\s+de\s+aceite(?:\s+y\s+filtro)?|'
    r'cambio\s+de\s+filtro(?:\s+de\s+aceite)?|'
    r'cambio\s+de\s+pastillas(?:\s+de\s+freno)?(?:\s+delanteras|\s+traseras)?|'
    r'cambio\s+de\s+discos?(?:\s+de\s+freno)?|'
    r'diagn[oó]stico(?:\s+(?:de\s+)?(?:frenos|motor|electr[oó]nico))?|'
    r'alineaci[oó]n(?:\s+y\s+balanceo)?|'
    r'balanceo|'
    r'revisi[oó]n\s+(?:t[eé]cnica|pre\-?compra|general)|'
    r'scanne?r|'
    r'carga\s+de\s+aire\s+acondicionado|'
    r'cambio\s+de\s+buj[ií]as|'
    r'cambio\s+de\s+correa(?:\s+de\s+distribuci[oó]n)?'
    r')\b',
    re.IGNORECASE,
)

_CLIENTE_PIDE_PRECIO_RE = re.compile(
    r'\b(?:'
    r'cu[aá]nto\s+(?:sale|cuesta|vale|cobra|cobran)|'
    r'precio|tarifa|presupuesto|cotizaci[oó]n|cotizar|'
    r'vale\s+la\s+pena|'
    r'qu[eé]\s+conlleva|'
    r'cu[aá]nto\s+me\s+(?:sale|cuesta|cobran)'
    r')\b',
    re.IGNORECASE,
)

_NEGACION_PRECIO_RE = re.compile(
    r'\b(?:no|nunca|jam[aá]s|todav[ií]a\s+no|a[uú]n\s+no)\b'
    r'(?:\s+\S+){0,4}?\s+'
    r'(?:cotizaci[oó]n|cotizar|presupuesto|precio|tarifa)\b',
    re.IGNORECASE,
)


def _sin_tildes(texto: str) -> str:
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto or '')
        if unicodedata.category(c) != 'Mn'
    )


def _clave_servicio_dedup(nombre: str) -> str:
    base = _SERVICIO_PAREN_RE.sub('', (nombre or '').strip())
    base = re.sub(r'\s*\([^)]*\)\s*', ' ', base).strip()
    return normalizar_nombre_servicio(base)


def _cliente_pide_agregar_a_cotizacion(texto_cliente: str) -> bool:
    return bool(_AGREGAR_A_COTIZACION_RE.search(_sin_tildes(texto_cliente)))


def _cliente_pide_quitar_de_cotizacion(texto: str) -> bool:
    return bool(_QUITAR_DE_COTIZACION_RE.search(_sin_tildes(texto)))


def _cliente_niega_pedir_precio(texto_cliente: str) -> bool:
    return bool(_NEGACION_PRECIO_RE.search(_sin_tildes(texto_cliente)))


def _extraer_servicios_mencionados_en_texto(texto: str) -> list[str]:
    out: list[str] = []
    vistos: set[str] = set()
    for m in _SERVICIO_MENCION_RE.finditer(texto or ''):
        nombre = re.sub(r'\s+', ' ', (m.group(1) or '').strip())
        if not nombre:
            continue
        if re.match(r'^filtro\s+de\s+', nombre, re.IGNORECASE):
            nombre = 'Cambio de ' + nombre[0].lower() + nombre[1:]
        if not nombre:
            continue
        nombre = nombre[0].upper() + nombre[1:]
        clave = _clave_servicio_dedup(nombre)
        if clave and clave not in vistos:
            vistos.add(clave)
            out.append(nombre)
    return out


def _patente_de_datos(datos: dict) -> str:
    from mecanimovilapp.apps.agente_ia.services.contexto_patente import normalizar_patente

    veh = (datos or {}).get('vehiculo') or {}
    if not isinstance(veh, dict):
        veh = {}
    return normalizar_patente(
        (veh.get('patente') or '') or ((datos or {}).get('patente_enriquecida') or '')
    )


def _cambio_vehiculo_capturado(previos: dict, datos: dict) -> bool:
    p0, p1 = _patente_de_datos(previos or {}), _patente_de_datos(datos or {})
    if p0 and p1 and p0 != p1:
        return True
    v0 = (previos or {}).get('vehiculo') or {}
    v1 = (datos or {}).get('vehiculo') or {}
    if not isinstance(v0, dict):
        v0 = {}
    if not isinstance(v1, dict):
        v1 = {}
    m0, mo0 = v0.get('marca'), v0.get('modelo')
    m1, mo1 = v1.get('marca'), v1.get('modelo')
    if m0 and mo0 and m1 and mo1:
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.vehiculo_exacto import (
            vehiculo_historial_identico,
        )

        if not vehiculo_historial_identico(m0, mo0, m1, mo1):
            return True
    return False


def _aplicar_poda_servicios(datos: dict, texto_cliente: str) -> dict:
    datos = dict(datos or {})
    lista = list(datos.get('servicios') or [])
    if not lista:
        return datos
    texto = texto_cliente or ''
    texto_plano = _sin_tildes(texto)

    solo = _SOLO_SERVICIO_RE.search(texto_plano) or _SOLO_SERVICIO_RE.search(texto)
    if solo:
        keep_nombres = _extraer_servicios_mencionados_en_texto(solo.group(1) or '')
        if keep_nombres:
            keep_claves = {_clave_servicio_dedup(n) for n in keep_nombres}
            lista = [n for n in lista if _clave_servicio_dedup(str(n)) in keep_claves]
            datos['servicios'] = lista
            if lista:
                datos['servicio_nombre'] = lista[0] if len(lista) == 1 else ' + '.join(
                    str(x) for x in lista
                )
            return datos

    if _cliente_pide_quitar_de_cotizacion(texto):
        quitar = _extraer_servicios_mencionados_en_texto(texto)
        if quitar:
            quitar_claves = {_clave_servicio_dedup(n) for n in quitar}
            lista = [n for n in lista if _clave_servicio_dedup(str(n)) not in quitar_claves]
            datos['servicios'] = lista
            if lista:
                datos['servicio_nombre'] = lista[0] if len(lista) == 1 else ' + '.join(
                    str(x) for x in lista
                )
            else:
                datos['servicio_nombre'] = ''
    return datos


def _acotar_servicios_al_pedido(
    *,
    previos: dict,
    datos: dict,
    texto_cliente: str,
) -> dict:
    datos = dict(datos or {})
    previos = previos or {}
    if _cambio_vehiculo_capturado(previos, datos):
        menciones = _extraer_servicios_mencionados_en_texto(texto_cliente)
        sn = (datos.get('servicio_nombre') or '').strip()
        datos['servicios'] = menciones or ([sn] if sn else [])
        if datos['servicios'] and not sn:
            datos['servicio_nombre'] = datos['servicios'][0]
        return datos

    datos = _aplicar_poda_servicios(datos, texto_cliente)
    prev_servicios = list(previos.get('servicios') or [])
    add = _cliente_pide_agregar_a_cotizacion(texto_cliente)
    quitar = _cliente_pide_quitar_de_cotizacion(texto_cliente) or bool(
        _SOLO_SERVICIO_RE.search(_sin_tildes(texto_cliente))
        or _SOLO_SERVICIO_RE.search(texto_cliente or '')
    )
    pide_cotizar = bool(_CLIENTE_PIDE_PRECIO_RE.search(_sin_tildes(texto_cliente))) and not (
        _cliente_niega_pedir_precio(texto_cliente)
    )
    if add or (pide_cotizar and _extraer_servicios_mencionados_en_texto(texto_cliente)):
        menciones = _extraer_servicios_mencionados_en_texto(texto_cliente)
        lista = list(datos.get('servicios') or [])
        vistos = {_clave_servicio_dedup(str(x)) for x in lista if x}
        for nombre in menciones:
            clave = _clave_servicio_dedup(nombre)
            if nombre and clave and clave not in vistos:
                lista.append(nombre)
                vistos.add(clave)
        if lista:
            datos['servicios'] = lista
        return datos
    if not add and not quitar and prev_servicios:
        datos['servicios'] = prev_servicios
        prev_sn = (previos.get('servicio_nombre') or '').strip()
        if prev_sn:
            datos['servicio_nombre'] = prev_sn
    return datos
