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
_GENERIC_TOKENS = frozenset(
    {
        'cambio',
        'cambios',
        'servicio',
        'servicios',
        'mantencion',
        'mantenimiento',
        'revision',
        'reparacion',
        'trabajo',
        'trabajos',
        'kit',
        'repuesto',
        'repuestos',
        'completo',
        'general',
        'preventivo',
        'seguro',
    }
)
# Familias de trabajo: un SKU de aceite no puede ganar un pedido de embrague
# solo porque ambos dicen "cambio" o aparece la palabra "aceite" en una lista.
_FAMILIAS_SERVICIO: tuple[frozenset[str], ...] = (
    frozenset({'embrague', 'embragues', 'clutch', 'collarin', 'collarines'}),
    frozenset({'piola', 'piolas'}),
    frozenset({'aceite', 'aceites', 'lubricante', 'lubricantes'}),
    frozenset({'freno', 'frenos', 'pastilla', 'pastillas', 'caliper'}),
    frozenset({'bujia', 'bujias', 'bobina', 'bobinas', 'encendido'}),
    frozenset({'correa', 'correas', 'tensor', 'tensores', 'distribucion'}),
    frozenset({'amortiguador', 'amortiguadores', 'suspension'}),
    frozenset({'rodamiento', 'rodamientos', 'ruleman', 'rulemanes', 'balinera'}),
    frozenset({'radiador', 'refrigerante', 'termostato'}),
    frozenset({'bateria', 'baterias', 'alternador'}),
    frozenset({'alineacion', 'balanceo'}),
    frozenset({'scanner', 'diagnostico', 'diagnosticos'}),
)
_ACEITE_MOTOR = frozenset({'motor', 'engine'})
_ACEITE_CAJA = frozenset({'caja', 'transmision', 'atf', 'diferencial'})
_OIL_PACK_TOKENS = frozenset(
    {'aceite', 'filtro', 'motor', 'gasolina', 'diesel', 'bencina'}
)
_PREFIJO_SERVICIO_RE = re.compile(
    r'^(?:servicio\s+(?:para|de)\s+|servicios?\s+:?\s*)',
    re.IGNORECASE,
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
    limpio = _MODALIDAD_SUFIJO_RE.sub('', (texto or '').strip()).strip()
    return limpio or (texto or '').strip()


def texto_servicio_canonico(texto: str) -> str:
    """Nombre comparable: minúsculas, sin modalidad ni prefijo 'servicio para'."""
    t = normalizar_nombre_servicio(_sin_sufijo_modalidad(texto))
    t = _PREFIJO_SERVICIO_RE.sub('', t).strip()
    return t or normalizar_nombre_servicio(texto)


def _tokens_servicio(nombre_norm: str) -> set[str]:
    limpio = re.sub(r'[^a-z0-9\s]', ' ', nombre_norm or '')
    return {
        t
        for t in re.split(r'\s+', limpio)
        if t and t not in _STOP_TOKENS and len(t) > 1
    }


def _familias_de(tokens: set[str]) -> set[int]:
    hits: set[int] = set()
    for i, fam in enumerate(_FAMILIAS_SERVICIO):
        if tokens & fam:
            hits.add(i)
    return hits


def _conflicto_subtipo_aceite(query_tokens: set[str], serv_tokens: set[str]) -> bool:
    """Aceite de caja ≠ aceite motor / filtro de gasolina."""
    if 'aceite' not in query_tokens and 'aceite' not in serv_tokens:
        return False
    q_caja = bool(query_tokens & _ACEITE_CAJA)
    s_caja = bool(serv_tokens & _ACEITE_CAJA)
    s_motor = bool(serv_tokens & _ACEITE_MOTOR) or bool(
        serv_tokens & {'gasolina', 'bencina', 'diesel'}
    )
    q_motor = bool(query_tokens & _ACEITE_MOTOR)
    if q_caja and not s_caja and (s_motor or 'filtro' in serv_tokens):
        return True
    if q_motor and s_caja and not s_motor:
        return True
    return False


def oferta_nombre_compatible_con_pedido(pedido: str, nombre_catalogo: str) -> bool:
    """True si el SKU del catálogo es el mismo trabajo que el texto pedido.

    Evita que 'cambio' + 'aceite' dentro de una lista (kit embrague, aceite caja,
    piola…) se tome como 'Cambio de aceite motor y filtro de gasolina'.
    """
    nombre_norm = texto_servicio_canonico(pedido)
    serv_norm = texto_servicio_canonico(nombre_catalogo)
    if not nombre_norm or not serv_norm:
        return False

    query_tokens = _tokens_servicio(nombre_norm)
    serv_tokens = _tokens_servicio(serv_norm)
    q_fam = _familias_de(query_tokens)
    s_fam = _familias_de(serv_tokens)
    if q_fam and s_fam and q_fam.isdisjoint(s_fam):
        return False
    if q_fam - s_fam:
        return False
    if _conflicto_subtipo_aceite(query_tokens, serv_tokens):
        return False

    if nombre_norm in serv_norm or serv_norm in nombre_norm:
        return True

    core_q = query_tokens - _GENERIC_TOKENS
    core_s = serv_tokens - _GENERIC_TOKENS
    overlap_core = core_q & core_s if core_q and core_s else set()
    overlap_all = query_tokens & serv_tokens if query_tokens and serv_tokens else set()

    if overlap_core:
        return True
    if len(overlap_all) == 1 and overlap_all & {
        'diagnostico',
        'alineacion',
        'balanceo',
        'scanner',
    }:
        return True
    if 'aceite' in overlap_all and core_q <= _OIL_PACK_TOKENS:
        return True
    return False


def pedido_familias_cubiertas_por_catalogos(
    pedido: str,
    nombres_catalogo: list[str],
) -> bool:
    """False si el pedido pide trabajos (embrague, piola…) que ningún SKU cubre."""
    q_fam = _familias_de(_tokens_servicio(texto_servicio_canonico(pedido)))
    if not q_fam:
        return True
    s_fam: set[int] = set()
    for nombre in nombres_catalogo:
        s_fam |= _familias_de(_tokens_servicio(texto_servicio_canonico(nombre)))
    return q_fam <= s_fam


def _familias_texto(texto: str) -> set[int]:
    return _familias_de(_tokens_servicio(texto_servicio_canonico(texto)))


def servicios_mismo_trabajo(pedido: str, candidato: str) -> bool:
    """Mismo tipo de trabajo. False si el candidato mete otro (embrague ≠ amortiguadores).

    'Cambio' no cuenta: dos 'cambio de X' distintos no son el mismo servicio.
    """
    fam_p = _familias_texto(pedido)
    fam_c = _familias_texto(candidato)
    if fam_p and fam_c:
        if fam_c - fam_p:
            return False
        if fam_p.isdisjoint(fam_c):
            return False
        return True
    return oferta_nombre_compatible_con_pedido(pedido, candidato)


def textos_tienen_trabajo_ajeno(pedido: str, textos: list[str] | None) -> bool:
    """True si algún texto trae una familia que el pedido no pidió."""
    fam_p = _familias_texto(pedido)
    if not fam_p:
        return False
    for raw in textos or []:
        fam_t = _familias_texto(str(raw or ''))
        if fam_t and fam_t.isdisjoint(fam_p):
            return True
    return False


def repuesto_compatible_con_servicios(nombre_rep: str, servicios: list[str] | None) -> bool:
    """Pieza con familia ajena (amortiguador en un embrague) no entra."""
    pedidos = [str(s).strip() for s in (servicios or []) if str(s or '').strip()]
    if not pedidos:
        return True
    fam_serv: set[int] = set()
    for s in pedidos:
        fam_serv |= _familias_texto(s)
    if not fam_serv:
        return True
    fam_r = _familias_texto(nombre_rep)
    if not fam_r:
        return True
    return bool(fam_r & fam_serv)


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
    nombre_norm = texto_servicio_canonico(servicio_nombre)
    if not nombre_norm:
        return None
    query_tokens = _tokens_servicio(nombre_norm)

    qs = (
        OfertaServicio.objects.filter(taller=taller, disponible=True)
        .select_related('servicio', 'marca_vehiculo_seleccionada', 'modelo_vehiculo_seleccionado')
    )

    candidatas: list[OfertaServicio] = []
    for oferta in qs:
        serv_nombre = getattr(oferta.servicio, 'nombre', '') or ''
        if not oferta_nombre_compatible_con_pedido(servicio_nombre, serv_nombre):
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
        serv_norm = texto_servicio_canonico(oferta.servicio.nombre)
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
