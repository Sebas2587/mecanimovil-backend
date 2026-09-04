"""Búsqueda web de repuestos: Tavily (agregador gratis) + Gemini como formateador.

Arquitectura (en orden de preferencia):
1. Tavily Search API (free tier, 1000 créditos/mes, sin tarjeta) devuelve
   resultados REALES (título, url, snippet) buscando en Chile (`country`), y
   la validación se queda solo con tiendas .cl que no sean listados. Gemini
   SOLO filtra compatibilidad y da formato al JSON final (sin tool
   `url_context`, sin re-fetch de páginas).
2. Fallback (si no hay `TAVILY_API_KEY`, o Tavily no devuelve nada): Gemini
   con `url_context` sobre URLs de tiendas construidas por nosotros. Es más
   frágil (Mercado Libre bloquea slugs con marca; tiendas tipo SPA como
   AutoPlanet no muestran productos en el HTML crudo, y el modelo a veces
   "confirma" haber leído una URL que en realidad fue bloqueada), por eso
   Tavily es la ruta preferida cuando hay API key configurada.

`TAVILY_API_KEY` se obtiene gratis (sin tarjeta) en https://app.tavily.com
"""
from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from datetime import date
from typing import Any
from urllib.parse import quote_plus, urlparse

import requests
from django.conf import settings
from django.core.cache import cache

from .enriquecer_repuestos import (
    _clave_fuzzy,
    _inferir_marca_desde_nombre,
    _marca_repuesto_valida,
    _norm,
    _to_int_clp,
)
from .generador import _parse_json

logger = logging.getLogger(__name__)

_CACHE_RPD_PREFIX = 'busqueda_web_repuestos_rpd:'
_ESPERA_REINTENTO_GEMINI = 3.0
_URL_RETRIEVAL_OK = frozenset({
    'URL_RETRIEVAL_STATUS_SUCCESS',
    'url_retrieval_status_success',
    'SUCCESS',
    'success',
})


def busqueda_web_habilitada() -> bool:
    return bool(getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_ENABLED', False)) and bool(
        (getattr(settings, 'GEMINI_API_KEY', '') or '').strip()
    )


def _fuentes() -> list[dict[str, str]]:
    raw = getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_FUENTES', None) or []
    out: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        nombre = str(item.get('nombre') or '').strip()
        dominio = str(item.get('dominio') or '').strip().lower()
        plantilla = str(item.get('plantilla') or '').strip()
        if not dominio or not plantilla or '{q}' not in plantilla:
            continue
        out.append({'nombre': nombre or dominio, 'dominio': dominio, 'plantilla': plantilla})
    return out


def _dominios_whitelist() -> set[str]:
    return {f['dominio'] for f in _fuentes()} | _dominios_especialistas()


def _especialistas() -> list[dict[str, Any]]:
    """Casas de repuestos especialistas configuradas."""
    raw = getattr(settings, 'REPUESTOS_TIENDAS_ESPECIALISTAS', None) or []
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        alias = str(item.get('alias') or item.get('nombre') or '').strip()
        if not alias:
            continue
        marcas = item.get('marcas') or []
        out.append({
            'nombre': str(item.get('nombre') or alias).strip(),
            'alias': alias,
            'dominio': str(item.get('dominio') or '').strip().lower(),
            'marcas': [_norm(m) for m in marcas if str(m or '').strip()],
        })
    return out


def _dominios_especialistas() -> set[str]:
    return {e['dominio'] for e in _especialistas() if e['dominio']}


def _especialistas_de_marca(marca: str) -> list[dict[str, Any]]:
    """Casas que trabajan esa marca: las configuradas y las que ya rindieron.

    Las aprendidas van primero: son dominios que en búsquedas anteriores
    devolvieron la ficha del modelo consultado para esta misma marca.
    """
    m = _norm(marca)
    if not m:
        return []
    configuradas = [e for e in _especialistas() if any(mk in m or m in mk for mk in e['marcas'])]
    vistas = {e['dominio'] for e in configuradas if e['dominio']}
    aprendidas = [e for e in _casas_aprendidas(m) if e['dominio'] not in vistas]
    return aprendidas + configuradas


_MIN_ACIERTOS_CASA = 2


def _casas_aprendidas(marca_norm: str, limite: int = 3) -> list[dict[str, Any]]:
    """Dominios que ya entregaron fichas del modelo para esta marca."""
    try:
        from mecanimovilapp.apps.ordenes.models import TiendaEspecialistaMarca

        filas = TiendaEspecialistaMarca.objects.filter(
            marca=marca_norm[:80],
            aciertos__gte=_MIN_ACIERTOS_CASA,
        ).order_by('-aciertos')[:limite]
        return [
            {
                'nombre': f.nombre or f.dominio,
                'alias': f.nombre or _raiz_dominio(f.dominio),
                'dominio': f.dominio,
                'marcas': [marca_norm],
            }
            for f in filas
        ]
    except Exception as exc:  # pragma: no cover - la búsqueda no puede caerse por esto
        logger.info('busqueda_web_repuestos: casas aprendidas no disponibles: %s', exc)
        return []


def registrar_casa_de_marca(marca: str, url: str, tienda: str, *, acierto: bool) -> None:
    """Anota que un dominio entregó (o no) la ficha del modelo para esa marca."""
    marca_norm = _norm(marca)[:80]
    dominio = _dominio_de_url(url)
    if not marca_norm or not dominio or _es_generalista(url):
        return
    try:
        from django.db.models import F
        from django.utils import timezone

        from mecanimovilapp.apps.ordenes.models import TiendaEspecialistaMarca

        fila, creada = TiendaEspecialistaMarca.objects.get_or_create(
            marca=marca_norm,
            dominio=dominio[:200],
            defaults={
                'nombre': (tienda or '')[:200],
                'apariciones': 1,
                'aciertos': 1 if acierto else 0,
                'ultimo_acierto': timezone.now() if acierto else None,
            },
        )
        if creada:
            return
        campos: dict[str, Any] = {'apariciones': F('apariciones') + 1}
        if acierto:
            campos['aciertos'] = F('aciertos') + 1
            campos['ultimo_acierto'] = timezone.now()
        if tienda and not fila.nombre:
            campos['nombre'] = tienda[:200]
        TiendaEspecialistaMarca.objects.filter(pk=fila.pk).update(**campos)
    except Exception as exc:  # pragma: no cover
        logger.info('busqueda_web_repuestos: no se pudo anotar la casa %s: %s', dominio, exc)


def _tokens_vehiculo(marca: str, modelo: str, anio: str | int | None, cilindraje: str) -> list[str]:
    """Señas que debe nombrar la ficha para ser de ESTE auto."""
    tokens: list[str] = []
    for parte in (marca, modelo, str(anio or '')):
        for tok in _norm(parte).split():
            if len(tok) >= 2 and tok not in tokens:
                tokens.append(tok)
    # La cilindrada va entera ("1 4"): suelta, cada dígito no dice nada.
    cil = _norm(cilindraje)
    if cil and cil not in tokens:
        tokens.append(cil)
    return tokens


def _calce_vehiculo(candidato: dict[str, Any], tokens: list[str]) -> int:
    """Cuántas señas del vehículo nombra la ficha (marca, modelo, variante, motor)."""
    if not tokens:
        return 0
    texto = _norm(f"{candidato.get('title') or ''} {candidato.get('content') or ''}"[:1200])
    if not texto:
        return 0
    # Compacto para que "TJET" calce con "T-Jet" y "1.4" con "1 4".
    compacto = texto.replace(' ', '')
    n = 0
    for t in tokens:
        junto = t.replace(' ', '')
        if f' {t} ' in f' {texto} ' or (len(junto) >= 4 and junto in compacto):
            n += 1
    return n


def _es_generalista(url: str) -> bool:
    """Retail que vende de todo: su ficha rara vez es del modelo exacto."""
    host = _dominio_de_url(url)
    if not host:
        return False
    dominios = getattr(settings, 'REPUESTOS_DOMINIOS_GENERALISTAS', None) or []
    return any(host == d or host.endswith('.' + d) for d in dominios)


