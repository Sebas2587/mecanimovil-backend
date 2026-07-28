"""Helpers compartidos de match y precio desde catálogo publicado del taller."""
from __future__ import annotations

import re
import unicodedata

from mecanimovilapp.apps.servicios.models import OfertaServicio
from mecanimovilapp.apps.servicios.oferta_compatibilidad import (
    normalizar_tipo_motor_oferta,
    oferta_compatible_con_tipo_motor,
)
from mecanimovilapp.apps.usuarios.models import Taller
from mecanimovilapp.apps.vehiculos.catalogo_resolver import normalizar_tipo_motor_vehiculo

# El agente a veces mete la modalidad dentro del nombre del servicio
# (ej. "cambio de aceite a domicilio") aunque la modalidad se guarda aparte.
# Sin esto, el match por substring falla contra el nombre real del catálogo
# ("Cambio de aceite") y el sistema cree que NO hay precio publicado.
_MODALIDAD_SUFIJO_RE = re.compile(
    r'\s*\b(?:a|en)\s+(?:el\s+)?(?:domicilio|taller|casa|local)\b.*$',
    re.IGNORECASE,
)

_STOP_TOKENS = frozenset(
    {'de', 'del', 'la', 'el', 'los', 'las', 'y', 'para', 'con', 'sin', 'a', 'e', 'un', 'una'}
)
# En packs de aceite, gasolina/diesel/bencina = tipo de motor del SKU, no "filtro de combustible".
_ENGINE_NAME_TOKENS = frozenset({'gasolina', 'diesel', 'bencina', 'motor'})
_FILTER_TYPE_TOKENS = frozenset(
    {'aire', 'polen', 'habitaculo', 'cabina', 'combustible', 'aceite'}
)


def normalizar_nombre_servicio(texto: str) -> str:
    t = unicodedata.normalize('NFKD', (texto or '').strip().lower())
    return ''.join(c for c in t if not unicodedata.combining(c))


def _sin_sufijo_modalidad(texto: str) -> str:
    """Quita coletillas de modalidad ("a domicilio", "en taller") del nombre de servicio."""
    limpio = _MODALIDAD_SUFIJO_RE.sub('', (texto or '').strip()).strip()
    return limpio or (texto or '').strip()


def _tokens_servicio(nombre_norm: str) -> set[str]:
    return {t for t in re.split(r'\s+', nombre_norm or '') if t and t not in _STOP_TOKENS}


def oferta_compatible_con_vehiculo(
    oferta: OfertaServicio,
    *,
    marca: str = '',
    modelo: str = '',
    tipo_motor: str = '',
) -> bool:
    """True si la oferta puede aplicarse al vehículo (sin conflicto de cobertura).

    Reglas:
    - Oferta sin marca/modelo/motor → cobertura general, siempre compatible.
    - Si la oferta fija marca/modelo/motor y el cliente también los tiene,
      deben coincidir (case-insensitive; motor con bencina≡gasolina).
    - Si el cliente aún no tiene marca/modelo, no se excluye (faltan datos).
    """
    om = (getattr(oferta.marca_vehiculo_seleccionada, 'nombre', '') or '').strip()
    omod = (getattr(oferta.modelo_vehiculo_seleccionado, 'nombre', '') or '').strip()
    marca_req = (marca or '').strip()
    modelo_req = (modelo or '').strip()

    if marca_req and om and om.lower() != marca_req.lower():
        return False
    if modelo_req and omod and omod.lower() != modelo_req.lower():
        return False
    if (tipo_motor or '').strip() and not oferta_compatible_con_tipo_motor(oferta, tipo_motor):
        return False
    return True


