"""Enriquece repuestos de cotización con marca/precio/proveedor multi-fuente.

Fuentes (merge por confianza; marca y su fuente viajan siempre juntas en un
mismo "hit" — nunca se asigna una marca sin decir de dónde salió):
1. CatalogSource — ofertas del taller (disponible) + maestro Repuesto → fuente_marketplace='catalogo'
2. HistorialCotizacionSource — cotizaciones enviada/aceptada del taller → fuente_marketplace='historial'
3. MercadoLibreSource — best-effort OAuth (nunca bloquea ni inventa) → fuente_marketplace='mercadolibre'
4. KnowledgeBrandSource — inferencia de marca desde el nombre; SOLO si no hubo match
   real arriba, y siempre etiquetada fuente_marketplace='estimado' (nunca se confunde
   con un dato verificado de catálogo/tienda).

La IA (Gemini) nunca asigna marca_repuesto: siempre llega "" desde el prompt. Solo el
backend la asigna, y solo junto con su fuente real o el rótulo 'estimado'.
"""
from __future__ import annotations

import logging
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any

import requests
from django.utils import timezone

logger = logging.getLogger(__name__)

_MARCAS_REPUESTO_CONOCIDAS = (
    'Vimasa', 'Sachs', 'LuK', 'Luk', 'Bosch', 'Mann', 'Mahle', 'Valeo', 'TRW',
    'Brembo', 'Gates', 'Dayco', 'Contitech', 'SKF', 'INA', 'FAG', 'KYB', 'Monroe',
    'NGK', 'Denso', 'Delphi', 'ACDelco', 'Philips', 'Osram', 'Hella', 'Febi',
    'Lemforder', 'Lemförder', 'Moog', 'Textar', 'Ferodo', 'Jurid', 'Pagid',
    'Wix', 'Fram', 'Purflux', 'Hengst', 'Corteco', 'Elring', 'Victor Reinz',
    'ATE', 'Zimmermann', 'Pilenga', 'SNR', 'Ruville', 'Optimal',
)

_ML_CATEGORY_REPUESTOS = 'MLC1747'
_CONF_CATALOGO = 0.9
_CONF_HISTORIAL = 0.7
_CONF_ML = 0.75
_CONF_KNOWLEDGE = 0.4
_HIST_MIN_MUESTRAS = 2
_HIST_MESES = 6

# Fuentes "grounded": la marca viene atada a un dato real y trazable
# (catálogo del taller, historial de cotizaciones o un listado real de ML).
# 'estimado' (inferencia por nombre) NUNCA se considera grounded: se muestra
# siempre con su propia etiqueta de Canal para no confundirla con un dato verificado.
_FUENTES_GROUND = ('catalogo', 'historial', 'mercadolibre')


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


def _to_int_clp(valor: Any) -> int:
    if valor is None:
        return 0
    if isinstance(valor, (int, float)):
        return max(0, int(round(valor)))
    digits = ''.join(ch for ch in str(valor) if ch.isdigit())
    if not digits:
        return 0
    try:
        return max(0, int(digits))
    except ValueError:
        return 0


def _hit(
    *,
    nombre: str = '',
    marca_repuesto: str = '',
    precio_unitario_clp: int = 0,
    fuente_marketplace: str = '',
    proveedor_nombre: str = '',
    tienda_ml: str = '',
    confianza: float = 0.0,
    clave: str = '',
) -> dict[str, Any]:
    return {
        'nombre': nombre,
        'marca_repuesto': (marca_repuesto or '').strip()[:100],
        'precio_unitario_clp': max(0, int(precio_unitario_clp or 0)),
        'fuente_marketplace': (fuente_marketplace or '').strip()[:50],
        'proveedor_nombre': (proveedor_nombre or '').strip()[:200],
        'tienda_ml': (tienda_ml or '').strip()[:200],
        'confianza': float(confianza or 0),
        'clave': clave or _clave_fuzzy(nombre),
    }


def _mejor_hit(nombre: str, candidatos: list[dict[str, Any]], *, min_score: int = 50) -> dict[str, Any] | None:
    q = _clave_fuzzy(nombre)
    if not q:
        return None
    best: dict[str, Any] | None = None
    best_score = 0
    best_conf = -1.0
    for cand in candidatos:
        score = _match_score(q, cand.get('clave') or '')
        conf = float(cand.get('confianza') or 0)
        if score < min_score:
            continue
        if score > best_score or (score == best_score and conf > best_conf):
            best_score = score
            best_conf = conf
            best = cand
    return best


