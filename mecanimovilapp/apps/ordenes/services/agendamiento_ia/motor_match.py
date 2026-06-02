"""
Matching de hasta 3 candidatos desde OfertaServicio (stateless).
Incluye talleres y mecánicos a domicilio según distancia, marca, servicio y catálogo completo.
"""
from __future__ import annotations

import logging
import math
import re
from functools import lru_cache
from typing import Any

from django.contrib.gis.geos import Point
from django.db.models import Q

from mecanimovilapp.apps.personalizacion.ml_engine import MotorRecomendaciones
from mecanimovilapp.apps.servicios.models import OfertaServicio
from mecanimovilapp.apps.usuarios.models import ChileanCommune, MechanicServiceArea
from mecanimovilapp.apps.vehiculos.models import Vehiculo
from mecanimovilapp.storage.utils import get_image_url

logger = logging.getLogger(__name__)

MAX_CANDIDATOS = 3
MAX_OTROS_CANDIDATOS = 10
# Mismo radar que explore/home (100 m – 5 km desde la dirección del servicio).
MAX_RADIO_KM = 5.0
# Por debajo de este score_match el proveedor va a «otros» (coincidencia parcial).
_SCORE_UMBRAL_COINCIDENCIA_PARCIAL = 0.52
_DISTANCIA_SIN_UBICACION_KM = 999.0
_RE_COMUNA_INVALIDA = re.compile(r'\d{3,}')


def _safe_float(value, default: float = 0.0) -> float:
    """Evita NaN/Inf que rompen la serialización JSON de DRF."""
    try:
        n = float(value if value is not None else default)
    except (TypeError, ValueError):
        return default
    if math.isnan(n) or math.isinf(n):
        return default
    return n


def _looks_like_lat_chile(value: float) -> bool:
    return 17.0 <= abs(value) <= 56.0


def _looks_like_lng_chile(value: float) -> bool:
    return 64.0 <= abs(value) <= 76.0


def _en_rango_chile(lat: float, lng: float) -> bool:
    return -56.0 <= lat <= -17.0 and -80.0 <= lng <= -66.0


def _normalizar_lat_lng_chile(lat: float, lng: float) -> tuple[float, float] | None:
    """Valida lat/lng en Chile; solo intercambia si el par semántico está invertido."""
    try:
        la = float(lat)
        lo = float(lng)
    except (TypeError, ValueError):
        return None
    if abs(la) > 90 or abs(lo) > 180:
        return None

    if _looks_like_lat_chile(lo) and _looks_like_lng_chile(la) and not _en_rango_chile(la, lo):
        la, lo = lo, la

    if la > 0 and lo < 0:
        la = -abs(la)
    if lo > 0 and la < 0:
        lo = -abs(lo)

    if not _en_rango_chile(la, lo):
        return None
    return la, lo


def _punto_servicio(lat: float, lng: float) -> Point:
    normalizado = _normalizar_lat_lng_chile(lat, lng)
    if not normalizado:
        raise ValueError('coordenadas fuera de rango')
    lat_n, lng_n = normalizado
    return Point(float(lng_n), float(lat_n), srid=4326)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia geodésica en km (misma base que endpoints `cerca` con spheroid)."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return 6371.0 * c


def _ubicacion_proveedor(proveedor) -> Any:
    """Solo ubicación del taller/mecánico (no usuario: suele coincidir con el cliente y da 0 km)."""
    if not proveedor:
        return None
    return getattr(proveedor, 'ubicacion', None)


def _distancia_geodesica_km(punto: Point, ubic: Any) -> float | None:
    """Distancia en km (PostGIS/geography en metros; fallback haversine)."""
    try:
        dist = punto.distance(ubic)
        if dist is not None:
            if hasattr(dist, 'km'):
                km = float(dist.km)
            elif hasattr(dist, 'm'):
                km = float(dist.m) / 1000.0
            else:
                km = float(dist) / 1000.0
            if km >= 0 and not math.isnan(km) and not math.isinf(km):
                return km
    except Exception:
        pass
    try:
        km = _haversine_km(float(punto.y), float(punto.x), float(ubic.y), float(ubic.x))
        if km >= 0 and not math.isnan(km) and not math.isinf(km):
            return km
    except Exception:
        pass
    return None


def _format_distancia_km_api(dist_km: float | None) -> float | None:
    if dist_km is None or dist_km >= _DISTANCIA_SIN_UBICACION_KM:
        return None
    if dist_km < 0.05:
        return round(dist_km, 2)
    return round(dist_km, 1)


def _distancia_km_proveedor(oferta: OfertaServicio, punto: Point) -> float | None:
    proveedor = oferta.taller if oferta.tipo_proveedor == 'taller' else oferta.mecanico
    if not proveedor:
        return None
    try:
        ubic = _ubicacion_proveedor(proveedor)
        if ubic is None:
            return None
        return _distancia_geodesica_km(punto, ubic)
    except Exception:
        logger.debug('No se pudo calcular distancia proveedor', exc_info=True)
        return None


def _oferta_ofrece_repuestos(oferta: OfertaServicio) -> bool:
    """
    Catálogo con repuestos configurados (no basta precio_con == precio_sin legacy).
    """
    if not oferta or not oferta.disponible:
        return False
    if getattr(oferta, 'tipo_servicio', None) == 'sin_repuestos':
        return False
    if _safe_float(oferta.costo_repuestos_sin_iva) > 0:
        return True
    precio_rep = _safe_float(oferta.precio_con_repuestos)
    precio_sin = _safe_float(oferta.precio_sin_repuestos)
    if precio_rep > 0 and precio_sin > 0 and precio_rep > precio_sin * 1.005:
        return True
    repuestos_json = getattr(oferta, 'repuestos_seleccionados', None)
    if isinstance(repuestos_json, list) and len(repuestos_json) > 0:
        return True
    return False


