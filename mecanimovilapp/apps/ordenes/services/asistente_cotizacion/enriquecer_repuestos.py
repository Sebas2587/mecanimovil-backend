"""Enriquece repuestos de cotización con marca/precio/proveedor multi-fuente.

Fuentes verificables (marca y fuente viajan juntas; nunca se inventa tienda/catálogo):
1. CatalogSource — SOLO ofertas del taller (`OfertaServicio.disponible=True`)
   → fuente_marketplace='catalogo', proveedor='Catálogo del taller'
2. HistorialCotizacionSource — cotizaciones enviada|aceptada del mismo taller
   → fuente_marketplace='historial'
3. WebSource — cache `PrecioRepuestoWeb` (Gemini URL Context, tiendas chilenas)
   → fuente_marketplace='web' + tienda + url_producto; precio_referencia_mercado=True
4. MercadoLibreSource — best-effort OAuth con listing real
   → fuente_marketplace='mercadolibre' + nickname tienda
5. KnowledgeBrandSource — solo si el NOMBRE de la pieza ya incluye una marca conocida
   → fuente_marketplace='estimado' (NO es catálogo ni tienda)

IMPORTANTE — el maestro global `Repuesto` (Catálogo Mecanimovil) NO es fuente de
cotización: es taxonomía de producto. Usarlo como "Catálogo" engañaba al taller
(ej. Marca GENÉRICO + Proveedor Catálogo Mecanimovil sin servicios publicados).
Solo se usa para completar nombre/marca de un ítem YA presente en una oferta del taller.

La IA (Gemini) nunca asigna marca_repuesto: llega "". Precios sin match de
catálogo/historial del taller quedan marcados precio_estimado=True.
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

# Placeholders del maestro / JSON que NUNCA deben mostrarse como marca verificada.
_MARCAS_INVALIDAS = frozenset({
    'generico', 'genérico', 'generic', 'n/a', 'na', 'sin marca', 's/m', 'sm',
    'otro', 'otros', 'desconocido', 'unknown', 'ninguna', 'ninguno', '-', '--',
    'original', 'oem', 'no especificada', 'no especificado', 'sin especificar',
})

_ML_CATEGORY_REPUESTOS = 'MLC1747'
_CONF_CATALOGO = 0.9
_CONF_HISTORIAL = 0.7
_CONF_WEB = 0.8
_CONF_ML = 0.75
_CONF_KNOWLEDGE = 0.4
_HIST_MIN_MUESTRAS = 2
_HIST_MESES = 6
# Match más estricto para no atribuir catálogo del taller a un nombre genérico flojo.
_MIN_SCORE_CATALOGO = 70
_MIN_SCORE_HISTORIAL = 60
_MIN_SCORE_WEB = 55

# Fuentes "grounded": dato real y trazable del taller, web verificada o listing ML.
# 'estimado' NUNCA es grounded.
_FUENTES_GROUND = ('proveedor', 'catalogo', 'historial', 'web', 'mercadolibre')
_FUENTES_PRECIO_TALLER = ('proveedor', 'catalogo', 'historial')


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


_NOMBRES_PLACEHOLDER = frozenset({
    'repuesto', 'repuestos', 'item', 'pieza', 'n/a', 'na', '-',
})


def nombre_repuesto_buscable(nombre: str | None) -> bool:
    n = _norm(nombre or '')
    return bool(n) and n not in _NOMBRES_PLACEHOLDER


def linea_necesita_busqueda_web(rep: Any) -> bool:
    """True si la línea aún no tiene precio/fuente verificable para el taller."""
    if not isinstance(rep, dict):
        return False
    if not nombre_repuesto_buscable(str(rep.get('nombre') or '')):
        return False
    fuente = str(rep.get('fuente_marketplace') or '').strip().lower()
    if bool(rep.get('especificacion_pendiente')):
        return False
    if fuente in ('catalogo', 'historial', 'proveedor'):
        return False
    precio = _to_int_clp(rep.get('precio_unitario_clp'))
    if precio <= 0:
        return True
    if fuente in ('web', 'mercadolibre') and str(rep.get('proveedor_nombre') or '').strip():
        return False
    return (
        bool(rep.get('precio_estimado', True))
        or not str(rep.get('marca_repuesto') or '').strip()
        or not str(rep.get('proveedor_nombre') or '').strip()
    )


def _inferir_marca_desde_nombre(nombre: str) -> str:
    raw = nombre or ''
    for marca in _MARCAS_REPUESTO_CONOCIDAS:
        if re.search(rf'\b{re.escape(marca)}\b', raw, flags=re.IGNORECASE):
            return marca if marca != 'Luk' else 'LuK'
    return ''


def _nombre_con_marca(nombre: str, marca: str | None) -> str:
    """Incluye la marca en el nombre visible al cliente si aún no está.

    'Discos de freno delanteros' + 'Repstock' → 'Discos de freno delanteros Repstock'
    No duplica si el nombre ya contiene la marca (case-insensitive).
    """
    base = str(nombre or '').strip()
    marca_ok = _marca_repuesto_valida(marca)
    if not base:
        return marca_ok
    if not marca_ok:
        return base
    if marca_ok.lower() in base.lower():
        return base
    return f'{base} {marca_ok}'.strip()[:200]


def _marca_repuesto_valida(marca: str | None) -> str:
    """Devuelve marca usable o '' si es placeholder (GENÉRICO, N/A, …)."""
    m = (marca or '').strip()
    if not m:
        return ''
    if _norm(m) in _MARCAS_INVALIDAS:
        return ''
    return m[:100]


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
    url_producto: str = '',
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
        'url_producto': (url_producto or '').strip()[:500],
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
    """Deshabilitado a propósito.

    El maestro global `Repuesto` no es precio ni catálogo del taller. Antes se
    etiquetaba como 'catalogo' / 'Catálogo Mecanimovil' y producía tags falsos
    (ej. Marca GENÉRICO) aunque el taller no tuviera el servicio publicado.
    Se mantiene el stub por compatibilidad de tests/imports.
    """
    return []


def _candidatos_ofertas_taller(
    taller,
    marca_vehiculo: str = '',
    modelo_vehiculo: str = '',
) -> list[dict[str, Any]]:
    if taller is None:
        return []
    try:
        from mecanimovilapp.apps.servicios.models import OfertaServicio, Repuesto

        qs = (
            OfertaServicio.objects.filter(taller=taller, disponible=True)
            .select_related('marca_vehiculo_seleccionada', 'modelo_vehiculo_seleccionado')
            .only(
                'id',
                'repuestos_seleccionados',
                'marca_vehiculo_seleccionada',
                'marca_vehiculo_seleccionada__nombre',
                'modelo_vehiculo_seleccionado',
                'modelo_vehiculo_seleccionado__nombre',
            )[:200]
        )

        marca_req = _norm(marca_vehiculo)
        modelo_req = _norm(modelo_vehiculo)
        repuesto_ids: set[int] = set()
        items: list[dict[str, Any]] = []

        for oferta in qs:
            if marca_req and oferta.marca_vehiculo_seleccionada_id:
                marca_oferta = _norm(getattr(oferta.marca_vehiculo_seleccionada, 'nombre', '') or '')
                if marca_oferta and marca_oferta != marca_req:
                    continue
            modelo_oferta = ''
            if oferta.modelo_vehiculo_seleccionado_id:
                modelo_oferta = _norm(
                    getattr(oferta.modelo_vehiculo_seleccionado, 'nombre', '') or '',
                )
                # Si la oferta es de otro modelo concreto, no mezclar sus piezas.
                if modelo_req and modelo_oferta and modelo_oferta != modelo_req:
                    continue
            # Preferir cobertura exacta marca+modelo sobre "toda la marca".
            conf = _CONF_CATALOGO
            if modelo_req and modelo_oferta and modelo_oferta == modelo_req:
                conf = min(0.98, _CONF_CATALOGO + 0.05)
            elif modelo_req and not modelo_oferta:
                conf = _CONF_CATALOGO * 0.92

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
                marca = _marca_repuesto_valida(
                    raw.get('marca_repuesto') or raw.get('marca') or '',
                )
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
                    'confianza': conf,
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
                # Solo completar marca del maestro si es una marca real (no GENÉRICO).
                if not it.get('marca_repuesto'):
                    it['marca_repuesto'] = _marca_repuesto_valida(cat.marca)

        return [
            _hit(
                nombre=it.get('nombre') or '',
                marca_repuesto=_marca_repuesto_valida(it.get('marca_repuesto')),
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

def _modelo_vehiculo_coincide(a: str, b: str) -> bool:
    """Igualdad estricta de modelo. Usar vehiculo_historial_identico para marca+modelo."""
    from .vehiculo_exacto import _norm_vehiculo_campo

    na, nb = _norm_vehiculo_campo(a), _norm_vehiculo_campo(b)
    if not na or not nb:
        return False
    return na == nb


def _servicio_tokens_hist(nombre: str) -> set[str]:
    return {t for t in _norm(nombre).split() if len(t) > 2}


def _servicios_similares_hist(a: str, b: str) -> bool:
    ta, tb = _servicio_tokens_hist(a), _servicio_tokens_hist(b)
    if not ta or not tb:
        return True  # sin filtro de servicio → aceptar
    if ta == tb:
        return True
    inter = ta & tb
    return len(inter) >= max(1, min(len(ta), len(tb)) // 2)


def _candidatos_historial_taller(
    taller,
    *,
    marca_vehiculo: str = '',
    modelo_vehiculo: str = '',
    servicio_nombre: str = '',
) -> list[dict[str, Any]]:
    if taller is None:
        return []
    try:
        from mecanimovilapp.apps.ordenes.models import CotizacionCanal
        from .vehiculo_exacto import vehiculo_historial_identico

        if not (marca_vehiculo or '').strip() or not (modelo_vehiculo or '').strip():
            return []

        desde = timezone.now() - timedelta(days=_HIST_MESES * 30)
        qs = (
            CotizacionCanal.objects.filter(
                taller=taller,
                estado__in=('enviada', 'aceptada'),
                creado_en__gte=desde,
            )
            .only(
                'id',
                'repuestos',
                'vehiculo_marca',
                'vehiculo_modelo',
                'servicio_nombre',
                'creado_en',
            )
            .order_by('-creado_en')[:80]
        )

        marca_req = (marca_vehiculo or '').strip()
        modelo_req = (modelo_vehiculo or '').strip()
        servicio_req = (servicio_nombre or '').strip()
        buckets: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                'precios': [],
                'marcas': [],
                'proveedores': [],
                'urls': [],
                'match_modelo': False,
            },
        )

        for cot in qs:
            if not vehiculo_historial_identico(
                marca_req,
                modelo_req,
                cot.vehiculo_marca,
                cot.vehiculo_modelo,
            ):
                continue
            match_modelo = True
            if servicio_req and (cot.servicio_nombre or '').strip():
                if not _servicios_similares_hist(cot.servicio_nombre, servicio_req):
                    continue
            for raw in (cot.repuestos or []):
                if not isinstance(raw, dict):
                    continue
                nombre = str(raw.get('nombre') or '').strip()
                clave = _clave_fuzzy(nombre)
                if not clave:
                    continue
                precio = _to_int_clp(raw.get('precio_unitario_clp'))
                marca = _marca_repuesto_valida(raw.get('marca_repuesto'))
                prov = str(
                    raw.get('proveedor_nombre') or raw.get('tienda_ml') or '',
                ).strip()
                # No aprender "Catálogo Mecanimovil" como proveedor del taller.
                if _norm(prov) in ('catalogo mecanimovil', 'catálogo mecanimovil'):
                    prov = ''
                url = str(raw.get('url_producto') or '').strip()
                b = buckets[clave]
                if precio > 0:
                    b['precios'].append(precio)
                if marca:
                    b['marcas'].append(marca)
                if prov:
                    b['proveedores'].append(prov)
                if url:
                    b['urls'].append(url)
                b['nombre'] = nombre
                b['match_modelo'] = b['match_modelo'] or match_modelo

        out: list[dict[str, Any]] = []
        for clave, data in buckets.items():
            # Con match de marca+modelo basta 1 cotización enviada; si no, umbral clásico.
            min_muestras = 1 if data.get('match_modelo') else _HIST_MIN_MUESTRAS
            if len(data['precios']) < min_muestras and len(data['marcas']) < min_muestras:
                continue
            precio_med = int(statistics.median(data['precios'])) if data['precios'] else 0
            marca_moda = (
                _marca_repuesto_valida(Counter(data['marcas']).most_common(1)[0][0])
                if data['marcas'] else ''
            )
            prov_moda = (
                Counter(data['proveedores']).most_common(1)[0][0] if data['proveedores'] else ''
            )
            url_moda = (
                Counter(data['urls']).most_common(1)[0][0] if data['urls'] else ''
            )
            conf = _CONF_HISTORIAL + (0.05 if data.get('match_modelo') else 0.0)
            hit = _hit(
                nombre=data.get('nombre') or clave,
                marca_repuesto=marca_moda,
                precio_unitario_clp=precio_med,
                fuente_marketplace='historial',
                proveedor_nombre=prov_moda or 'Historial del taller',
                url_producto=url_moda,
                confianza=min(0.88, conf),
                clave=clave,
            )
            out.append(hit)
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
# WebSource (cache PrecioRepuestoWeb)
# ---------------------------------------------------------------------------

def _candidatos_web_cache(
    *,
    marca_vehiculo: str = '',
    modelo_vehiculo: str = '',
    anio_vehiculo: str | int | None = '',
    tipo_motor: str = '',
    cilindraje: str = '',
    nombres: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Hits vigentes desde PrecioRepuestoWeb (rellenado por Celery/Gemini URL Context)."""
    try:
        from mecanimovilapp.apps.ordenes.models import PrecioRepuestoWeb
        from .busqueda_web_repuestos import _es_listado_sin_vendedor, clave_cache_repuesto

        now = timezone.now()
        qs = PrecioRepuestoWeb.objects.filter(expira_en__gt=now)
        if nombres:
            claves: list[str] = []
            for nom in nombres:
                if not str(nom or '').strip():
                    continue
                claves.append(clave_cache_repuesto(
                    nom,
                    marca_vehiculo=marca_vehiculo,
                    modelo_vehiculo=modelo_vehiculo,
                    anio=anio_vehiculo,
                    tipo_motor=tipo_motor,
                    cilindraje=cilindraje,
                ))
            qs = qs.filter(clave__in=[c for c in claves if c])
        qs = qs.order_by('-confianza')[:400]
        out: list[dict[str, Any]] = []
        from .vehiculo_exacto import clave_historial_cubre_vehiculo

        veh_norm = _norm(
            ' '.join(str(p) for p in (marca_vehiculo, modelo_vehiculo, anio_vehiculo or '') if p),
        )
        for row in qs:
            clave = str(row.clave or '')
            dominio = str(row.dominio or '').strip().lower()
            if dominio in ('historial-taller', 'historial_taller'):
                if not clave_historial_cubre_vehiculo(clave, marca_vehiculo, modelo_vehiculo):
                    continue
            elif '|' not in clave:
                # Fila legada sin vehículo en la clave: no se puede atribuir a
                # este auto y mezclaba precios entre modelos.
                continue
            elif veh_norm and veh_norm not in _norm(clave):
                continue
            elif _es_listado_sin_vendedor(str(row.url or '') or f'https://{dominio}/'):
                # Fila cacheada de un listado: no dice de qué tienda es el precio.
                continue
            marca = _marca_repuesto_valida(row.marca_repuesto)
            clave_nombre = clave.split('|', 1)[0] if '|' in clave else clave
            dominio = str(row.dominio or '').strip().lower()
            # Semilla post-envío (aprendizaje) → historial del taller, no marketplace web.
            if dominio in ('historial-taller', 'historial_taller'):
                fuente = 'historial'
                conf = float(row.confianza or _CONF_HISTORIAL)
                proveedor = str(row.tienda or 'Historial del taller')[:200]
            else:
                fuente = 'web'
                conf = float(row.confianza or _CONF_WEB)
                proveedor = str(row.tienda or '')[:200]
            hit = _hit(
                nombre=str(row.nombre_producto or '')[:200],
                marca_repuesto=marca,
                precio_unitario_clp=int(row.precio_clp or 0),
                fuente_marketplace=fuente,
                proveedor_nombre=proveedor,
                url_producto=str(row.url or '')[:500],
                confianza=conf if conf > 0 else (_CONF_HISTORIAL if fuente == 'historial' else _CONF_WEB),
                clave=clave_nombre or _clave_fuzzy(str(row.nombre_producto or '')),
            )
            out.append(hit)
        return out
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def _aplicar_hit_campos(next_rep: dict[str, Any], hit: dict[str, Any]) -> None:
    """Asigna marca/fuente/proveedor como grupo atómico (misma fuente = mismo hit).

    Una fuente real (catálogo/historial/web/ML) puede sobrescribir un valor existente
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
        # El cliente ve el nombre del ítem: la marca debe ir ahí, no solo en un tag.
        next_rep['nombre'] = _nombre_con_marca(
            str(next_rep.get('nombre') or ''),
            hit['marca_repuesto'],
        )

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

    url_actual = str(next_rep.get('url_producto') or '').strip()
    if hit.get('url_producto') and (not url_actual or puede_reemplazar):
        next_rep['url_producto'] = hit['url_producto']

    if hit.get('proveedor_id') and (not next_rep.get('proveedor_id') or puede_reemplazar):
        next_rep['proveedor_id'] = hit['proveedor_id']
    if hit.get('especificacion') and (not str(next_rep.get('especificacion') or '').strip() or puede_reemplazar):
        next_rep['especificacion'] = hit['especificacion']


def _aplicar_precio(next_rep: dict[str, Any], hits: list[dict[str, Any]]) -> None:
    """Delega a resolver_precio_linea (banda + certeza; flag apagado = legado)."""
    from .resolver_precio import resolver_precio_linea

    resolver_precio_linea(next_rep, hits)


def enriquecer_repuestos_cotizacion(
    repuestos: list[dict[str, Any]],
    *,
    marca_vehiculo: str = '',
    modelo_vehiculo: str = '',
    anio_vehiculo: str | int | None = '',
    cilindraje: str = '',
    tipo_motor: str = '',
    servicio_nombre: str = '',
    taller=None,
    usar_ml: bool = True,
    usar_web: bool = True,
) -> list[dict[str, Any]]:
    """Devuelve nueva lista de repuestos enriquecida multi-fuente.

    Solo el catálogo/historial del taller, web verificada y ML real pueden marcar
    Canal. Sin match del taller, el precio queda estimado (web marca referencia de mercado).
    """
    if not repuestos:
        return []

    # Solo ofertas del taller (marca/modelo). El maestro global NUNCA se mezcla aquí.
    proveedor_cands: list[dict[str, Any]] = []
    try:
        from mecanimovilapp.apps.ordenes.services.precios_proveedor import (
            candidatos_precio_proveedor,
        )

        proveedor_cands = candidatos_precio_proveedor(
            taller,
            marca_vehiculo=marca_vehiculo,
            modelo_vehiculo=modelo_vehiculo,
            tipo_motor=tipo_motor,
        )
    except Exception:
        proveedor_cands = []

    catalogo = _candidatos_ofertas_taller(
        taller,
        marca_vehiculo,
        modelo_vehiculo=modelo_vehiculo,
    )
    historial = _candidatos_historial_taller(
        taller,
        marca_vehiculo=marca_vehiculo,
        modelo_vehiculo=modelo_vehiculo,
        servicio_nombre=servicio_nombre,
    )
    nombres_lineas = [
        str(r.get('nombre') or '')
        for r in repuestos
        if isinstance(r, dict) and not r.get('especificacion_pendiente')
    ]
    web_cands = (
        _candidatos_web_cache(
            marca_vehiculo=marca_vehiculo,
            modelo_vehiculo=modelo_vehiculo,
            anio_vehiculo=anio_vehiculo,
            tipo_motor=tipo_motor,
            cilindraje=cilindraje,
            nombres=nombres_lineas,
        )
        if usar_web
        else []
    )

    out: list[dict[str, Any]] = []
    for rep in repuestos:
        if not isinstance(rep, dict):
            continue
        next_rep = dict(rep)
        # Descarta proveedor falso del maestro global (nunca es fuente del taller).
        if _norm(str(next_rep.get('proveedor_nombre') or '')) in (
            'catalogo mecanimovil', 'catálogo mecanimovil',
        ):
            next_rep.pop('proveedor_nombre', None)
        marca_in = _marca_repuesto_valida(next_rep.get('marca_repuesto'))
        if marca_in:
            next_rep['marca_repuesto'] = marca_in
        else:
            next_rep.pop('marca_repuesto', None)
        # Si venía etiquetado como catálogo sin ofertas del taller, limpiar.
        fuente_in = str(
            next_rep.get('fuente_marketplace') or next_rep.get('fuente_repuesto') or '',
        ).strip()
        if fuente_in == 'catalogo' and not catalogo:
            next_rep.pop('fuente_marketplace', None)
            next_rep.pop('fuente_repuesto', None)
            next_rep.pop('proveedor_nombre', None)

        nombre = str(next_rep.get('nombre') or '')

        hits: list[dict[str, Any]] = []
        prov_hit = _mejor_hit(nombre, proveedor_cands, min_score=_MIN_SCORE_CATALOGO) if proveedor_cands else None
        if prov_hit:
            hits.append(prov_hit)
        cat_hit = _mejor_hit(nombre, catalogo, min_score=_MIN_SCORE_CATALOGO)
        if cat_hit:
            hits.append(cat_hit)
        hist_hit = _mejor_hit(nombre, historial, min_score=_MIN_SCORE_HISTORIAL)
        if hist_hit:
            hits.append(hist_hit)
        grounded_taller = bool(prov_hit or cat_hit or hist_hit)

        web_hit = None
        if usar_web and not grounded_taller and web_cands:
            web_hit = _mejor_hit(nombre, web_cands, min_score=_MIN_SCORE_WEB)
            if web_hit:
                hits.append(web_hit)

        grounded_encontrado = bool(grounded_taller or web_hit)

        # ML solo si no hay dato real de catálogo/historial/web.
        needs_ml = usar_ml and not grounded_encontrado and (
            not str(next_rep.get('tienda_ml') or '').strip()
            or not str(next_rep.get('marca_repuesto') or '').strip()
        )
        if needs_ml:
            ml = _buscar_ml_repuesto(
                nombre,
                marca_vehiculo=marca_vehiculo,
                modelo_vehiculo=modelo_vehiculo,
            )
            if ml:
                ml['marca_repuesto'] = _marca_repuesto_valida(ml.get('marca_repuesto'))
                hits.append(ml)
                grounded_encontrado = True

        # Inferencia por nombre: solo si el texto YA trae la marca y no hubo fuente real.
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
            if hit.get('marca_repuesto'):
                hit = dict(hit)
                hit['marca_repuesto'] = _marca_repuesto_valida(hit.get('marca_repuesto'))
            _aplicar_hit_campos(next_rep, hit)
        next_rep.pop('precio_referencia_mercado', None)
        _aplicar_precio(next_rep, hits)

        fuente_final = str(next_rep.get('fuente_marketplace') or '').strip()
        precio_de_taller = fuente_final in _FUENTES_PRECIO_TALLER and any(
            str(h.get('fuente_marketplace') or '') in _FUENTES_PRECIO_TALLER
            and _to_int_clp(h.get('precio_unitario_clp')) > 0
            for h in hits
        )
        # Precio IA / web / ML / sin match de taller → estimado (el taller debe revisar).
        next_rep['precio_estimado'] = not precio_de_taller
        if fuente_final == 'web' or next_rep.get('precio_referencia_mercado'):
            next_rep['precio_referencia_mercado'] = True
        else:
            next_rep.pop('precio_referencia_mercado', None)

        # No mostrar proveedor/canal de catálogo sin marca ni precio del taller.
        if fuente_final == 'catalogo' and not (
            _marca_repuesto_valida(next_rep.get('marca_repuesto'))
            or precio_de_taller
        ):
            next_rep.pop('fuente_marketplace', None)
            next_rep.pop('proveedor_nombre', None)
            fuente_final = ''

        # Limpiar vacíos y basura
        if not fuente_final:
            next_rep.pop('fuente_marketplace', None)
            next_rep.pop('fuente_repuesto', None)
        if not _marca_repuesto_valida(next_rep.get('marca_repuesto')):
            next_rep.pop('marca_repuesto', None)
        if not str(next_rep.get('tienda_ml') or '').strip():
            next_rep.pop('tienda_ml', None)
        if not str(next_rep.get('proveedor_nombre') or '').strip():
            next_rep.pop('proveedor_nombre', None)
        if not str(next_rep.get('url_producto') or '').strip():
            next_rep.pop('url_producto', None)
        # Nunca persistir "Catálogo Mecanimovil"
        if _norm(str(next_rep.get('proveedor_nombre') or '')) in (
            'catalogo mecanimovil', 'catálogo mecanimovil',
        ):
            next_rep.pop('proveedor_nombre', None)

        out.append(next_rep)
    return out
