"""
Matching de hasta 3 candidatos desde OfertaServicio (stateless).
Incluye talleres y mecánicos a domicilio según distancia y comunas de cobertura.
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any

from django.contrib.gis.geos import Point
from django.db.models import Q

from mecanimovilapp.apps.personalizacion.ml_engine import MotorRecomendaciones
from mecanimovilapp.apps.servicios.models import OfertaServicio
from mecanimovilapp.apps.usuarios.models import ChileanCommune, MechanicServiceArea, MecanicoDomicilio, Taller
from mecanimovilapp.apps.vehiculos.models import Vehiculo

logger = logging.getLogger(__name__)

MAX_CANDIDATOS = 3
MAX_RADIO_KM = 80.0
_RE_COMUNA_INVALIDA = re.compile(r'\d{3,}')


def _punto_servicio(lat: float, lng: float) -> Point:
    return Point(float(lng), float(lat), srid=4326)


def _distancia_km_proveedor(oferta: OfertaServicio, punto: Point) -> float | None:
    proveedor = oferta.taller if oferta.tipo_proveedor == 'taller' else oferta.mecanico
    if not proveedor or not getattr(proveedor, 'ubicacion', None):
        return None
    try:
        ubic = proveedor.ubicacion
        if ubic is None:
            return None
        p = punto
        if getattr(ubic, 'srid', None) and getattr(p, 'srid', None) and ubic.srid != p.srid:
            p = Point(p.x, p.y, srid=ubic.srid)
        metros = ubic.distance(p)
        if metros is None:
            return None
        km = float(metros) / 1000.0
        if math.isnan(km) or math.isinf(km):
            return None
        return km
    except Exception:
        logger.debug('No se pudo calcular distancia proveedor', exc_info=True)
        return None


def _score_y_explicacion(
    *,
    dist_km: float | None,
    rating: float,
) -> tuple[float, str]:
    rating_norm = min(1.0, max(0.0, rating / 5.0))
    if dist_km is not None:
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


def _inferir_comunas_desde_direccion(direccion_texto: str | None) -> list[str]:
    """Busca nombres de comunas chilenas dentro del texto de la dirección."""
    texto = (direccion_texto or '').strip()
    if len(texto) < 4:
        return []
    texto_low = texto.lower()
    encontradas: list[str] = []
    for nombre in ChileanCommune.objects.filter(is_active=True).values_list('name', flat=True):
        n = (nombre or '').strip()
        if len(n) < 3:
            continue
        if n.lower() in texto_low:
            encontradas.append(n)
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


def _mecanico_apto_en_zona(
    oferta: OfertaServicio,
    *,
    comunas: list[str],
    punto: Point | None,
) -> bool:
    """Mecánico a domicilio: distancia al punto y/o comunas de su zona de servicio."""
    if not oferta.mecanico_id:
        return False
    if punto:
        dist = _distancia_km_proveedor(oferta, punto)
        if dist is not None and dist <= MAX_RADIO_KM:
            return True
    if comunas and _mecanico_cubre_comunas(oferta.mecanico_id, comunas):
        return True
    return False


def _proveedor_aprobado(proveedor) -> bool:
    if not proveedor or not getattr(proveedor, 'activo', True):
        return False
    estado = getattr(proveedor, 'estado_verificacion', None)
    if estado:
        return estado == 'aprobado'
    return bool(getattr(proveedor, 'verificado', False))


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


def _build_desglose(oferta: OfertaServicio, requiere_repuestos: bool) -> dict[str, Any]:
    mo = float(oferta.costo_mano_de_obra_sin_iva or 0)
    rep = float(oferta.costo_repuestos_sin_iva or 0)
    gest = float(oferta.costo_gestion_compra_sin_iva or 0) if requiere_repuestos else 0.0
    total = float(oferta.precio_publicado_cliente or 0)
    if total <= 0:
        total = float(
            oferta.precio_con_repuestos if requiere_repuestos else oferta.precio_sin_repuestos
        )
    return {
        'mano_obra': mo,
        'repuestos': rep,
        'gestion': gest,
        'precio_publicado_cliente': total,
    }


def _serialize_candidato(
    oferta: OfertaServicio,
    score: float,
    explicacion: str,
    requiere_repuestos: bool,
) -> dict[str, Any]:
    usuario_id, proveedor = _proveedor_usuario(oferta)
    nombre = ''
    rating = 0.0
    a_domicilio = oferta.tipo_proveedor == 'mecanico'

    if proveedor:
        nombre = getattr(proveedor, 'nombre', None) or str(proveedor)
        rating = float(getattr(proveedor, 'calificacion_promedio', 0) or 0)

    precio_rep = float(oferta.precio_con_repuestos or 0)
    precio_sin = float(oferta.precio_sin_repuestos or 0)

    return {
        'oferta_servicio_id': oferta.id,
        'proveedor': {
            'usuario_id': str(usuario_id) if usuario_id else None,
            'nombre': nombre,
            'tipo': oferta.tipo_proveedor,
            'rating': rating,
        },
        'servicio': {
            'id': oferta.servicio_id,
            'nombre': oferta.servicio.nombre if oferta.servicio_id else '',
        },
        'precio_con_repuestos': precio_rep,
        'precio_sin_repuestos': precio_sin,
        'incluye_repuestos_sugerido': requiere_repuestos,
        'a_domicilio': a_domicilio,
        'desglose': _build_desglose(oferta, requiere_repuestos),
        'score_match': round(score, 3),
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
        OfertaServicio.objects.filter(
            servicio_id__in=servicio_ids,
            disponible=True,
        )
        .filter(
            Q(marca_vehiculo_seleccionada__isnull=True)
            | Q(marca_vehiculo_seleccionada=marca)
            if marca
            else Q()
        )
        .select_related(
            'servicio',
            'taller',
            'taller__usuario',
            'mecanico',
            'mecanico__usuario',
        )
    )

    filtered: list[OfertaServicio] = []
    comunas = _resolver_comunas(comunas_extraidas, direccion_texto)
    punto = None
    if lat is not None and lng is not None:
        try:
            punto = _punto_servicio(lat, lng)
        except (TypeError, ValueError):
            punto = None

    for oferta in qs:
        if oferta.tipo_proveedor == 'taller' and oferta.taller_id:
            t = oferta.taller
            if not _proveedor_aprobado(t):
                continue
            if marca and not t.marcas_atendidas.filter(pk=marca.pk).exists():
                continue
            if punto:
                dist = _distancia_km_proveedor(oferta, punto)
                if dist is not None and dist > MAX_RADIO_KM:
                    continue
            filtered.append(oferta)
        elif oferta.tipo_proveedor == 'mecanico' and oferta.mecanico_id:
            m = oferta.mecanico
            if not _proveedor_aprobado(m):
                continue
            if marca and not m.marcas_atendidas.filter(pk=marca.pk).exists():
                continue
            if not _mecanico_apto_en_zona(oferta, comunas=comunas, punto=punto):
                continue
            filtered.append(oferta)

    if not filtered:
        return {
            'candidatos': [],
            'ordenado_por_distancia': bool(punto),
            'comunas_resueltas': comunas,
            'requiere_repuestos': requiere_repuestos,
        }

    pool = filtered
    if not punto:
        motor = MotorRecomendaciones()
        try:
            ordered = motor.ordenar_por_relevancia(
                OfertaServicio.objects.filter(
                    id__in=[o.id for o in filtered]
                ).select_related(
                    'servicio', 'taller', 'mecanico', 'taller__usuario', 'mecanico__usuario'
                ),
                vehiculo,
            )
            pool = list(ordered) if isinstance(ordered, list) else list(ordered)
        except Exception:
            pool = filtered

    scored: list[tuple[float, OfertaServicio, str]] = []
    for oferta in pool:
        rating = float(
            getattr(oferta.taller or oferta.mecanico, 'calificacion_promedio', 0) or 0
        )
        dist_km = _distancia_km_proveedor(oferta, punto) if punto else None
        score, expl = _score_y_explicacion(dist_km=dist_km, rating=rating)
        scored.append((score, oferta, expl))

    scored.sort(key=lambda item: item[0], reverse=True)

    candidatos = _armar_candidatos_finales(scored, requiere_repuestos=requiere_repuestos)

    return {
        'candidatos': candidatos,
        'ordenado_por_distancia': bool(punto),
        'requiere_repuestos': requiere_repuestos,
        'comunas_resueltas': comunas,
    }