# ---------------------------------------------------------------------------
# CatalogSource
# ---------------------------------------------------------------------------

def _candidatos_catalogo_maestro(marca_vehiculo: str = '') -> list[dict[str, Any]]:
    try:
        from mecanimovilapp.apps.servicios.models import Repuesto

        qs = (
            Repuesto.objects.filter(activo=True)
            .exclude(marca__isnull=True)
            .exclude(marca='')
            .only('id', 'nombre', 'marca')[:500]
        )
        out: list[dict[str, Any]] = []
        for r in qs:
            marca_pieza = (r.marca or '').strip()
            if not marca_pieza and not r.nombre:
                continue
            out.append(_hit(
                nombre=r.nombre or '',
                marca_repuesto=marca_pieza,
                fuente_marketplace='catalogo',
                proveedor_nombre='Catálogo Mecanimovil',
                confianza=_CONF_CATALOGO * 0.85,
                clave=_clave_fuzzy(r.nombre or ''),
            ))
        return out
    except Exception as exc:
        logger.info('Catalogo maestro no disponible para enrich: %s', exc)
        return []


def _candidatos_ofertas_taller(taller, marca_vehiculo: str = '') -> list[dict[str, Any]]:
    if taller is None:
        return []
    try:
        from mecanimovilapp.apps.servicios.models import OfertaServicio, Repuesto

        qs = (
            OfertaServicio.objects.filter(taller=taller, disponible=True)
            .select_related('marca_vehiculo_seleccionada')
            .only(
                'id',
                'repuestos_seleccionados',
                'marca_vehiculo_seleccionada',
                'marca_vehiculo_seleccionada__nombre',
            )[:120]
        )

        marca_req = _norm(marca_vehiculo)
        repuesto_ids: set[int] = set()
        items: list[dict[str, Any]] = []

        for oferta in qs:
            if marca_req and oferta.marca_vehiculo_seleccionada_id:
                marca_oferta = _norm(getattr(oferta.marca_vehiculo_seleccionada, 'nombre', '') or '')
                if marca_oferta and marca_oferta != marca_req:
                    continue
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
                precio = _to_int_clp(
                    raw.get('precio_unitario_clp')
                    if raw.get('precio_unitario_clp') is not None
                    else raw.get('precio'),
                )
                if not nombre and not marca and rid is None:
                    continue
                items.append({
                    'id': rid,
                    'nombre': nombre,
                    'marca_repuesto': marca,
                    'precio_unitario_clp': precio,
                    'fuente_marketplace': 'catalogo',
                    'proveedor_nombre': 'Catálogo del taller',
                    'confianza': _CONF_CATALOGO,
                    'clave': _clave_fuzzy(nombre),
                })

        if repuesto_ids:
            by_id = {
                r.id: r
                for r in Repuesto.objects.filter(id__in=repuesto_ids).only('id', 'nombre', 'marca')
            }
            for it in items:
                try:
                    rid_int = int(it['id']) if it.get('id') is not None else None
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

        return [
            _hit(
                nombre=it.get('nombre') or '',
                marca_repuesto=it.get('marca_repuesto') or '',
                precio_unitario_clp=int(it.get('precio_unitario_clp') or 0),
                fuente_marketplace='catalogo',
                proveedor_nombre=it.get('proveedor_nombre') or 'Catálogo del taller',
                confianza=float(it.get('confianza') or _CONF_CATALOGO),
                clave=it.get('clave') or '',
            )
            for it in items
            if it.get('clave') or it.get('marca_repuesto') or it.get('precio_unitario_clp')
        ]
    except Exception as exc:
        logger.info('Ofertas taller no disponibles para enrich: %s', exc)
        return []


# ---------------------------------------------------------------------------
# HistorialCotizacionSource
# ---------------------------------------------------------------------------