def buscar_oferta_exacta(
    *,
    taller: Taller,
    servicio_nombre: str,
    marca: str,
    modelo: str,
    tipo_motor: str = '',
) -> OfertaServicio | None:
    """Match determinístico taller + servicio + marca/modelo + motor.

    Nunca devuelve una oferta de OTRA marca/modelo/motor cuando el vehículo
    del cliente ya tiene esos datos. Solo acepta coincidencia exacta o
    cobertura general (campos vacíos en la oferta).
    """
    nombre_norm = normalizar_nombre_servicio(_sin_sufijo_modalidad(servicio_nombre))
    if not nombre_norm:
        return None
    query_tokens = _tokens_servicio(nombre_norm)

    qs = (
        OfertaServicio.objects.filter(taller=taller, disponible=True)
        .select_related('servicio', 'marca_vehiculo_seleccionada', 'modelo_vehiculo_seleccionado')
    )

    candidatas: list[OfertaServicio] = []
    for oferta in qs:
        serv_norm = normalizar_nombre_servicio(getattr(oferta.servicio, 'nombre', '') or '')
        if not serv_norm:
            continue
        serv_tokens = _tokens_servicio(serv_norm)
        # Substring clásico O overlap de tokens significativo (evita perder packs cercanos).
        substring_ok = nombre_norm in serv_norm or serv_norm in nombre_norm
        overlap = query_tokens & serv_tokens if query_tokens and serv_tokens else set()
        token_ok = bool(overlap) and (
            len(overlap) >= 2
            or (
                len(overlap) == 1
                and overlap & {'aceite', 'diagnostico', 'alineacion', 'balanceo', 'scanner'}
            )
        )
        if not substring_ok and not token_ok:
            continue
        if not oferta_compatible_con_vehiculo(
            oferta,
            marca=marca,
            modelo=modelo,
            tipo_motor=tipo_motor,
        ):
            continue
        candidatas.append(oferta)

    if not candidatas:
        return None

    def _score(oferta: OfertaServicio) -> int:
        s = 0
        om = getattr(oferta.marca_vehiculo_seleccionada, 'nombre', '') or ''
        omod = getattr(oferta.modelo_vehiculo_seleccionado, 'nombre', '') or ''
        # Preferir match exacto de cobertura sobre ofertas "todas las marcas".
        if marca and om and om.lower() == marca.lower():
            s += 4
        elif not om:
            s += 1
        if modelo and omod and omod.lower() == modelo.lower():
            s += 4
        elif not omod:
            s += 1
        tm = normalizar_tipo_motor_oferta(getattr(oferta, 'tipo_motor', None))
        tm_req = normalizar_tipo_motor_vehiculo(tipo_motor) if tipo_motor else ''
        if tm_req and tm and tm == tm_req:
            s += 2
        elif not tm:
            s += 1
        serv_norm = normalizar_nombre_servicio(oferta.servicio.nombre)
        serv_tokens = _tokens_servicio(serv_norm)
        if serv_norm == nombre_norm:
            s += 5
        if query_tokens and serv_tokens:
            union = query_tokens | serv_tokens
            jaccard = len(query_tokens & serv_tokens) / len(union) if union else 0
            s += int(round(jaccard * 6))
        # Pack aceite+filtro: preferir SKU que tenga ambos si el cliente pidió ambos.
        if 'aceite' in query_tokens and 'filtro' in query_tokens:
            if 'aceite' in serv_tokens and 'filtro' in serv_tokens:
                s += 3
            elif 'aceite' in serv_tokens and 'filtro' not in serv_tokens:
                s -= 1
        # No subir a "filtro de aire/polen/combustible" si el cliente no lo pidió.
        extra_filtros = (serv_tokens - query_tokens) & _FILTER_TYPE_TOKENS
        # En packs de aceite el token "aceite" del catálogo no es "extra indebido".
        if 'aceite' in query_tokens:
            extra_filtros -= {'aceite'}
        if extra_filtros:
            s -= 5
        # Sufijo de motor en el nombre del SKU (… filtro Gasolina): leve penalización
        # para preferir el nombre más corto si ambos matchean; no es filtro de combustible.
        extra_engine = (serv_tokens - query_tokens) & _ENGINE_NAME_TOKENS
        if extra_engine:
            s -= 2 if 'aceite' in query_tokens else 4
        if int(oferta.precio_con_repuestos or 0) or int(oferta.precio_sin_repuestos or 0):
            s += 2
        # Preferir nombre de catálogo más corto a igualdad de score (menos ruido "Gasolina").
        s -= min(len(serv_tokens), 6) // 3
        return s

    candidatas.sort(key=_score, reverse=True)
    mejor = candidatas[0]
    if _score(mejor) < 3:
        return None
    return mejor


def buscar_oferta_por_id(*, taller: Taller, oferta_servicio_id: int) -> OfertaServicio | None:
    return (
        OfertaServicio.objects.filter(
            pk=oferta_servicio_id,
            taller=taller,
            disponible=True,
        )
        .select_related('servicio')
        .first()
    )


def precio_publico_oferta(oferta: OfertaServicio, *, con_repuestos: bool = True) -> tuple[int, bool]:
    """Devuelve (precio al público con IVA, usó_con_repuestos)."""
    if con_repuestos and int(oferta.precio_con_repuestos or 0):
        return int(oferta.precio_con_repuestos), True
    if int(oferta.precio_sin_repuestos or 0):
        return int(oferta.precio_sin_repuestos), False
    if int(oferta.precio_con_repuestos or 0):
        return int(oferta.precio_con_repuestos), True
    mano = int(oferta.costo_mano_de_obra_sin_iva or 0)
    rep = int(oferta.costo_repuestos_sin_iva or 0)
    if mano or rep:
        base = mano + (rep if con_repuestos else 0)
        return int(round(base * 1.19)), con_repuestos and rep > 0
    return 0, con_repuestos


def linea_desde_oferta_catalogo(
    oferta: OfertaServicio,
    *,
    cantidad: int = 1,
) -> dict:
    """Construye una línea de servicio con precio de catálogo."""
    precio_cat, _ = precio_publico_oferta(oferta, con_repuestos=True)
    nombre = getattr(oferta.servicio, 'nombre', '') or 'Servicio'
    return {
        'nombre': nombre,
        'oferta_servicio_id': oferta.id,
        'precio_desde_catalogo': precio_cat > 0,
        'precio_clp': precio_cat,
        'cantidad': max(1, int(cantidad or 1)),
    }