def _es_de_especialista(candidato: dict[str, Any]) -> bool:
    """Ficha de una casa especialista: por dominio propio o por su nombre en la ficha."""
    host = _dominio_de_url(str(candidato.get('url') or ''))
    texto = _norm(f"{candidato.get('title') or ''} {candidato.get('content') or ''}"[:600])
    for esp in _especialistas():
        dom = esp['dominio']
        if dom and (host == dom or host.endswith('.' + dom.removeprefix('www.'))):
            return True
        if _norm(esp['alias']) in texto:
            return True
    return False


def _slug_query(texto: str) -> str:
    """Slug tipo 'kit-embrague-hyundai-accent-2015' para path de ML."""
    t = unicodedata.normalize('NFD', (texto or '').strip().lower())
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    t = re.sub(r'[^a-z0-9]+', '-', t)
    return re.sub(r'-+', '-', t).strip('-')[:120]


_STOP_QUERY = frozenset({
    'de', 'del', 'la', 'el', 'los', 'las', 'un', 'una', 'y', 'para', 'con',
    'bidon', 'bidón', 'litro', 'litros', 'ml', 'kit', 'juego', 'par',
})

# Slugs ML con buen retrieval (los filtros largos marca+año suelen dar ERROR).
_CATEGORY_SLUG_ML = {
    'termostato': 'termostato-auto',
    'sensor': 'sensor-temperatura-agua',
    'refrigerante': 'refrigerante-anticongelante',
    'anticongelante': 'refrigerante-anticongelante',
    'bujia': 'bujias',
    'bujias': 'bujias',
    'filtro': 'filtro-aceite-auto',
    'aceite': 'aceite-motor',
    'embrague': 'kit-embrague',
    'disco': 'disco-de-freno',
    'discos': 'disco-de-freno',
    'pastilla': 'pastillas-de-freno',
    'pastillas': 'pastillas-de-freno',
    'amortiguador': 'amortiguadores',
    'amortiguadores': 'amortiguadores',
    'correa': 'correa-distribucion',
    'bomba': 'bomba-agua-auto',
    'bateria': 'baterias-auto',
    'baterias': 'baterias-auto',
    'neumatico': 'neumaticos',
    'neumaticos': 'neumaticos',
    'radiador': 'radiador-auto',
    'alternador': 'alternador-auto',
    'bobina': 'bobina-encendido',
    'inyector': 'inyectores',
    'inyectores': 'inyectores',
    'zapata': 'zapatas-freno',
    'zapatas': 'zapatas-freno',
    'balata': 'pastillas-de-freno',
    'balatas': 'pastillas-de-freno',
    'rotula': 'rotula-suspension',
    'rotulas': 'rotula-suspension',
    'homocinetica': 'homocinetica',
    'caliper': 'caliper-freno',
}

# Cabezas que no describen la pieza por sí solas ("líquido", "aditivo").
_HEADS_GENERICOS = frozenset({'liquido', 'aditivo', 'set', 'pack', 'repuesto'})


def _slug_categoria_ml(nombre: str) -> str:
    tokens = _nombre_busqueda_corto(nombre).split()
    if not tokens:
        return ''
    if tokens[0] not in _HEADS_GENERICOS:
        mapeado = _CATEGORY_SLUG_ML.get(tokens[0])
        if mapeado:
            return mapeado
    # Un token genérico o sin mapeo ("liquido") no busca nada: usa dos.
    return ' '.join(tokens[:2])


# Cilindrada (1.4) y año (2016) no son parte del nombre del modelo; el número
# suelto sí lo es y no se puede botar (Peugeot 208, Kia Rio 5, Mazda 3).
_RE_CILINDRADA_TOKEN = re.compile(r'^\d[.,]\d\d?$')
_RE_ANIO_TOKEN = re.compile(r'^(19|20)\d{2}$')


def _tokens_modelo(modelo: str) -> list[str]:
    return [
        t for t in str(modelo or '').strip().split()
        if t and not _RE_CILINDRADA_TOKEN.match(t) and not _RE_ANIO_TOKEN.match(t)
    ]


def _modelo_busqueda(modelo: str) -> str:
    """Primera palabra útil del modelo (CELERIO HB 1.0 → Celerio)."""
    tokens = _tokens_modelo(modelo)
    return tokens[0] if tokens else str(modelo or '').strip()


def _modelo_busqueda_completo(modelo: str) -> str:
    """Modelo con su variante (BRAVO SPORT TJET → Bravo Sport Tjet).

    La variante manda en el precio: un Bravo T-Jet 1.4 turbo no lleva los
    mismos discos que un Bravo base.
    """
    tokens = _tokens_modelo(modelo)
    return ' '.join(tokens[:3]).title() if tokens else str(modelo or '').strip()


def _nombre_busqueda_corto(nombre: str) -> str:
    """'Termostato de refrigerante' → 'termostato refrigerante' (máx 3 tokens)."""
    raw = unicodedata.normalize('NFD', (nombre or '').lower())
    raw = ''.join(c for c in raw if unicodedata.category(c) != 'Mn')
    tokens = [t for t in re.split(r'[^a-z0-9]+', raw) if t and t not in _STOP_QUERY]
    return ' '.join(tokens[:3])


def _query_repuesto(
    nombre: str,
    *,
    marca: str = '',
    modelo: str = '',
    anio: str | int | None = '',
    compact: bool = False,
) -> str:
    """Query enfocada: 1 repuesto (+ marca). `compact` = slugs cortos para ML."""
    nucleo = _nombre_busqueda_corto(nombre) or str(nombre or '').strip()
    if not nucleo:
        return ''
    if compact:
        # ML falla con slugs largos, pero un token suelto ("liquido") no busca nada:
        # usa la categoría mapeada o dos tokens + marca (termostato-suzuki).
        cabeza = _slug_categoria_ml(nombre) or nucleo
        return ' '.join(p for p in [cabeza, marca] if p).strip()
    extras = [marca, _modelo_busqueda(modelo)]
    return ' '.join(p for p in [nucleo, *extras] if p).strip()


def _url_desde_plantilla(plantilla: str, dominio: str, q: str) -> str:
    q_enc = quote_plus(q)
    q_slug = _slug_query(q)
    if 'listado.mercadolibre' in dominio or ('/{q}' in plantilla):
        return plantilla.replace('{q}', q_slug or q_enc)
    return plantilla.replace('{q}', q_enc)


