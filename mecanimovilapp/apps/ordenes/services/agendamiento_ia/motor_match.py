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

logger = logging.getLogger(__name__)

MAX_CANDIDATOS = 3
MAX_RADIO_KM = 80.0
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


def _punto_servicio(lat: float, lng: float) -> Point:
    return Point(float(lng), float(lat), srid=4326)


def _distancia_km_proveedor(oferta: OfertaServicio, punto: Point) -> float | None:
    proveedor = oferta.taller if oferta.tipo_proveedor == 'taller' else oferta.mecanico
    if not proveedor:
        return None
    try:
        ubic = getattr(proveedor, 'ubicacion', None)
        if ubic is None:
            return None
        p = punto
        if getattr(ubic, 'srid', None) and getattr(p, 'srid', None) and ubic.srid != p.srid:
            p = Point(p.x, p.y, srid=ubic.srid)
        metros = ubic.distance(p)
        if metros is None:
            return None
        km = _safe_float(metros, default=-1.0) / 1000.0
        if km < 0:
            return None
        return km
    except Exception:
        logger.debug('No se pudo calcular distancia proveedor', exc_info=True)
        return None


def _oferta_catalogo_completa(oferta: OfertaServicio, *, requiere_repuestos: bool) -> bool:
    """Catálogo con precio publicado (misma lógica práctica que listados de servicios)."""
    if not oferta.disponible:
        return False
    precio_pub = _safe_float(oferta.precio_publicado_cliente)
    precio_rep = _safe_float(oferta.precio_con_repuestos)
    precio_sin = _safe_float(oferta.precio_sin_repuestos)
    if requiere_repuestos:
        return max(precio_pub, precio_rep, precio_sin) > 0
    return max(precio_pub, precio_sin) > 0


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

    return (ofertas_taller | ofertas_mecanico).distinct()


def _score_y_explicacion(
    *,
    dist_km: float | None,
    rating: float,
) -> tuple[float, str]:
    rating_norm = min(1.0, max(0.0, _safe_float(rating) / 5.0))
    if dist_km is not None and dist_km < _DISTANCIA_SIN_UBICACION_KM:
        dist_km = _safe_float(dist_km, default=MAX_RADIO_KM)
        proximidad = max(0.0, 1.0 - min(dist_km, MAX_RADIO_KM) / MAX_RADIO_KM)
        score = min(0.99, 0.45 * proximidad + 0.35 * rating_norm + 0.2)
        if dist_km < 5:
            expl = f'Muy cerca de ti ({dist_km:.1f} km)'
        elif dist_km < 25:
            expl = f'A {dist_km:.0f} km de tu ubicación'
        else:
            expl = f'Disponible a ~{dist_km:.0f} km'
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
            score, expl = _score_y_explicacion(dist_km=dist_km, rating=rating)
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


def _armar_candidatos_finales(
    scored: list[tuple[float, OfertaServicio, str]],
    *,
    requiere_repuestos: bool,
) -> list[dict[str, Any]]:
    """Hasta MAX_CANDIDATOS, priorizando al menos un taller y un mecánico si existen."""
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


def _gestion_catalogo_sin_iva(oferta: OfertaServicio) -> float:
    """OfertaServicio no tiene gestión de compra; solo OfertaProveedor la usa al confirmar."""
    return _safe_float(getattr(oferta, 'costo_gestion_compra_sin_iva', None))


def _build_desglose(oferta: OfertaServicio, requiere_repuestos: bool) -> dict[str, Any]:
    mo = _safe_float(oferta.costo_mano_de_obra_sin_iva)
    rep = _safe_float(oferta.costo_repuestos_sin_iva) if requiere_repuestos else 0.0
    gest = _gestion_catalogo_sin_iva(oferta) if requiere_repuestos else 0.0
    total = _safe_float(oferta.precio_publicado_cliente)
    if total <= 0:
        total = _safe_float(
            oferta.precio_con_repuestos if requiere_repuestos else oferta.precio_sin_repuestos
        )
    completo = _oferta_catalogo_completa(oferta, requiere_repuestos=requiere_repuestos)
    return {
        'mano_obra': mo,
        'repuestos': rep,
        'gestion': gest,
        'precio_publicado_cliente': total,
        'catalogo_completo': completo,
    }


def _serialize_candidato(
    oferta: OfertaServicio,
    score: float,
    explicacion: str,
    requiere_repuestos: bool,
    *,
    dist_km: float | None = None,
) -> dict[str, Any]:
    usuario_id, proveedor = _proveedor_usuario(oferta)
    nombre = ''
    rating = 0.0
    a_domicilio = oferta.tipo_proveedor == 'mecanico'

    if proveedor:
        nombre = getattr(proveedor, 'nombre', None) or str(proveedor)
        rating = _safe_float(getattr(proveedor, 'calificacion_promedio', 0))

    precio_rep = _safe_float(oferta.precio_con_repuestos)
    precio_sin = _safe_float(oferta.precio_sin_repuestos)
    servicio = getattr(oferta, 'servicio', None)
    nombre_servicio = getattr(servicio, 'nombre', '') if servicio else ''
    desglose = _build_desglose(oferta, requiere_repuestos)
    score_safe = _safe_float(score)

    return {
        'oferta_servicio_id': oferta.id,
        'proveedor': {
            'usuario_id': str(usuario_id) if usuario_id else None,
            'proveedor_id': oferta.taller_id or oferta.mecanico_id,
            'nombre': nombre,
            'tipo': oferta.tipo_proveedor,
            'rating': rating,
        },
        'servicio': {
            'id': oferta.servicio_id,
            'nombre': nombre_servicio,
        },
        'precio_con_repuestos': precio_rep,
        'precio_sin_repuestos': precio_sin,
        'incluye_repuestos_sugerido': requiere_repuestos,
        'a_domicilio': a_domicilio,
        'desglose': desglose,
        'distancia_km': round(dist_km, 1) if dist_km is not None and dist_km < _DISTANCIA_SIN_UBICACION_KM else None,
        'dentro_radio_km': (
            dist_km is not None and dist_km <= MAX_RADIO_KM
        ),
        'score_match': round(score_safe, 3),
        'explicacion': explicacion,
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

    scored = _ordenar_por_distancia_y_score(pool_meta)
    candidatos_raw = _armar_candidatos_finales(scored, requiere_repuestos=requiere_repuestos)

    dist_por_id = {o.id: d for o, d, _, _ in pool_meta}
    candidatos = []
    for cand in candidatos_raw:
        oid = cand.get('oferta_servicio_id')
        dist = dist_por_id.get(oid)
        candidatos.append(
            {
                **cand,
                'distancia_km': (
                    round(dist, 1)
                    if dist is not None and dist < _DISTANCIA_SIN_UBICACION_KM
                    else cand.get('distancia_km')
                ),
                'dentro_radio_km': dist is not None and dist <= MAX_RADIO_KM,
            }
        )

    resultado: dict[str, Any] = {
        'candidatos': candidatos,
        'ordenado_por_distancia': bool(punto),
        'requiere_repuestos': requiere_repuestos,
        'comunas_resueltas': comunas,
        'radio_km': MAX_RADIO_KM,
    }
    if uso_fallback_precio:
        resultado['aviso'] = 'Algunos precios de catálogo están pendientes de configurar'
    return resultado