def _candidatos_historial_taller(
    taller,
    *,
    marca_vehiculo: str = '',
) -> list[dict[str, Any]]:
    if taller is None:
        return []
    try:
        from mecanimovilapp.apps.ordenes.models import CotizacionCanal

        desde = timezone.now() - timedelta(days=_HIST_MESES * 30)
        qs = (
            CotizacionCanal.objects.filter(
                taller=taller,
                estado__in=('enviada', 'aceptada'),
                creado_en__gte=desde,
            )
            .only('id', 'repuestos', 'vehiculo_marca', 'creado_en')
            .order_by('-creado_en')[:80]
        )

        marca_req = _norm(marca_vehiculo)
        buckets: dict[str, dict[str, Any]] = defaultdict(
            lambda: {'precios': [], 'marcas': [], 'proveedores': []},
        )

        for cot in qs:
            if marca_req:
                cot_marca = _norm(cot.vehiculo_marca or '')
                if cot_marca and cot_marca != marca_req:
                    continue
            for raw in (cot.repuestos or []):
                if not isinstance(raw, dict):
                    continue
                nombre = str(raw.get('nombre') or '').strip()
                clave = _clave_fuzzy(nombre)
                if not clave:
                    continue
                precio = _to_int_clp(raw.get('precio_unitario_clp'))
                marca = str(raw.get('marca_repuesto') or '').strip()
                prov = str(
                    raw.get('proveedor_nombre') or raw.get('tienda_ml') or '',
                ).strip()
                b = buckets[clave]
                if precio > 0:
                    b['precios'].append(precio)
                if marca:
                    b['marcas'].append(marca)
                if prov:
                    b['proveedores'].append(prov)
                b['nombre'] = nombre

        out: list[dict[str, Any]] = []
        for clave, data in buckets.items():
            if len(data['precios']) < _HIST_MIN_MUESTRAS and len(data['marcas']) < _HIST_MIN_MUESTRAS:
                continue
            precio_med = int(statistics.median(data['precios'])) if data['precios'] else 0
            marca_moda = Counter(data['marcas']).most_common(1)[0][0] if data['marcas'] else ''
            prov_moda = (
                Counter(data['proveedores']).most_common(1)[0][0] if data['proveedores'] else ''
            )
            out.append(_hit(
                nombre=data.get('nombre') or clave,
                marca_repuesto=marca_moda,
                precio_unitario_clp=precio_med,
                fuente_marketplace='historial',
                proveedor_nombre=prov_moda or 'Historial del taller',
                confianza=_CONF_HISTORIAL,
                clave=clave,
            ))
        return out
    except Exception as exc:
        logger.info('Historial cotización no disponible para enrich: %s', exc)
        return []


# ---------------------------------------------------------------------------
# MercadoLibreSource
# ---------------------------------------------------------------------------

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
) -> dict[str, Any] | None:
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
    precio = _to_int_clp(item.get('price'))

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
    return _hit(
        nombre=titulo or nombre,
        marca_repuesto=marca,
        precio_unitario_clp=precio,
        fuente_marketplace='mercadolibre',
        proveedor_nombre=tienda,
        tienda_ml=tienda,
        confianza=_CONF_ML,
        clave=_clave_fuzzy(nombre),
    )


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def _aplicar_hit_campos(next_rep: dict[str, Any], hit: dict[str, Any]) -> None:
    """Asigna marca/fuente/proveedor como grupo atómico (misma fuente = mismo hit).

    Una fuente real (catálogo/historial/ML) puede sobrescribir un valor existente
    que no esté ya atado a una fuente real (p. ej. un residuo sin `fuente_marketplace`,
    o una marca 'estimado' de inferencia por nombre). Nunca sobrescribe un dato que
    ya viene de otra fuente real: la primera fuente real gana (se procesa por confianza).
    """
    if not hit:
        return
    fuente_hit = str(hit.get('fuente_marketplace') or '').strip()
    fuente_actual = str(next_rep.get('fuente_marketplace') or next_rep.get('fuente_repuesto') or '').strip()
    hit_grounded = fuente_hit in _FUENTES_GROUND
    actual_grounded = fuente_actual in _FUENTES_GROUND

    # Solo se permite sobrescribir cuando el hit es real y lo existente no lo es.
    puede_reemplazar = hit_grounded and not actual_grounded

    marca_actual = str(next_rep.get('marca_repuesto') or '').strip()
    if hit.get('marca_repuesto') and (not marca_actual or puede_reemplazar):
        next_rep['marca_repuesto'] = hit['marca_repuesto']

    if hit.get('fuente_marketplace') and (not fuente_actual or puede_reemplazar):
        next_rep['fuente_marketplace'] = hit['fuente_marketplace']
        next_rep.pop('fuente_repuesto', None)

    proveedor_actual = str(next_rep.get('proveedor_nombre') or '').strip()
    if hit.get('proveedor_nombre') and (not proveedor_actual or puede_reemplazar):
        next_rep['proveedor_nombre'] = hit['proveedor_nombre']

    tienda_actual = str(next_rep.get('tienda_ml') or '').strip()
    if hit.get('tienda_ml') and (not tienda_actual or puede_reemplazar):
        next_rep['tienda_ml'] = hit['tienda_ml']
        if not str(next_rep.get('proveedor_nombre') or '').strip():
            next_rep['proveedor_nombre'] = hit['tienda_ml']