def _oferta_ofrece_solo_mano_obra(oferta: OfertaServicio) -> bool:
    if not oferta or not oferta.disponible:
        return False
    if _safe_float(oferta.precio_sin_repuestos) > 0:
        return True
    precio_pub = _safe_float(oferta.precio_publicado_cliente)
    return precio_pub > 0


def _oferta_catalogo_completa(oferta: OfertaServicio, *, requiere_repuestos: bool) -> bool:
    """Catálogo con precio publicado (misma lógica práctica que listados de servicios)."""
    if not oferta.disponible:
        return False
    if requiere_repuestos:
        return _oferta_ofrece_repuestos(oferta) or _oferta_ofrece_solo_mano_obra(oferta)
    return _oferta_ofrece_solo_mano_obra(oferta)


def _ajustar_score_match_repuestos(
    score: float,
    oferta: OfertaServicio,
    *,
    requiere_repuestos_solicitud: bool,
) -> tuple[float, str | None]:
    """Prioriza match con repuestos en catálogo cuando el cliente los solicitó."""
    if not requiere_repuestos_solicitud:
        return score, None
    if _oferta_ofrece_repuestos(oferta):
        return min(0.99, _safe_float(score) * 1.12 + 0.04), None
    return max(0.08, _safe_float(score) * 0.78), ' · Solo mano de obra en catálogo'


def _modo_desglose_oferta(oferta: OfertaServicio, requiere_repuestos_solicitud: bool) -> bool:
    """True = desglose/precio con repuestos; False = solo mano de obra para mostrar."""
    if not requiere_repuestos_solicitud:
        return False
    return _oferta_ofrece_repuestos(oferta)


def _queryset_ofertas_compatibles(
    servicio_ids: list[int],
    marca,
) -> Any:
    """
    Mismo criterio que proveedores_filtrados + ofertas por servicio:
    proveedor verificado, atiende la marca, oferta disponible y marca en oferta
  o genérica (null).
    """
    base = OfertaServicio.objects.filter(
        servicio_id__in=servicio_ids,
        disponible=True,
    )
    if not marca:
        return base.filter(
            Q(taller__verificado=True, taller__activo=True)
            | Q(mecanico__verificado=True, mecanico__activo=True)
        ).distinct()

    q_marca_oferta = Q(marca_vehiculo_seleccionada=marca) | Q(
        marca_vehiculo_seleccionada__isnull=True
    )

    from mecanimovilapp.apps.usuarios.proveedor_cobertura import TIPO_COBERTURA_MULTIMARCA

    ofertas_taller = base.filter(
        tipo_proveedor='taller',
        taller__isnull=False,
        taller__marcas_atendidas=marca,
        taller__verificado=True,
        taller__activo=True,
    ).filter(q_marca_oferta)

    ofertas_mecanico = base.filter(
        tipo_proveedor='mecanico',
        mecanico__isnull=False,
        mecanico__marcas_atendidas=marca,
        mecanico__verificado=True,
        mecanico__activo=True,
    ).filter(q_marca_oferta)

    ofertas_taller_mm = base.filter(
        tipo_proveedor='taller',
        taller__isnull=False,
        taller__tipo_cobertura_marca=TIPO_COBERTURA_MULTIMARCA,
        taller__verificado=True,
        taller__activo=True,
    ).filter(q_marca_oferta)

    ofertas_mecanico_mm = base.filter(
        tipo_proveedor='mecanico',
        mecanico__isnull=False,
        mecanico__tipo_cobertura_marca=TIPO_COBERTURA_MULTIMARCA,
        mecanico__verificado=True,
        mecanico__activo=True,
    ).filter(q_marca_oferta)

    qs = (ofertas_taller | ofertas_mecanico | ofertas_taller_mm | ofertas_mecanico_mm).distinct()
    if marca:
        from mecanimovilapp.apps.servicios.oferta_resolucion import (
            resolver_ofertas_preferidas_por_marca,
        )

        ofertas_list = list(
            qs.select_related(
                'servicio',
                'taller',
                'mecanico',
                'marca_vehiculo_seleccionada',
            )
        )
        ids = [o.id for o in resolver_ofertas_preferidas_por_marca(ofertas_list, marca)]
        if not ids:
            return OfertaServicio.objects.none()
        return OfertaServicio.objects.filter(id__in=ids).select_related(
            'servicio',
            'taller',
            'mecanico',
            'marca_vehiculo_seleccionada',
        )
    return qs


def _score_y_explicacion(
    *,
    dist_km: float | None,
    rating: float,
    con_ubicacion_cliente: bool = False,
) -> tuple[float, str]:
    rating_norm = min(1.0, max(0.0, _safe_float(rating) / 5.0))
    if dist_km is not None and dist_km < _DISTANCIA_SIN_UBICACION_KM:
        dist_km = _safe_float(dist_km, default=MAX_RADIO_KM)
        proximidad = max(0.0, 1.0 - min(dist_km, MAX_RADIO_KM) / MAX_RADIO_KM)
        if con_ubicacion_cliente:
            score = min(0.99, 0.7 * proximidad + 0.22 * rating_norm + 0.08)
        else:
            score = min(0.99, 0.45 * proximidad + 0.35 * rating_norm + 0.2)
        if dist_km < 5:
            expl = f'Muy cerca de ti ({dist_km:.1f} km)'
        elif dist_km < 25:
            expl = f'A {dist_km:.1f} km de tu ubicación'
        else:
            expl = f'A ~{dist_km:.0f} km de tu ubicación'
        return score, expl
    score = min(0.99, 0.4 + 0.35 * rating_norm + 0.25)
    return score, 'Ofrece el servicio para tu vehículo y zona'


