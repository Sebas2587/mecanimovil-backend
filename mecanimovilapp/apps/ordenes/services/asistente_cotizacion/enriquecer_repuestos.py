"""Enriquece repuestos de cotización con marca (catálogo) y tienda ML (best-effort).

Prioridad:
1. Match a catálogo maestro `servicios.Repuesto` / oferta del taller → marca + fuente catalogo.
2. Mercado Libre (OAuth): si la búsqueda aún responde, toma seller nickname real.
3. Inferencia de marca conocida desde el nombre del repuesto (sin inventar tienda).
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Marcas de repuesto frecuentes en Chile (no marcas de vehículo).
_MARCAS_REPUESTO_CONOCIDAS = (
    'Vimasa', 'Sachs', 'LuK', 'Luk', 'Bosch', 'Mann', 'Mahle', 'Valeo', 'TRW',
    'Brembo', 'Gates', 'Dayco', 'Contitech', 'SKF', 'INA', 'FAG', 'KYB', 'Monroe',
    'NGK', 'Denso', 'Delphi', 'ACDelco', 'Philips', 'Osram', 'Hella', 'Febi',
    'Lemforder', 'Lemförder', 'Moog', 'Textar', 'Ferodo', 'Jurid', 'Pagid',
    'Wix', 'Fram', 'Purflux', 'Hengst', 'Corteco', 'Elring', 'Victor Reinz',
    'ATE', 'Zimmermann', 'Pilenga', 'SNR', 'Ruville', 'Optimal',
)

# Categoría genérica autopartes/repuestos autos en MLC (puede variar; se usa como hint).
_ML_CATEGORY_REPUESTOS = 'MLC1747'


def _norm(texto: str) -> str:
    t = unicodedata.normalize('NFD', (texto or '').strip().lower())
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    t = re.sub(r'[^a-z0-9]+', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def _clave_fuzzy(nombre: str) -> str:
    t = _norm(nombre)
    t = re.sub(r'\([^)]*\)', ' ', t)
    for ruido in (
        'repuesto', 'repuestos', 'original', 'oem', 'alternativo', 'kit',
        'incluye', 'para', 'del', 'de', 'la', 'el', 'los', 'las',
    ):
        t = re.sub(rf'\b{ruido}\b', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def _inferir_marca_desde_nombre(nombre: str) -> str:
    raw = nombre or ''
    for marca in _MARCAS_REPUESTO_CONOCIDAS:
        if re.search(rf'\b{re.escape(marca)}\b', raw, flags=re.IGNORECASE):
            return marca if marca != 'Luk' else 'LuK'
    return ''


def _match_score(query_key: str, candidate_key: str) -> int:
    if not query_key or not candidate_key:
        return 0
    if query_key == candidate_key:
        return 100
    if query_key in candidate_key or candidate_key in query_key:
        return 80
    q_tokens = set(query_key.split())
    c_tokens = set(candidate_key.split())
    if not q_tokens or not c_tokens:
        return 0
    inter = q_tokens & c_tokens
    if not inter:
        return 0
    return int(60 * len(inter) / max(len(q_tokens), len(c_tokens)))


def _candidatos_catalogo_maestro(marca_vehiculo: str = '') -> list[dict[str, Any]]:
    try:
        from mecanimovilapp.apps.servicios.models import Repuesto
    except Exception:
        return []

    qs = (
        Repuesto.objects.filter(activo=True)
        .exclude(marca__isnull=True)
        .exclude(marca='')
        .only('id', 'nombre', 'marca')[:500]
    )
    marca_norm = _norm(marca_vehiculo)
    out: list[dict[str, Any]] = []
    for r in qs:
        marca_pieza = (r.marca or '').strip()
        if not marca_pieza and not r.nombre:
            continue
        out.append({
            'id': r.id,
            'nombre': r.nombre or '',
            'marca_repuesto': marca_pieza,
            'fuente': 'catalogo',
            'clave': _clave_fuzzy(r.nombre or ''),
            'marca_vehiculo_hint': marca_norm,
        })
    return out


def _candidatos_ofertas_taller(taller, marca_vehiculo: str = '') -> list[dict[str, Any]]:
    if taller is None:
        return []
    try:
        from mecanimovilapp.apps.servicios.models import OfertaServicio, Repuesto
    except Exception:
        return []

    ofertas = (
        OfertaServicio.objects.filter(taller=taller, activo=True)
        .only('id', 'repuestos_seleccionados')
        [:80]
    )
    repuesto_ids: set[int] = set()
    items: list[dict[str, Any]] = []
    for oferta in ofertas:
        for raw in (oferta.repuestos_seleccionados or []):
            if not isinstance(raw, dict):
                continue
            rid = raw.get('id')
            try:
                if rid is not None:
                    repuesto_ids.add(int(rid))
            except (TypeError, ValueError):
                pass
            nombre = (raw.get('nombre') or raw.get('repuesto') or '').strip()
            marca = (raw.get('marca_repuesto') or raw.get('marca') or '').strip()
            if not nombre and not marca:
                continue
            items.append({
                'id': rid,
                'nombre': nombre,
                'marca_repuesto': marca,
                'fuente': 'catalogo',
                'clave': _clave_fuzzy(nombre),
            })

    if repuesto_ids:
        by_id = {
            r.id: r
            for r in Repuesto.objects.filter(id__in=repuesto_ids).only('id', 'nombre', 'marca')
        }
        for it in items:
            rid = it.get('id')
            try:
                rid_int = int(rid) if rid is not None else None
            except (TypeError, ValueError):
                rid_int = None
            cat = by_id.get(rid_int) if rid_int else None
            if cat is None:
                continue
            if not it.get('nombre'):
                it['nombre'] = cat.nombre or ''
                it['clave'] = _clave_fuzzy(it['nombre'])
            if not it.get('marca_repuesto'):
                it['marca_repuesto'] = (cat.marca or '').strip()
    return [it for it in items if it.get('clave') or it.get('marca_repuesto')]


def _mejor_candidato(nombre: str, candidatos: list[dict[str, Any]]) -> dict[str, Any] | None:
    q = _clave_fuzzy(nombre)
    if not q:
        return None
    best: dict[str, Any] | None = None
    best_score = 0
    for cand in candidatos:
        score = _match_score(q, cand.get('clave') or '')
        if score > best_score:
            best_score = score
            best = cand
    if best_score < 50:
        return None
    return best


def _ml_access_token() -> str:
    try:
        from mecanimovilapp.apps.valoracion_mercado.services.ml_auth import (
            get_mercadolibre_access_token,
        )
        return (get_mercadolibre_access_token() or '').strip()
    except Exception as exc:
        logger.info('ML token no disponible para enrich repuestos: %s', exc)
        return ''


def _buscar_ml_repuesto(
    nombre: str,
    *,
    marca_vehiculo: str = '',
    modelo_vehiculo: str = '',
) -> dict[str, str] | None:
    """Best-effort: busca listing y extrae marca + seller nickname reales.

    Si la búsqueda general sigue en 403 (deprecada), retorna None sin inventar.
    """
    token = _ml_access_token()
    if not token:
        return None

    query = ' '.join(
        p for p in (
            (nombre or '').strip(),
            (marca_vehiculo or '').strip(),
            (modelo_vehiculo or '').split()[0] if (modelo_vehiculo or '').strip() else '',
        ) if p
    ).strip()
    if len(query) < 4:
        return None

    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {token}',
        'User-Agent': 'MecanimovilCotizacion/1.0',
    }
    try:
        resp = requests.get(
            'https://api.mercadolibre.com/sites/MLC/search',
            params={
                'q': query[:120],
                'category': _ML_CATEGORY_REPUESTOS,
                'limit': 5,
            },
            headers=headers,
            timeout=12,
        )
    except requests.RequestException as exc:
        logger.info('ML search repuestos network error: %s', exc)
        return None

    if resp.status_code == 403:
        logger.info(
            'ML search repuestos 403 (búsqueda general deprecada); no se inventa tienda. q=%r',
            query[:80],
        )
        return None
    if resp.status_code >= 400:
        logger.info('ML search repuestos status=%s q=%r', resp.status_code, query[:80])
        return None

    results = (resp.json() or {}).get('results') or []
    if not results:
        return None

    item = results[0]
    item_id = str(item.get('id') or '').strip()
    titulo = str(item.get('title') or '').strip()
    seller = item.get('seller') or {}
    tienda = (
        str(seller.get('nickname') or '').strip()
        or str(seller.get('id') or '').strip()
    )

    marca = ''
    attrs = item.get('attributes') or []
    if isinstance(attrs, list):
        for attr in attrs:
            if not isinstance(attr, dict):
                continue
            aid = str(attr.get('id') or '').upper()
            if aid in ('BRAND', 'MARCA', 'PART_BRAND'):
                marca = str(attr.get('value_name') or '').strip()
                if marca:
                    break
    if not marca:
        marca = _inferir_marca_desde_nombre(titulo)

    # Detalle del ítem para seller nickname si faltó en search.
    if item_id and (not tienda or tienda.isdigit()):
        try:
            detail = requests.get(
                f'https://api.mercadolibre.com/items/{item_id}',
                headers=headers,
                timeout=10,
            )
            if detail.status_code < 400:
                data = detail.json() or {}
                seller_id = data.get('seller_id')
                if seller_id:
                    user = requests.get(
                        f'https://api.mercadolibre.com/users/{seller_id}',
                        headers=headers,
                        timeout=10,
                    )
                    if user.status_code < 400:
                        nick = str((user.json() or {}).get('nickname') or '').strip()
                        if nick:
                            tienda = nick
                if not marca:
                    for attr in (data.get('attributes') or []):
                        if str(attr.get('id') or '').upper() in ('BRAND', 'MARCA'):
                            marca = str(attr.get('value_name') or '').strip()
                            break
        except requests.RequestException:
            pass

    if not tienda and not marca:
        return None
    return {
        'marca_repuesto': marca[:100],
        'tienda_ml': tienda[:200],
        'fuente_marketplace': 'mercadolibre',
        'ml_item_id': item_id,
        'ml_titulo': titulo[:200],
    }


def enriquecer_repuestos_cotizacion(
    repuestos: list[dict[str, Any]],
    *,
    marca_vehiculo: str = '',
    modelo_vehiculo: str = '',
    taller=None,
    usar_ml: bool = True,
) -> list[dict[str, Any]]:
    """Devuelve nueva lista de repuestos con marca/tienda/fuente cuando hay fuente real."""
    if not repuestos:
        return []

    candidatos = _candidatos_ofertas_taller(taller, marca_vehiculo)
    # Catálogo maestro como respaldo (limitado en memoria: solo si ofertas no cubren).
    if len(candidatos) < 20:
        candidatos.extend(_candidatos_catalogo_maestro(marca_vehiculo))

    out: list[dict[str, Any]] = []
    for rep in repuestos:
        if not isinstance(rep, dict):
            continue
        next_rep = dict(rep)
        nombre = str(next_rep.get('nombre') or '')
        marca_actual = str(next_rep.get('marca_repuesto') or '').strip()
        tienda_actual = str(next_rep.get('tienda_ml') or '').strip()
        fuente_actual = str(
            next_rep.get('fuente_marketplace') or next_rep.get('fuente_repuesto') or '',
        ).strip()

        # 1) Catálogo / oferta taller
        if not marca_actual or not fuente_actual:
            hit = _mejor_candidato(nombre, candidatos)
            if hit:
                if not marca_actual and hit.get('marca_repuesto'):
                    next_rep['marca_repuesto'] = str(hit['marca_repuesto'])[:100]
                    marca_actual = next_rep['marca_repuesto']
                if not fuente_actual:
                    next_rep['fuente_marketplace'] = 'catalogo'
                    fuente_actual = 'catalogo'

        # 2) Inferir marca desde el nombre (sin tocar tienda)
        if not marca_actual:
            inferred = _inferir_marca_desde_nombre(nombre)
            if inferred:
                next_rep['marca_repuesto'] = inferred
                marca_actual = inferred

        # 3) ML solo si falta tienda (o marca) y está permitido
        needs_ml = usar_ml and (not tienda_actual or not marca_actual)
        if needs_ml:
            ml = _buscar_ml_repuesto(
                nombre,
                marca_vehiculo=marca_vehiculo,
                modelo_vehiculo=modelo_vehiculo,
            )
            if ml:
                if not marca_actual and ml.get('marca_repuesto'):
                    next_rep['marca_repuesto'] = ml['marca_repuesto']
                if ml.get('tienda_ml'):
                    next_rep['tienda_ml'] = ml['tienda_ml']
                    next_rep['fuente_marketplace'] = 'mercadolibre'
                elif not fuente_actual and ml.get('fuente_marketplace'):
                    next_rep['fuente_marketplace'] = ml['fuente_marketplace']

        # Limpiar vacíos legacy
        if not str(next_rep.get('fuente_marketplace') or '').strip():
            next_rep.pop('fuente_marketplace', None)
            next_rep.pop('fuente_repuesto', None)
        if not str(next_rep.get('marca_repuesto') or '').strip():
            next_rep.pop('marca_repuesto', None)
        if not str(next_rep.get('tienda_ml') or '').strip():
            next_rep.pop('tienda_ml', None)

        out.append(next_rep)
    return out
