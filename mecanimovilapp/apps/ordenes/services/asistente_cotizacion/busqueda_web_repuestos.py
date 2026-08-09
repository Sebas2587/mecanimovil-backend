"""Búsqueda web de repuestos vía Gemini URL Context (sin SerpApi).

Construye URLs de tiendas chilenas a partir del vehículo (patente → marca/modelo/año)
+ nombre del repuesto, pide a Gemini que lea esas páginas con `url_context` y
devuelva JSON con marca, tienda, precio y link. Se aceptan resultados de
dominios en whitelist con retrieval exitoso en `url_context_metadata`, o —si
Gemini omite metadata— cuyo dominio coincida con las URLs que pedimos leer.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import date
from typing import Any
from urllib.parse import quote_plus, urlparse

import requests
from django.conf import settings
from django.core.cache import cache

from .enriquecer_repuestos import _clave_fuzzy, _marca_repuesto_valida, _norm, _to_int_clp
from .generador import _parse_json

logger = logging.getLogger(__name__)

_CACHE_RPD_PREFIX = 'busqueda_web_repuestos_rpd:'
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
    return {f['dominio'] for f in _fuentes()}


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
    'disco': 'disco-freno',
    'pastilla': 'pastillas-freno',
    'pastillas': 'pastillas-freno',
    'amortiguador': 'amortiguadores',
    'amortiguadores': 'amortiguadores',
    'correa': 'correa-distribucion',
    'bomba': 'bomba-agua-auto',
}


def _slug_categoria_ml(nombre: str) -> str:
    tokens = _nombre_busqueda_corto(nombre).split()
    if not tokens:
        return ''
    return _CATEGORY_SLUG_ML.get(tokens[0], tokens[0])


def _modelo_busqueda(modelo: str) -> str:
    """Primera palabra útil del modelo (CELERIO HB 1.0 → Celerio)."""
    tokens = [t for t in str(modelo or '').strip().split() if t and not t.replace('.', '').isdigit()]
    return tokens[0] if tokens else str(modelo or '').strip()


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
        # ML falla con slugs largos. 1 token + marca recupera mejor (termostato-suzuki).
        cabeza = nucleo.split()[0] if nucleo.split() else nucleo
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
    fuentes = _fuentes()
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
    return host[:200]


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
4. tienda = nombre del sitio (Mercado Libre, AutoPlanet, …). url = link del producto o del listado leído (https).
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
    doms_req = dominios_solicitados or set()
    retrieval_ok = _host_relacionado_con(host, urls_ok) or (url in urls_ok)
    solicitado_ok = _host_relacionado_con(host, doms_req)
    # Si hubo retrieval o pedimos leer tiendas whitelist, aceptar producto
    # del mismo ecosistema (p. ej. articulo.mercadolibre.cl tras listado.*).
    contexto_ok = bool(urls_ok or doms_req)
    if not retrieval_ok and not solicitado_ok and not (
        contexto_ok and _dominio_permitido(url, whitelist)
    ):
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
        from .enriquecer_repuestos import _inferir_marca_desde_nombre
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


def buscar_repuestos_web(
    nombres: list[str],
    *,
    vehiculo: dict[str, Any] | None = None,
    servicio_nombre: str = '',
) -> dict[str, dict[str, Any]]:
    """Una llamada Gemini url_context por cotización. Devuelve mapa clave_fuzzy → hit validado."""
    if not busqueda_web_habilitada():
        return {}
    nombres_limpios = [str(n).strip()[:200] for n in nombres if str(n).strip()]
    if not nombres_limpios:
        return {}
    if not cuota_diaria_disponible():
        logger.warning('busqueda_web_repuestos: tope diario RPD alcanzado')
        return {}

    veh = vehiculo or {}
    marca = str(veh.get('marca') or '').strip()
    modelo = str(veh.get('modelo') or '').strip()
    anio = veh.get('anio') or ''
    cilindraje = str(veh.get('cilindraje') or '').strip()
    tipo_motor = str(veh.get('tipo_motor') or '').strip()

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

    api_key = (getattr(settings, 'GEMINI_API_KEY', '') or '').strip()
    model = (
        getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_MODEL', '')
        or getattr(settings, 'GEMINI_MODEL', 'gemini-3.1-flash-lite')
        or 'gemini-3.1-flash-lite'
    ).strip()
    timeout = int(getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_TIMEOUT', 45) or 45)
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
    endpoint = (
        f'https://generativelanguage.googleapis.com/v1beta/models/{model}:'
        f'generateContent?key={api_key}'
    )
    payload: dict[str, Any] = {
        'contents': [{'parts': [{'text': prompt}]}],
        'tools': [{'url_context': {}}],
        'generationConfig': {
            'temperature': 0.2,
            'maxOutputTokens': 4096,
        },
    }
    # Grounding con Search queda apagado (requiere billing). Flag reservado.
    if getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_GROUNDING', False):
        payload['tools'].append({'google_search': {}})

    try:
        resp = requests.post(endpoint, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning('busqueda_web_repuestos: error de red Gemini: %s', exc)
        return {}

    if resp.status_code != 200:
        logger.warning(
            'busqueda_web_repuestos: Gemini status=%s body=%s',
            resp.status_code,
            (resp.text or '')[:300],
        )
        return {}

    try:
        body = resp.json()
    except ValueError:
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
) -> str:
    base = _clave_fuzzy(nombre)
    veh = _norm(' '.join(str(p) for p in (marca_vehiculo, modelo_vehiculo, anio or '') if p))
    return f'{base}|{veh}'[:240]


def hits_cache_vigentes_para_nombres(
    nombres: list[str],
    *,
    marca_vehiculo: str = '',
    modelo_vehiculo: str = '',
    anio: str | int | None = '',
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
        claves_objetivo[fuzzy] = nombre
        claves_objetivo[clave_cache_repuesto(
            nombre,
            marca_vehiculo=marca_vehiculo,
            modelo_vehiculo=modelo_vehiculo,
            anio=anio,
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
    for row in rows:
        clave = str(row.clave or '')
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
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Separa nombres que aún requieren Gemini vs hits ya cacheados."""
    cache_hits = hits_cache_vigentes_para_nombres(
        nombres,
        marca_vehiculo=marca_vehiculo,
        modelo_vehiculo=modelo_vehiculo,
        anio=anio,
    )
    faltantes: list[str] = []
    for nombre in nombres:
        fuzzy = _clave_fuzzy(nombre)
        if fuzzy and fuzzy in cache_hits:
            continue
        faltantes.append(nombre)
    return faltantes, cache_hits