def _proveedor_usuario(oferta: OfertaServicio):
    if oferta.tipo_proveedor == 'taller' and oferta.taller_id:
        return oferta.taller.usuario_id, oferta.taller
    if oferta.tipo_proveedor == 'mecanico' and oferta.mecanico_id:
        return oferta.mecanico.usuario_id, oferta.mecanico
    return None, None


def _filtrar_comunas_validas(comunas: list[str] | None) -> list[str]:
    """Descarta calles u otros textos que no son nombre de comuna."""
    if not comunas:
        return []
    validas: list[str] = []
    for raw in comunas:
        c = (raw or '').strip()
        if len(c) < 3 or len(c) > 50:
            continue
        if _RE_COMUNA_INVALIDA.search(c):
            continue
        if any(ch.isdigit() for ch in c):
            continue
        validas.append(c)
    return validas


@lru_cache(maxsize=1)
def _nombres_comunas_chile() -> tuple[str, ...]:
    """Nombres activos, más largos primero (evita falsos positivos por subcadenas)."""
    try:
        nombres = list(
            ChileanCommune.objects.filter(is_active=True).values_list('name', flat=True)
        )
    except Exception:
        logger.warning('No se pudo cargar ChileanCommune', exc_info=True)
        return ()
    limpios = sorted(
        {(n or '').strip() for n in nombres if n and len((n or '').strip()) >= 3},
        key=len,
        reverse=True,
    )
    return tuple(limpios)


def _inferir_comunas_desde_direccion(direccion_texto: str | None) -> list[str]:
    """Busca nombres de comunas chilenas dentro del texto de la dirección."""
    texto = (direccion_texto or '').strip()
    if len(texto) < 4:
        return []
    texto_low = texto.lower()
    encontradas: list[str] = []
    for nombre in _nombres_comunas_chile():
        if nombre.lower() in texto_low:
            encontradas.append(nombre)
            if len(encontradas) >= 4:
                break
    return encontradas


def _resolver_comunas(comunas_extraidas: list[str] | None, direccion_texto: str | None) -> list[str]:
    comunas = _filtrar_comunas_validas(comunas_extraidas)
    if comunas:
        return comunas
    return _inferir_comunas_desde_direccion(direccion_texto)


def _mecanico_cubre_comunas(mecanico_id: int, comunas: list[str]) -> bool:
    if not comunas:
        return False
    comunas_norm = [c.strip().lower() for c in comunas if c and str(c).strip()]
    if not comunas_norm:
        return False
    areas = MechanicServiceArea.objects.filter(
        mechanic_id=mecanico_id,
        is_active=True,
    )
    for area in areas:
        names = area.commune_names or []
        for name in names:
            n_low = str(name).strip().lower()
            if not n_low:
                continue
            for comuna in comunas_norm:
                if comuna == n_low or comuna in n_low or n_low in comuna:
                    return True
    return False


def _mecanico_prioridad_zona(
    oferta: OfertaServicio,
    *,
    comunas: list[str],
    punto: Point | None,
) -> tuple[bool, float | None]:
    """
    No excluye por zona (como proveedores_filtrados); devuelve si cubre comuna y distancia
    para priorizar en el score.
    """
    dist_km = _distancia_km_proveedor(oferta, punto) if punto else None
    cubre = bool(comunas and _mecanico_cubre_comunas(oferta.mecanico_id, comunas))
    return cubre, dist_km


def _construir_pool_meta(
    qs,
    *,
    punto: Point | None,
    requiere_repuestos: bool,
    exigir_precio: bool,
    comunas: list[str],
) -> tuple[list[tuple[OfertaServicio, float | None, float, str]], dict[str, int]]:
    pool_meta: list[tuple[OfertaServicio, float | None, float, str]] = []
    stats = {'evaluadas': 0, 'sin_precio': 0, 'sin_proveedor': 0, 'errores': 0}

    for oferta in qs:
        stats['evaluadas'] += 1
        try:
            if exigir_precio and not _oferta_catalogo_completa(
                oferta, requiere_repuestos=requiere_repuestos
            ):
                stats['sin_precio'] += 1
                continue

            proveedor_pool = oferta.taller or oferta.mecanico
            if not proveedor_pool:
                stats['sin_proveedor'] += 1
                continue

            dist_km = _distancia_km_proveedor(oferta, punto) if punto else None
            if oferta.tipo_proveedor == 'mecanico' and oferta.mecanico_id:
                _cubre, dist_m = _mecanico_prioridad_zona(
                    oferta, comunas=comunas, punto=punto
                )
                if dist_m is not None:
                    dist_km = dist_m

            rating = _safe_float(getattr(proveedor_pool, 'calificacion_promedio', 0))
            score, expl = _score_y_explicacion(
                dist_km=dist_km,
                rating=rating,
                con_ubicacion_cliente=bool(punto),
            )
            score, sufijo_rep = _ajustar_score_match_repuestos(
                score,
                oferta,
                requiere_repuestos_solicitud=requiere_repuestos,
            )
            if sufijo_rep and sufijo_rep not in expl:
                expl = f'{expl}{sufijo_rep}'
            if not exigir_precio and not _oferta_catalogo_completa(
                oferta, requiere_repuestos=requiere_repuestos
            ):
                expl = 'Precio del catálogo pendiente de configurar'
            pool_meta.append((oferta, dist_km, _safe_float(score), expl))
        except Exception:
            stats['errores'] += 1
            logger.warning(
                'Omitiendo oferta %s por error al evaluar candidato',
                getattr(oferta, 'id', '?'),
                exc_info=True,
            )

    return pool_meta, stats