def _aplicar_precio(next_rep: dict[str, Any], hits: list[dict[str, Any]]) -> None:
    """Prefiere precio de catálogo, luego historial; ML solo si IA no tiene precio."""
    precio_ia = _to_int_clp(next_rep.get('precio_unitario_clp'))
    for fuente in ('catalogo', 'historial'):
        for hit in hits:
            if str(hit.get('fuente_marketplace') or '') != fuente:
                continue
            precio_hit = _to_int_clp(hit.get('precio_unitario_clp'))
            if precio_hit > 0:
                next_rep['precio_unitario_clp'] = precio_hit
                return
    if precio_ia <= 0:
        for hit in hits:
            if str(hit.get('fuente_marketplace') or '') != 'mercadolibre':
                continue
            precio_hit = _to_int_clp(hit.get('precio_unitario_clp'))
            if precio_hit > 0:
                next_rep['precio_unitario_clp'] = precio_hit
                return


def enriquecer_repuestos_cotizacion(
    repuestos: list[dict[str, Any]],
    *,
    marca_vehiculo: str = '',
    modelo_vehiculo: str = '',
    taller=None,
    usar_ml: bool = True,
) -> list[dict[str, Any]]:
    """Devuelve nueva lista de repuestos enriquecida multi-fuente."""
    if not repuestos:
        return []

    catalogo = _candidatos_ofertas_taller(taller, marca_vehiculo)
    if len(catalogo) < 20:
        catalogo.extend(_candidatos_catalogo_maestro(marca_vehiculo))
    historial = _candidatos_historial_taller(taller, marca_vehiculo=marca_vehiculo)

    out: list[dict[str, Any]] = []
    for rep in repuestos:
        if not isinstance(rep, dict):
            continue
        next_rep = dict(rep)
        nombre = str(next_rep.get('nombre') or '')

        hits: list[dict[str, Any]] = []
        cat_hit = _mejor_hit(nombre, catalogo)
        if cat_hit:
            hits.append(cat_hit)
        hist_hit = _mejor_hit(nombre, historial)
        if hist_hit:
            hits.append(hist_hit)
        grounded_encontrado = bool(cat_hit or hist_hit)

        # ML solo si no hay dato real de catálogo/historial del taller (evita
        # pisar una marca/precio ya trazable con un hit de menor jerarquía).
        needs_ml = usar_ml and not grounded_encontrado and (
            not str(next_rep.get('tienda_ml') or next_rep.get('proveedor_nombre') or '').strip()
            or not str(next_rep.get('marca_repuesto') or '').strip()
        )
        if needs_ml:
            ml = _buscar_ml_repuesto(
                nombre,
                marca_vehiculo=marca_vehiculo,
                modelo_vehiculo=modelo_vehiculo,
            )
            if ml:
                hits.append(ml)
                grounded_encontrado = True

        # La inferencia por nombre (Vimasa, Bosch, ...) NUNCA sustituye a una fuente
        # real; solo aporta una marca "estimada" cuando no hay ningún dato trazable,
        # y siempre queda etiquetada como fuente_marketplace='estimado' en la UI.
        if not grounded_encontrado:
            inferred = _inferir_marca_desde_nombre(nombre)
            if inferred:
                hits.append(_hit(
                    nombre=nombre,
                    marca_repuesto=inferred,
                    fuente_marketplace='estimado',
                    confianza=_CONF_KNOWLEDGE,
                    clave=_clave_fuzzy(nombre),
                ))

        hits.sort(key=lambda h: float(h.get('confianza') or 0), reverse=True)
        for hit in hits:
            _aplicar_hit_campos(next_rep, hit)
        _aplicar_precio(next_rep, hits)

        # Limpiar vacíos
        if not str(next_rep.get('fuente_marketplace') or '').strip():
            next_rep.pop('fuente_marketplace', None)
            next_rep.pop('fuente_repuesto', None)
        if not str(next_rep.get('marca_repuesto') or '').strip():
            next_rep.pop('marca_repuesto', None)
        if not str(next_rep.get('tienda_ml') or '').strip():
            next_rep.pop('tienda_ml', None)
        if not str(next_rep.get('proveedor_nombre') or '').strip():
            next_rep.pop('proveedor_nombre', None)

        out.append(next_rep)
    return out
