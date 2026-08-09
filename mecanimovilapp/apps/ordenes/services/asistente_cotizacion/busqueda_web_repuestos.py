"""Búsqueda web de repuestos vía Gemini URL Context (sin SerpApi).

Construye URLs de tiendas chilenas a partir del vehículo (patente → marca/modelo/año)
+ nombre del repuesto, pide a Gemini que lea esas páginas con `url_context` y
devuelva JSON con marca, tienda, precio y link. Solo se aceptan resultados cuyo
dominio esté en whitelist y cuya URL aparezca con retrieval exitoso en
`url_context_metadata`.
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


def _query_vehiculo(
    nombres: list[str],
    *,
    marca: str = '',
    modelo: str = '',
    anio: str | int | None = '',
    cilindraje: str = '',
) -> str:
    partes = [str(n).strip() for n in nombres if str(n).strip()]
    # Una sola query compacta: primer repuesto + vehículo (evita URLs enormes).
    nucleo = partes[0] if partes else 'repuesto'
    if len(partes) > 1:
        nucleo = f'{nucleo} {" ".join(partes[1:3])}'
    extras = [marca, modelo]
    if anio:
        extras.append(str(anio))
    if cilindraje:
        extras.append(str(cilindraje).strip())
    return ' '.join(p for p in [nucleo, *extras] if p).strip()


def construir_urls_busqueda(
    nombres: list[str],
    *,
    marca: str = '',
    modelo: str = '',
    anio: str | int | None = '',
    cilindraje: str = '',
) -> list[str]:
    """Arma URLs de búsqueda por dominio whitelist. Tope MAX_URLS (duro 20)."""
    max_urls = max(1, min(int(getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_MAX_URLS', 4) or 4), 20))
    q = _query_vehiculo(nombres, marca=marca, modelo=modelo, anio=anio, cilindraje=cilindraje)
    if not q:
        return []
    q_enc = quote_plus(q)
    q_slug = _slug_query(q)
    urls: list[str] = []
    for fuente in _fuentes():
        plantilla = fuente['plantilla']
        # ML listado usa path con guiones; el resto usa query string.
        if 'listado.mercadolibre' in fuente['dominio'] or '{q}' in plantilla and '/{q}' in plantilla:
            url = plantilla.replace('{q}', q_slug or q_enc)
        else:
            url = plantilla.replace('{q}', q_enc)
        if url and url not in urls:
            urls.append(url)
        if len(urls) >= max_urls:
            break
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
    """Extrae URLs con retrieval exitoso de url_context_metadata."""
    ok: set[str] = set()
    try:
        candidates = body.get('candidates') or []
        if not candidates:
            return ok
        meta = (candidates[0] or {}).get('url_context_metadata') or {}
        for item in meta.get('url_metadata') or []:
            if not isinstance(item, dict):
                continue
            status = str(item.get('url_retrieval_status') or '')
            retrieved = str(item.get('retrieved_url') or item.get('url') or '').strip()
            if retrieved and status in _URL_RETRIEVAL_OK:
                ok.add(retrieved)
                # También host-level: a veces el modelo cita un producto bajo el mismo dominio.
                ok.add(_dominio_de_url(retrieved))
    except (TypeError, IndexError, AttributeError):
        return ok
    return ok


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
Debes LEER ÚNICAMENTE el contenido de las URLs listadas (herramienta url_context).
NO inventes marcas, tiendas, precios ni links. Si no hay dato en las páginas, marca encontrado=false.

Vehículo exacto: {vehiculo}
Servicio solicitado: {servicio_nombre or 'N/A'}

Repuestos a buscar:
{lista_reps}

URLs a consultar:
{lista_urls}

Reglas:
1. Solo reporta productos que aparezcan en las páginas leídas.
2. Valida compatibilidad con marca/modelo/año/cilindraje del vehículo. Si no es compatible, encontrado=false.
3. marca_repuesto = marca de la PIEZA (Bosch, Sachs, LuK, etc.). NUNCA "GENÉRICO", "N/A" ni marca del auto.
4. tienda = nombre de la tienda del dominio leído. url = link del producto o del listado leído.
5. precio_clp = entero en pesos chilenos (sin puntos ni símbolo).
6. Responde SOLO JSON válido (sin markdown) con esta forma:
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
Incluye un ítem por cada repuesto buscado. Si no hay match, encontrado=false y deja el resto vacío.
"""


def _validar_resultado(
    item: dict[str, Any],
    *,
    urls_ok: set[str],
    whitelist: set[str],
) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    if not bool(item.get('encontrado')):
        return None
    url = str(item.get('url') or '').strip()
    if not url.startswith('http'):
        return None
    if not _dominio_permitido(url, whitelist):
        return None
    # Sin retrieval exitoso no hay prueba de que Gemini leyó la página.
    if not urls_ok:
        return None
    host = _dominio_de_url(url)
    if url not in urls_ok and host not in urls_ok:
        # Aceptar si algún dominio recuperado es "pariente" (mismo sitio).
        if not any(
            _dominio_permitido(str(u) if str(u).startswith('http') else f'https://{u}/', {host})
            or (isinstance(u, str) and host and (host in u or u in host))
            for u in urls_ok
        ):
            return None
    marca = _marca_repuesto_valida(item.get('marca_repuesto'))
    precio = _to_int_clp(item.get('precio_clp'))
    if not _precio_en_rango(precio):
        return None
    # Exigimos marca o al menos nombre de producto usable + precio.
    nombre_prod = str(item.get('nombre_producto') or item.get('nombre_buscado') or '').strip()[:200]
    if not nombre_prod:
        return None
    tienda = str(item.get('tienda') or '').strip()[:200] or _tienda_por_dominio(host)
    compat = str(item.get('compatibilidad') or '').strip().lower()[:20]
    if compat not in ('alta', 'media', 'baja'):
        compat = 'media'
    return {
        'nombre_buscado': str(item.get('nombre_buscado') or '').strip()[:200],
        'nombre_producto': nombre_prod,
        'marca_repuesto': marca,
        'precio_clp': precio,
        'tienda': tienda,
        'dominio': host[:200],
        'url': url[:500],
        'compatibilidad': compat,
        'confianza': 0.8 if compat == 'alta' else (0.7 if compat == 'media' else 0.55),
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
            'temperature': 0.1,
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
    text = ''
    try:
        parts = body['candidates'][0]['content']['parts']
        text = ''.join(str(p.get('text') or '') for p in parts if isinstance(p, dict))
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
    for item in resultados:
        validado = _validar_resultado(item, urls_ok=urls_ok, whitelist=whitelist)
        if not validado:
            continue
        clave = _clave_fuzzy(validado['nombre_buscado'] or validado['nombre_producto'])
        if not clave:
            continue
        # Conservar el de mayor confianza por clave.
        prev = out.get(clave)
        if prev and float(prev.get('confianza') or 0) >= float(validado.get('confianza') or 0):
            continue
        out[clave] = validado
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