def _ordenar_por_distancia_y_score(
    candidatos_con_meta: list[tuple[OfertaServicio, float | None, float, str]],
) -> list[tuple[float, OfertaServicio, str]]:
    """Prioriza dentro del radio; si faltan, completa con los más cercanos fuera del radio."""

    def sort_key(item: tuple[OfertaServicio, float | None, float, str]):
        oferta, dist_km, score, _expl = item
        en_radio = dist_km is not None and dist_km <= MAX_RADIO_KM
        dist_sort = dist_km if dist_km is not None else _DISTANCIA_SIN_UBICACION_KM
        return (0 if en_radio else 1, dist_sort, -score, oferta.id or 0)

    candidatos_con_meta.sort(key=sort_key)
    return [(score, oferta, expl) for oferta, _d, score, expl in candidatos_con_meta]


def _sort_key_candidato(cand: dict[str, Any]) -> tuple:
    dist = cand.get('distancia_km')
    return (
        dist is None,
        dist if dist is not None else _DISTANCIA_SIN_UBICACION_KM,
        -(cand.get('score_match') or 0),
    )


def _ordenar_candidatos_por_distancia(candidatos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(candidatos, key=_sort_key_candidato)


def _armar_candidatos_finales(
    scored: list[tuple[float, OfertaServicio, str]],
    *,
    requiere_repuestos: bool,
    priorizar_distancia: bool = False,
) -> list[dict[str, Any]]:
    """Hasta MAX_CANDIDATOS. Con ubicación: los más cercanos; sin ubicación: mix taller/mecánico."""
    if priorizar_distancia:
        elegidos: list[dict[str, Any]] = []
        vistos: set[int] = set()
        for score, oferta, expl in scored:
            uid, _ = _proveedor_usuario(oferta)
            if not uid or uid in vistos:
                continue
            elegidos.append(_serialize_candidato(oferta, score, expl, requiere_repuestos))
            vistos.add(uid)
            if len(elegidos) >= MAX_CANDIDATOS:
                break
        return elegidos

    por_tipo: dict[str, list[tuple[float, OfertaServicio, str, int]]] = {
        'taller': [],
        'mecanico': [],
    }
    for score, oferta, expl in scored:
        uid, _ = _proveedor_usuario(oferta)
        if not uid:
            continue
        tipo = oferta.tipo_proveedor or ''
        if tipo in por_tipo:
            por_tipo[tipo].append((score, oferta, expl, uid))

    elegidos: list[dict[str, Any]] = []
    vistos: set[int] = set()

    for tipo in ('taller', 'mecanico'):
        for score, oferta, expl, uid in por_tipo[tipo]:
            if uid in vistos:
                continue
            elegidos.append(_serialize_candidato(oferta, score, expl, requiere_repuestos))
            vistos.add(uid)
            break

    for score, oferta, expl in scored:
        uid, _ = _proveedor_usuario(oferta)
        if not uid or uid in vistos:
            continue
        elegidos.append(_serialize_candidato(oferta, score, expl, requiere_repuestos))
        vistos.add(uid)
        if len(elegidos) >= MAX_CANDIDATOS:
            break

    return elegidos


def _mejor_oferta_por_proveedor(
    pool_meta: list[tuple[OfertaServicio, float | None, float, str]],
) -> list[tuple[OfertaServicio, float | None, float, str]]:
    """Una oferta por usuario proveedor (la de mayor score_match)."""
    por_uid: dict[int, tuple[OfertaServicio, float | None, float, str]] = {}

    for oferta, dist_km, score, expl in pool_meta:
        uid, _ = _proveedor_usuario(oferta)
        if not uid:
            continue
        prev = por_uid.get(uid)
        if prev is None:
            por_uid[uid] = (oferta, dist_km, score, expl)
            continue
        _po, pd, ps, _ = prev
        dist_sort = dist_km if dist_km is not None else _DISTANCIA_SIN_UBICACION_KM
        prev_dist = pd if pd is not None else _DISTANCIA_SIN_UBICACION_KM
        if score > ps or (score == ps and dist_sort < prev_dist):
            por_uid[uid] = (oferta, dist_km, score, expl)

    return list(por_uid.values())


def _distancia_grupo_proveedor(
    items: list[tuple[OfertaServicio, float | None, float, str]],
) -> float | None:
    """Menor distancia del grupo (misma lógica que al serializar candidato)."""
    dists = [
        d for _, d, _, _ in items
        if d is not None and d < _DISTANCIA_SIN_UBICACION_KM
    ]
    return min(dists) if dists else None


def _dentro_radar_direccion(punto: Point | None, dist_km: float | None) -> bool:
    """En zona de la dirección: distancia conocida y ≤ MAX_RADIO_KM (5 km)."""
    if not punto:
        return True
    if dist_km is None:
        return False
    return dist_km <= MAX_RADIO_KM


def _explicacion_coincidencia_parcial(score: float, dist_km: float | None) -> str:
    pct = max(0, min(100, int(round(_safe_float(score) * 100))))
    if dist_km is not None and dist_km < _DISTANCIA_SIN_UBICACION_KM:
        return f'Mismo servicio · coincidencia parcial ({pct}%) · {dist_km:.1f} km'
    return f'Mismo servicio · coincidencia parcial ({pct}%)'


def _explicacion_fuera_radar(score: float, dist_km: float | None) -> str:
    pct = max(0, min(100, int(round(_safe_float(score) * 100))))
    if dist_km is not None and dist_km < _DISTANCIA_SIN_UBICACION_KM:
        return (
            f'Mismo servicio · fuera de tu zona ({pct}%) · {dist_km:.1f} km'
        )
    return f'Mismo servicio · fuera de tu zona ({pct}%)'


def _agrupar_ofertas_validas_por_proveedor(
    pool_meta: list[tuple[OfertaServicio, float | None, float, str]],
    *,
    requiere_repuestos: bool,
    punto: Point | None,
) -> dict[int, list[tuple[OfertaServicio, float | None, float, str]]]:
    """Todas las ofertas de catálogo válidas por usuario proveedor (no solo la mejor)."""
    por_uid: dict[int, list[tuple[OfertaServicio, float | None, float, str]]] = {}
    for oferta, dist_km, score, expl in pool_meta:
        if not _oferta_catalogo_completa(oferta, requiere_repuestos=requiere_repuestos):
            continue
        uid, _ = _proveedor_usuario(oferta)
        if not uid:
            continue
        por_uid.setdefault(uid, []).append((oferta, dist_km, score, expl))
    return por_uid


def _mejor_oferta_por_servicio_en_grupo(
    items: list[tuple[OfertaServicio, float | None, float, str]],
    servicio_ids_pedidos: list[int],
) -> list[tuple[OfertaServicio, float | None, float, str]]:
    pedidos = {int(s) for s in servicio_ids_pedidos if s is not None}
    por_servicio: dict[int, tuple[OfertaServicio, float | None, float, str]] = {}
    for oferta, dist_km, score, expl in items:
        sid = oferta.servicio_id
        if sid is None or sid not in pedidos:
            continue
        prev = por_servicio.get(sid)
        if prev is None or score > prev[2]:
            por_servicio[sid] = (oferta, dist_km, score, expl)
    return list(por_servicio.values())


def _serialize_candidato_proveedor(
    items: list[tuple[OfertaServicio, float | None, float, str]],
    servicio_ids_pedidos: list[int],
    requiere_repuestos: bool,
    *,
    es_coincidencia_exacta: bool,
    request=None,
    explicacion_override: str | None = None,
) -> dict[str, Any] | None:
    """Un candidato por proveedor con N servicios del pedido y precio total sumado."""
    seleccionados = _mejor_oferta_por_servicio_en_grupo(items, servicio_ids_pedidos)
    if not seleccionados:
        return None

    pedidos_count = len({int(s) for s in servicio_ids_pedidos if s is not None}) or 1
    servicios_ofrecidos: list[dict[str, Any]] = []
    mo_total = rep_total = gest_total = 0.0
    precio_total = 0.0
    oferta_ids: list[int] = []

    for oferta, _dist, _score, _expl in sorted(
        seleccionados, key=lambda x: (x[0].servicio_id or 0, -x[2])
    ):
        modo_desglose = _modo_desglose_oferta(oferta, requiere_repuestos)
        d = _build_desglose(oferta, modo_desglose)
        precio_item = _safe_float(d['precio_publicado_cliente'])
        servicio = getattr(oferta, 'servicio', None)
        servicios_ofrecidos.append({
            'id': oferta.servicio_id,
            'nombre': getattr(servicio, 'nombre', '') if servicio else '',
            'precio': precio_item,
            'oferta_servicio_id': oferta.id,
            'desglose': d,
        })
        mo_total += _safe_float(d['mano_obra'])
        rep_total += _safe_float(d['repuestos'])
        gest_total += _safe_float(d['gestion'])
        precio_total += precio_item
        oferta_ids.append(int(oferta.id))

    coberturas = len(servicios_ofrecidos)
    cobertura_pct = coberturas / pedidos_count if pedidos_count else 0.0

    oferta_rep, dist_km_rep, score_base, expl_rep = max(seleccionados, key=lambda x: x[2])
    score_ajustado = min(0.99, _safe_float(score_base) * (0.6 + 0.4 * cobertura_pct))

    explicacion = explicacion_override or expl_rep
    if explicacion_override is None and coberturas < pedidos_count:
        explicacion = (
            f'{expl_rep} · Cubre {coberturas}/{pedidos_count} servicios solicitados'
        )

    base = _serialize_candidato(
        oferta_rep,
        score_ajustado,
        explicacion,
        requiere_repuestos,
        dist_km=dist_km_rep,
        es_coincidencia_exacta=es_coincidencia_exacta,
        request=request,
    )
    base['servicios_ofrecidos'] = servicios_ofrecidos
    base['servicios_cubiertos'] = coberturas
    base['servicios_pedidos'] = pedidos_count
    base['cobertura_pct'] = round(cobertura_pct, 3)
    base['precio_total'] = round(precio_total)
    base['oferta_servicio_ids'] = oferta_ids
    base['desglose'] = {
        'mano_obra': mo_total,
        'repuestos': rep_total,
        'gestion': gest_total,
        'precio_publicado_cliente': precio_total,
        'catalogo_completo': True,
    }
    ofrece_rep_grupo = bool(seleccionados) and all(
        _oferta_ofrece_repuestos(o) for o, _, _, _ in seleccionados
    )
    base['ofrece_repuestos'] = ofrece_rep_grupo
    base['ofrece_solo_mano_obra'] = any(
        _oferta_ofrece_solo_mano_obra(o) for o, _, _, _ in seleccionados
    )
    base['solicitud_requiere_repuestos'] = requiere_repuestos
    rep_sum = sum(
        _safe_float(o.precio_con_repuestos)
        for o, _, _, _ in seleccionados
        if _oferta_ofrece_repuestos(o)
    )
    sin_sum = sum(_safe_float(o.precio_sin_repuestos) for o, _, _, _ in seleccionados)
    base['precio_total'] = round(precio_total)
    if ofrece_rep_grupo and rep_sum > 0:
        base['precio_con_repuestos'] = round(rep_sum if rep_sum > 0 else precio_total)
    elif rep_sum > 0:
        base['precio_con_repuestos'] = round(rep_sum)
    if sin_sum > 0:
        base['precio_sin_repuestos'] = round(sin_sum)
    elif not ofrece_rep_grupo:
        base['precio_sin_repuestos'] = round(precio_total)
    base['tipo_servicio_catalogo'] = (
        'con_repuestos' if ofrece_rep_grupo else 'sin_repuestos'
    )
    base['coincidencia_repuestos'] = (
        'con_repuestos' if ofrece_rep_grupo else 'solo_mano_obra_alternativa'
    )
    if len(servicios_ofrecidos) > 1:
        nombres = [s['nombre'] for s in servicios_ofrecidos if s.get('nombre')]
        base['servicio'] = {
            'id': servicios_ofrecidos[0]['id'],
            'nombre': ' · '.join(nombres) if nombres else base['servicio']['nombre'],
        }
    return base


def _clasificar_recomendados_y_otros(
    pool_meta: list[tuple[OfertaServicio, float | None, float, str]],
    *,
    servicio_ids_pedidos: list[int],
    requiere_repuestos: bool,
    punto: Point | None,
    request=None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Coincidencia exacta: mejores proveedores dentro del radar (≤ MAX_RADIO_KM) desde la dirección.
    Otros: coincidencia parcial en zona o compatibles fuera del radar de la dirección.
    """
    por_uid = _agrupar_ofertas_validas_por_proveedor(
        pool_meta, requiere_repuestos=requiere_repuestos, punto=punto
    )

    grupos_ranked: list[tuple[int, list, dict[str, Any]]] = []
    for uid, items in por_uid.items():
        cand = _serialize_candidato_proveedor(
            items,
            servicio_ids_pedidos,
            requiere_repuestos,
            es_coincidencia_exacta=True,
            request=request,
        )
        if cand:
            grupos_ranked.append((uid, items, cand))

    def sort_grupo(g):
        _uid, _items, cand = g
        score = _safe_float(cand.get('score_match'))
        dist = cand.get('distancia_km')
        dist_sort = dist if dist is not None else _DISTANCIA_SIN_UBICACION_KM
        rep_prio = 0
        if requiere_repuestos:
            rep_prio = 0 if cand.get('ofrece_repuestos') else 1
        if punto:
            return (rep_prio, -score, dist_sort)
        return (rep_prio, -score)

    grupos_ranked.sort(key=sort_grupo)

    recomendados: list[dict[str, Any]] = []
    otros: list[dict[str, Any]] = []

    for uid, items, cand in grupos_ranked:
        if len(recomendados) >= MAX_CANDIDATOS:
            break
        best_score = _safe_float(cand.get('score_match'))
        if best_score < _SCORE_UMBRAL_COINCIDENCIA_PARCIAL and len(recomendados) > 0:
            break
        dist_grupo = _distancia_grupo_proveedor(items)
        if not _dentro_radar_direccion(punto, dist_grupo):
            continue
        recomendados.append(cand)

    uids_exacta = _usuario_ids_en_candidatos(recomendados)

    for uid, items, cand in grupos_ranked:
        if uid in uids_exacta:
            continue
        best_score = _safe_float(cand.get('score_match'))
        dist_grupo = _distancia_grupo_proveedor(items)
        fuera_radar = bool(punto) and not _dentro_radar_direccion(punto, dist_grupo)
        expl_override = (
            _explicacion_fuera_radar(best_score, dist_grupo)
            if fuera_radar
            else _explicacion_coincidencia_parcial(best_score, dist_grupo)
        )
        otro = _serialize_candidato_proveedor(
            items,
            servicio_ids_pedidos,
            requiere_repuestos,
            es_coincidencia_exacta=False,
            request=request,
            explicacion_override=expl_override,
        )
        if otro:
            otros.append(otro)
        if len(otros) >= MAX_OTROS_CANDIDATOS:
            break

    return (
        _ordenar_candidatos_priorizando_repuestos(recomendados, requiere_repuestos),
        _ordenar_candidatos_priorizando_repuestos(otros, requiere_repuestos),
    )


def _ordenar_candidatos_priorizando_repuestos(
    candidatos: list[dict[str, Any]],
    requiere_repuestos_solicitud: bool,
) -> list[dict[str, Any]]:
    if not requiere_repuestos_solicitud:
        return _ordenar_candidatos_por_distancia(candidatos)
    con_rep = [c for c in candidatos if c.get('ofrece_repuestos')]
    solo_mo = [c for c in candidatos if not c.get('ofrece_repuestos')]
    return (
        _ordenar_candidatos_por_distancia(con_rep)
        + _ordenar_candidatos_por_distancia(solo_mo)
    )


def _usuario_ids_en_candidatos(candidatos: list[dict[str, Any]]) -> set[int]:
    ids: set[int] = set()
    for cand in candidatos:
        uid = (cand.get('proveedor') or {}).get('usuario_id')
        if uid is None:
            continue
        try:
            ids.add(int(uid))
        except (TypeError, ValueError):
            continue
    return ids


def _gestion_catalogo_sin_iva(oferta: OfertaServicio) -> float:
    """OfertaServicio no tiene gestión de compra; solo OfertaProveedor la usa al confirmar."""
    return _safe_float(getattr(oferta, 'costo_gestion_compra_sin_iva', None))


def _build_desglose(oferta: OfertaServicio, con_repuestos_en_desglose: bool) -> dict[str, Any]:
    mo = _safe_float(oferta.costo_mano_de_obra_sin_iva)
    rep = _safe_float(oferta.costo_repuestos_sin_iva) if con_repuestos_en_desglose else 0.0
    gest = _gestion_catalogo_sin_iva(oferta) if con_repuestos_en_desglose else 0.0
    total = _safe_float(oferta.precio_publicado_cliente)
    if total <= 0:
        total = _safe_float(
            oferta.precio_con_repuestos
            if con_repuestos_en_desglose
            else oferta.precio_sin_repuestos
        )
    completo = _oferta_catalogo_completa(
        oferta,
        requiere_repuestos=con_repuestos_en_desglose,
    )
    return {
        'mano_obra': mo,
        'repuestos': rep,
        'gestion': gest,
        'precio_publicado_cliente': total,
        'catalogo_completo': completo,
    }


def _foto_url_proveedor(proveedor, request=None) -> str | None:
    if not proveedor:
        return None
    url = get_image_url(getattr(proveedor, 'foto_perfil', None), request)
    if url:
        return url
    usuario = getattr(proveedor, 'usuario', None)
    if usuario:
        return get_image_url(getattr(usuario, 'foto_perfil', None), request)
    return None


def _serialize_candidato(
    oferta: OfertaServicio,
    score: float,
    explicacion: str,
    requiere_repuestos: bool,
    *,
    dist_km: float | None = None,
    es_coincidencia_exacta: bool = True,
    request=None,
) -> dict[str, Any]:
    usuario_id, proveedor = _proveedor_usuario(oferta)
    nombre = ''
    rating = 0.0
    a_domicilio = oferta.tipo_proveedor == 'mecanico'
    foto_url = None
    lat_proveedor = None
    lng_proveedor = None

    tipo_cobertura_marca = None
    if proveedor:
        nombre = getattr(proveedor, 'nombre', None) or str(proveedor)
        rating = _safe_float(getattr(proveedor, 'calificacion_promedio', 0))
        tipo_cobertura_marca = getattr(proveedor, 'tipo_cobertura_marca', None)
        foto_url = _foto_url_proveedor(proveedor, request)
        ubic = _ubicacion_proveedor(proveedor)
        if ubic is not None:
            try:
                lat_proveedor = float(ubic.y)
                lng_proveedor = float(ubic.x)
            except (TypeError, ValueError):
                lat_proveedor = None
                lng_proveedor = None

    precio_rep = _safe_float(oferta.precio_con_repuestos)
    precio_sin = _safe_float(oferta.precio_sin_repuestos)
    servicio = getattr(oferta, 'servicio', None)
    nombre_servicio = getattr(servicio, 'nombre', '') if servicio else ''
    modo_desglose = _modo_desglose_oferta(oferta, requiere_repuestos)
    desglose = _build_desglose(oferta, modo_desglose)
    score_safe = _safe_float(score)

    return {
        'oferta_servicio_id': oferta.id,
        'proveedor': {
            'usuario_id': str(usuario_id) if usuario_id else None,
            'proveedor_id': oferta.taller_id or oferta.mecanico_id,
            'nombre': nombre,
            'tipo': oferta.tipo_proveedor,
            'rating': rating,
            'tipo_cobertura_marca': tipo_cobertura_marca,
            'foto_perfil': foto_url,
            'foto_perfil_url': foto_url,
            'lat': lat_proveedor,
            'lng': lng_proveedor,
        },
        'tipo_cobertura_marca': tipo_cobertura_marca,
        'servicio': {
            'id': oferta.servicio_id,
            'nombre': nombre_servicio,
        },
        'precio_con_repuestos': precio_rep,
        'precio_sin_repuestos': precio_sin,
        'incluye_repuestos_sugerido': requiere_repuestos,
        'solicitud_requiere_repuestos': requiere_repuestos,
        'ofrece_repuestos': _oferta_ofrece_repuestos(oferta),
        'ofrece_solo_mano_obra': _oferta_ofrece_solo_mano_obra(oferta),
        'tipo_servicio_catalogo': getattr(oferta, 'tipo_servicio', None),
        'coincidencia_repuestos': (
            'con_repuestos' if _oferta_ofrece_repuestos(oferta) else 'solo_mano_obra_alternativa'
        ),
        'a_domicilio': a_domicilio,
        'desglose': desglose,
        'distancia_km': _format_distancia_km_api(dist_km),
        'dentro_radio_km': (
            dist_km is not None and dist_km <= MAX_RADIO_KM
        ),
        'score_match': round(score_safe, 3),
        'explicacion': explicacion,
        'es_recomendado': es_coincidencia_exacta,
        'es_coincidencia_exacta': es_coincidencia_exacta,
        'nivel_coincidencia': 'exacta' if es_coincidencia_exacta else 'parcial',
    }


def listar_candidatos_proveedor(
    *,
    vehiculo_id: int,
    servicio_ids: list[int],
    requiere_repuestos: bool = True,
    comunas_extraidas: list[str] | None = None,
    direccion_texto: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    request=None,
) -> dict[str, Any]:
    """Stateless: no persiste consulta."""
    vehiculo = (
        Vehiculo.objects.select_related('marca', 'modelo')
        .filter(pk=vehiculo_id)
        .first()
    )
    if not vehiculo:
        return {'candidatos': [], 'error': 'vehiculo_no_encontrado'}

    if not servicio_ids:
        return {'candidatos': []}

    marca = vehiculo.marca
    qs = (
        _queryset_ofertas_compatibles(servicio_ids, marca)
        .select_related(
            'servicio',
            'taller',
            'taller__usuario',
            'mecanico',
            'mecanico__usuario',
        )
        .prefetch_related('taller__marcas_atendidas', 'mecanico__marcas_atendidas')
    )

    comunas = _resolver_comunas(comunas_extraidas, direccion_texto)
    punto = None
    if lat is not None and lng is not None:
        try:
            punto = _punto_servicio(lat, lng)
        except (TypeError, ValueError):
            punto = None

    count_qs = qs.count()
    pool_meta, stats = _construir_pool_meta(
        qs,
        punto=punto,
        requiere_repuestos=requiere_repuestos,
        exigir_precio=True,
        comunas=comunas,
    )
    uso_fallback_precio = False
    if not pool_meta and count_qs > 0:
        pool_meta, stats = _construir_pool_meta(
            qs,
            punto=punto,
            requiere_repuestos=requiere_repuestos,
            exigir_precio=False,
            comunas=comunas,
        )
        uso_fallback_precio = bool(pool_meta)

    if not pool_meta:
        logger.info(
            'candidatos-proveedor vacío: vehiculo=%s servicios=%s ofertas_qs=%s stats=%s comunas=%s',
            vehiculo_id,
            servicio_ids,
            count_qs,
            stats,
            comunas,
        )
        return {
            'candidatos': [],
            'ordenado_por_distancia': bool(punto),
            'comunas_resueltas': comunas,
            'requiere_repuestos': requiere_repuestos,
            'radio_km': MAX_RADIO_KM,
            'diagnostico': {
                'ofertas_en_queryset': count_qs,
                'marca_id': marca.pk if marca else None,
                **stats,
            },
        }

    if not punto:
        ids = [o.id for o, _, _, _ in pool_meta]
        try:
            motor = MotorRecomendaciones()
            ordered = motor.ordenar_por_relevancia(
                OfertaServicio.objects.filter(id__in=ids).select_related(
                    'servicio', 'taller', 'mecanico', 'taller__usuario', 'mecanico__usuario'
                ),
                vehiculo,
            )
            orden_ids = [o.id for o in (ordered if isinstance(ordered, list) else list(ordered))]
            pool_meta.sort(
                key=lambda item: (
                    orden_ids.index(item[0].id) if item[0].id in orden_ids else 9999,
                    -(item[2]),
                )
            )
        except Exception:
            pool_meta.sort(key=lambda item: -item[2])

    candidatos_recomendados, otros_candidatos = _clasificar_recomendados_y_otros(
        pool_meta,
        servicio_ids_pedidos=servicio_ids,
        requiere_repuestos=requiere_repuestos,
        punto=punto,
        request=request,
    )

    def _cuenta_rep(cands: list[dict[str, Any]]) -> dict[str, int]:
        con = sum(1 for c in cands if c.get('ofrece_repuestos'))
        solo = max(0, len(cands) - con)
        return {
            'con_repuestos': con,
            'solo_mano_obra': solo,
        }

    def _mensaje_repuestos(rec: dict[str, int], otros: dict[str, int]) -> str | None:
        if not requiere_repuestos:
            return None
        total_con = rec['con_repuestos'] + otros['con_repuestos']
        total_solo = rec['solo_mano_obra'] + otros['solo_mano_obra']
        if total_con == 0 and total_solo == 0:
            return None
        if total_con == 0:
            return (
                'No hay proveedores con repuestos en catálogo para este servicio. '
                f'Se muestran {total_solo} alternativa(s) solo mano de obra.'
            )
        if total_solo == 0:
            return f'{total_con} proveedor(es) con repuestos en catálogo.'
        return (
            f'{total_con} con repuestos en catálogo · '
            f'{total_solo} alternativa(s) solo mano de obra.'
        )

    rep_rec = _cuenta_rep(candidatos_recomendados)
    rep_otros = _cuenta_rep(otros_candidatos)
    mensaje_repuestos = _mensaje_repuestos(rep_rec, rep_otros)

    resultado: dict[str, Any] = {
        'candidatos': candidatos_recomendados,
        'candidatos_recomendados': candidatos_recomendados,
        'otros_candidatos': otros_candidatos,
        'ordenado_por_distancia': bool(punto),
        'requiere_repuestos': requiere_repuestos,
        'solicitud_requiere_repuestos': requiere_repuestos,
        'resumen_repuestos': {
            'solicitud_requiere_repuestos': requiere_repuestos,
            'recomendados': rep_rec,
            'otros': rep_otros,
            'mensaje': mensaje_repuestos,
        },
        'mensaje_repuestos': mensaje_repuestos,
        'comunas_resueltas': comunas,
        'radio_km': MAX_RADIO_KM,
        'diagnostico': {
            'proveedores_en_pool': len(_mejor_oferta_por_proveedor(pool_meta)),
            'coincidencia_exacta': len(candidatos_recomendados),
            'otros_proveedores': len(otros_candidatos),
        },
    }
    if uso_fallback_precio:
        resultado['aviso'] = 'Algunos precios de catálogo están pendientes de configurar'
    return resultado