def construir_urls_busqueda(
    nombres: list[str],
    *,
    marca: str = '',
    modelo: str = '',
    anio: str | int | None = '',
    cilindraje: str = '',
) -> list[str]:
    """Arma URLs de búsqueda: una query por repuesto (no mezclar nombres).

    Prioriza Mercado Libre con slugs cortos (mejor retrieval); luego otras tiendas.
    Tope MAX_URLS (duro 20).
    """
    del anio, cilindraje  # año/cilindraje empeoran retrieval en listados
    max_urls = max(1, min(int(getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_MAX_URLS', 8) or 8), 20))
    nombres_limpios = [str(n).strip()[:120] for n in nombres if str(n).strip()]
    if not nombres_limpios:
        return []
    # Los listados quedan fuera: su precio no se puede atribuir a una tienda.
    fuentes = [f for f in _fuentes() if not _es_fuente_listado(f)]
    if not fuentes:
        return []

    urls: list[str] = []

    def _add(url: str) -> bool:
        if url and url not in urls:
            urls.append(url)
        return len(urls) >= max_urls

    fuente_pri = fuentes[0]
    es_ml = 'mercadolibre' in fuente_pri['dominio']

    # Pasada 1 (ML): slugs de categoría con buen retrieval (termostato-auto, etc.).
    if es_ml:
        for nombre in nombres_limpios:
            q_cat = _slug_categoria_ml(nombre)
            if not q_cat:
                continue
            url = _url_desde_plantilla(fuente_pri['plantilla'], fuente_pri['dominio'], q_cat)
            if _add(url):
                return urls

    # Pasada 2: query compacta marca+pieza (termostato-suzuki) por fuente primaria.
    for nombre in nombres_limpios:
        q = _query_repuesto(
            nombre, marca=marca, modelo=modelo, compact=es_ml,
        )
        if not q:
            continue
        url = _url_desde_plantilla(fuente_pri['plantilla'], fuente_pri['dominio'], q)
        if _add(url):
            return urls

    # Pasada 3: otras tiendas.
    for fuente in fuentes[1:]:
        for nombre in nombres_limpios:
            q = _query_repuesto(
                nombre,
                marca=marca,
                modelo=modelo,
                compact='mercadolibre' in fuente['dominio'],
            )
            if not q:
                continue
            url = _url_desde_plantilla(fuente['plantilla'], fuente['dominio'], q)
            if _add(url):
                return urls

    return urls


def _dominio_de_url(url: str) -> str:
    try:
        host = (urlparse(url).hostname or '').lower()
    except Exception:
        return ''
    if host.startswith('www.'):
        # Mantener www. si la whitelist lo tiene; también aceptar sin www.
        return host
    return host


_HOSTS_LISTADO = ('listado.mercadolibre.cl',)
# Publicación con vendedor: articulo.mercadolibre.cl/MLC-123, /p/MLC123 y las
# fichas de catálogo /up/MLCU123 (muestran precio y vendedor del buy box).
_RE_PUBLICACION_ML = re.compile(r'/(?:p|up)/mlc[a-z]?\d|/mlc-?\d', re.IGNORECASE)


def _es_fuente_listado(fuente: dict[str, str]) -> bool:
    """La fuente solo produce listados: no hay tienda a la que atribuir el precio."""
    dom = str(fuente.get('dominio') or '').lower()
    if not dom:
        return False
    return 'mercadolibre' in dom or any(
        dom == h or dom.endswith('.' + h) for h in _HOSTS_LISTADO
    )


_RE_PATH_NO_FICHA = re.compile(r'/(blog|blogs|noticias|glossary|pagina)/', re.IGNORECASE)


# ccTLD de la región: un precio en pesos colombianos o euros no orienta nada.
_TLDS_FORANEOS = (
    '.es', '.mx', '.co', '.ec', '.ar', '.pe', '.br', '.uy', '.py', '.bo',
    '.ve', '.us', '.gt', '.cr', '.pa', '.do',
)


# Euros, dólares o pesos de otro país: la ficha no cotiza en CLP.
_RE_MONEDA_FORANEA = re.compile(r'(€|EUR\b|US\s?\$|USD\b|MXN\b|COP\b|ARS\b|R\$)', re.IGNORECASE)


def _raiz_dominio(host: str) -> str:
    return (host or '').lower().removeprefix('www.').split('.')[0]


def _es_tienda_chilena(url: str, whitelist: set[str], texto: str = '') -> bool:
    """Tienda .cl (o whitelist explícita). Un precio de otro país no orienta nada."""
    if _dominio_permitido(url, whitelist):
        return True
    host = _dominio_de_url(url)
    if not host or any(host.endswith(t) for t in _TLDS_FORANEOS):
        return False
    if host.endswith('.cl'):
        return True
    # Misma tienda con otro TLD (mundorepuestos.com ↔ mundorepuestos.cl).
    if _raiz_dominio(host) in {_raiz_dominio(f['dominio']) for f in _fuentes()}:
        return True
    # TLD genérico (.shop, .com): la búsqueda ya viene acotada a Chile, así que
    # basta con que la ficha cotice en pesos y no en otra moneda.
    return bool(texto) and _precio_desde_texto(texto) > 0 and not _RE_MONEDA_FORANEA.search(texto)


def _es_pagina_sin_ficha(url: str) -> bool:
    """Home/blog/landing: puede citar montos que no son el precio de la pieza."""
    try:
        path = urlparse(url).path or '/'
    except Exception:
        return True
    if path.strip('/') == '':
        return True
    return bool(_RE_PATH_NO_FICHA.search(path))


def _es_listado_sin_vendedor(url: str) -> bool:
    """True si la URL agrega vendedores: no hay tienda a la que atribuir el precio."""
    host = _dominio_de_url(url)
    if not host:
        return False
    if any(host == h or host.endswith('.' + h) for h in _HOSTS_LISTADO):
        return True
    if 'mercadolibre' in host:
        try:
            path = urlparse(url).path or '/'
        except Exception:
            return True
        return not _RE_PUBLICACION_ML.search(path)
    return False


def _dominio_permitido(url: str, whitelist: set[str]) -> bool:
    host = _dominio_de_url(url)
    if not host:
        return False
    if host in whitelist:
        return True
    bare = host[4:] if host.startswith('www.') else host
    if bare in whitelist or f'www.{bare}' in whitelist:
        return True
    # Permitir subdominios (ej. articulo.mercadolibre.cl bajo listado.mercadolibre.cl).
    for allowed in whitelist:
        allowed_bare = allowed[4:] if allowed.startswith('www.') else allowed
        if host.endswith('.' + allowed_bare) or host == allowed_bare:
            return True
        # mercadolibre.cl ↔ listado.mercadolibre.cl
        if 'mercadolibre' in allowed_bare and 'mercadolibre' in host:
            return True
    return False


def _rpd_key() -> str:
    return f'{_CACHE_RPD_PREFIX}{date.today().isoformat()}'


def cuota_diaria_disponible() -> bool:
    limite = int(getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_RPD', 200) or 200)
    if limite <= 0:
        return False
    usados = int(cache.get(_rpd_key()) or 0)
    return usados < limite


def _consumir_cuota_diaria() -> bool:
    if not cuota_diaria_disponible():
        return False
    key = _rpd_key()
    try:
        usados = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=60 * 60 * 36)
        usados = 1
    limite = int(getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_RPD', 200) or 200)
    return int(usados) <= limite


def _urls_exitosas_metadata(body: dict[str, Any]) -> set[str]:
    """Extrae URLs con retrieval exitoso de url_context_metadata (REST o camelCase)."""
    ok: set[str] = set()
    try:
        candidates = body.get('candidates') or []
        if not candidates:
            return ok
        cand0 = candidates[0] or {}
        meta = (
            cand0.get('url_context_metadata')
            or cand0.get('urlContextMetadata')
            or {}
        )
        items = meta.get('url_metadata') or meta.get('urlMetadata') or []
        for item in items:
            if not isinstance(item, dict):
                continue
            status = str(
                item.get('url_retrieval_status')
                or item.get('urlRetrievalStatus')
                or '',
            )
            retrieved = str(
                item.get('retrieved_url')
                or item.get('retrievedUrl')
                or item.get('url')
                or '',
            ).strip()
            # Algunos responses omiten status y solo traen retrieved_url.
            status_ok = (not status) or status in _URL_RETRIEVAL_OK or 'SUCCESS' in status.upper()
            if retrieved and status_ok:
                ok.add(retrieved)
                ok.add(_dominio_de_url(retrieved))
    except (TypeError, IndexError, AttributeError):
        return ok
    return ok


def _raiz_registrable(host: str) -> str:
    """Aproxima eTLD+1 para .cl/.com (listado.mercadolibre.cl → mercadolibre.cl)."""
    h = (host or '').lower().strip('.')
    if h.startswith('www.'):
        h = h[4:]
    parts = [p for p in h.split('.') if p]
    if len(parts) >= 2:
        return '.'.join(parts[-2:])
    return h


def _dominios_relacionados(host: str) -> set[str]:
    """Host + variantes www + raíz registrable (para ML y subdominios de tienda)."""
    out: set[str] = set()
    h = (host or '').lower().strip()
    if not h:
        return out
    out.add(h)
    bare = h[4:] if h.startswith('www.') else h
    out.add(bare)
    out.add(f'www.{bare}')
    raiz = _raiz_registrable(h)
    if raiz:
        out.add(raiz)
        out.add(f'www.{raiz}')
    return out


def _dominios_de_urls(urls: list[str]) -> set[str]:
    out: set[str] = set()
    for u in urls or []:
        host = _dominio_de_url(str(u))
        out |= _dominios_relacionados(host)
        # También la URL completa ayuda al match exacto de retrieval.
        if str(u).startswith('http'):
            out.add(str(u).strip())
    return out


def _host_relacionado_con(host: str, conjunto: set[str]) -> bool:
    """True si host comparte sitio con algún valor del conjunto (URL o dominio)."""
    if not host or not conjunto:
        return False
    relacionados = _dominios_relacionados(host)
    for u in conjunto:
        if not isinstance(u, str) or not u:
            continue
        if u.startswith('http'):
            u_host = _dominio_de_url(u)
        else:
            u_host = u.lower().strip()
        if not u_host:
            continue
        if u_host in relacionados or host in _dominios_relacionados(u_host):
            return True
        # Substring seguro por raíz (mercadolibre.cl ⊂ articulo.mercadolibre.cl).
        raiz_h = _raiz_registrable(host)
        raiz_u = _raiz_registrable(u_host)
        if raiz_h and raiz_h == raiz_u:
            return True
    return False


def _precio_en_rango(precio: int) -> bool:
    minimo = int(getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_PRECIO_MIN', 1000) or 1000)
    maximo = int(getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_PRECIO_MAX', 3_000_000) or 3_000_000)
    return minimo <= precio <= maximo


def _tienda_por_dominio(dominio: str) -> str:
    host = (dominio or '').lower()
    for fuente in _fuentes():
        d = fuente['dominio']
        if host == d or host.endswith('.' + d.lstrip('www.')) or d in host:
            return fuente['nombre']
    if 'mercadolibre' in host:
        return 'Mercado Libre'
    # Tienda fuera de la lista configurada: nombre legible desde el dominio.
    raiz = host.removeprefix('www.').split('.')[0].replace('-', ' ').strip()
    return (raiz.title() or host)[:200]


def _construir_prompt(
    *,
    nombres: list[str],
    urls: list[str],
    marca: str,
    modelo: str,
    anio: str,
    cilindraje: str,
    tipo_motor: str,
    servicio_nombre: str,
) -> str:
    vehiculo = ' '.join(
        p for p in [marca, modelo, anio, cilindraje, tipo_motor] if p
    ).strip() or 'desconocido'
    lista_reps = '\n'.join(f'- {n}' for n in nombres)
    lista_urls = '\n'.join(f'- {u}' for u in urls)
    return f"""Eres un extractor de precios de repuestos automotrices en Chile.
LEE el contenido de las URLs con la herramienta url_context.
NO inventes precios ni URLs: solo datos visibles en las páginas leídas.

Vehículo de referencia (orientativo): {vehiculo}
Servicio: {servicio_nombre or 'N/A'}

Repuestos a buscar:
{lista_reps}

URLs:
{lista_urls}

Reglas:
1. Si la página muestra un producto de la MISMA CATEGORÍA del repuesto, reporta encontrado=true con el mejor candidato visible (aunque no diga el modelo exacto).
2. compatibilidad: alta si menciona marca/modelo del auto; media si es la categoría correcta; baja si es genérico del rubro. NO uses encontrado=false solo por duda de año.
3. marca_repuesto = marca de la PIEZA (Bosch, Gates, Wahler, NGK, etc.). Si no aparece, "". NUNCA "GENÉRICO", "Original", "N/A" ni la marca del auto.
4. tienda = quién vende. En una tienda es el sitio (AutoPlanet, Refax, …); en una publicación de marketplace es el nombre del vendedor visible, no "Mercado Libre". url = link de la publicación o producto leído (https).
5. precio_clp = entero CLP sin puntos ni símbolo.
6. Solo encontrado=false si en las páginas NO hay ningún producto relacionado a ese repuesto.
7. Responde SOLO JSON válido (sin markdown):
{{
  "resultados": [
    {{
      "nombre_buscado": "texto del repuesto",
      "encontrado": true,
      "nombre_producto": "...",
      "marca_repuesto": "...",
      "precio_clp": 0,
      "tienda": "...",
      "url": "https://...",
      "compatibilidad": "alta|media|baja"
    }}
  ]
}}
Incluye un ítem por cada repuesto buscado.
"""


def _normalizar_item_gemini(item: Any) -> dict[str, Any] | None:
    """Unifica claves alternativas que a veces devuelve Gemini."""
    if not isinstance(item, dict):
        return None
    out = {k: ('' if v is None else v) for k, v in item.items()}
    if not out.get('nombre_producto'):
        out['nombre_producto'] = out.get('titulo') or out.get('nombre') or ''
    if not out.get('url'):
        out['url'] = out.get('link_tienda') or out.get('link') or out.get('link_producto') or ''
    if not out.get('marca_repuesto'):
        out['marca_repuesto'] = out.get('marca') or ''
    if not out.get('nombre_buscado'):
        out['nombre_buscado'] = out.get('query') or out.get('nombre_producto') or ''
    # Si trajo producto/precio y omitió el flag, asumir encontrado.
    if out.get('encontrado') in ('', None) and (
        out.get('nombre_producto') or _to_int_clp(out.get('precio_clp')) > 0
    ):
        out['encontrado'] = True
    return out


def _motivo_descarte(
    item: dict[str, Any],
    *,
    urls_ok: set[str],
    whitelist: set[str],
    dominios_solicitados: set[str] | None = None,
) -> str | None:
    """None si válido; si no, razón corta para logs."""
    if not isinstance(item, dict):
        return 'no_dict'
    encontrado = item.get('encontrado')
    if encontrado in (False, None, '', 0, 'false', 'False', '0'):
        return 'no_encontrado'
    url = str(item.get('url') or '').strip()
    if not url.startswith('http'):
        return 'url_invalida'
    if not _dominio_permitido(url, whitelist):
        return f'dominio_fuera_whitelist:{_dominio_de_url(url)}'
    host = _dominio_de_url(url)
    if _es_listado_sin_vendedor(url):
        return f'listado_sin_vendedor:{host}'
    doms_req = dominios_solicitados or set()
    retrieval_ok = _host_relacionado_con(host, urls_ok) or (url in urls_ok)
    solicitado_ok = _host_relacionado_con(host, doms_req)
    # El host tiene que venir de una URL leída o pedida (así entra
    # articulo.mercadolibre.cl tras leer listado.*). Estar en la whitelist no
    # basta: el modelo reportaba productos de tiendas que nunca se leyeron.
    if not retrieval_ok and not solicitado_ok:
        return f'dominio_sin_contexto:{host}'
    nombre_prod = str(item.get('nombre_producto') or item.get('nombre_buscado') or '').strip()
    if not nombre_prod:
        return 'sin_nombre'
    return None


def _validar_resultado(
    item: dict[str, Any],
    *,
    urls_ok: set[str],
    whitelist: set[str],
    dominios_solicitados: set[str] | None = None,
) -> dict[str, Any] | None:
    motivo = _motivo_descarte(
        item,
        urls_ok=urls_ok,
        whitelist=whitelist,
        dominios_solicitados=dominios_solicitados,
    )
    if motivo:
        return None
    url = str(item.get('url') or '').strip()
    host = _dominio_de_url(url)
    doms_req = dominios_solicitados or set()
    retrieval_ok = _host_relacionado_con(host, urls_ok) or (url in urls_ok)
    marca = _marca_repuesto_valida(item.get('marca_repuesto'))
    precio = _to_int_clp(item.get('precio_clp'))
    precio_ok = _precio_en_rango(precio)
    # Marca/tienda deben llegar a la UI aunque el precio venga mal parseado.
    if not precio_ok:
        precio = 0
    nombre_prod = str(item.get('nombre_producto') or item.get('nombre_buscado') or '').strip()[:200]
    if not marca:
        marca = _marca_repuesto_valida(_inferir_marca_desde_nombre(nombre_prod))
    tienda = str(item.get('tienda') or '').strip()[:200] or _tienda_por_dominio(host)
    if not marca and not tienda and not precio_ok:
        return None
    compat = str(item.get('compatibilidad') or '').strip().lower()[:20]
    if compat not in ('alta', 'media', 'baja'):
        compat = 'media'
    conf = 0.8 if compat == 'alta' else (0.7 if compat == 'media' else 0.55)
    if not retrieval_ok:
        conf = min(conf, 0.65)
    if not precio_ok:
        conf = min(conf, 0.55)
    return {
        'nombre_buscado': str(item.get('nombre_buscado') or '').strip()[:200],
        'nombre_producto': nombre_prod,
        'marca_repuesto': marca,
        'precio_clp': precio,
        'tienda': tienda,
        'dominio': host[:200],
        'url': url[:500],
        'compatibilidad': compat,
        'confianza': conf,
    }


TAVILY_SEARCH_ENDPOINT = 'https://api.tavily.com/search'


def tavily_habilitada() -> bool:
    return bool((getattr(settings, 'TAVILY_API_KEY', '') or '').strip())


def _tavily_buscar_uno(
    query: str,
    *,
    max_results: int = 4,
    timeout: int = 20,
) -> list[dict[str, str]]:
    """1 crédito Tavily (search_depth=basic). Devuelve [{title, url, content}]."""
    api_key = (getattr(settings, 'TAVILY_API_KEY', '') or '').strip()
    if not api_key or not query.strip():
        return []
    try:
        resp = requests.post(
            TAVILY_SEARCH_ENDPOINT,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'query': query.strip()[:400],
                'search_depth': 'basic',
                'max_results': max(1, min(max_results, 10)),
                # `country` + `include_domains` juntos devuelven 0 resultados, y
                # restringir a un puñado de tiendas trae landings y blogs en vez
                # de fichas: se busca Chile abierto y se filtra al validar.
                'country': 'chile',
                'include_answer': False,
                'include_raw_content': False,
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.warning('tavily_buscar: error de red: %s', exc)
        return []
    if resp.status_code != 200:
        logger.warning('tavily_buscar: status=%s body=%s', resp.status_code, resp.text[:300])
        return []
    try:
        data = resp.json()
    except ValueError:
        return []
    out: list[dict[str, str]] = []
    for r in data.get('results') or []:
        if not isinstance(r, dict):
            continue
        url = str(r.get('url') or '').strip()
        if not url:
            continue
        out.append({
            'title': str(r.get('title') or '')[:200],
            'url': url[:500],
            'content': str(r.get('content') or '')[:700],
        })
    return out


TAVILY_EXTRACT_ENDPOINT = 'https://api.tavily.com/extract'


def _tavily_extraer(urls: list[str], *, timeout: int = 25) -> dict[str, str]:
    """Ficha completa del producto (specs/descripción) para rescatar marca/precio.

    Barato: ~1 crédito cada 5 URLs exitosas (basic). Se llama 1 vez por
    cotización con el mejor candidato de cada repuesto (máx 20 URLs).
    """
    api_key = (getattr(settings, 'TAVILY_API_KEY', '') or '').strip()
    urls_unicas = [u for u in dict.fromkeys(urls) if u][:20]
    if not api_key or not urls_unicas:
        return {}
    try:
        resp = requests.post(
            TAVILY_EXTRACT_ENDPOINT,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'urls': urls_unicas,
                'extract_depth': 'basic',
                'format': 'text',
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.warning('tavily_extraer: error de red: %s', exc)
        return {}
    if resp.status_code != 200:
        logger.info('tavily_extraer: status=%s (se sigue con snippets de búsqueda)', resp.status_code)
        return {}
    try:
        data = resp.json()
    except ValueError:
        return {}
    out: dict[str, str] = {}
    for r in data.get('results') or []:
        if not isinstance(r, dict):
            continue
        url = str(r.get('url') or '').strip()
        raw = str(r.get('raw_content') or '').strip()
        if url and raw:
            out[url] = raw[:2000]
    return out


# El `$` no puede venir pegado a letras: así "US$ 45.00" y "R$ 45,00" no entran
# como pesos. "CLP" sí es prefijo válido, con o sin signo.
_PRECIO_CLP_RE = re.compile(r'(?:(?<![A-Za-z])\$|CLP\s?\$?)\s?([\d.,]{4,10})')


def _precio_desde_texto(texto: str) -> int:
    """Extrae el primer precio CLP plausible de un snippet ('$ 18.990 ...')."""
    for m in _PRECIO_CLP_RE.finditer(texto or ''):
        val = _to_int_clp(m.group(1))
        if _precio_en_rango(val):
            return val
    return 0


def _construir_prompt_tavily(
    *,
    candidatos_por_nombre: dict[str, list[dict[str, str]]],
    marca: str,
    modelo: str,
    anio: str,
    cilindraje: str,
    tipo_motor: str,
    servicio_nombre: str,
) -> str:
    vehiculo = ' '.join(p for p in [marca, modelo, anio, cilindraje, tipo_motor] if p).strip() or 'desconocido'
    bloques = []
    for nombre, candidatos in candidatos_por_nombre.items():
        lineas = '\n'.join(
            f'  [{i}] título: {c["title"]}\n      url: {c["url"]}'
            f'\n      casa especialista: {"sí" if _es_de_especialista(c) else "no"}'
            # El texto se recorta, así que el monto detectado va explícito.
            f'\n      precio detectado: {_precio_desde_texto(c.get("content") or "") or "ninguno"}'
            f'\n      texto: {c["content"][:400]}'
            for i, c in enumerate(candidatos)
        ) or '  (sin resultados)'
        bloques.append(f'Repuesto: "{nombre}"\n{lineas}')
    cuerpo = '\n\n'.join(bloques)
    return f"""Eres un extractor de precios de repuestos automotrices en Chile.
Se te dan, por cada repuesto, resultados REALES de búsqueda (título/url/texto) de tiendas chilenas.
NO inventes datos que no estén en el texto entregado. Usa SOLO la información de estos candidatos.

Vehículo a cotizar: {vehiculo}
Servicio: {servicio_nombre or 'N/A'}

{cuerpo}

Para cada repuesto, elige el MEJOR candidato de su lista (por índice):
1. Prioridad: (a) ficha que nombre el modelo y la variante/motor de ESTE vehículo, (b) ficha que nombre marca y modelo, (c) casa especialista por sobre retail generalista. Si ningún candidato nombra el vehículo, sirve uno de la categoría correcta (hay insumos universales).
2. compatibilidad: alta si el título/texto nombra modelo y variante/motor/año; media si nombra la marca o es un insumo universal; baja si es genérico.
3. marca_repuesto = marca de la PIEZA visible en título/texto (Bosch, Gates, NGK, etc.). Si no aparece, "". NUNCA "Original", "GENÉRICO" ni la marca del auto.
4. precio_clp = precio CLP del candidato elegido (entero, sin puntos/símbolo). Si el candidato trae "precio detectado", usa ese monto salvo que el texto muestre claramente otro precio de la pieza; si no hay ninguno, 0.
4b. Entre candidatos de la misma categoría, PREFIERE el que tenga precio; uno sin monto solo si ninguno lo trae (una línea sin precio no le sirve al taller).
5. url = EXACTAMENTE la url del candidato elegido (cópiala tal cual, no la modifiques).
6. tienda = quién vende: el sitio según el dominio (AutoPlanet, Refax, etc.) o, si es una publicación de marketplace, el nombre del vendedor visible en el texto.
7. Si NINGÚN candidato de la lista sirve, encontrado=false.
8. Responde SOLO JSON válido (sin markdown):
{{
  "resultados": [
    {{
      "nombre_buscado": "...",
      "encontrado": true,
      "nombre_producto": "...",
      "marca_repuesto": "...",
      "precio_clp": 0,
      "tienda": "...",
      "url": "https://...",
      "compatibilidad": "alta|media|baja"
    }}
  ]
}}
Incluye un ítem por cada repuesto listado arriba.
"""


def _gemini_generar(prompt: str, *, timeout: int, use_url_context: bool) -> dict[str, Any] | None:
    api_key = (getattr(settings, 'GEMINI_API_KEY', '') or '').strip()
    model = (
        getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_MODEL', '')
        or getattr(settings, 'GEMINI_MODEL', 'gemini-3.1-flash-lite')
        or 'gemini-3.1-flash-lite'
    ).strip()
    endpoint = (
        f'https://generativelanguage.googleapis.com/v1beta/models/{model}:'
        f'generateContent?key={api_key}'
    )
    payload: dict[str, Any] = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {'temperature': 0.2, 'maxOutputTokens': 4096},
    }
    if use_url_context:
        payload['tools'] = [{'url_context': {}}]
        if getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_GROUNDING', False):
            payload['tools'].append({'google_search': {}})
    # El modelo saturado (503) o con cuota momentánea (429) dejaba la cotización
    # entera sin precios: se reintenta una vez antes de rendirse.
    for intento in (1, 2):
        try:
            resp = requests.post(endpoint, json=payload, timeout=timeout)
        except requests.RequestException as exc:
            logger.warning('busqueda_web_repuestos: error de red Gemini: %s', exc)
            return None
        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                return None
        logger.warning(
            'busqueda_web_repuestos: Gemini status=%s body=%s',
            resp.status_code,
            resp.text[:300],
        )
        if resp.status_code not in (429, 503) or intento == 2:
            return None
        time.sleep(_ESPERA_REINTENTO_GEMINI)
    return None


def _escalera_consultas(
    nombre: str,
    *,
    marca: str,
    modelo: str,
    cilindraje: str,
    casas: list[dict[str, Any]],
) -> list[str]:
    """Consultas de la más específica a la más tolerante, sin repetir.

    Se recorre hasta encontrar precio: primero la casa que trabaja la marca,
    después la búsqueda abierta con la variante, y por último el modelo a secas
    (hay equipamientos como "RIO 5 EX" que no existen en las fichas y dejarían
    la línea sin ninguna referencia).
    """
    completo = _modelo_busqueda_completo(modelo)
    base = ' '.join(p for p in [nombre, marca, completo, cilindraje] if p)
    corta = ' '.join(p for p in [nombre, marca, _modelo_busqueda(modelo)] if p)
    consultas = [f"{base} {casa['alias']}" for casa in casas[:1]] + [base, corta]
    vistas: set[str] = set()
    out: list[str] = []
    for q in consultas:
        clave = _norm(q)
        if q and clave not in vistas:
            vistas.add(clave)
            out.append(q)
    return out


def _candidatos_validos(query: str, whitelist: set[str]) -> list[dict[str, Any]]:
    """Fichas de tienda chilena para la consulta, sin listados ni blogs."""
    return [
        c for c in _tavily_buscar_uno(query, max_results=6)
        if _es_tienda_chilena(c['url'], whitelist, c.get('content') or '')
        and not _es_listado_sin_vendedor(c['url'])
        and not _es_pagina_sin_ficha(c['url'])
    ]


def _ordenar_candidatos(
    crudos: list[dict[str, Any]],
    *,
    tokens_vehiculo: list[str] | None = None,
    priorizar_precio: bool = False,
) -> list[dict[str, Any]]:
    """Manda la ficha que nombra a ESTE auto; después la casa y el precio.

    El calce con el vehículo funciona para cualquier marca y modelo sin
    configurar nada: una ficha que dice "Bravo Sport 1.4 T-Jet" vale más que
    una que solo dice "pastillas de freno". Antes de pedir la ficha completa se
    mira a la casa especialista; ya leída, una ficha sin monto pasa al final.
    """
    unicos: dict[str, dict[str, Any]] = {}
    for c in crudos:
        unicos.setdefault(c['url'], c)
    candidatos = list(unicos.values())
    # El retail generalista solo se usa si no hay ninguna casa de repuestos.
    especializados = [c for c in candidatos if not _es_generalista(c['url'])]
    if especializados:
        candidatos = especializados
    tokens = tokens_vehiculo or []

    def rango(c: dict[str, Any]) -> tuple[int, ...]:
        calce = -_calce_vehiculo(c, tokens)
        sin_precio = 0 if _precio_desde_texto(c.get('content') or '') else 1
        no_esp = 0 if _es_de_especialista(c) else 1
        if priorizar_precio:
            return (sin_precio, calce, no_esp)
        return (calce, no_esp, sin_precio)

    return sorted(candidatos, key=rango)


def _candidatos_de_linea(
    candidatos_por_nombre: dict[str, list[dict[str, Any]]],
    nombre_buscado: Any,
) -> list[dict[str, Any]]:
    """Candidatos de la línea tolerando que el modelo reescriba el nombre."""
    nombre = str(nombre_buscado or '').strip()
    if not nombre:
        return []
    exacto = candidatos_por_nombre.get(nombre)
    if exacto is not None:
        return exacto
    clave = _clave_fuzzy(nombre)
    if not clave:
        return []
    for original, candidatos in candidatos_por_nombre.items():
        if _clave_fuzzy(original) == clave:
            return candidatos
    return []


def _buscar_repuestos_web_tavily(
    nombres_limpios: list[str],
    *,
    marca: str,
    modelo: str,
    anio: str | int | None,
    cilindraje: str,
    tipo_motor: str,
    servicio_nombre: str,
    timeout: int,
) -> dict[str, dict[str, Any]]:
    """Agregador Tavily (JSON real) + Gemini solo como filtro/formateador."""
    whitelist = _dominios_whitelist()
    casas_marca = _especialistas_de_marca(marca)
    tokens_veh = _tokens_vehiculo(marca, modelo, anio, cilindraje)
    candidatos_por_nombre: dict[str, list[dict[str, str]]] = {}
    for nombre in nombres_limpios:
        crudos: list[dict[str, Any]] = []
        for query in _escalera_consultas(
            nombre, marca=marca, modelo=modelo, cilindraje=cilindraje, casas=casas_marca,
        ):
            crudos += _candidatos_validos(query, whitelist)
            # Basta una ficha con monto legible: no se gastan más búsquedas.
            if any(_precio_desde_texto(c.get('content') or '') for c in crudos):
                break
        candidatos = _ordenar_candidatos(crudos, tokens_vehiculo=tokens_veh)[:4]
        if candidatos:
            candidatos_por_nombre[nombre] = candidatos

    if not candidatos_por_nombre:
        logger.info('busqueda_web_repuestos[tavily]: 0 candidatos para %s repuestos', len(nombres_limpios))
        return {}

    # Ficha completa del mejor candidato: la marca casi nunca aparece en el
    # título. Si ningún candidato del repuesto muestra monto, se piden dos más
    # para rescatar el precio antes de dejar la línea sin nada.
    urls_ficha: list[str] = []
    for candidatos in candidatos_por_nombre.values():
        if not candidatos:
            continue
        urls_ficha.append(candidatos[0]['url'])
        if all(not _precio_desde_texto(c.get('content') or '') for c in candidatos):
            urls_ficha.extend(c['url'] for c in candidatos[1:3])
    fichas = _tavily_extraer(urls_ficha)
    if fichas:
        for nombre, candidatos in candidatos_por_nombre.items():
            con_ficha = [
                {**c, 'content': fichas[c['url']]} if c['url'] in fichas else c
                for c in candidatos
            ]
            candidatos_por_nombre[nombre] = _ordenar_candidatos(
                con_ficha, tokens_vehiculo=tokens_veh, priorizar_precio=True,
            )

    prompt = _construir_prompt_tavily(
        candidatos_por_nombre=candidatos_por_nombre,
        marca=marca,
        modelo=modelo,
        anio=str(anio or ''),
        cilindraje=cilindraje,
        tipo_motor=tipo_motor,
        servicio_nombre=servicio_nombre,
    )
    body = _gemini_generar(prompt, timeout=timeout, use_url_context=False)
    if not body:
        return {}

    text = ''
    try:
        parts = body['candidates'][0]['content']['parts']
        text = ''.join(str(p.get('text') or '') for p in parts if isinstance(p, dict) and p.get('text'))
    except (KeyError, IndexError, TypeError):
        return {}
    parsed = _parse_json(text) or {}
    resultados = parsed.get('resultados') or []
    if not isinstance(resultados, list):
        return {}

    # URLs válidas = las que Tavily realmente devolvió (anti-alucinación).
    urls_reales: set[str] = set()
    for cands in candidatos_por_nombre.values():
        urls_reales |= {c['url'] for c in cands}

    out: dict[str, dict[str, Any]] = {}
    for raw in resultados:
        item = _normalizar_item_gemini(raw)
        if not item or not bool(item.get('encontrado')):
            continue
        url = str(item.get('url') or '').strip()
        # Los candidatos ya pasaron el filtro de tienda antes del prompt.
        if url not in urls_reales:
            continue
        if _es_listado_sin_vendedor(url) or _es_pagina_sin_ficha(url):
            # Sin ficha de una tienda concreta no hay precio atribuible.
            continue
        host = _dominio_de_url(url)
        marca_it = _marca_repuesto_valida(item.get('marca_repuesto'))
        nombre_prod = str(item.get('nombre_producto') or item.get('nombre_buscado') or '').strip()[:200]
        if not nombre_prod:
            continue
        if not marca_it:
            marca_it = _marca_repuesto_valida(_inferir_marca_desde_nombre(nombre_prod))
        # El modelo parafrasea el nombre buscado; con igualdad exacta la lista
        # quedaba vacía y los dos rescates de abajo no hacían nada.
        candidatos_linea = _candidatos_de_linea(candidatos_por_nombre, item.get('nombre_buscado'))
        precio = _to_int_clp(item.get('precio_clp'))
        if not _precio_en_rango(precio):
            # Backstop: intenta extraer el precio del snippet original.
            snippet = next((c['content'] for c in candidatos_linea if c['url'] == url), '')
            precio = _precio_desde_texto(snippet)
        if not _precio_en_rango(precio):
            # El modelo eligió una ficha sin monto habiendo otra con precio:
            # se cambia de candidato, porque una línea en $0 no sirve.
            with_precio = [
                (c, _precio_desde_texto(c.get('content') or ''))
                for c in candidatos_linea if c['url'] != url
            ]
            alternativa = next(((c, p) for c, p in with_precio if _precio_en_rango(p)), None)
            if alternativa:
                candidato_alt, precio = alternativa
                url = candidato_alt['url']
                host = _dominio_de_url(url)
                nombre_prod = str(candidato_alt.get('title') or nombre_prod)[:200]
                item['tienda'] = ''
        if not _precio_en_rango(precio):
            # Guardar la línea en $0 envenena el cache y la deja igual sin
            # referencia; se descarta para que el rescate del snippet la tome.
            continue
        tienda = str(item.get('tienda') or '').strip()[:200] or _tienda_por_dominio(host)
        compat = str(item.get('compatibilidad') or '').strip().lower()[:20]
        if compat not in ('alta', 'media', 'baja'):
            compat = 'media'
        conf = 0.85 if compat == 'alta' else (0.75 if compat == 'media' else 0.6)
        clave = _clave_fuzzy(str(item.get('nombre_buscado') or nombre_prod))
        if not clave:
            continue
        prev = out.get(clave)
        if prev and float(prev.get('confianza') or 0) >= conf:
            continue
        out[clave] = {
            'nombre_buscado': str(item.get('nombre_buscado') or '').strip()[:200],
            'nombre_producto': nombre_prod,
            'marca_repuesto': marca_it,
            'precio_clp': precio,
            'tienda': tienda,
            'dominio': host[:200],
            'url': url,
            'compatibilidad': compat,
            'confianza': conf,
        }
        # Aprendizaje: si la ficha nombraba al auto, esa casa sirve para la
        # marca y en la próxima cotización se la consulta primero.
        candidato = next(
            (c for c in candidatos_por_nombre.get(item.get('nombre_buscado') or '', []) if c['url'] == url),
            None,
        )
        calce = _calce_vehiculo(candidato or {'title': nombre_prod}, tokens_veh)
        registrar_casa_de_marca(
            marca, url, tienda,
            acierto=compat == 'alta' or calce >= max(2, len(tokens_veh) // 2),
        )
    # El modelo omite líneas cuando la ficha no menciona el auto. Una ficha de
    # tienda chilena con monto legible ya es una referencia: vale más que dejar
    # la línea en $0, así que se arma el hit sin pasar por el modelo.
    rescatadas = 0
    for nombre, candidatos in candidatos_por_nombre.items():
        clave = _clave_fuzzy(nombre)
        if not clave or clave in out:
            continue
        rescate = next(
            (
                (c, precio)
                for c, precio in (
                    (c, _precio_desde_texto(c.get('content') or '')) for c in candidatos
                )
                if _precio_en_rango(precio)
            ),
            None,
        )
        if not rescate:
            continue
        candidato, precio = rescate
        host = _dominio_de_url(candidato['url'])
        nombre_prod = str(candidato.get('title') or nombre)[:200]
        calce = _calce_vehiculo(candidato, tokens_veh)
        out[clave] = {
            'nombre_buscado': nombre[:200],
            'nombre_producto': nombre_prod,
            'marca_repuesto': _marca_repuesto_valida(_inferir_marca_desde_nombre(nombre_prod)),
            'precio_clp': precio,
            'tienda': _tienda_por_dominio(host),
            'dominio': host[:200],
            'url': candidato['url'],
            'compatibilidad': 'media' if calce >= 2 else 'baja',
            'confianza': 0.7 if calce >= 2 else 0.6,
        }
        rescatadas += 1

    sin_hit = [n for n in nombres_limpios if _clave_fuzzy(n) not in out]
    logger.info(
        'busqueda_web_repuestos[tavily]: %s hits válidos de %s repuestos consultados '
        '(%s con candidatos, %s rescatados del snippet) sin_hit=%s',
        len(out),
        len(nombres_limpios),
        len(candidatos_por_nombre),
        rescatadas,
        sin_hit,
    )
    return out


def buscar_repuestos_web(
    nombres: list[str],
    *,
    vehiculo: dict[str, Any] | None = None,
    servicio_nombre: str = '',
) -> dict[str, dict[str, Any]]:
    """Punto de entrada único: Tavily (si hay API key) y luego url_context para lo faltante."""
    nombres_limpios = [str(n).strip()[:200] for n in nombres if str(n).strip()]
    if not nombres_limpios:
        return {}

    veh = vehiculo or {}
    marca = str(veh.get('marca') or '').strip()
    modelo = str(veh.get('modelo') or '').strip()
    anio = veh.get('anio') or ''
    cilindraje = str(veh.get('cilindraje') or '').strip()
    tipo_motor = str(veh.get('tipo_motor') or '').strip()
    timeout = int(getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_TIMEOUT', 45) or 45)

    resultados: dict[str, dict[str, Any]] = {}
    pendientes = list(nombres_limpios)

    if tavily_habilitada() and (getattr(settings, 'GEMINI_API_KEY', '') or '').strip():
        try:
            resultados = _buscar_repuestos_web_tavily(
                nombres_limpios,
                marca=marca,
                modelo=modelo,
                anio=anio,
                cilindraje=cilindraje,
                tipo_motor=tipo_motor,
                servicio_nombre=servicio_nombre,
                timeout=timeout,
            )
        except Exception as exc:
            logger.warning('busqueda_web_repuestos[tavily]: fallo inesperado: %s', exc)
            resultados = {}
        claves_resueltas = {_clave_fuzzy(n) for n in nombres_limpios} & {
            _clave_fuzzy(v.get('nombre_buscado') or '') for v in resultados.values()
        }
        pendientes = [n for n in nombres_limpios if _clave_fuzzy(n) not in claves_resueltas] or (
            [] if resultados else nombres_limpios
        )

    if not pendientes or not busqueda_web_habilitada():
        return resultados

    legacy = _buscar_repuestos_web_url_context(
        pendientes,
        marca=marca,
        modelo=modelo,
        anio=anio,
        cilindraje=cilindraje,
        tipo_motor=tipo_motor,
        servicio_nombre=servicio_nombre,
        timeout=timeout,
    )
    resultados.update(legacy)
    return resultados


def _buscar_repuestos_web_url_context(
    nombres_limpios: list[str],
    *,
    marca: str,
    modelo: str,
    anio: str | int | None,
    cilindraje: str,
    tipo_motor: str,
    servicio_nombre: str,
    timeout: int,
) -> dict[str, dict[str, Any]]:
    """Fallback: Gemini adivina/lee URLs de tiendas con la tool `url_context`."""
    if not busqueda_web_habilitada():
        return {}
    if not cuota_diaria_disponible():
        logger.warning('busqueda_web_repuestos: tope diario RPD alcanzado')
        return {}

    urls = construir_urls_busqueda(
        nombres_limpios,
        marca=marca,
        modelo=modelo,
        anio=anio,
        cilindraje=cilindraje,
    )
    if not urls:
        return {}

    if not _consumir_cuota_diaria():
        logger.warning('busqueda_web_repuestos: no se pudo consumir cuota diaria')
        return {}

    prompt = _construir_prompt(
        nombres=nombres_limpios,
        urls=urls,
        marca=marca,
        modelo=modelo,
        anio=str(anio or ''),
        cilindraje=cilindraje,
        tipo_motor=tipo_motor,
        servicio_nombre=servicio_nombre or '',
    )
    body = _gemini_generar(prompt, timeout=timeout, use_url_context=True)
    if not body:
        return {}

    urls_ok = _urls_exitosas_metadata(body)
    dominios_solicitados = _dominios_de_urls(urls)
    if not urls_ok:
        logger.info(
            'busqueda_web_repuestos: sin url_context_metadata; fallback a dominios solicitados=%s',
            sorted(dominios_solicitados),
        )
    text = ''
    try:
        parts = body['candidates'][0]['content']['parts']
        text = ''.join(
            str(p.get('text') or '')
            for p in parts
            if isinstance(p, dict) and p.get('text')
        )
    except (KeyError, IndexError, TypeError):
        return {}

    parsed = _parse_json(text)
    if not parsed:
        logger.info('busqueda_web_repuestos: respuesta no-JSON descartada')
        return {}

    resultados = parsed.get('resultados') or []
    if not isinstance(resultados, list):
        return {}

    whitelist = _dominios_whitelist()
    out: dict[str, dict[str, Any]] = {}
    descartes: list[str] = []
    for raw in resultados:
        item = _normalizar_item_gemini(raw)
        if not item:
            descartes.append('no_dict:')
            continue
        validado = _validar_resultado(
            item,
            urls_ok=urls_ok,
            whitelist=whitelist,
            dominios_solicitados=dominios_solicitados,
        )
        if not validado:
            motivo = _motivo_descarte(
                item,
                urls_ok=urls_ok,
                whitelist=whitelist,
                dominios_solicitados=dominios_solicitados,
            ) or 'desconocido'
            url_dbg = str(item.get('url') or '')[:80]
            descartes.append(f'{motivo}:{url_dbg}')
            continue
        clave = _clave_fuzzy(validado['nombre_buscado'] or validado['nombre_producto'])
        if not clave:
            continue
        # Conservar el de mayor confianza por clave.
        prev = out.get(clave)
        if prev and float(prev.get('confianza') or 0) >= float(validado.get('confianza') or 0):
            continue
        out[clave] = validado
    if not out:
        logger.info(
            'busqueda_web_repuestos: 0 hits válidos de %s resultados (urls_ok=%s) descartes=%s',
            len(resultados),
            len(urls_ok),
            descartes[:8],
        )
    else:
        logger.info(
            'busqueda_web_repuestos: %s hits válidos de %s resultados',
            len(out),
            len(resultados),
        )
    return out


def clave_cache_repuesto(
    nombre: str,
    *,
    marca_vehiculo: str = '',
    modelo_vehiculo: str = '',
    anio: str | int | None = '',
    especificacion: str = '',
    tipo_motor: str = '',
    cilindraje: str = '',
) -> str:
    base = _clave_fuzzy(nombre)
    spec = _norm(especificacion)
    veh = _norm(' '.join(str(p) for p in (marca_vehiculo, modelo_vehiculo, anio or '') if p))
    motor = _norm(tipo_motor)
    cil = _norm(cilindraje)
    parts = [base]
    if spec:
        parts.append(spec)
    parts.append(veh)
    if motor:
        parts.append(motor)
    if cil:
        parts.append(cil)
    return '|'.join(p for p in parts if p)[:240]


def hits_cache_vigentes_para_nombres(
    nombres: list[str],
    *,
    marca_vehiculo: str = '',
    modelo_vehiculo: str = '',
    anio: str | int | None = '',
    especificacion: str = '',
    tipo_motor: str = '',
    cilindraje: str = '',
) -> dict[str, dict[str, Any]]:
    """Devuelve mapa clave_fuzzy → hit vigente de PrecioRepuestoWeb (sin llamar Gemini)."""
    nombres_limpios = [str(n).strip() for n in nombres if str(n).strip()]
    if not nombres_limpios:
        return {}
    try:
        from django.utils import timezone
        from mecanimovilapp.apps.ordenes.models import PrecioRepuestoWeb
    except Exception:
        return {}

    now = timezone.now()
    claves_objetivo: dict[str, str] = {}
    for nombre in nombres_limpios:
        fuzzy = _clave_fuzzy(nombre)
        if not fuzzy:
            continue
        # Solo claves con vehículo: el precio de un Fiat Uno no sirve para un
        # Bravo T-Jet, y la clave suelta por nombre los mezclaba.
        claves_objetivo[clave_cache_repuesto(
            nombre,
            marca_vehiculo=marca_vehiculo,
            modelo_vehiculo=modelo_vehiculo,
            anio=anio,
            especificacion=especificacion,
            tipo_motor=tipo_motor,
            cilindraje=cilindraje,
        )] = nombre

    if not claves_objetivo:
        return {}

    rows = (
        PrecioRepuestoWeb.objects.filter(
            clave__in=list(claves_objetivo.keys()),
            expira_en__gt=now,
            precio_clp__gt=0,
        )
        .order_by('-confianza', '-consultado_en')
    )
    out: dict[str, dict[str, Any]] = {}
    from .vehiculo_exacto import clave_historial_cubre_vehiculo

    for row in rows:
        clave = str(row.clave or '')
        dominio = str(row.dominio or '').strip().lower()
        if dominio in ('historial-taller', 'historial_taller'):
            if not clave_historial_cubre_vehiculo(clave, marca_vehiculo, modelo_vehiculo):
                continue
        fuzzy = clave.split('|', 1)[0] if '|' in clave else clave
        fuzzy = fuzzy or _clave_fuzzy(str(row.nombre_producto or ''))
        if not fuzzy:
            continue
        # Preferir primer hit (mayor confianza) por fuzzy.
        if fuzzy in out:
            continue
        marca = _marca_repuesto_valida(row.marca_repuesto)
        out[fuzzy] = {
            'nombre_buscado': claves_objetivo.get(clave) or claves_objetivo.get(fuzzy) or row.nombre_producto,
            'nombre_producto': str(row.nombre_producto or '')[:200],
            'marca_repuesto': marca,
            'precio_clp': int(row.precio_clp or 0),
            'tienda': str(row.tienda or '')[:200],
            'dominio': str(row.dominio or '')[:200],
            'url': str(row.url or '')[:500],
            'compatibilidad': str(row.compatibilidad or 'media')[:20],
            'confianza': float(row.confianza or 0.8),
            'desde_cache': True,
        }
    return out


def nombres_sin_cache_vigente(
    nombres: list[str],
    *,
    marca_vehiculo: str = '',
    modelo_vehiculo: str = '',
    anio: str | int | None = '',
    especificacion: str = '',
    tipo_motor: str = '',
    cilindraje: str = '',
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Separa nombres que aún requieren Gemini vs hits ya cacheados."""
    cache_hits = hits_cache_vigentes_para_nombres(
        nombres,
        marca_vehiculo=marca_vehiculo,
        modelo_vehiculo=modelo_vehiculo,
        anio=anio,
        especificacion=especificacion,
        tipo_motor=tipo_motor,
        cilindraje=cilindraje,
    )
    faltantes: list[str] = []
    for nombre in nombres:
        fuzzy = _clave_fuzzy(nombre)
        if fuzzy and fuzzy in cache_hits:
            continue
        faltantes.append(nombre)
    return faltantes, cache_hits
