"""Búsqueda web de repuestos: Tavily (agregador gratis) + Gemini como formateador.

Arquitectura (en orden de preferencia):
1. Tavily Search API (free tier, 1000 créditos/mes, sin tarjeta) devuelve
   resultados REALES (título, url, snippet) buscando en Chile (`country`), y
   la validación se queda solo con tiendas .cl que no sean listados. Gemini
   SOLO filtra compatibilidad y da formato al JSON final (sin tool
   `url_context`). Si el snippet y el extract no traen monto, se descarga el
   HTML de las URLs que Tavily sí devolvió (JSON-LD, og:price, WooCommerce,
   Mercado Libre o Shopify) y se queda la ficha con precio válido.
2. Fallback (solo si no hay `TAVILY_API_KEY`): Gemini con `url_context` sobre
   URLs de tiendas construidas por nosotros. Si Tavily ya corrió, no se
   inventan URLs: ese round alucinaba fichas y sumaba 45–135s.

`TAVILY_API_KEY` se obtiene gratis (sin tarjeta) en https://app.tavily.com
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote_plus, urlparse

import requests
from django.conf import settings
from django.core.cache import cache

from .enriquecer_repuestos import (
    _clave_fuzzy,
    _inferir_marca_desde_nombre,
    _marca_canonica,
    _marca_desde_etiqueta,
    _marca_repuesto_valida,
    _norm,
    _to_int_clp,
)
from .generador import (
    generation_config_gemini,
    _parse_json,
    modelos_gemini_cotizacion,
    texto_candidato_gemini,
    timeout_http_gemini,
)

logger = logging.getLogger(__name__)

_CACHE_RPD_PREFIX = 'busqueda_web_repuestos_rpd:'
# Un kit (Morning, i10, …) dispara 6–8 queries. Cada search Tavily puede irse
# a 20s: eso solo ya supera los 3 min del overlay. Tres consultas bastan:
# extract lee el precio aunque el snippet no lo traiga.
_MAX_CONSULTAS_TAVILY_POR_LINEA = 3
_TAVILY_SEARCH_TIMEOUT = 12
_TAVILY_EXTRACT_TIMEOUT = 18
_GEMINI_FORMATEO_TIMEOUT = 22
# Una línea con candidatos y sin monto lee hasta 5 fichas. Más que eso
# deja al worker colgado en tiendas lentas.
_FICHA_HTML_MAX = 5
_FICHA_HTML_TIMEOUT = 6
_FICHA_HTML_BYTES = 400_000
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
# Calidad y marca de la pieza no están en el título de la casa
# ("Pastilla freno delantera Fiat Bravo", "Aceite 5W40 4L").
_RUIDO_CALIDAD_BUSQUEDA = frozenset({
    'sintetico', 'sintetica', 'semisintetico', 'semisintetica',
    'mineral', 'ceramica', 'ceramico', 'ceramicas',
    'organica', 'organico', 'semimetalica', 'semimetalico',
    'original', 'oem', 'alternativo', 'alternativa',
})
_RE_ENVASE_LITROS = re.compile(
    r'(?<![a-z0-9])(\d+(?:[.,]\d+)?)\s*(ml|lts|litros|litro|lt|l)\b',
    re.I,
)

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


def _marcas_pieza_busqueda() -> set[str]:
    from .enriquecer_repuestos import _MARCAS_REPUESTO_CONOCIDAS

    return {_norm(m) for m in _MARCAS_REPUESTO_CONOCIDAS}


def _nombre_busqueda_amplia(nombre: str) -> tuple[str, bool]:
    """Pieza sin marca comercial ni calidad.

    'Aceite de motor TISS 5W40 sintético' → ('aceite motor 5w40', True).
    La viscosidad se queda: es el producto. TISS y 'sintético' no.
    """
    marcas = _marcas_pieza_busqueda()
    tokens: list[str] = []
    saco = False
    for tok in _norm(nombre).split():
        if not tok or tok in _STOP_QUERY:
            continue
        if tok in marcas or tok in _RUIDO_CALIDAD_BUSQUEDA:
            saco = True
            continue
        tokens.append(tok)
    # '5W-40' se parte en '5w' + '40'. La ficha lo escribe junto.
    amplia = re.sub(r'\b(\d{1,2})w\s+(\d{2})\b', r'\1w\2', ' '.join(tokens[:4]))
    return amplia, saco


def litros_envase(titulo: str) -> float:
    """Litros del envase en el título. 5W40 no cuenta; '4L' sí."""
    mejor = 0.0
    for match in _RE_ENVASE_LITROS.finditer(titulo or ''):
        try:
            num = float(match.group(1).replace(',', '.'))
        except ValueError:
            continue
        unidad = match.group(2).lower()
        litros = num / 1000.0 if unidad == 'ml' else num
        if 0.25 <= litros <= 20:
            mejor = max(mejor, litros)
    return mejor


def precio_unitario_desde_envase(nombre: str, precio_ficha: int, titulo: str) -> tuple[int, str]:
    """Un bidón de 4 L no es el precio de 1 L. El aceite se cotiza por litro."""
    precio = int(precio_ficha or 0)
    if precio <= 0:
        return precio, ''
    n = _norm(nombre)
    if 'aceite' not in n or 'filtro' in n:
        return precio, ''
    litros = litros_envase(titulo)
    if litros < 1.5:
        return precio, ''
    por_litro = max(1, int(round(precio / litros)))
    litros_txt = f'{litros:g}'
    nota = (
        f'La ficha es un envase de {litros_txt} L a ${precio:,} CLP. '
        f'Se cotiza ${por_litro:,} por litro.'
    ).replace(',', '.')
    return por_litro, nota


_RE_PACK = re.compile(
    r'(?:juego|set|pack|kit)\s+de\s+(\d{1,2})'
    r'|(\d{1,2})\s+unidades'
    r'|(?:^|[^0-9])x\s*(\d{1,2})(?:[^0-9]|$)',
    re.IGNORECASE,
)


def unidades_pack(titulo: str) -> int:
    """Cuántas unidades trae el título. 0 si no es un juego, set o pack."""
    mejor = 0
    for match in _RE_PACK.finditer(titulo or ''):
        raw = next((grupo for grupo in match.groups() if grupo), '')
        try:
            n = int(raw)
        except ValueError:
            continue
        if 2 <= n <= 12:
            mejor = max(mejor, n)
    return mejor


def _monto_bujia_por_unidad(nombre: str, precio: int, titulo: str) -> int:
    """Un juego de 4 a $32.000 se compara con la banda por bujía, no por el set."""
    pack = unidades_pack(titulo)
    if pack < 2 or int(precio or 0) < 20_000 or 'bujia' not in _norm(nombre):
        return int(precio or 0)
    return max(1, int(round(int(precio) / pack)))


def precio_unitario_desde_pack(
    nombre: str,
    precio_ficha: int,
    titulo: str,
    cantidad,
) -> tuple[int, str]:
    """La línea pide N bujías y la ficha vende el juego. Se cotiza cada una.

    Un 'juego de 4' barato no se parte: puede ser el precio de una sola.
    Cantidad 1 deja el set como está: el taller está comprando el juego.
    """
    precio = int(precio_ficha or 0)
    if precio <= 0 or 'bujia' not in _norm(nombre):
        return precio, ''
    pack = unidades_pack(titulo)
    try:
        cant = int(float(cantidad))
    except (TypeError, ValueError):
        cant = 0
    if pack < 2 or cant < pack or precio < 20_000:
        return precio, ''
    unit = max(1, int(round(precio / pack)))
    nota = (
        f'La ficha es un juego de {pack} bujías a ${precio:,} CLP. '
        f'Se cotiza ${unit:,} por unidad.'
    ).replace(',', '.')
    return unit, nota


def precio_unitario_bujia_asumido(
    nombre: str,
    precio: int,
    cantidad,
    *,
    tiene_ficha: bool,
) -> tuple[int, str]:
    """Sin tienda, $32.000 × 4 en un 1.4 T-Jet es el juego, no cada NGK.

    Una bujía publicada (aunque sea cara) no se parte. Una sola a $15.000
    tampoco: el corte está en $22.000 y hace falta cantidad 2 o más.
    """
    monto = int(precio or 0)
    if tiene_ficha or monto < 22_000 or 'bujia' not in _norm(nombre):
        return monto, ''
    try:
        cant = int(float(cantidad))
    except (TypeError, ValueError):
        return monto, ''
    if cant < 2:
        return monto, ''
    unit = max(1, int(round(monto / cant)))
    nota = (
        f'El monto de la IA (${monto:,} CLP) corresponde al juego de {cant} bujías. '
        f'Se cotiza ${unit:,} por unidad.'
    ).replace(',', '.')
    return unit, nota


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


_RE_PATH_NO_FICHA = re.compile(
    r'/(blog|blogs|noticias|glossary|pagina|busqueda|buscar|search|listado|'
    r'collections|categorias?|category)(/|$|\?)',
    re.I,
)
_HOSTS_SOCIAL = (
    'tiktok.com', 'facebook.com', 'instagram.com', 'youtube.com', 'youtu.be',
    'x.com', 'twitter.com', 'pinterest.com',
)


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
    """Home/blog/listado/red social: puede citar montos que no son el precio de la pieza."""
    host = _dominio_de_url(url)
    if host and any(host == h or host.endswith('.' + h) for h in _HOSTS_SOCIAL):
        return True
    try:
        parsed = urlparse(url)
    except Exception:
        return True
    path = parsed.path or '/'
    if path.strip('/') == '':
        return True
    if _RE_PATH_NO_FICHA.search(path):
        return True
    query = (parsed.query or '').lower()
    # Filtro de catálogo (Boston, etc.): no es la ficha de un SKU.
    if 'marca_vehiculo=' in query or 'modelo_vehiculo=' in query:
        return True
    path_l = path.lower()
    if re.search(r'/marca/[^/]+/[^/]+/', path_l) and not re.search(
        r'/(producto|product|products|p)/', path_l,
    ):
        return True
    return False


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


_ANIO_RANGO_RE = re.compile(
    r'\b((?:19|20)\d{2})\s*(?:-|–|/|a)\s*((?:19|20)\d{2})\b',
    re.I,
)
_ANIO_SOLO_RE = re.compile(r'\b((?:19|20)\d{2})\b')
_KIT_RE = re.compile(r'\b(kit|juego|set)\b')
_COMPONENTE_EMBRAGUE = frozenset({
    'prensa', 'plato', 'disco', 'collarin',
    'rodamiento', 'empuje', 'piloto',
})


def _anio_vehiculo_int(anio: Any) -> int | None:
    try:
        y = int(str(anio).strip()[:4])
    except (TypeError, ValueError):
        return None
    if 1980 <= y <= 2035:
        return y
    return None


def _ficha_cubre_anio(texto: str, anio: Any, *, holgura: int = 0) -> bool | None:
    """True/False si la ficha declara años; None si no se puede saber.

    `holgura`: años de borde (un Morning 2011 vs ficha 2012-2016). 0 = estricto.
    """
    y = _anio_vehiculo_int(anio)
    if y is None:
        return None
    extra = max(0, int(holgura or 0))
    raw = texto or ''
    rangos: list[tuple[int, int]] = []
    for match in _ANIO_RANGO_RE.finditer(raw):
        a, b = int(match.group(1)), int(match.group(2))
        if a > b:
            a, b = b, a
        if 1980 <= a <= 2035 and 1980 <= b <= 2035:
            rangos.append((a, b))
    if rangos:
        return any(lo - extra <= y <= hi + extra for lo, hi in rangos)
    solos = [
        int(m.group(1)) for m in _ANIO_SOLO_RE.finditer(raw)
        if 1980 <= int(m.group(1)) <= 2035
    ]
    if not solos:
        return None
    if y in solos:
        return True
    if extra and any(abs(s - y) <= extra for s in solos):
        return True
    return False


_CILINDRAJE_RE = re.compile(r'(?<!\d)([1-4])[.,\-]([0-9])(?!\d)')
_MOTOR_CODE_RE = re.compile(r'\bg[0-9][a-z0-9]{2,4}\b', re.I)


def _cilindraje_litros(raw: Any) -> str | None:
    s = str(raw or '').strip().lower().replace(',', '.')
    if not s:
        return None
    m = re.search(r'\b([1-4]\.[0-9])\b', s)
    if m:
        return m.group(1)
    m = re.search(r'\b([1-4])([0-9])00(?:\s*cc)?\b', s)
    if m:
        return f'{m.group(1)}.{m.group(2)}'
    return None


def _ficha_cubre_cilindraje(texto: str, cilindraje: Any) -> bool | None:
    """True/False si la ficha declara litros; None si no se puede saber.

    Un kit Morning 1.2 no cotiza un 1.1 G4HG.
    """
    y = _cilindraje_litros(cilindraje)
    if not y:
        return None
    found = {
        f'{m.group(1)}.{m.group(2)}' for m in _CILINDRAJE_RE.finditer(texto or '')
    }
    if not found:
        return None
    return y in found


def _codigo_motor_query(tipo_motor: str) -> str:
    """G4HG sí va a la búsqueda; GASOLINA no."""
    t = (tipo_motor or '').strip()
    if _MOTOR_CODE_RE.fullmatch(t):
        return t.upper()
    m = _MOTOR_CODE_RE.search(t)
    return m.group(0).upper() if m else ''


def _pieza_exige_compatibilidad(nombre_linea: str) -> bool:
    n = _norm(nombre_linea)
    return any(k in n for k in (
        'embrague', 'clutch', 'volante', 'inyector', 'turbo',
        'kit distribucion', 'kit de distribucion',
    ))


def _linea_es_kit(nombre_linea: str) -> bool:
    n = _norm(nombre_linea)
    return bool(_KIT_RE.search(n)) or (
        'embrague' in n and 'disco' in n and 'prensa' in n
    )


def _ficha_es_kit_embrague_completo(titulo_ficha: str) -> bool:
    """La casa vende disco, prensa y rodamiento de empuje como un solo kit."""
    ficha = _norm(titulo_ficha)
    if not ficha:
        return False
    if _KIT_RE.search(ficha) and ('embrague' in ficha or 'clutch' in ficha):
        return True
    tiene_disco = 'disco' in ficha
    tiene_prensa = 'prensa' in ficha or 'plato' in ficha
    tiene_empuje = 'rodamiento' in ficha or 'collarin' in ficha or 'empuje' in ficha
    return tiene_disco and tiene_prensa and tiene_empuje


def _ficha_es_rodamiento_piloto(titulo: str) -> bool:
    """Rulemán piloto. Un 'Rodamiento Suzuki' suelto es otra pieza (rueda, maza)."""
    ficha = _norm(titulo)
    if not ficha or 'piola' in ficha or 'prensa' in ficha or 'disco' in ficha:
        return False
    if 'piloto' in ficha or 'ruleman' in ficha:
        return True
    return 'rodamiento' in ficha and 'volante' in ficha


def _ficha_cubre_pieza(nombre_linea: str, titulo_ficha: str) -> bool:
    """La ficha tiene que ser la misma pieza. Una piola no cotiza el kit."""
    linea = _norm(nombre_linea)
    ficha = _norm(titulo_ficha)
    if not linea or not ficha:
        return True
    ficha_kit = _ficha_es_kit_embrague_completo(titulo_ficha)
    ficha_piola = _es_piola_embrague(ficha)
    ficha_piloto = _ficha_es_rodamiento_piloto(titulo_ficha)
    if _es_rodamiento_piloto(linea):
        if _ficha_es_volante_motor(titulo_ficha) or ficha_kit or ficha_piola:
            return False
        return ficha_piloto
    if _es_aceite_caja(linea) and (
        ficha_kit
        or _ficha_es_volante_motor(titulo_ficha)
        or ficha_piloto
        or ficha_piola
        or ('embrague' in ficha and 'aceite' not in ficha)
    ):
        return False
    if _es_piola_embrague(linea):
        if ficha_kit or _ficha_es_volante_motor(titulo_ficha) or ficha_piloto:
            return False
        return ficha_piola
    if _linea_es_kit(nombre_linea):
        if ficha_piola or ficha_piloto or 'aceite' in ficha or 'reten' in ficha or 'ciguenal' in ficha:
            return False
        if ficha_kit:
            return True
        if any(c in ficha for c in _COMPONENTE_EMBRAGUE):
            return False
        return False
    if ficha_kit and any(c in linea for c in _COMPONENTE_EMBRAGUE) and 'kit' not in linea:
        return False
    from .enriquecer_repuestos import _validar_tipo_parte

    if not _validar_tipo_parte(nombre_linea, titulo_ficha):
        return False
    return True


def _ficha_nombra_modelo(texto: str, modelo: str) -> bool | None:
    """True/False si hay un modelo que buscar. None si no hay modelo útil."""
    token = _norm(_modelo_busqueda(modelo))
    if len(token) < 3:
        return None
    return token in _norm(texto)


# La pastilla del Bravo T-Jet (Fras-le PD/92) también calza en Linea y Punto
# T-Jet. Idea, Stilo, Fiorino y Strada son otra pastilla.
_MODELOS_PASTILLA_AJENOS = frozenset({
    'idea', 'stilo', 'fiorino', 'strada', 'palio', 'siena', 'doblo',
    'argo', 'cronos', 'mobi', 'toro', 'adventur', 'adventure',
})


def _compat_pastilla(
    texto: str,
    modelo: str,
    tipo_motor: str,
    *,
    permite_cruce: bool = True,
) -> bool | None:
    """True si nombra el auto pedido. False si nombra otro. None si no hay modelo.

    El cruce Linea/Punto T-Jet solo vale en el título o el cuerpo. El slug
    de la URL no alcanza: un listado 'Envío gratis' no es la pastilla del Bravo
    porque la ruta dice fiat-linea-t-jet. "Bravo" en el texto sí cuenta aunque
    el modelo guardado empiece por el trim ("Sport Bravo"), no por Bravo.
    """
    norm = _norm(texto)
    if not norm:
        return None
    if 'bravo' in _norm(f'{modelo} {tipo_motor}') and re.search(r'\bbravo\b', norm):
        return True
    token = _norm(_modelo_busqueda(modelo))
    if len(token) >= 3 and re.search(rf'\b{re.escape(token)}\b', norm):
        return True
    tokens = set(norm.split())
    if permite_cruce and _bravo_tjet(modelo, tipo_motor):
        cruce = 'linea' in tokens or 'punto' in tokens
        if cruce and ('t jet' in norm or 'tjet' in norm.replace(' ', '')):
            return True
    if tokens & _MODELOS_PASTILLA_AJENOS:
        return False
    return None


def _titulo_nombra_modelo(titulo: str, modelo: str) -> bool:
    token = _norm(_modelo_busqueda(modelo))
    if len(token) < 3:
        return False
    return re.search(rf'\b{re.escape(token)}\b', _norm(titulo)) is not None


def _titulo_es_del_auto(titulo: str, modelo: str, tipo_motor: str = '') -> bool:
    """El título nombra este auto, no solo la primera palabra del modelo.

    "Sport Bravo" tiene como primera palabra Sport, que no está en
    "Pastillas Fiat Bravo 1.4". Lider y Sodimac se caían del cupo por eso.
    """
    norm = _norm(titulo)
    if not norm:
        return False
    if 'bravo' in _norm(f'{modelo} {tipo_motor}') and re.search(r'\bbravo\b', norm):
        return True
    for parte in (modelo, tipo_motor):
        for tok in _tokens_modelo(parte):
            n = _norm(tok)
            if len(n) >= 3 and re.search(rf'\b{re.escape(n)}\b', norm):
                return True
    return False


def _titulo_nombra_bravo_14(titulo: str, modelo: str) -> bool:
    """El título dice Bravo 1.4. El slug de otro modelo no cuenta."""
    if 'bravo' not in _norm(modelo):
        return False
    norm = _norm(titulo)
    if not re.search(r'\bbravo\b', norm):
        return False
    return re.search(r'\b1\s+4\b', norm) is not None


def _titulo_es_cruce_tjet(titulo: str, modelo: str, tipo_motor: str) -> bool:
    if _titulo_nombra_modelo(titulo, modelo):
        return False
    return _compat_pastilla(titulo, modelo, tipo_motor, permite_cruce=True) is True


def _texto_ficha_sin_url(candidato: dict[str, Any]) -> str:
    return ' '.join(
        str((candidato or {}).get(campo) or '')
        for campo in ('title', 'cuerpo', 'content')
    )


def _compat_pastilla_candidato(
    candidato: dict[str, Any],
    modelo: str,
    tipo_motor: str,
) -> bool | None:
    """La URL confirma el modelo pedido o bota Idea/Stilo. No otorga el cruce."""
    ficha = _compat_pastilla(
        _texto_ficha_sin_url(candidato), modelo, tipo_motor, permite_cruce=True,
    )
    url = _compat_pastilla(
        str((candidato or {}).get('url') or '').replace('-', ' ').replace('/', ' '),
        modelo,
        tipo_motor,
        permite_cruce=False,
    )
    titulo = str((candidato or {}).get('title') or '')
    if ficha is True and _titulo_nombra_modelo(titulo, modelo):
        return True
    if ficha is False or url is False:
        return False
    if ficha is True or url is True:
        return True
    return None


def _ficha_nombra_modelo_pedido(
    candidato: dict[str, Any],
    modelo: str,
    tipo_motor: str,
) -> bool:
    return _compat_pastilla(
        _texto_ficha_sin_url(candidato), modelo, tipo_motor, permite_cruce=False,
    ) is True


def _ficha_es_cruce_tjet(
    candidato: dict[str, Any],
    modelo: str,
    tipo_motor: str,
) -> bool:
    if _ficha_nombra_modelo_pedido(candidato, modelo, tipo_motor):
        return False
    return _compat_pastilla(
        _texto_ficha_sin_url(candidato), modelo, tipo_motor, permite_cruce=True,
    ) is True


def _es_listado_pastilla(candidato: dict[str, Any], modelo: str, tipo_motor: str) -> bool:
    """Categoría, búsqueda, o tarjeta 'Envío gratis' que no nombra el auto."""
    url = str((candidato or {}).get('url') or '')
    if url and _es_pagina_sin_ficha(url):
        return True
    titulo = str((candidato or {}).get('title') or '')
    if 'envio gratis' not in _norm(titulo):
        return False
    cabeza = titulo.split('|')[0]
    return _compat_pastilla(cabeza, modelo, tipo_motor) is not True


def _pastilla_es_exacta(candidato: dict[str, Any], modelo: str, tipo_motor: str) -> bool:
    """La ficha nombra el auto pedido en el título o en el cuerpo. El slug no."""
    if _es_pagina_sin_ficha(str((candidato or {}).get('url') or '')):
        return False
    return _ficha_nombra_modelo_pedido(candidato, modelo, tipo_motor)


def _host_de_url(url: str) -> str:
    try:
        from urllib.parse import urlparse

        host = (urlparse(url or '').hostname or '').lower()
    except Exception:
        return ''
    return host[4:] if host.startswith('www.') else host


def _marcar_respaldo_alto(
    crudos: list[dict[str, Any]],
    nombre: str,
    banda_max: int,
) -> None:
    """Dos tiendas distintas, con montos a menos de 40%, sostienen un precio alto.

    Una sola publicación de Mercado Libre a 5× la banda no es evidencia.
    """
    techo = int(banda_max or 0)
    if techo <= 0:
        return
    altos: list[tuple[str, int, dict[str, Any]]] = []
    for cand in crudos:
        precio = _precio_de_candidato(cand, nombre)
        if precio <= 0 or precio * 2 <= techo * 5:
            continue
        altos.append((_host_de_url(str(cand.get('url') or '')), precio, cand))
    hosts = {host for host, _, _ in altos if host}
    if len(hosts) < 2:
        return
    precios = [precio for _, precio, _ in altos]
    if max(precios) * 10 > min(precios) * 14:
        return
    for _, _, cand in altos:
        cand['respaldo_alto'] = True


def _rechazo_precio_pastilla(
    candidato: dict[str, Any],
    *,
    nombre: str,
    modelo: str,
    tipo_motor: str,
    banda_min: int,
    banda_max: int = 0,
) -> str:
    """Piso y techo de la banda de la IA. '' si el monto todavía puede cotizarse.

    Un título que dice Bravo 1.4 baja el piso al 40%: la banda 28.000–55.000
    deja afuera fichas reales de ese auto. Linea/Punto T-Jet solo calza si el
    precio está dentro de la banda. Un listado genérico sigue en el 50%.
    Por encima, 2,5× el máximo de la IA es precio_alto_banda en cualquier
    categoría. Una sola ficha de Mercado Libre a $81.900 no alcanza: hacen
    falta dos tiendas distintas con montos parecidos.
    """
    precio = _precio_de_candidato(candidato, nombre)
    piso = int(banda_min or 0)
    techo = int(banda_max or 0)
    if precio <= 0:
        return ''
    titulo = str((candidato or {}).get('title') or '')
    # El set de 4 se mide por bujía. El estante sigue siendo el de la ficha.
    precio_alto = _monto_bujia_por_unidad(nombre, precio, titulo)
    if (
        techo > 0
        and precio_alto * 2 > techo * 5
        and not (candidato or {}).get('respaldo_alto')
    ):
        return 'precio_alto_banda'
    if piso <= 0:
        return ''
    # La banda 28.000–55.000 deja afuera fichas reales de Bravo 1.4.
    # Con Bravo 1.4 en el título, el piso baja al 40% ($10.000 no, $21.390 sí).
    if _titulo_nombra_bravo_14(titulo, f'{modelo} {tipo_motor}') and precio < piso * 2 // 5:
        return 'precio_bajo_banda'
    if _titulo_nombra_bravo_14(titulo, f'{modelo} {tipo_motor}'):
        return ''
    if _ficha_nombra_modelo_pedido(candidato, modelo, tipo_motor):
        return ''
    if _ficha_es_cruce_tjet(candidato, modelo, tipo_motor):
        if precio < piso or (techo > 0 and precio_alto > techo):
            return 'precio_bajo_banda' if precio < piso else 'precio_alto_banda'
        return ''
    if precio * 2 < piso:
        return 'precio_bajo_banda'
    return ''


def _motivo_calidad_pastilla(
    candidato: dict[str, Any],
    *,
    nombre: str,
    modelo: str,
    tipo_motor: str = '',
    banda_min: int = 0,
    banda_max: int = 0,
) -> str:
    """Por qué una ficha no se cotiza. '' si todavía puede servir.

    La compuerta vale para cualquier pieza, no solo pastillas. El aceite de
    motor no nombra el auto: esa línea no entra. Sin la página leída no se
    descarta un título genérico sin precio: la tabla de compatibilidad puede
    nombrar al Bravo. Un título 'Envío gratis' que ya trae monto es listado
    aunque nadie haya abierto la ficha. El cruce Linea/Punto T-Jet y el
    monto se miden contra la banda de la IA.
    """
    from .enriquecer_repuestos import _es_linea_aceite_motor

    if _es_linea_aceite_motor(nombre):
        return ''
    if _es_pastillas_freno(nombre):
        titulo = str((candidato or {}).get('title') or '')
        if titulo and not _es_pastillas_freno(titulo):
            return ''
    elif _pieza_exige_compatibilidad(nombre):
        return ''
    compat = _compat_pastilla_candidato(candidato, modelo, tipo_motor)
    if compat is False:
        return 'modelo_incompatible'
    leida = bool((candidato or {}).get('ficha_leida'))
    precio = _precio_de_candidato(candidato, nombre)
    if _es_listado_pastilla(candidato, modelo, tipo_motor) and (leida or precio > 0):
        return 'listado'
    if not leida:
        if precio <= 0:
            return ''
        return _rechazo_precio_pastilla(
            candidato,
            nombre=nombre,
            modelo=modelo,
            tipo_motor=tipo_motor,
            banda_min=banda_min,
            banda_max=banda_max,
        )
    bajo = _rechazo_precio_pastilla(
        candidato,
        nombre=nombre,
        modelo=modelo,
        tipo_motor=tipo_motor,
        banda_min=banda_min,
        banda_max=banda_max,
    )
    if bajo:
        return bajo
    if compat is None:
        return 'sin_modelo'
    return ''


def _candidato_sirve_linea(
    nombre_linea: str,
    candidato: dict[str, Any],
    *,
    anio: Any = None,
    cilindraje: Any = None,
    modelo: str = '',
    tipo_motor: str = '',
    banda_min: int = 0,
    banda_max: int = 0,
) -> bool:
    titulo = str(candidato.get('title') or '')
    texto = f'{titulo} {candidato.get("content") or ""} {candidato.get("url") or ""}'
    if not _ficha_cubre_pieza(nombre_linea, titulo):
        return False
    if not _pieza_exige_compatibilidad(nombre_linea):
        # Pastillas: Bravo, Stilo y Punto en la MISMA ficha siguen sirviendo.
        # Una ficha que solo nombra Idea, o un listado sin modelo ya leído, no.
        if _motivo_calidad_pastilla(
            candidato,
            nombre=nombre_linea,
            modelo=modelo,
            tipo_motor=tipo_motor,
            banda_min=banda_min,
            banda_max=banda_max,
        ):
            return False
        return True
    if _ficha_nombra_modelo(texto, modelo) is False:
        return False
    holgura = 1 if _linea_es_kit(nombre_linea) else 0
    if _ficha_cubre_anio(texto, anio, holgura=holgura) is False:
        return False
    if _ficha_cubre_cilindraje(texto, cilindraje) is False:
        return False
    return True


_NOMBRES_TIENDA_GENERICOS = frozenset({
    'repuestos', 'repuesto', 'tienda', 'shop', 'store', 'www',
})


def _sld_host(host: str) -> str:
    """Etiqueta registrable, sin TLD. mundorepuestos.com y .cl coinciden."""
    limpio = (host or '').lower().removeprefix('www.').strip('.')
    labels = [parte for parte in limpio.split('.') if parte]
    if not labels:
        return ''
    if (
        len(labels) >= 3
        and labels[-2] in ('com', 'co', 'gob', 'org', 'net')
        and len(labels[-1]) <= 3
    ):
        base = labels[:-2]
    elif len(labels) >= 2:
        base = labels[:-1]
    else:
        base = labels
    return base[-1] if base else ''


def _canon_nombre_tienda(nombre: str) -> str:
    """El nombre que ya usa la cotización, no el primer rótulo DNS."""
    crudo = str(nombre or '').strip()
    if not crudo:
        return ''
    n = _norm(crudo)
    if 'sergio' in n and 'escobar' in n:
        return 'Repuestos Sergio Escobar'
    if 'mundo' in n and 'repuesto' in n:
        return 'Mundo Repuestos'
    if 'frenos' in n and 'vergara' in n:
        return 'Frenos Vergara'
    limpio = re.sub(r'\s+chile\s*$', '', crudo, flags=re.I).strip(' |-')
    return limpio[:200]


def _tienda_por_dominio(dominio: str) -> str:
    host = (dominio or '').lower()
    for fuente in _fuentes():
        d = fuente['dominio']
        if host == d or host.endswith('.' + d.lstrip('www.')) or d in host:
            return fuente['nombre']
        if _sld_host(host) and _sld_host(host) == _sld_host(d):
            return fuente['nombre']
    if 'mercadolibre' in host:
        return 'Mercado Libre'
    sld = _sld_host(host)
    for esp in _especialistas():
        d = (esp.get('dominio') or '').lower().removeprefix('www.')
        if d and (
            host == d or host.endswith('.' + d) or d in host or (sld and sld == _sld_host(d))
        ):
            return esp.get('nombre') or d
    # 'repuestos.sergioescobar.cl' no se llama "Repuestos": esa etiqueta es genérica.
    labels = host.removeprefix('www.').split('.')
    raiz = (labels[0] if labels else '').replace('-', ' ').strip()
    if raiz in _NOMBRES_TIENDA_GENERICOS and len(labels) >= 2:
        siguiente = labels[1].replace('-', ' ').strip()
        if siguiente and siguiente not in ('cl', 'com', 'shop', 'net', 'org'):
            return _canon_nombre_tienda(siguiente.title())[:200]
    if raiz in _NOMBRES_TIENDA_GENERICOS:
        return ''
    return _canon_nombre_tienda((raiz.title() or host))[:200]


def _tienda_desde_titulo(titulo: str) -> str:
    """Sufijo '… | Sergio Escobar Repuestos' cuando el dominio no alcanza."""
    texto = str(titulo or '').strip()
    if not texto:
        return ''
    if '|' in texto:
        cola = texto.split('|')[-1].strip()
    elif ' - ' in texto:
        cola = texto.split(' - ')[-1].strip()
    else:
        return ''
    nombre = _canon_nombre_tienda(cola)
    if not nombre or _norm(nombre) in _NOMBRES_TIENDA_GENERICOS:
        return ''
    if 'envio gratis' in _norm(nombre):
        return ''
    return nombre


def _tienda_de_ficha(url: str, titulo: str = '') -> str:
    por_dominio = _tienda_por_dominio(_dominio_de_url(url))
    if por_dominio and _norm(por_dominio) not in _NOMBRES_TIENDA_GENERICOS:
        return por_dominio
    return _tienda_desde_titulo(titulo) or por_dominio


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
1. encontrado=true SOLO si la ficha es LA MISMA PIEZA y es compatible con este auto (marca, modelo, año y motor o cilindrada). El kit de embrague es disco + prensa + rodamiento de empuje vendidos juntos: esa ficha SÍ es el kit. Una ficha de solo disco, solo prensa o solo rodamiento NO es el kit. El precio del kit no se usa para una pieza suelta.
2. compatibilidad: alta si nombra marca+modelo y el año del auto entra en el rango de la ficha; media si nombra el modelo sin año; baja si es genérico. Si la ficha declara años y el auto queda fuera, encontrado=false.
3. marca_repuesto = marca de la PIEZA (Bosch, Gates, Wahler, NGK, etc.). Si no aparece, "". NUNCA "GENÉRICO", "Original", "N/A" ni la marca del auto.
4. calidad = original (genuino/agencia), oem (equivalente OEM) o alternativo (aftermarket). Solo si el texto lo decide. Si duda, "".
5. pais_origen = país de la PIEZA (China, Japón, Alemania…) solo si dice hecho/fabricado/importado/origen. No uses Chile por ser la tienda.
6. tienda = quién vende. En una tienda es el sitio (AutoPlanet, Refax, …); en una publicación de marketplace es el nombre del vendedor visible, no "Mercado Libre". url = link de la publicación o producto leído (https).
7. precio_clp = entero CLP sin puntos ni símbolo: el "Precio:" de ESA ficha, no relacionados ni cuotas. Si el monto es irreal para la pieza, encontrado=false: kit 3 piezas ~35.000–280.000, prensa suelta ~8.000–120.000, rodamiento piloto ~3.000–45.000 (un volante bimasa no es el rodamiento), piola ~4.000–55.000, aceite de caja ~3.000–90.000.
8. Solo encontrado=false si en las páginas NO hay ningún producto de la misma pieza.
9. Responde SOLO JSON válido (sin markdown):
{{
  "resultados": [
    {{
      "nombre_buscado": "texto del repuesto",
      "encontrado": true,
      "nombre_producto": "...",
      "marca_repuesto": "...",
      "calidad": "original|oem|alternativo|",
      "pais_origen": "",
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
    anio: Any = None,
    cilindraje: Any = None,
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
    nombre_linea = str(item.get('nombre_buscado') or nombre_prod)
    if not _candidato_sirve_linea(
        nombre_linea,
        {
            'title': nombre_prod,
            'content': str(item.get('content') or ''),
            'url': url,
        },
        anio=anio,
        cilindraje=cilindraje,
    ):
        return None
    if precio and not _precio_plausible_para_linea(nombre_linea, precio):
        precio = 0
        precio_ok = False
    attrs = _atributos_desde_texto(
        nombre_prod,
        item.get('marca_repuesto'),
        item.get('calidad'),
        item.get('pais_origen'),
    )
    if not marca:
        marca = attrs['marca_repuesto']
    calidad, pais = _calidad_pais_de_item(item, attrs)
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
    out = {
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
    if calidad:
        out['calidad'] = calidad
    if pais:
        out['pais_origen'] = pais
    return out


TAVILY_EXTRACT_QUERY = (
    'Precio de venta Precio $ CLP oferta '
    'marca tipo original OEM alternativo genuino '
    'procedencia país origen fabricado hecho en importado'
)
TAVILY_SCORE_MIN = 0.35


def _atributos_desde_texto(*partes: Any, marca_vehiculo: str = '') -> dict[str, str]:
    """Marca de la pieza, calidad y país solo si el texto los nombra."""
    from .calidad_repuesto import (
        CALIDADES,
        detectar_calidad,
        detectar_pais_origen,
        normalizar_pais_origen,
    )

    blob = ' '.join(str(p or '') for p in partes if p not in (None, ''))
    marca = _marca_repuesto_valida(_inferir_marca_desde_nombre(blob))
    if not marca:
        marca = _marca_desde_etiqueta(blob, marca_vehiculo)
    marca = _marca_canonica(marca, blob)
    if marca and _norm(marca) == _norm(marca_vehiculo):
        marca = ''
    cal = detectar_calidad(blob) or ''
    if cal not in CALIDADES:
        cal = ''
    pais = detectar_pais_origen(blob) or normalizar_pais_origen(blob)
    return {
        'marca_repuesto': marca,
        'calidad': cal,
        'pais_origen': pais,
    }


def _calidad_pais_de_item(item: dict[str, Any], attrs: dict[str, str]) -> tuple[str, str]:
    from .calidad_repuesto import CALIDADES, normalizar_pais_origen

    cal_item = str(item.get('calidad') or '').strip().lower()
    calidad = cal_item if cal_item in CALIDADES else (attrs.get('calidad') or '')
    pais = normalizar_pais_origen(item.get('pais_origen')) or (attrs.get('pais_origen') or '')
    return calidad, pais


TAVILY_SEARCH_ENDPOINT = 'https://api.tavily.com/search'


def tavily_habilitada() -> bool:
    return bool((getattr(settings, 'TAVILY_API_KEY', '') or '').strip())


def _tavily_buscar_uno(
    query: str,
    *,
    max_results: int = 4,
    timeout: int = _TAVILY_SEARCH_TIMEOUT,
) -> list[dict[str, str]]:
    """1 crédito Tavily (search_depth=basic). Devuelve [{title, url, content}].

    Post-filtro por `score` (best practice Tavily): el score mide relevancia
    semántica, no certeza de ficha; el corte es bajo para no perder .cl.
    """
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
        logger.info(
            'busqueda_web_repuestos[tavily] query=%s resultados=0',
            query.strip()[:160],
        )
        return []
    if resp.status_code != 200:
        logger.warning('tavily_buscar: status=%s body=%s', resp.status_code, resp.text[:300])
        logger.info(
            'busqueda_web_repuestos[tavily] query=%s resultados=0',
            query.strip()[:160],
        )
        return []
    try:
        data = resp.json()
    except ValueError:
        logger.info(
            'busqueda_web_repuestos[tavily] query=%s resultados=0',
            query.strip()[:160],
        )
        return []
    brutos = data.get('results') or []
    n_api = len(brutos) if isinstance(brutos, list) else 0
    out: list[dict[str, str]] = []
    for r in brutos:
        if not isinstance(r, dict):
            continue
        url = str(r.get('url') or '').strip()
        if not url:
            continue
        try:
            score = float(r.get('score') or 0)
        except (TypeError, ValueError):
            score = 0.0
        if score and score < TAVILY_SCORE_MIN:
            continue
        out.append({
            'title': str(r.get('title') or '')[:200],
            'url': url[:500],
            'content': str(r.get('content') or '')[:900],
        })
    logger.info(
        'busqueda_web_repuestos[tavily] query=%s resultados=%s utiles=%s',
        query.strip()[:160],
        n_api,
        len(out),
    )
    return out


TAVILY_EXTRACT_ENDPOINT = 'https://api.tavily.com/extract'


def _tavily_extraer(
    urls: list[str],
    *,
    timeout: int = _TAVILY_EXTRACT_TIMEOUT,
    extract_depth: str = 'basic',
) -> dict[str, str]:
    """Ficha de producto: marca, calidad, origen y precio.

    Search + extract (no raw_content en search). `query` + chunks recorta la
    ficha a specs útiles (~1 crédito cada 5 URLs, basic).
    """
    api_key = (getattr(settings, 'TAVILY_API_KEY', '') or '').strip()
    urls_unicas = [u for u in dict.fromkeys(urls) if u][:20]
    if not api_key or not urls_unicas:
        return {}
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    profundidad = 'advanced' if str(extract_depth).lower() == 'advanced' else 'basic'
    payload: dict[str, Any] = {
        'urls': urls_unicas,
        'extract_depth': profundidad,
        'format': 'text',
        'query': TAVILY_EXTRACT_QUERY,
        'chunks_per_source': 6,
    }
    try:
        resp = requests.post(
            TAVILY_EXTRACT_ENDPOINT,
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        # `query`/`chunks_per_source` no existen en todos los planes: 400 → extract plano.
        if resp.status_code == 400:
            logger.warning(
                'tavily_extraer: status=400 body=%s; reintenta sin query',
                (resp.text or '')[:300],
            )
            plano = {
                'urls': urls_unicas,
                'extract_depth': profundidad,
                'format': 'text',
            }
            resp = requests.post(
                TAVILY_EXTRACT_ENDPOINT,
                headers=headers,
                json=plano,
                timeout=timeout,
            )
    except requests.RequestException as exc:
        logger.warning('tavily_extraer: error de red: %s', exc)
        return {}
    if resp.status_code != 200:
        logger.info(
            'tavily_extraer: status=%s body=%s (se sigue con snippets de búsqueda)',
            resp.status_code,
            (resp.text or '')[:300],
        )
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


_FICHA_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
)


def _leer_html_fichas(urls: list[str]) -> dict[str, str]:
    """HTML de las URLs que Tavily ya devolvió. No inventa direcciones."""
    out: dict[str, str] = {}
    for url in list(dict.fromkeys(u for u in urls if u))[:20]:
        try:
            resp = requests.get(
                url,
                timeout=_FICHA_HTML_TIMEOUT,
                headers={
                    'User-Agent': _FICHA_UA,
                    'Accept': 'text/html,application/xhtml+xml',
                    'Accept-Language': 'es-CL,es;q=0.9',
                },
            )
        except requests.RequestException:
            continue
        if resp.status_code != 200 or not (resp.text or '').strip():
            continue
        out[url] = resp.text[:_FICHA_HTML_BYTES]
    return out


# El `$` no puede venir pegado a letras: así "US$ 45.00" y "R$ 45,00" no entran
# como pesos. "CLP" sí es prefijo válido, con o sin signo.
_PRECIO_CLP_RE = re.compile(r'(?:(?<![A-Za-z])\$|CLP\s?\$?)\s?([\d.,]{4,10})')
_PRECIO_ETIQUETA_RE = re.compile(
    r'(?:precio(?:\s+(?:habitual|de\s+oferta|oferta|ahora|web|exclusivo))?)\s*:?\s*'
    r'(?:CLP\s*)?\$?\s*([\d.,]{3,12})',
    re.I,
)
_CUOTA_RE = re.compile(r'\d+\s*cuotas?\s+de\s+\$?\s*[\d.]+', re.I)
_ENVIO_PRECIO_RE = re.compile(
    r'(?:costo\s+de\s+env[ií]o|env[ií]o\s+a\s+domicilio|despacho|flete)\s*:?\s*\$?\s*[\d.]{3,12}',
    re.I,
)

# Bandas de mercado Chile (aftermarket). Evitan SKU, id de ficha o un kit de
# camioneta colado en el snippet de una prensa de auto chico.
_BANDA_DEFAULT = (1_000, 3_000_000)
_BANDAS_CATEGORIA = {
    'filtros': (2_000, 90_000),
    'bujias': (1_200, 50_000),
    'aceites': (3_000, 90_000),
    'frenos': (6_000, 200_000),
    'refrigeracion': (4_000, 250_000),
    'bateria': (30_000, 250_000),
    'suspension': (15_000, 250_000),
    'distribucion': (20_000, 400_000),
    'electrico': (8_000, 500_000),
    'embrague': (8_000, 280_000),
    'otros': _BANDA_DEFAULT,
}
_BANDA_KIT_EMBRAGUE = (35_000, 280_000)
_BANDA_COMPONENTE_EMBRAGUE = (8_000, 120_000)
# Un rodamiento piloto o una piola no valen lo de un volante bimasa ni de un kit.
_BANDA_RODAMIENTO_PILOTO = (3_000, 45_000)
_BANDA_PIOLA_EMBRAGUE = (4_000, 55_000)


def _es_rodamiento_piloto(nombre: str) -> bool:
    n = _norm(nombre)
    if 'empuje' in n or 'bimasa' in n:
        return False
    return ('rodamiento' in n or 'ruleman' in n) and ('volante' in n or 'piloto' in n)


def _es_piola_embrague(nombre: str) -> bool:
    n = _norm(nombre)
    return 'piola' in n or 'guaya' in n or (
        'cable' in n and ('embrague' in n or 'clutch' in n)
    )


def _es_aceite_caja(nombre: str) -> bool:
    n = _norm(nombre)
    return 'aceite' in n and ('caja' in n or 'transmision' in n or 'valvulina' in n)


def _ficha_es_volante_motor(titulo: str) -> bool:
    """Volante bimasa o volante de motor: no es el rodamiento piloto."""
    ficha = _norm(titulo)
    if not ficha or 'volante' not in ficha:
        return False
    if any(k in ficha for k in ('rodamiento', 'piloto', 'ruleman', 'piola', 'aceite')):
        return False
    return True


def _banda_precio_linea(nombre: str) -> tuple[int, int]:
    n = _norm(nombre)
    if not n:
        return _BANDA_DEFAULT
    if _es_rodamiento_piloto(n):
        return _BANDA_RODAMIENTO_PILOTO
    if _es_piola_embrague(n):
        return _BANDA_PIOLA_EMBRAGUE
    if _es_aceite_caja(n):
        return _BANDAS_CATEGORIA['aceites']
    if any(k in n for k in ('embrague', 'clutch')):
        if _linea_es_kit(nombre):
            return _BANDA_KIT_EMBRAGUE
        if any(c in n for c in _COMPONENTE_EMBRAGUE):
            return _BANDA_COMPONENTE_EMBRAGUE
        return _BANDA_KIT_EMBRAGUE
    from .categoria_repuesto import clasificar_categoria

    return _BANDAS_CATEGORIA.get(clasificar_categoria(nombre), _BANDA_DEFAULT)


def _precio_plausible_para_linea(nombre: str, precio: int) -> bool:
    if not _precio_en_rango(precio):
        return False
    lo, hi = _banda_precio_linea(nombre)
    return lo <= precio <= hi


def _precio_de_candidato(candidato: dict[str, Any], nombre_linea: str) -> int:
    """Precio del snippet, y si la ficha extraída lo tapó, el que ya habíamos leído."""
    visto = _precio_desde_texto(str((candidato or {}).get('content') or ''), nombre_linea)
    if _precio_plausible_para_linea(nombre_linea, visto):
        return visto
    guardado = _to_int_clp((candidato or {}).get('precio_snippet'))
    if _precio_plausible_para_linea(nombre_linea, guardado):
        return guardado
    return 0


def _linea_duena_de_url(
    candidatos_por_nombre: dict[str, list[dict[str, Any]]],
    url: str,
) -> str:
    """La línea cuya lista contiene esa URL. Vacío si la comparten dos líneas."""
    encontrada = ''
    for nombre, candidatos in (candidatos_por_nombre or {}).items():
        if any(str(c.get('url') or '') == url for c in candidatos):
            if encontrada:
                return ''
            encontrada = nombre
    return encontrada


def _precio_desde_texto(texto: str, nombre_linea: str = '') -> int:
    """Precio de VENTA de la ficha. No el primer `$` del snippet (relacionados/cuotas)."""
    raw = texto or ''
    for m in _PRECIO_ETIQUETA_RE.finditer(raw):
        val = _parse_monto_clp(m.group(1))
        if _precio_plausible_para_linea(nombre_linea, val):
            return val
    limpio = _CUOTA_RE.sub(' ', raw)
    en_banda: list[int] = []
    for m in _PRECIO_CLP_RE.finditer(limpio):
        val = _parse_monto_clp(m.group(1))
        if _precio_plausible_para_linea(nombre_linea, val):
            en_banda.append(val)
    if not en_banda:
        return 0
    if len(en_banda) == 1:
        return en_banda[0]
    lo, hi = min(en_banda), max(en_banda)
    if hi > lo * 3:
        # Relacionados mezclados: el de esta ficha suele ser el etiquetado; si
        # no hubo etiqueta, el de la banda de la línea (no el kit de camioneta).
        piso, techo = _banda_precio_linea(nombre_linea)
        centro = (piso + techo) / 2
        return min(en_banda, key=lambda v: abs(v - centro))
    return en_banda[0]


_JSONLD_RE = re.compile(
    r'<script[^>]*type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)
_META_TAG_RE = re.compile(r'<meta\b[^>]*>', re.I)
_JSON_APP_RE = re.compile(
    r'<script[^>]*type\s*=\s*["\']application/json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)
_WOO_AMOUNT_RE = re.compile(
    r'woocommerce-Price-amount\b[^>]*>.{0,400}?(\d{1,3}(?:\.\d{3})+|\d+[.,]\d{2})',
    re.I | re.S,
)
_INS_WOO_RE = re.compile(
    r'<ins\b[^>]*>.{0,800}?woocommerce-Price-amount\b[^>]*>.{0,400}?'
    r'(\d{1,3}(?:\.\d{3})+|\d+[.,]\d{2})',
    re.I | re.S,
)
_DEL_RE = re.compile(r'<del\b[^>]*>.*?</del>', re.I | re.S)
_PRECIO_ACTUAL_RE = re.compile(
    r'precio\s+actual(?:\s+es)?\s*:?\s*(?:clp\s*)?\$?\s*([\d.]{4,12})',
    re.I,
)
_ML_FRACTION_RE = re.compile(
    r'andes-money-amount__fraction[^>]*>\s*([\d.]+)',
    re.I,
)
_SHOPIFY_PRICE_RE = re.compile(r'"price"\s*:\s*"?(\d+)"?')
_MONEDAS_EXTRANJERAS = frozenset({
    'USD', 'US', 'EUR', 'BRL', 'ARS', 'MXN', 'COP', 'PEN', 'UYU', 'GBP',
})


def _parse_monto_clp(raw: Any) -> int:
    """28.990 → 28990. 28990.00 y 28990,00 → 28990. No junta los decimales."""
    if isinstance(raw, bool) or raw is None:
        return 0
    if isinstance(raw, int):
        return raw if raw > 0 else 0
    if isinstance(raw, float):
        return int(round(raw)) if raw > 0 else 0
    texto = str(raw).strip()
    texto = re.sub(r'(?i)\bclp\b', '', texto)
    texto = texto.replace('$', '')
    texto = re.sub(r'\s+', '', texto)
    # El regex del snippet se come el punto final: "18.990." sigue siendo 18990.
    texto = texto.strip('.,')
    if not texto:
        return 0
    if re.fullmatch(r'\d{1,3}(\.\d{3})+', texto):
        return int(texto.replace('.', ''))
    if re.fullmatch(r'\d{1,3}(,\d{3})+', texto):
        return int(texto.replace(',', ''))
    decimal = re.fullmatch(r'(\d+)[.,](\d{2})', texto)
    if decimal:
        return int(decimal.group(1))
    if re.fullmatch(r'\d+', texto):
        return int(texto)
    return 0


def _moneda_es_clp(currency: Any) -> bool:
    letras = re.sub(r'[^A-Za-z]', '', str(currency or '')).upper()
    if not letras:
        return True
    if letras in ('CLP', 'CLF'):
        return True
    return letras not in _MONEDAS_EXTRANJERAS and not letras.startswith('US')


def _iter_jsonld(html: str):
    for raw in _JSONLD_RE.findall(html or ''):
        texto = (raw or '').strip()
        if not texto:
            continue
        try:
            yield json.loads(texto)
        except ValueError:
            continue


def _recolectar_precios_jsonld(node: Any, found: list[tuple[int, str]]) -> None:
    if isinstance(node, list):
        for item in node:
            _recolectar_precios_jsonld(item, found)
        return
    if not isinstance(node, dict):
        return
    if '@graph' in node:
        _recolectar_precios_jsonld(node.get('@graph'), found)
    tipo = node.get('@type') or ''
    if isinstance(tipo, list):
        tipo_s = ' '.join(str(t) for t in tipo)
    else:
        tipo_s = str(tipo)
    es_oferta = any(t in tipo_s for t in ('Product', 'Offer', 'AggregateOffer'))
    if es_oferta or 'price' in node or 'lowPrice' in node:
        if _moneda_es_clp(node.get('priceCurrency')):
            nombre = str(node.get('name') or '')
            for key in ('lowPrice', 'price'):
                if node.get(key) in (None, ''):
                    continue
                monto = _parse_monto_clp(node.get(key))
                if monto > 0:
                    found.append((monto, nombre))
                    break
        if node.get('priceSpecification'):
            _recolectar_precios_jsonld(node.get('priceSpecification'), found)
        if node.get('offers'):
            _recolectar_precios_jsonld(node.get('offers'), found)


def _precio_meta(html: str) -> int:
    for tag in _META_TAG_RE.findall(html or ''):
        low = tag.lower()
        if 'og:price:amount' not in low and 'product:price:amount' not in low:
            continue
        content = re.search(r'\bcontent\s*=\s*["\']([^"\']+)["\']', tag, flags=re.I)
        if not content:
            continue
        monto = _parse_monto_clp(content.group(1))
        if monto > 0:
            return monto
    return 0


def _meta_moneda_extranjera(html: str) -> bool:
    for tag in _META_TAG_RE.findall(html or ''):
        low = tag.lower()
        if 'price:currency' not in low:
            continue
        content = re.search(r'\bcontent\s*=\s*["\']([^"\']+)["\']', tag, flags=re.I)
        moneda = (content.group(1) if content else '').strip().upper()
        if moneda in _MONEDAS_EXTRANJERAS or 'usd' in low:
            return True
    return False


def _texto_plano_html(html: str) -> str:
    from html import unescape

    sin_script = re.sub(r'<script\b[^>]*>.*?</script>', ' ', html or '', flags=re.I | re.S)
    sin_style = re.sub(r'<style\b[^>]*>.*?</style>', ' ', sin_script, flags=re.I | re.S)
    sin_tags = re.sub(r'<[^>]+>', ' ', sin_style)
    return re.sub(r'\s+', ' ', unescape(sin_tags)).strip()


def _precio_oferta_visible(html: str) -> int:
    """El precio actual: <ins> de WooCommerce o 'El precio actual es'.

    El primer woocommerce-Price-amount de Sergio Escobar es el tachado
    ($58.500). El que se cobra está en <ins> ($52.650).
    """
    pagina = html or ''
    ins = _INS_WOO_RE.search(pagina)
    if ins:
        monto = _parse_monto_clp(ins.group(1))
        if monto > 0:
            return monto
    actual = _PRECIO_ACTUAL_RE.search(_texto_plano_html(pagina))
    if actual:
        monto = _parse_monto_clp(actual.group(1))
        if monto > 0:
            return monto
    return 0


def _precio_woo(html: str) -> int:
    pagina = _DEL_RE.sub(' ', html or '')
    match = _WOO_AMOUNT_RE.search(pagina)
    if not match:
        return 0
    return _parse_monto_clp(match.group(1))


def _precio_ml_visible(html: str, url: str) -> int:
    blob = f'{url} {html or ""}'[:800].lower()
    if 'mercadolibre' not in blob and 'andes-money-amount__fraction' not in (html or ''):
        return 0
    match = _ML_FRACTION_RE.search(html or '')
    if not match:
        return 0
    return _parse_monto_clp(match.group(1))


def _precio_shopify(html: str, url: str, nombre_linea: str) -> int:
    """El variant de Shopify guarda centavos. El JSON-LD de la misma ficha no."""
    blob = f'{url}\n{(html or "")[:12000]}'.lower()
    if 'shopify' not in blob:
        return 0
    for bloque in _JSON_APP_RE.findall(html or ''):
        for match in _SHOPIFY_PRICE_RE.finditer(bloque):
            valor = int(match.group(1))
            if _precio_plausible_para_linea(nombre_linea, valor):
                return valor
            if valor % 100 == 0:
                mayor = valor // 100
                if _precio_plausible_para_linea(nombre_linea, mayor):
                    return mayor
    return 0


def _cuerpo_compatibilidad(html: str) -> str:
    """Título, marca y tabla de compatibilidad. No el menú de la tienda."""
    pagina = html or ''
    if not pagina.strip():
        return ''
    partes: list[str] = []
    titulo = re.search(r'<title[^>]*>(.*?)</title>', pagina, flags=re.I | re.S)
    if titulo:
        partes.append(_texto_plano_html(titulo.group(1))[:240])
    h1 = re.search(r'<h1[^>]*>(.*?)</h1>', pagina, flags=re.I | re.S)
    if h1:
        partes.append(_texto_plano_html(h1.group(1))[:240])
    for tag in _META_TAG_RE.findall(pagina):
        low = tag.lower()
        if 'og:description' not in low and 'name="description"' not in low and "name='description'" not in low:
            continue
        content = re.search(r'\bcontent\s*=\s*["\']([^"\']+)["\']', tag, flags=re.I)
        if content:
            partes.append(content.group(1)[:400])
    for data in _iter_jsonld(pagina):
        _texto_producto_jsonld(data, partes)
    plano = _texto_plano_html(pagina)
    bajo = plano.lower()
    for ancla in (
        'modelos de autos compatibles',
        'compatible con',
        'compatibilidades',
        'aplicaciones',
        'marca:',
        'marca |',
    ):
        idx = bajo.find(ancla)
        if idx >= 0:
            partes.append(plano[idx:idx + 420])
    return re.sub(r'\s+', ' ', ' '.join(parte for parte in partes if parte)).strip()[:1500]


def _texto_producto_jsonld(node: Any, partes: list[str], depth: int = 0) -> None:
    if depth > 6:
        return
    if isinstance(node, list):
        for item in node:
            _texto_producto_jsonld(item, partes, depth + 1)
        return
    if not isinstance(node, dict):
        return
    if '@graph' in node:
        _texto_producto_jsonld(node.get('@graph'), partes, depth + 1)
    tipo = node.get('@type') or ''
    tipo_s = ' '.join(str(t) for t in tipo) if isinstance(tipo, list) else str(tipo)
    if 'Product' in tipo_s or node.get('name') or node.get('description'):
        nombre = str(node.get('name') or '').strip()
        descripcion = str(node.get('description') or '').strip()
        if nombre:
            partes.append(nombre[:240])
        if descripcion:
            partes.append(descripcion[:400])


def _html_sin_ruido_precio(html: str) -> str:
    """Saca cuotas y el monto del envío antes de leer el precio de la ficha."""
    limpio = _CUOTA_RE.sub(' ', html or '')
    return _ENVIO_PRECIO_RE.sub(' ', limpio)


def _precio_desde_html(html: str, nombre_linea: str = '', url: str = '') -> int:
    """Precio de ESTA ficha. El actual, no el tachado ni el de los relacionados."""
    pagina = html or ''
    if not pagina.strip():
        return 0
    oferta = _precio_oferta_visible(pagina)
    if oferta and _precio_plausible_para_linea(nombre_linea, oferta):
        return oferta
    jsonld: list[tuple[int, str]] = []
    for data in _iter_jsonld(pagina):
        _recolectar_precios_jsonld(data, jsonld)
    respaldo = 0
    en_banda: list[int] = []
    if jsonld:
        con_nombre = [
            (monto, nom) for monto, nom in jsonld
            if nom and _titulo_nombra_pieza(nombre_linea, nom)
        ]
        pool = con_nombre or jsonld
        en_banda = [
            monto for monto, _nom in pool
            if _precio_plausible_para_linea(nombre_linea, monto)
        ]
        if not en_banda:
            respaldo = pool[0][0]
    if en_banda:
        estante = _precio_woo(_html_sin_ruido_precio(pagina))
        # JSON-LD de una cuota o un relacionado: la mitad del estante visible.
        if (
            estante
            and estante > en_banda[0] * 2
            and _precio_plausible_para_linea(nombre_linea, estante)
        ):
            return estante
        return en_banda[0]
    if not _meta_moneda_extranjera(pagina):
        meta = _precio_meta(pagina)
        if meta and _precio_plausible_para_linea(nombre_linea, meta):
            return meta
        if meta and not jsonld:
            return meta
    for lector in (
        _precio_woo(_html_sin_ruido_precio(pagina)),
        _precio_ml_visible(pagina, url),
        _precio_shopify(pagina, url, nombre_linea),
    ):
        if lector and _precio_plausible_para_linea(nombre_linea, lector):
            return lector
    # 1192 en el JSON-LD no pisa un $11.920 visible: el punto es de miles.
    visible = _precio_desde_texto(
        _texto_plano_html(_html_sin_ruido_precio(pagina)),
        nombre_linea,
    )
    if visible and _precio_plausible_para_linea(nombre_linea, visible):
        return visible
    return respaldo


def _banda_min_de(bandas_min: dict[str, int] | None, nombre: str) -> int:
    if not bandas_min:
        return 0
    if nombre in bandas_min:
        try:
            return max(0, int(bandas_min[nombre] or 0))
        except (TypeError, ValueError):
            return 0
    clave = _clave_fuzzy(nombre)
    for llave, valor in bandas_min.items():
        if _clave_fuzzy(str(llave)) == clave:
            try:
                return max(0, int(valor or 0))
            except (TypeError, ValueError):
                return 0
    return 0


def _motivo_de_candidato(
    cand: dict[str, Any],
    *,
    nombre: str,
    cupo: set[str],
    url_elegida: str,
    pedidas: set[str],
    htmls: dict[str, str],
    anio: Any = None,
    cilindraje: Any = None,
    modelo: str = '',
    tipo_motor: str = '',
    banda_min: int = 0,
    banda_max: int = 0,
) -> str:
    """Por qué esta URL quedó o se botó. Una línea de log por candidato."""
    url = str(cand.get('url') or '')
    if url_elegida and url == url_elegida:
        return 'elegido'
    motivo_pad = _motivo_calidad_pastilla(
        cand,
        nombre=nombre,
        modelo=modelo,
        tipo_motor=tipo_motor,
        banda_min=banda_min,
        banda_max=banda_max,
    )
    if motivo_pad:
        return motivo_pad
    if not _candidato_sirve_linea(
        nombre, cand, anio=anio, cilindraje=cilindraje, modelo=modelo,
        tipo_motor=tipo_motor, banda_min=banda_min, banda_max=banda_max,
    ):
        return 'otra_pieza'
    titulo = str(cand.get('title') or '')
    if titulo and not _titulo_nombra_pieza(nombre, titulo):
        return 'titulo_no_es_la_pieza'
    # fuera_del_cupo: no está entre las 5 URLs que se abren. Un listado con
    # precio no puede ocupar ese lugar delante de una ficha que nombra al Bravo.
    if url not in cupo:
        return 'fuera_del_cupo'
    if int(cand.get('precio_fuera_banda') or 0) > 0:
        return 'precio_fuera_de_banda'
    precio = _precio_de_candidato(cand, nombre)
    if precio and not _precio_plausible_para_linea(nombre, precio):
        return 'precio_fuera_de_banda'
    if url in pedidas and url not in htmls and not precio:
        return 'ficha_no_leida'
    if not precio:
        return 'sin_precio'
    return 'otra_ficha_mejor'


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
            f'\n      precio detectado: {_precio_desde_texto(c.get("content") or "", nombre) or "ninguno"}'
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
1. encontrado=true SOLO si la ficha es LA MISMA PIEZA y es compatible con este auto (marca, modelo, año y motor o cilindrada). El kit de embrague es disco + prensa + rodamiento de empuje vendidos juntos: esa ficha SÍ es el kit. Una ficha de solo disco, solo prensa o solo rodamiento NO es el kit. Prioridad: (a) ficha que nombre el modelo y la variante/motor de ESTE vehículo, (b) ficha que nombre marca y modelo, (c) casa especialista por sobre retail generalista. Insumos universales (filtro, aceite) sí pueden ser de la categoría sin el modelo.
2. compatibilidad: alta si el título/texto nombra modelo y el año del auto entra en el rango de la ficha; media si nombra la marca o es un insumo universal; baja si es genérico. Si la ficha declara años y el auto queda fuera, encontrado=false.
3. marca_repuesto = marca de la PIEZA visible en título/texto (Bosch, Gates, NGK, etc.). Si no aparece, "". NUNCA "Original", "GENÉRICO" ni la marca del auto.
4. calidad = original (genuino/agencia), oem (equivalente OEM) o alternativo (aftermarket / tipo alternativo). Solo si el texto lo decide. Si duda o nombra dos, "".
5. pais_origen = país de fabricación/procedencia de la pieza solo si el texto lo dice (hecho en, importado de, origen). No uses Chile por ser la tienda.
6. precio_clp = el precio de VENTA de ESA ficha, el que está junto a "Precio:". Entero CLP sin puntos ni símbolo. NO uses precios de productos relacionados, cuotas, REF, EAN ni SKU. Si el candidato trae "precio detectado", úsalo solo si coincide con "Precio:" o es el único monto creíble de esa ficha.
6b. Entre candidatos de la misma pieza, PREFIERE el que tenga precio; uno sin monto solo si ninguno lo trae.
6c. Si el monto es irreal para esa pieza, descarta ese candidato: prensa/disco/collarín de auto liviano fuera de 8.000–120.000; kit de 3 piezas fuera de 35.000–280.000; rodamiento piloto o de volante fuera de 3.000–45.000 (un volante bimasa no es el rodamiento); piola o cable de embrague fuera de 4.000–55.000; aceite de caja fuera de 3.000–90.000 (un litro o el llenado, no la caja de cambios ni el kit).
6d. Si la línea es un KIT y hay un candidato "kit … 3 piezas" compatible con el auto, elígelo. Un componente no cotiza el kit.
7. url = EXACTAMENTE la url del candidato elegido (cópiala tal cual, no la modifiques).
8. tienda = quién vende: el sitio según el dominio (AutoPlanet, Refax, etc.) o, si es una publicación de marketplace, el nombre del vendedor visible en el texto.
9. Si NINGÚN candidato de la lista sirve, encontrado=false.
10. Responde SOLO JSON válido (sin markdown):
{{
  "resultados": [
    {{
      "nombre_buscado": "...",
      "encontrado": true,
      "nombre_producto": "...",
      "marca_repuesto": "...",
      "calidad": "original|oem|alternativo|",
      "pais_origen": "",
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
    override = (getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_MODEL', '') or '').strip()
    modelos = modelos_gemini_cotizacion(override or None)
    if not api_key or not modelos:
        return None
    timeout_http = timeout_http_gemini(timeout)
    for mi, model in enumerate(modelos):
        endpoint = (
            f'https://generativelanguage.googleapis.com/v1beta/models/{model}:'
            f'generateContent?key={api_key}'
        )
        usar_thinking = True
        payload: dict[str, Any] = {
            'contents': [{'parts': [{'text': prompt}]}],
            'generationConfig': generation_config_gemini(
                temperature=0.2,
                max_output=4096,
                thinking=usar_thinking,
            ),
        }
        if use_url_context:
            payload['tools'] = [{'url_context': {}}]
            if getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_GROUNDING', False):
                payload['tools'].append({'google_search': {}})
        for thinking_pass in (1, 2):
            try:
                resp = requests.post(endpoint, json=payload, timeout=timeout_http)
            except (requests.ReadTimeout, requests.Timeout) as exc:
                logger.warning('busqueda_web_repuestos: timeout Gemini model=%s: %s', model, exc)
                break
            except requests.RequestException as exc:
                logger.warning('busqueda_web_repuestos: error de red Gemini model=%s: %s', model, exc)
                break
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError:
                    return None
            logger.warning(
                'busqueda_web_repuestos: Gemini status=%s model=%s body=%s',
                resp.status_code,
                model,
                resp.text[:300],
            )
            if resp.status_code == 400 and usar_thinking:
                usar_thinking = False
                payload['generationConfig'] = generation_config_gemini(
                    temperature=0.2,
                    max_output=4096,
                    thinking=False,
                )
                continue
            if resp.status_code in (429, 503) and mi < len(modelos) - 1:
                logger.warning(
                    'busqueda_web_repuestos: Gemini %s model=%s (Google saturado, no es la cuota); '
                    'pasa a %s',
                    resp.status_code,
                    model,
                    modelos[mi + 1],
                )
            break
    return None


def _es_pastillas_freno(nombre: str) -> bool:
    """Pastilla o balata. Un disco de freno no entra."""
    n = _norm(nombre)
    if 'freno' not in n and 'balata' not in n:
        return False
    return 'pastilla' in n or 'balata' in n


def _viscosidad_aceite(texto: str) -> str:
    """'5W-40' y '5W40' → '5w40'. La cilindrada 1.4 no es viscosidad."""
    m = re.search(r'\b(\d{1,2})\s*w\s*(\d{2})\b', _norm(texto))
    if not m:
        return ''
    return f'{m.group(1)}w{m.group(2)}'


def _consultas_aceite_motor(nombre: str, especificacion: str = '') -> list[str]:
    """El lubricante no es del auto: se busca por viscosidad y envase.

    'Aceite de motor' + '5W40 sintético' → 
    'aceite 5w40 sintetico 4 litros', 'aceite motor 5w40 1 litro'.
    Sin modelo, sin año y sin el alias de la casa.
    """
    texto = _norm(f'{nombre} {especificacion}')
    visc = _viscosidad_aceite(texto)
    if 'sintetic' in texto and 'semi' not in texto:
        calidad = 'sintetico'
    elif 'semi' in texto and 'sintetic' in texto:
        calidad = 'semisintetico'
    elif 'mineral' in texto:
        calidad = 'mineral'
    else:
        calidad = ''
    if visc and calidad:
        return [
            f'aceite {visc} {calidad} 4 litros',
            f'aceite motor {visc} 1 litro',
        ]
    if visc:
        return [
            f'aceite {visc} 4 litros',
            f'aceite motor {visc} 1 litro',
        ]
    return ['aceite motor 4 litros', 'aceite motor 1 litro']


def _bravo_tjet(modelo: str, tipo_motor: str) -> bool:
    """Bravo II T-Jet. El 1.4 atmosférico usa otra pastilla."""
    texto = _norm(f'{modelo} {tipo_motor}')
    return 'bravo' in texto and ('tjet' in texto or 't jet' in texto)


def _consultas_pastillas(
    nombre: str,
    *,
    marca: str,
    modelo: str,
    cilindraje: str,
    tipo_motor: str = '',
) -> list[str]:
    """Toda la escalera corta, no solo la primera frase.

    'pastillas freno delanteras fiat bravo 1.4', 'pastillas freno fiat bravo'
    y, si el auto es un Bravo T-Jet, 'pastillas freno fiat linea t-jet'.
    Fras-le PD/92 (Teves) lista juntos el Bravo 1.4, el Linea 1.4 T-Jet y el
    Punto 1.4 T-Jet. El Stilo 1.4 no entra: comparte la pastilla chica Bosch
    (ATE 603982) con el Bravo II 1.4 de 90 hp, no con el T-Jet.
    """
    n = _norm(nombre)
    if 'traser' in n:
        posicion = 'traseras'
    elif 'delanter' in n:
        posicion = 'delanteras'
    else:
        posicion = ''
    modelo_corto = _modelo_busqueda(modelo).lower()
    marca_q = str(marca or '').strip().lower()
    cil = str(cilindraje or '').strip()
    especifica = ' '.join(
        p for p in ['pastillas freno', posicion, marca_q, modelo_corto, cil] if p
    )
    corta = ' '.join(p for p in ['pastillas freno', marca_q, modelo_corto] if p)
    consultas = [especifica, corta]
    if posicion != 'traseras' and _bravo_tjet(modelo, tipo_motor):
        consultas.append('pastillas freno fiat linea t-jet')
    return consultas


_SPEC_BUJIA = frozenset({
    'iridio', 'iridium', 'platino', 'cobre', 'niquel', 'nickel',
})


def _es_consumible_corto(nombre: str) -> bool:
    """Bujías y filtros. La casa no los publica con el año ni con la marca NGK."""
    n = _norm(nombre)
    return 'bujia' in n or 'filtro' in n


def _nucleo_consumible(nombre: str) -> str:
    n = _norm(nombre)
    if 'bujia' in n:
        return 'bujias'
    if 'filtro' in n and 'aire' in n:
        return 'filtro aire'
    if 'filtro' in n and any(k in n for k in ('polen', 'habitaculo', 'cabina')):
        return 'filtro polen'
    if 'filtro' in n and any(k in n for k in ('combustible', 'bencina', 'gasolina', 'nafta')):
        return 'filtro combustible'
    if 'filtro' in n and 'aceite' in n:
        return 'filtro aceite'
    amplia, _ = _nombre_busqueda_amplia(nombre)
    tokens = [t for t in amplia.split() if t not in _SPEC_BUJIA]
    return ' '.join(tokens[:3]) or _nombre_busqueda_corto(nombre)


def _modelo_corto_auto(modelo: str, tipo_motor: str = '') -> str:
    """'Sport Bravo' y 'BRAVO SPORT TJET' se buscan como bravo."""
    if 'bravo' in _norm(f'{modelo} {tipo_motor}'):
        return 'bravo'
    return _modelo_busqueda(modelo).lower()


def _consultas_consumible(
    nombre: str,
    *,
    marca: str,
    modelo: str,
    cilindraje: str,
    tipo_motor: str = '',
) -> list[str]:
    """Igual que las pastillas: pieza + auto, sin año, sin trim y sin NGK.

    'bujias fiat bravo 1.4', 'bujias fiat bravo' y, en un Bravo T-Jet,
    'bujias fiat linea t-jet'. El filtro de aire usa la misma escalera.
    """
    nucleo = _nucleo_consumible(nombre)
    modelo_corto = _modelo_corto_auto(modelo, tipo_motor)
    marca_q = str(marca or '').strip().lower()
    cil = str(cilindraje or '').strip()
    especifica = ' '.join(p for p in [nucleo, marca_q, modelo_corto, cil] if p)
    corta = ' '.join(p for p in [nucleo, marca_q, modelo_corto] if p)
    consultas = [especifica, corta]
    if _bravo_tjet(modelo, tipo_motor):
        consultas.append(f'{nucleo} fiat linea t-jet')
    if nucleo:
        consultas.append(nucleo)
    return consultas


def _escalera_consultas(
    nombre: str,
    *,
    marca: str,
    modelo: str,
    cilindraje: str,
    casas: list[dict[str, Any]],
    tipo_motor: str = '',
    especificacion: str = '',
) -> list[str]:
    """Consultas como las haría un humano en Google, de más específica a más corta.

    Un kit de embrague se publica como "kit embrague kia morning 1.1 g4hg", no
    como "3 piezas". Esa frase mandaba al agente a listados y a kits de otro motor.
    El aceite de motor se publica como "aceite 5w40 4 litros", no con el auto.
    Las pastillas, como "pastillas freno fiat bravo", sin el trim ni el año.
    """
    from .enriquecer_repuestos import _es_linea_aceite_motor

    if _es_linea_aceite_motor(nombre):
        consultas = _consultas_aceite_motor(nombre, especificacion)
    elif _es_pastillas_freno(nombre):
        consultas = _consultas_pastillas(
            nombre,
            marca=marca,
            modelo=modelo,
            cilindraje=cilindraje,
            tipo_motor=tipo_motor,
        )
    elif _es_consumible_corto(nombre):
        consultas = _consultas_consumible(
            nombre,
            marca=marca,
            modelo=modelo,
            cilindraje=cilindraje,
            tipo_motor=tipo_motor,
        )
    else:
        consultas = _escalera_consultas_vehiculo(
            nombre,
            marca=marca,
            modelo=modelo,
            cilindraje=cilindraje,
            casas=casas,
            tipo_motor=tipo_motor,
        )
    vistas: set[str] = set()
    out: list[str] = []
    for q in consultas:
        clave = _norm(q)
        if q and clave not in vistas:
            vistas.add(clave)
            out.append(q)
    return out


def _escalera_consultas_vehiculo(
    nombre: str,
    *,
    marca: str,
    modelo: str,
    cilindraje: str,
    casas: list[dict[str, Any]],
    tipo_motor: str = '',
) -> list[str]:
    """Escalera con el auto. No la usan el aceite de motor ni las pastillas."""
    completo = _modelo_busqueda_completo(modelo)
    # "rodamiento de volante" en Google cae en el volante bimasa. La casa
    # publica el piloto como rodamiento piloto. La piola, como cable.
    if _es_rodamiento_piloto(nombre):
        nombre = 'rodamiento piloto'
    elif _es_piola_embrague(nombre):
        nombre = 'piola de embrague'
    elif _es_aceite_caja(nombre):
        nombre = 'aceite caja cambios'
    nucleo = _nombre_busqueda_corto(nombre)
    motor = _codigo_motor_query(tipo_motor)
    base = ' '.join(p for p in [nombre, marca, completo, cilindraje, motor] if p)
    corta = ' '.join(p for p in [nombre, marca, _modelo_busqueda(modelo)] if p)
    consultas = (
        [f"{base} {casa['alias']}" for casa in casas[:1]]
        + [base, corta]
        + ([f'{nucleo} {marca}'.strip()] if nucleo and marca else [])
        + ([nucleo] if nucleo else [])
    )
    if _linea_es_kit(nombre):
        kit_nucleo = 'kit embrague' if 'embrague' in _norm(nombre) else nucleo or nombre
        kit_qs = [
            ' '.join(
                p for p in [kit_nucleo, marca, _modelo_busqueda(modelo), cilindraje, motor]
                if p
            ),
            ' '.join(p for p in [kit_nucleo, marca, _modelo_busqueda(modelo), cilindraje] if p),
            ' '.join(p for p in [kit_nucleo, marca, _modelo_busqueda(modelo)] if p),
        ]
        consultas = kit_qs + consultas
    amplia, saco_ruido = _nombre_busqueda_amplia(nombre)
    if saco_ruido and amplia and not _linea_es_kit(nombre):
        # La frase con TISS / cerámica / Sport T-Jet gasta las 3 consultas
        # y la casa publica "pastilla freno fiat bravo" o "aceite 5w40 4l".
        modelo_corto = _modelo_busqueda(modelo)
        consultas = [
            ' '.join(p for p in [amplia, marca, modelo_corto] if p),
            amplia,
        ] + list(consultas)
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
    crudos = _tavily_buscar_uno(query, max_results=8)
    validos = [
        c for c in crudos
        if _es_tienda_chilena(c['url'], whitelist, c.get('content') or '')
        and not _es_listado_sin_vendedor(c['url'])
        and not _es_pagina_sin_ficha(c['url'])
    ]
    logger.info(
        'busqueda_web_repuestos[tavily] query=%s resultados=%s fichas=%s',
        str(query or '')[:160],
        len(crudos),
        len(validos),
    )
    return validos


def _ordenar_candidatos(
    crudos: list[dict[str, Any]],
    *,
    tokens_vehiculo: list[str] | None = None,
    priorizar_precio: bool = False,
    nombre_linea: str = '',
    anio: Any = None,
    cilindraje: Any = None,
    modelo: str = '',
    tipo_motor: str = '',
    banda_min: int = 0,
    banda_max: int = 0,
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
    # El retail generalista solo se usa si no hay ninguna casa de repuestos,
    # salvo que el título ya nombre el auto (Sodimac/Lider "Fiat Bravo 1.4").
    if any(not _es_generalista(c['url']) for c in candidatos):
        def _se_queda(c: dict[str, Any]) -> bool:
            if not _es_generalista(c['url']):
                return True
            return _titulo_es_del_auto(str(c.get('title') or ''), modelo, tipo_motor)

        candidatos = [c for c in candidatos if _se_queda(c)]
    tokens = tokens_vehiculo or []

    def rango(c: dict[str, Any]) -> tuple[int, ...]:
        no_sirve = 0 if _candidato_sirve_linea(
            nombre_linea, c, anio=anio, cilindraje=cilindraje, modelo=modelo,
            tipo_motor=tipo_motor, banda_min=banda_min, banda_max=banda_max,
        ) else 1
        calce = -_calce_vehiculo(c, tokens)
        precio = _precio_desde_texto(c.get('content') or '', nombre_linea)
        sin_precio = 0 if precio else 1
        no_esp = 0 if _es_de_especialista(c) else 1
        # Pastillas: un título que dice Bravo entra al cupo antes que un
        # listado con precio. Sin esto, GMAK y Repuestos del Sol quedan
        # fuera_del_cupo (no están entre las 5 URLs que se abren).
        if _es_pastillas_freno(nombre_linea) or _es_consumible_corto(nombre_linea):
            titulo_c = str(c.get('title') or '')
            if _titulo_es_del_auto(titulo_c, modelo, tipo_motor):
                rango_modelo = 0
            elif _titulo_es_cruce_tjet(titulo_c, modelo, tipo_motor):
                rango_modelo = 1
            else:
                rango_modelo = 2
        else:
            rango_modelo = 0
        if priorizar_precio:
            return (no_sirve, rango_modelo, sin_precio, calce, no_esp)
        return (no_sirve, rango_modelo, calce, no_esp, sin_precio)

    return sorted(candidatos, key=rango)


def _seleccionar_cupo(
    ordenados: list[dict[str, Any]],
    *,
    nombre: str,
    anio: Any = None,
    cilindraje: Any = None,
    modelo: str = '',
    tipo_motor: str = '',
    banda_min: int = 0,
    banda_max: int = 0,
) -> list[dict[str, Any]]:
    """Las 5 fichas que se abren. Un Bravo con precio no pierde contra una sin monto."""
    sirven = [
        c for c in ordenados
        if _candidato_sirve_linea(
            nombre, c, anio=anio, cilindraje=cilindraje, modelo=modelo,
            tipo_motor=tipo_motor, banda_min=banda_min, banda_max=banda_max,
        )
        and _titulo_nombra_pieza(nombre, str(c.get('title') or ''))
    ]
    if not (_es_pastillas_freno(nombre) or _es_consumible_corto(nombre)):
        return sirven[:_FICHA_HTML_MAX]
    con_precio: list[dict[str, Any]] = []
    sin_precio: list[dict[str, Any]] = []
    cruce: list[dict[str, Any]] = []
    resto: list[dict[str, Any]] = []
    for cand in sirven:
        titulo = str(cand.get('title') or '')
        if _titulo_es_del_auto(titulo, modelo, tipo_motor):
            if _precio_de_candidato(cand, nombre) > 0:
                con_precio.append(cand)
            else:
                sin_precio.append(cand)
        elif _titulo_es_cruce_tjet(titulo, modelo, tipo_motor):
            cruce.append(cand)
        else:
            resto.append(cand)
    return (con_precio + sin_precio + cruce + resto)[:_FICHA_HTML_MAX]


def _anotar_url_rechazada(notas: dict[str, Any], url: str, *, linea: str = '') -> None:
    """La URL ya no puede volver en Gemini, el cache ni el apply de este request.

    Sin línea, queda vedada en todo el request (listado, precio bajo, otro
    modelo). Con línea, solo en esa línea: el disco no es el termostato, pero
    sí puede cotizar la línea de discos.
    """
    limpia = str(url or '').strip()
    if not limpia:
        return
    bolsa = notas.get('_urls_rechazadas')
    if not isinstance(bolsa, dict):
        bolsa = {'motivo': 'rechazadas', 'urls': []}
        notas['_urls_rechazadas'] = bolsa
    if linea:
        por_linea = bolsa.setdefault('por_linea', {})
        lista = por_linea.setdefault(str(linea), [])
        if limpia not in lista:
            lista.append(limpia)
        return
    urls = bolsa.setdefault('urls', [])
    if limpia not in urls:
        urls.append(limpia)


def urls_rechazadas_de(notas: dict[str, Any] | None, linea: str = '') -> set[str]:
    if not isinstance(notas, dict):
        return set()
    bolsa = notas.get('_urls_rechazadas')
    if isinstance(bolsa, (list, set, tuple)):
        return {str(url) for url in bolsa if url}
    if not isinstance(bolsa, dict):
        return set()
    urls = {str(url) for url in (bolsa.get('urls') or []) if url}
    if not linea:
        return urls
    clave = _clave_fuzzy(linea)
    for nombre, lista in (bolsa.get('por_linea') or {}).items():
        if nombre == linea or (clave and _clave_fuzzy(str(nombre)) == clave):
            urls.update(str(url) for url in (lista or []) if url)
    return urls


def _motivo_rechazo_duro(
    cand: dict[str, Any],
    *,
    nombre: str,
    anio: Any = None,
    cilindraje: Any = None,
    modelo: str = '',
    tipo_motor: str = '',
    banda_min: int = 0,
    banda_max: int = 0,
) -> str:
    """Motivo que saca la URL del request. '' si todavía puede cotizarse.

    fuera_del_cupo no entra: esa ficha no se abrió, no está rechazada.
    """
    motivo = _motivo_calidad_pastilla(
        cand, nombre=nombre, modelo=modelo, tipo_motor=tipo_motor,
        banda_min=banda_min, banda_max=banda_max,
    )
    if motivo:
        return motivo
    if not _candidato_sirve_linea(
        nombre, cand, anio=anio, cilindraje=cilindraje, modelo=modelo,
        tipo_motor=tipo_motor, banda_min=banda_min, banda_max=banda_max,
    ):
        return 'otra_pieza'
    titulo = str(cand.get('title') or '')
    if titulo and not _titulo_nombra_pieza(nombre, titulo):
        return 'titulo_no_es_la_pieza'
    return ''


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


def _hits_desde_candidatos(
    candidatos_por_nombre: dict[str, list[dict[str, str]]],
    tokens_veh,
    *,
    marca_vehiculo: str = '',
    anio: Any = None,
    cilindraje: Any = None,
    modelo: str = '',
    tipo_motor: str = '',
    bandas_min: dict[str, int] | None = None,
    bandas_max: dict[str, int] | None = None,
) -> dict[str, dict[str, Any]]:
    """Arma hits desde snippet/ficha Tavily cuando el monto ya es legible."""
    out: dict[str, dict[str, Any]] = {}
    for nombre, candidatos in (candidatos_por_nombre or {}).items():
        clave = _clave_fuzzy(nombre)
        if not clave:
            continue
        piso = _banda_min_de(bandas_min, nombre)
        techo = _banda_min_de(bandas_max, nombre)
        rescate = next(
            (
                (c, precio)
                for c, precio in (
                    (c, _precio_de_candidato(c, nombre)) for c in candidatos
                )
                if _precio_plausible_para_linea(nombre, precio)
                and _candidato_sirve_linea(
                    nombre, c, anio=anio, cilindraje=cilindraje, modelo=modelo,
                    tipo_motor=tipo_motor, banda_min=piso, banda_max=techo,
                )
                and _titulo_nombra_pieza(nombre, str(c.get('title') or ''))
            ),
            None,
        )
        if not rescate:
            continue
        candidato, precio = rescate
        host = _dominio_de_url(candidato['url'])
        nombre_prod = str(candidato.get('title') or nombre)[:200]
        ficha_txt = f"{nombre_prod} {candidato.get('content') or ''} {candidato.get('cuerpo') or ''}"
        attrs = _atributos_desde_texto(
            ficha_txt,
            marca_vehiculo=marca_vehiculo,
        )
        calce = _calce_vehiculo(candidato, tokens_veh)
        hit = {
            'nombre_buscado': nombre[:200],
            'nombre_producto': nombre_prod,
            'marca_repuesto': _marca_canonica(attrs['marca_repuesto'], ficha_txt),
            'precio_clp': precio,
            'tienda': _tienda_de_ficha(candidato['url'], ficha_txt),
            'dominio': host[:200],
            'url': candidato['url'],
            'compatibilidad': 'media' if calce >= 2 else 'baja',
            'confianza': 0.7 if calce >= 2 else 0.6,
        }
        if attrs['calidad']:
            hit['calidad'] = attrs['calidad']
        if attrs['pais_origen']:
            hit['pais_origen'] = attrs['pais_origen']
        out[clave] = hit
    return out


class BusquedaWebCancelada(Exception):
    """El taller cortó la búsqueda. No se siguen consultando tiendas."""


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
    on_progreso=None,
    deberia_cancelar=None,
    avisos: dict[str, dict[str, str]] | None = None,
    plan: dict[str, Any] | None = None,
    especificaciones: dict[str, str] | None = None,
    bandas_min: dict[str, int] | None = None,
    bandas_max: dict[str, int] | None = None,
) -> dict[str, dict[str, Any]]:
    """Agregador Tavily (JSON real) + Gemini solo como filtro/formateador."""
    whitelist = _dominios_whitelist()
    casas_marca = _especialistas_de_marca(marca)
    tokens_veh = _tokens_vehiculo(marca, modelo, anio, cilindraje)
    fuentes_vivo = ['Tiendas de Chile']
    fuentes_vivo += [c['nombre'] for c in casas_marca[:2] if c.get('nombre')]
    if 'Mercado Libre' not in fuentes_vivo:
        fuentes_vivo.append('Mercado Libre')
    def _cortar() -> None:
        if callable(deberia_cancelar) and deberia_cancelar():
            raise BusquedaWebCancelada()

    candidatos_por_nombre: dict[str, list[dict[str, str]]] = {}
    consultas_usadas: dict[str, list[str]] = {}
    crudos_por_nombre: dict[str, list[dict[str, Any]]] = {}
    cupo_por_nombre: dict[str, list[str]] = {}
    pedidas: list[str] = []
    htmls: dict[str, str] = {}
    notas = avisos if avisos is not None else {}
    pisos = bandas_min or {}
    techos = bandas_max or {}

    def _piso(nombre_linea: str) -> int:
        return _banda_min_de(pisos, nombre_linea)

    def _techo(nombre_linea: str) -> int:
        return _banda_min_de(techos, nombre_linea)

    def _cerrar_sin_hit(hits: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Si la línea quedó sin ficha, el motivo dice qué se buscó y qué se botó."""
        rechazadas = urls_rechazadas_de(notas)
        if rechazadas:
            hits = {
                clave: hit for clave, hit in (hits or {}).items()
                if str((hit or {}).get('url') or '') not in rechazadas
            }
        elegido: dict[str, str] = {}
        for hit in (hits or {}).values():
            if not isinstance(hit, dict):
                continue
            clave_hit = _clave_fuzzy(str(hit.get('nombre_buscado') or ''))
            url_hit = str(hit.get('url') or '')
            if clave_hit and url_hit:
                elegido[clave_hit] = url_hit
        pedidas_set = set(pedidas)
        for nombre_linea, crudos_linea in crudos_por_nombre.items():
            cupo = set(cupo_por_nombre.get(nombre_linea) or [])
            url_elegida = elegido.get(_clave_fuzzy(nombre_linea), '')
            vistos: set[str] = set()
            for cand in crudos_linea:
                url = str(cand.get('url') or '')
                if not url or url in vistos:
                    continue
                vistos.add(url)
                motivo = _motivo_de_candidato(
                    cand,
                    nombre=nombre_linea,
                    cupo=cupo,
                    url_elegida=url_elegida,
                    pedidas=pedidas_set,
                    htmls=htmls,
                    anio=anio,
                    cilindraje=cilindraje,
                    modelo=modelo,
                    tipo_motor=tipo_motor,
                    banda_min=_piso(nombre_linea),
                    banda_max=_techo(nombre_linea),
                )
                logger.info(
                    'busqueda_web_repuestos[tavily] candidato linea=%s titulo=%s url=%s motivo=%s '
                    'precio=%s banda_min=%s',
                    nombre_linea[:80],
                    str(cand.get('title') or '')[:120],
                    url[:180],
                    motivo,
                    _precio_de_candidato(cand, nombre_linea) or int(cand.get('precio_fuera_banda') or 0) or '',
                    _piso(nombre_linea) or '',
                )
                if motivo in (
                    'listado', 'precio_bajo_banda', 'precio_alto_banda',
                    'modelo_incompatible', 'sin_modelo',
                ):
                    _anotar_url_rechazada(notas, url)
                elif motivo in ('otra_pieza', 'titulo_no_es_la_pieza'):
                    _anotar_url_rechazada(notas, url, linea=nombre_linea)
        hits = {
            clave: hit for clave, hit in (hits or {}).items()
            if str((hit or {}).get('url') or '') not in urls_rechazadas_de(
                notas, str((hit or {}).get('nombre_buscado') or ''),
            )
        }
        for nombre_linea in nombres_limpios:
            if _clave_fuzzy(nombre_linea) in hits or nombre_linea in notas:
                continue
            notas[nombre_linea] = _aviso_sin_ficha(
                nombre_linea,
                candidatos_por_nombre.get(nombre_linea) or [],
                modelo,
                False,
                consultas=consultas_usadas.get(nombre_linea),
            )
        return hits

    from .razonar_pedido import consulta_de, es_escasa

    plan = plan or {}
    for i, nombre in enumerate(nombres_limpios):
        _cortar()
        if callable(on_progreso):
            on_progreso({
                'paso': 'web',
                'detalle': f'Buscando {nombre} para {modelo or marca or "este auto"}',
                'fuentes': fuentes_vivo,
                'nombre_actual': nombre,
                'indice': i,
                'total': len(nombres_limpios),
            })
        crudos: list[dict[str, Any]] = []
        from .enriquecer_repuestos import _es_linea_aceite_motor

        spec = str((especificaciones or {}).get(nombre) or '')
        # Aceite, pastillas, bujías y filtros no usan la frase del plan
        # (NGK + año + trim) ni el tope de "escasa": esa frase es la que
        # llegó a producción como única consulta.
        pieza_de_spec = (
            _es_linea_aceite_motor(nombre)
            or _es_pastillas_freno(nombre)
            or _es_consumible_corto(nombre)
        )
        consultas = _escalera_consultas(
            nombre,
            marca=marca,
            modelo=modelo,
            cilindraje=cilindraje,
            casas=casas_marca,
            tipo_motor=tipo_motor,
            especificacion=spec,
        )
        pensada = '' if pieza_de_spec else consulta_de(plan, nombre)
        if pensada:
            resto = [q for q in consultas if _norm(q) != _norm(pensada)]
            _, saco_ruido = _nombre_busqueda_amplia(nombre)
            # El plan repite la línea larga (TISS, cerámica, Sport T-Jet).
            # Esa frase no puede ocupar el cupo antes de "pastillas freno fiat bravo".
            if saco_ruido and not es_escasa(plan, nombre) and not _linea_es_kit(nombre):
                consultas = resto[:2] + [pensada] + resto[2:]
            else:
                consultas = [pensada] + resto
        max_q = (
            _MAX_CONSULTAS_TAVILY_POR_LINEA
            if pieza_de_spec or not es_escasa(plan, nombre)
            else 1
        )
        n_consultas = 0
        corto_mal = False
        for i_query, query in enumerate(consultas):
            _cortar()
            if i_query >= max_q:
                break
            n_consultas += 1
            crudos += _candidatos_validos(query, whitelist)
            sirven = [
                c for c in crudos
                if _candidato_sirve_linea(
                    nombre, c, anio=anio, cilindraje=cilindraje, modelo=modelo,
                    tipo_motor=tipo_motor, banda_min=_piso(nombre),
                    banda_max=_techo(nombre),
                )
                and _titulo_nombra_pieza(nombre, str(c.get('title') or ''))
            ]
            # Ficha de LA MISMA pieza con monto: listo, salvo pastillas,
            # bujías y filtros. La primera consulta puede traer un snippet
            # con precio que no es la ficha, y ahí se cortaba el resto.
            if not (_es_pastillas_freno(nombre) or _es_consumible_corto(nombre)):
                if any(_precio_desde_texto(c.get('content') or '', nombre) > 0 for c in sirven):
                    break
                if len({c['url'] for c in sirven}) >= 2:
                    break
            # Otra pieza (enfriador, piola) corta. Un listado genérico no:
            # la consulta siguiente puede ser la ficha real.
            otra_pieza = [
                c for c in crudos
                if not _candidato_sirve_linea(
                    nombre, c, anio=anio, cilindraje=cilindraje, modelo=modelo,
                    tipo_motor=tipo_motor, banda_min=_piso(nombre),
                    banda_max=_techo(nombre),
                )
            ]
            if crudos and not sirven and len(otra_pieza) == len(crudos) and not pieza_de_spec:
                corto_mal = True
                break
        rechazos: list[str] = []
        for cand in crudos:
            titulo = str(cand.get('title') or '').strip()
            etiqueta = titulo[:80] or '(sin título)'
            if not _candidato_sirve_linea(
                nombre, cand, anio=anio, cilindraje=cilindraje, modelo=modelo,
                tipo_motor=tipo_motor, banda_min=_piso(nombre),
                banda_max=_techo(nombre),
            ):
                detalle = _motivo_calidad_pastilla(
                    cand, nombre=nombre, modelo=modelo, tipo_motor=tipo_motor,
                    banda_min=_piso(nombre), banda_max=_techo(nombre),
                ) or 'otra pieza'
                rechazos.append(f'{etiqueta}: {detalle}')
            elif titulo and not _titulo_nombra_pieza(nombre, titulo):
                rechazos.append(f'{etiqueta}: el título no es esa pieza')
        logger.info(
            'busqueda_web_repuestos[tavily] linea=%s queries=%s n=%s/%s candidatos=%s '
            'corte=%s rechazos=%s',
            nombre[:80],
            consultas[:n_consultas],
            n_consultas,
            max_q,
            len({c['url'] for c in crudos}),
            'mal_clasificado' if corto_mal else 'ok',
            rechazos[:6],
        )
        consultas_usadas[nombre] = list(consultas[:n_consultas])
        vistos_url: set[str] = set()
        unicos_linea: list[dict[str, Any]] = []
        for cand in crudos:
            url_cand = str(cand.get('url') or '')
            if not url_cand or url_cand in vistos_url:
                continue
            vistos_url.add(url_cand)
            unicos_linea.append(cand)
        crudos_por_nombre[nombre] = unicos_linea
        _marcar_respaldo_alto(unicos_linea, nombre, _techo(nombre))
        ordenados = _ordenar_candidatos(
            crudos,
            tokens_vehiculo=tokens_veh,
            priorizar_precio=True,
            nombre_linea=nombre,
            anio=anio,
            cilindraje=cilindraje,
            modelo=modelo,
            tipo_motor=tipo_motor,
            banda_min=_piso(nombre),
            banda_max=_techo(nombre),
        )
        servir = _seleccionar_cupo(
            ordenados,
            nombre=nombre,
            anio=anio,
            cilindraje=cilindraje,
            modelo=modelo,
            tipo_motor=tipo_motor,
            banda_min=_piso(nombre),
            banda_max=_techo(nombre),
        )
        cupo_por_nombre[nombre] = [str(c.get('url') or '') for c in servir if c.get('url')]
        if servir:
            for cand in servir:
                cand['precio_snippet'] = _precio_desde_texto(
                    str(cand.get('content') or ''), nombre,
                )
            candidatos_por_nombre[nombre] = servir
        else:
            notas[nombre] = _aviso_sin_ficha(
                nombre,
                crudos,
                modelo,
                corto_mal,
                consultas=consultas[:n_consultas],
            )

    if not candidatos_por_nombre:
        logger.info('busqueda_web_repuestos[tavily]: 0 candidatos para %s repuestos', len(nombres_limpios))
        return _cerrar_sin_hit({})

    # Ficha completa del mejor candidato: la marca casi nunca aparece en el
    # título. Si ningún candidato del repuesto muestra monto, se piden dos más
    # para rescatar el precio antes de dejar la línea sin nada.
    urls_ficha: list[str] = []
    for nombre, candidatos in candidatos_por_nombre.items():
        if not candidatos:
            continue
        servir = [c for c in candidatos if _candidato_sirve_linea(
            nombre, c, anio=anio, cilindraje=cilindraje, modelo=modelo,
            tipo_motor=tipo_motor, banda_min=_piso(nombre),
            banda_max=_techo(nombre),
        )]
        if not servir:
            continue
        urls_ficha.extend(c['url'] for c in servir[:3])
    hay_kit = any(_linea_es_kit(n) for n in candidatos_por_nombre)
    fichas = _tavily_extraer(
        urls_ficha,
        extract_depth='advanced' if hay_kit else 'basic',
    )
    if fichas:
        for nombre, candidatos in candidatos_por_nombre.items():
            con_ficha = []
            for c in candidatos:
                extra = fichas.get(c['url']) or ''
                if not extra:
                    con_ficha.append(c)
                    continue
                # La ficha completa no borra el precio que ya venía en el snippet.
                snippet = str(c.get('content') or '')
                c['content'] = f'{snippet}\n{extra}'.strip() if snippet else extra
                con_ficha.append(c)
            candidatos_por_nombre[nombre] = _ordenar_candidatos(
                con_ficha,
                tokens_vehiculo=tokens_veh,
                priorizar_precio=True,
                nombre_linea=nombre,
                anio=anio,
                cilindraje=cilindraje,
                modelo=modelo,
                tipo_motor=tipo_motor,
                banda_min=_piso(nombre),
                banda_max=_techo(nombre),
            )

    # Snippet sin monto, o pastilla cuyo título no nombra el auto: se lee
    # la página real. El cuerpo (compatibilidad, marca) queda en la ficha.
    for nombre, candidatos in candidatos_por_nombre.items():
        hay_precio = any(
            _precio_plausible_para_linea(nombre, _precio_de_candidato(c, nombre))
            for c in candidatos
        )
        for cand in candidatos[:_FICHA_HTML_MAX]:
            url_cand = str(cand.get('url') or '')
            if not url_cand or url_cand in pedidas:
                continue
            titulo_cand = str(cand.get('title') or '')
            sin_precio = not _precio_plausible_para_linea(
                nombre, _precio_de_candidato(cand, nombre),
            )
            # Un listado con monto no alcanza: la ficha que dice Bravo en el
            # título, y el cruce Linea/Punto sin precio, se leen igual.
            quiere_modelo = (
                _es_pastillas_freno(nombre)
                and _es_pastillas_freno(titulo_cand)
                and (
                    _compat_pastilla_candidato(cand, modelo, tipo_motor) is None
                    or (
                        sin_precio
                        and (
                            _titulo_nombra_modelo(titulo_cand, modelo)
                            or _titulo_es_cruce_tjet(titulo_cand, modelo, tipo_motor)
                        )
                    )
                )
            )
            if (not hay_precio and sin_precio) or quiere_modelo:
                pedidas.append(url_cand)
    if pedidas:
        htmls = _leer_html_fichas(pedidas)
        pedidas_set_html = set(pedidas)
        for nombre, candidatos in list(candidatos_por_nombre.items()):
            cambio = False
            piso = _piso(nombre)
            for cand in candidatos:
                url_cand = str(cand.get('url') or '')
                if url_cand not in pedidas_set_html:
                    continue
                cand['ficha_leida'] = True
                html = htmls.get(url_cand) or ''
                if not html:
                    cambio = True
                    continue
                cuerpo = _cuerpo_compatibilidad(html)
                if cuerpo:
                    cand['cuerpo'] = cuerpo
                    snippet = str(cand.get('content') or '')
                    if cuerpo not in snippet:
                        cand['content'] = f'{snippet}\n{cuerpo}'.strip()
                    cambio = True
                monto = _precio_desde_html(html, nombre, url=url_cand)
                if not monto:
                    continue
                cambio = True
                if not _precio_plausible_para_linea(nombre, monto):
                    cand['precio_fuera_banda'] = monto
                    continue
                snippet = str(cand.get('content') or '')
                cand['content'] = f'{snippet}\nPrecio: ${monto}'.strip()
                cand['precio_snippet'] = monto
                if _motivo_calidad_pastilla(
                    cand, nombre=nombre, modelo=modelo, tipo_motor=tipo_motor,
                    banda_min=piso, banda_max=_techo(nombre),
                ):
                    continue
            if cambio:
                candidatos_por_nombre[nombre] = _ordenar_candidatos(
                    candidatos,
                    tokens_vehiculo=tokens_veh,
                    priorizar_precio=True,
                    nombre_linea=nombre,
                    anio=anio,
                    cilindraje=cilindraje,
                    modelo=modelo,
                    tipo_motor=tipo_motor,
                    banda_min=piso,
                    banda_max=_techo(nombre),
                )

    def _sellar_lista_negra() -> None:
        for nombre_linea, crudos_linea in crudos_por_nombre.items():
            piso = _piso(nombre_linea)
            techo = _techo(nombre_linea)
            vistos_rechazo: set[str] = set()
            for cand in crudos_linea:
                url_cand = str(cand.get('url') or '')
                if not url_cand or url_cand in vistos_rechazo:
                    continue
                vistos_rechazo.add(url_cand)
                motivo = _motivo_rechazo_duro(
                    cand,
                    nombre=nombre_linea,
                    anio=anio,
                    cilindraje=cilindraje,
                    modelo=modelo,
                    tipo_motor=tipo_motor,
                    banda_min=piso,
                    banda_max=techo,
                )
                if motivo in (
                    'listado', 'precio_bajo_banda', 'precio_alto_banda',
                    'modelo_incompatible', 'sin_modelo',
                ):
                    _anotar_url_rechazada(notas, url_cand)
                elif motivo:
                    _anotar_url_rechazada(notas, url_cand, linea=nombre_linea)
        if not notas.get('_urls_rechazadas'):
            return
        for nombre_linea, candidatos in list(candidatos_por_nombre.items()):
            prohibidas = urls_rechazadas_de(notas, nombre_linea)
            candidatos_por_nombre[nombre_linea] = [
                cand for cand in candidatos
                if str(cand.get('url') or '') not in prohibidas
            ]

    _sellar_lista_negra()

    preliminar = _hits_desde_candidatos(
        candidatos_por_nombre,
        tokens_veh,
        marca_vehiculo=marca,
        anio=anio,
        cilindraje=cilindraje,
        modelo=modelo,
        tipo_motor=tipo_motor,
        bandas_min=pisos,
        bandas_max=techos,
    )
    if preliminar and all(
        _clave_fuzzy(nombre) in preliminar for nombre in candidatos_por_nombre
    ):
        logger.info(
            'busqueda_web_repuestos[tavily]: skip Gemini, snippets cubren %s líneas',
            len(preliminar),
        )
        return _cerrar_sin_hit(preliminar)

    prompt = _construir_prompt_tavily(
        candidatos_por_nombre=candidatos_por_nombre,
        marca=marca,
        modelo=modelo,
        anio=str(anio or ''),
        cilindraje=cilindraje,
        tipo_motor=tipo_motor,
        servicio_nombre=servicio_nombre,
    )
    body = _gemini_generar(
        prompt,
        timeout=min(max(int(timeout), 8), _GEMINI_FORMATEO_TIMEOUT),
        use_url_context=False,
    )
    if not body:
        logger.info(
            'busqueda_web_repuestos[tavily]: Gemini vacío; se entregan %s hits de snippet',
            len(preliminar),
        )
        return _cerrar_sin_hit(preliminar)

    text = texto_candidato_gemini(body) or ''
    if not text:
        logger.info(
            'busqueda_web_repuestos[tavily]: Gemini vacío; se entregan %s hits de snippet',
            len(preliminar),
        )
        return _cerrar_sin_hit(preliminar)
    parsed = _parse_json(text) or {}
    resultados = parsed.get('resultados') or []
    if not isinstance(resultados, list) or not resultados:
        logger.info(
            'busqueda_web_repuestos[tavily]: Gemini sin JSON usable; se entregan %s hits de snippet',
            len(preliminar),
        )
        return _cerrar_sin_hit(preliminar)

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
        if url not in urls_reales or url in urls_rechazadas_de(notas):
            continue
        if _es_listado_sin_vendedor(url) or _es_pagina_sin_ficha(url):
            # Sin ficha de una tienda concreta no hay precio atribuible.
            continue
        host = _dominio_de_url(url)
        marca_it = _marca_repuesto_valida(item.get('marca_repuesto'))
        nombre_prod = str(item.get('nombre_producto') or item.get('nombre_buscado') or '').strip()[:200]
        if not nombre_prod:
            continue
        dicha = str(item.get('nombre_buscado') or '')
        duena = _linea_duena_de_url(candidatos_por_nombre, url)
        # La URL es de UNA línea. El nombre que escribió el modelo, o el
        # orden del JSON, no puede dejar el aceite en las pastillas.
        nombre_linea = duena or dicha
        if url in urls_rechazadas_de(notas, nombre_linea):
            continue
        if duena:
            candidatos_linea = list(candidatos_por_nombre.get(duena) or [])
            if _clave_fuzzy(dicha) and _clave_fuzzy(dicha) != _clave_fuzzy(duena):
                logger.info(
                    'busqueda_web_repuestos[tavily] reasignado dicho=%s duena=%s url=%s',
                    dicha[:80],
                    duena[:80],
                    url[:180],
                )
        else:
            candidatos_linea = _candidatos_de_linea(candidatos_por_nombre, dicha)
            if not any(str(c.get('url') or '') == url for c in candidatos_linea):
                continue
        ficha = next((c for c in candidatos_linea if c.get('url') == url), None)
        snippet = str((ficha or {}).get('content') or '')
        evaluar = dict(ficha or {})
        if not evaluar.get('title'):
            evaluar['title'] = nombre_prod
        evaluar['url'] = url
        if snippet:
            evaluar['content'] = snippet
        if not _candidato_sirve_linea(
            nombre_linea,
            evaluar,
            anio=anio,
            cilindraje=cilindraje,
            modelo=modelo,
            tipo_motor=tipo_motor,
            banda_min=_piso(nombre_linea),
            banda_max=_techo(nombre_linea),
        ):
            continue
        if not _titulo_nombra_pieza(nombre_linea, nombre_prod):
            continue
        attrs = _atributos_desde_texto(
            nombre_prod,
            snippet,
            item.get('marca_repuesto'),
            item.get('calidad'),
            item.get('pais_origen'),
            marca_vehiculo=marca,
        )
        if not marca_it:
            marca_it = attrs['marca_repuesto']
        marca_it = _marca_canonica(
            marca_it,
            f"{nombre_prod} {snippet} {(ficha or {}).get('cuerpo') or ''}",
        )
        calidad_it, pais_it = _calidad_pais_de_item(item, attrs)
        precio = _to_int_clp(item.get('precio_clp'))
        if not _precio_plausible_para_linea(nombre_linea, precio):
            precio = _precio_de_candidato(ficha or {}, nombre_linea)
        if not _precio_plausible_para_linea(nombre_linea, precio):
            # El modelo eligió una ficha sin monto creíble habiendo otra:
            # se cambia de candidato, porque una línea en $0 no sirve.
            with_precio = [
                (c, _precio_de_candidato(c, nombre_linea))
                for c in candidatos_linea if c['url'] != url
            ]
            alternativa = next(
                (
                    (c, p) for c, p in with_precio
                    if _precio_plausible_para_linea(nombre_linea, p)
                    and _candidato_sirve_linea(
                        nombre_linea, c, anio=anio, cilindraje=cilindraje, modelo=modelo,
                        tipo_motor=tipo_motor, banda_min=_piso(nombre_linea),
                        banda_max=_techo(nombre_linea),
                    )
                    and _titulo_nombra_pieza(nombre_linea, str(c.get('title') or ''))
                ),
                None,
            )
            if alternativa:
                candidato_alt, precio = alternativa
                url = candidato_alt['url']
                host = _dominio_de_url(url)
                nombre_prod = str(candidato_alt.get('title') or nombre_prod)[:200]
                item['tienda'] = ''
        if not _precio_plausible_para_linea(nombre_linea, precio):
            # Guardar la línea en $0 envenena el cache y la deja igual sin
            # referencia; se descarta para que el rescate del snippet la tome.
            continue
        tienda_item = str(item.get('tienda') or '').strip()
        if not tienda_item or _norm(tienda_item) in _NOMBRES_TIENDA_GENERICOS:
            tienda_item = _tienda_de_ficha(
                url, f"{nombre_prod} {snippet} {(ficha or {}).get('cuerpo') or ''}",
            )
        tienda = tienda_item[:200]
        compat = str(item.get('compatibilidad') or '').strip().lower()[:20]
        if compat not in ('alta', 'media', 'baja'):
            compat = 'media'
        conf = 0.85 if compat == 'alta' else (0.75 if compat == 'media' else 0.6)
        clave = _clave_fuzzy(nombre_linea)
        if not clave:
            continue
        prev = out.get(clave)
        if prev and float(prev.get('confianza') or 0) >= conf:
            continue
        hit_out = {
            'nombre_buscado': str(nombre_linea or '').strip()[:200],
            'nombre_producto': nombre_prod,
            'marca_repuesto': marca_it,
            'precio_clp': precio,
            'tienda': tienda,
            'dominio': host[:200],
            'url': url,
            'compatibilidad': compat,
            'confianza': conf,
        }
        if calidad_it:
            hit_out['calidad'] = calidad_it
        if pais_it:
            hit_out['pais_origen'] = pais_it
        out[clave] = hit_out
        # Aprendizaje: si la ficha nombraba al auto, esa casa sirve para la
        # marca y en la próxima cotización se la consulta primero.
        candidato = next(
            (c for c in candidatos_linea if c.get('url') == url),
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
    for clave, hit in _hits_desde_candidatos(
        candidatos_por_nombre,
        tokens_veh,
        marca_vehiculo=marca,
        anio=anio,
        cilindraje=cilindraje,
        modelo=modelo,
        tipo_motor=tipo_motor,
        bandas_min=pisos,
        bandas_max=techos,
    ).items():
        if clave in out:
            continue
        out[clave] = hit
        rescatadas += 1

    for hit in out.values():
        logger.info(
            'busqueda_web_repuestos[tavily] elegido linea=%s producto=%s url=%s precio=%s',
            str(hit.get('nombre_buscado') or '')[:80],
            str(hit.get('nombre_producto') or '')[:80],
            str(hit.get('url') or '')[:180],
            hit.get('precio_clp') or 0,
        )
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
    return _cerrar_sin_hit(out)


def _titulo_nombra_pieza(nombre: str, titulo: str) -> bool:
    """El título tiene que decir la pieza. Un listado 'Repuestos Fiat Bravo' no."""
    from .enriquecer_repuestos import (
        _es_linea_aceite_motor,
        _ficha_es_aceite_de_motor,
        _producto_menciona_pieza,
        _validar_tipo_parte,
    )

    texto = str(titulo or '').strip()
    if not texto:
        return True
    if _es_linea_aceite_motor(nombre) and not _ficha_es_aceite_de_motor(texto):
        return False
    return _validar_tipo_parte(nombre, texto) and _producto_menciona_pieza(nombre, texto)


def _aviso_sin_ficha(
    nombre: str,
    crudos: list[dict[str, Any]],
    modelo: str,
    otra_pieza: bool,
    consultas: list[str] | None = None,
) -> dict[str, str]:
    """Lo que el taller debe leer cuando no hay ficha de ESA pieza para ESTE auto."""
    vistos: list[str] = []
    descartados: list[str] = []
    for cand in crudos:
        titulo = str(cand.get('title') or '').strip()
        if not titulo or titulo in vistos:
            continue
        vistos.append(titulo[:90])
        if not _titulo_nombra_pieza(nombre, titulo):
            descartados.append(titulo[:90])
        if len(descartados) >= 3:
            break
    auto = modelo or 'este auto'
    buscadas = [q for q in (consultas or []) if str(q).strip()][:3]
    busqueda = ''
    if buscadas:
        citas = ', '.join(f'"{q}"' for q in buscadas)
        busqueda = f'Se buscó {citas}. '
    titulos_rechazados = ', '.join(f'"{t}"' for t in (descartados or vistos)[:3])
    if otra_pieza and vistos:
        detalle = (
            f'{busqueda}Sin ficha de {nombre} para {auto}. '
            f'Lo publicado era otra pieza: {titulos_rechazados}. '
            'No se siguió buscando. Escribe el precio de tu casa.'
        )
    elif descartados:
        detalle = (
            f'{busqueda}Sin ficha de {nombre} para {auto}. '
            f'Se descartó {titulos_rechazados} porque el título no es esa pieza.'
        )
    else:
        detalle = (
            f'{busqueda}{nombre} no está publicado para {auto} en las tiendas consultadas. '
            'Escribe el precio y la casa.'
        )
    return {
        'motivo': 'sin_ficha' if (otra_pieza or descartados or buscadas) else 'pieza_escasa',
        'detalle': detalle[:500],
    }


def buscar_repuestos_web(
    nombres: list[str],
    *,
    vehiculo: dict[str, Any] | None = None,
    servicio_nombre: str = '',
    on_progreso=None,
    deberia_cancelar=None,
    avisos: dict[str, dict[str, str]] | None = None,
    especificaciones: dict[str, str] | None = None,
    bandas_min: dict[str, int] | None = None,
    bandas_max: dict[str, int] | None = None,
) -> dict[str, dict[str, Any]]:
    """Tavily si hay API key. url_context solo si Tavily no está configurada."""
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
    tavily_listo = False

    if callable(deberia_cancelar) and deberia_cancelar():
        raise BusquedaWebCancelada()

    from .razonar_pedido import planificar

    plan = planificar(servicio_nombre, veh, usar_llm=True)
    if callable(on_progreso):
        on_progreso({
            'paso': 'pensando',
            'detalle': str(plan.get('razonamiento') or 'Revisando el trabajo de este auto')[:240],
            'fuentes': ['Razonamiento del trabajo'],
            'nombre_actual': '',
        })
    notas = avisos if avisos is not None else {}

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
                on_progreso=on_progreso,
                deberia_cancelar=deberia_cancelar,
                avisos=notas,
                plan=plan,
                especificaciones=especificaciones,
                bandas_min=bandas_min,
                bandas_max=bandas_max,
            )
            tavily_listo = True
        except BusquedaWebCancelada:
            raise
        except Exception as exc:
            logger.warning('busqueda_web_repuestos[tavily]: fallo inesperado: %s', exc)
            resultados = {}
        claves_resueltas = {_clave_fuzzy(n) for n in nombres_limpios} & {
            _clave_fuzzy(v.get('nombre_buscado') or '') for v in resultados.values()
        }
        pendientes = [n for n in nombres_limpios if _clave_fuzzy(n) not in claves_resueltas] or (
            [] if resultados else nombres_limpios
        )

    # Tavily ya recorrió Chile. url_context sobre URLs inventadas no encuentra
    # el kit del Morning y deja al worker 45–135s extra (Gemini 503).
    if callable(deberia_cancelar) and deberia_cancelar():
        raise BusquedaWebCancelada()

    if tavily_listo:
        if pendientes:
            logger.info(
                'busqueda_web_repuestos: Tavily sin hit para %s; se omite url_context',
                pendientes,
            )
        return resultados

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
    text = texto_candidato_gemini(body) or ''
    if not text:
        logger.info('busqueda_web_repuestos: respuesta sin texto descartada')
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
            anio=anio,
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
    calidad: str = '',
) -> str:
    base = _clave_fuzzy(nombre)
    spec = _norm(especificacion)
    veh = _norm(' '.join(str(p) for p in (marca_vehiculo, modelo_vehiculo, anio or '') if p))
    motor = _norm(tipo_motor)
    cil = _norm(cilindraje)
    cal = _norm(calidad)
    parts = [base]
    if spec:
        parts.append(spec)
    if cal in ('original', 'oem', 'alternativo'):
        parts.append(cal)
    parts.append(veh)
    if motor:
        parts.append(motor)
    if cil:
        parts.append(cil)
    return '|'.join(p for p in parts if p)[:240]


# Una fila recién escrita en este mismo request ya trae el precio parseado.
# Una fila de un request anterior puede guardar el tachado ($58.500).
_CACHE_RELECTURA_PRECIO = timedelta(seconds=90)
_CACHE_RELECTURA_CUPO = 4


def _candidato_desde_cache(row: Any, precio: int) -> dict[str, Any]:
    """La caché no tiene el cuerpo de la ficha. Un título genérico ya se puede botar."""
    return {
        'title': str(getattr(row, 'nombre_producto', '') or ''),
        'url': str(getattr(row, 'url', '') or ''),
        'content': '',
        'cuerpo': '',
        'ficha_leida': True,
        'precio_snippet': int(precio or 0),
    }


def _precio_cache_esta_viejo(row: Any, now) -> bool:
    consultado = getattr(row, 'consultado_en', None)
    if consultado is None:
        return True
    try:
        return (now - consultado) >= _CACHE_RELECTURA_PRECIO
    except TypeError:
        return True


def _expirar_fila_cache(row: Any, now, *, linea: str, producto: str, motivo: str) -> None:
    logger.info(
        'busqueda_web_repuestos[cache] ignorada linea=%s producto=%s motivo=%s',
        str(linea)[:80],
        str(producto)[:80],
        motivo,
    )
    row.expira_en = now
    row.save(update_fields=['expira_en'])


def _fila_cache_utilizable(
    row: Any,
    nombre_linea: str,
    *,
    modelo: str = '',
    tipo_motor: str = '',
    banda_min: int = 0,
    banda_max: int = 0,
    now,
    cupo: list[int] | None = None,
) -> int | None:
    """Precio vigente de la fila, o None si no se puede cotizar (queda vencida).

    Sin el cuerpo de la página, un título que no nombra el auto es
    sin_modelo, un 'Envío gratis' es listado, un monto bajo la banda es
    precio_bajo_banda y uno por encima de 2,5× el máximo es
    precio_alto_banda. El aceite de motor no nombra el auto y no entra
    en esa compuerta. Si la pieza es la correcta, se relee el HTML cuando
    la fila no es de este request y se queda el precio actual.
    """
    from .enriquecer_repuestos import _producto_es_la_pieza

    producto = str(getattr(row, 'nombre_producto', '') or '')
    if nombre_linea and producto and not _producto_es_la_pieza(
        nombre_linea, producto, fuente='web',
    ):
        _expirar_fila_cache(row, now, linea=nombre_linea, producto=producto, motivo='otra_pieza')
        return None

    precio = int(getattr(row, 'precio_clp', 0) or 0)
    cand = _candidato_desde_cache(row, precio)
    if nombre_linea:
        motivo = _motivo_calidad_pastilla(
            cand,
            nombre=nombre_linea,
            modelo=modelo,
            tipo_motor=tipo_motor,
            banda_min=banda_min,
            banda_max=banda_max,
        )
        if motivo:
            _expirar_fila_cache(
                row, now, linea=nombre_linea, producto=producto, motivo=motivo,
            )
            return None

    url = str(getattr(row, 'url', '') or '').strip()
    if (
        not url.startswith('http')
        or not _precio_cache_esta_viejo(row, now)
        or (cupo is not None and cupo[0] <= 0)
    ):
        return precio

    if cupo is not None:
        cupo[0] -= 1
    try:
        htmls = _leer_html_fichas([url])
    except Exception:
        htmls = {}
    html = htmls.get(url) or ''
    if not html:
        try:
            row.save(update_fields=['consultado_en'])
        except Exception:
            pass
        return precio

    cuerpo = _cuerpo_compatibilidad(html)
    if cuerpo:
        cand['cuerpo'] = cuerpo
        cand['content'] = cuerpo
    monto = _precio_desde_html(html, nombre_linea, url)
    if monto and _precio_plausible_para_linea(nombre_linea, monto):
        cand['precio_snippet'] = monto
    else:
        monto = precio
    if nombre_linea:
        motivo = _motivo_calidad_pastilla(
            cand,
            nombre=nombre_linea,
            modelo=modelo,
            tipo_motor=tipo_motor,
            banda_min=banda_min,
            banda_max=banda_max,
        )
        if motivo:
            _expirar_fila_cache(
                row, now, linea=nombre_linea, producto=producto, motivo=motivo,
            )
            return None
    if monto and monto != precio:
        # 10.990 → 4.990 es una cuota, el envío o un relacionado. Una baja
        # de verdad (58.500 → 52.650) sigue siendo el precio actual.
        if precio > 0 and monto * 2 < precio:
            logger.info(
                'busqueda_web_repuestos[cache] caida_ignorada linea=%s guardado=%s leido=%s',
                str(nombre_linea)[:80],
                precio,
                monto,
            )
            monto = precio
        else:
            logger.info(
                'busqueda_web_repuestos[cache] precio_actualizado linea=%s guardado=%s actual=%s',
                str(nombre_linea)[:80],
                precio,
                monto,
            )
            row.precio_clp = monto
            row.save(update_fields=['precio_clp'])
            return monto
    try:
        row.save(update_fields=['consultado_en'])
    except Exception:
        pass
    return precio


def hits_cache_vigentes_para_nombres(
    nombres: list[str],
    *,
    marca_vehiculo: str = '',
    modelo_vehiculo: str = '',
    anio: str | int | None = '',
    especificacion: str = '',
    tipo_motor: str = '',
    cilindraje: str = '',
    bandas_min: dict[str, int] | None = None,
    bandas_max: dict[str, int] | None = None,
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
    from .enriquecer_repuestos import _producto_es_la_pieza
    from .vehiculo_exacto import clave_historial_cubre_vehiculo

    cupo = [_CACHE_RELECTURA_CUPO]
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
        nombre_linea = claves_objetivo.get(clave) or claves_objetivo.get(fuzzy) or ''
        producto = str(row.nombre_producto or '')
        if dominio in ('historial-taller', 'historial_taller'):
            if nombre_linea and producto and not _producto_es_la_pieza(
                nombre_linea, producto, fuente='web',
            ):
                _expirar_fila_cache(
                    row, now, linea=nombre_linea, producto=producto, motivo='otra_pieza',
                )
                continue
            precio_usar = int(row.precio_clp or 0)
        else:
            # Fila vieja: listado sin modelo, precio tachado, bomba guardada
            # como aceite. Se vence para que Tavily vuelva a buscar.
            precio_usar = _fila_cache_utilizable(
                row,
                nombre_linea,
                modelo=modelo_vehiculo,
                tipo_motor=tipo_motor,
                banda_min=_banda_min_de(bandas_min, nombre_linea),
                banda_max=_banda_min_de(bandas_max, nombre_linea),
                now=now,
                cupo=cupo,
            )
            if precio_usar is None:
                continue
        # Preferir primer hit (mayor confianza) por fuzzy.
        if fuzzy in out:
            continue
        marca = _marca_repuesto_valida(row.marca_repuesto)
        out[fuzzy] = {
            'nombre_buscado': claves_objetivo.get(clave) or claves_objetivo.get(fuzzy) or row.nombre_producto,
            'nombre_producto': str(row.nombre_producto or '')[:200],
            'marca_repuesto': marca,
            'precio_clp': int(precio_usar or 0),
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
    bandas_min: dict[str, int] | None = None,
    bandas_max: dict[str, int] | None = None,
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
        bandas_min=bandas_min,
        bandas_max=bandas_max,
    )
    faltantes: list[str] = []
    for nombre in nombres:
        fuzzy = _clave_fuzzy(nombre)
        if fuzzy and fuzzy in cache_hits:
            continue
        faltantes.append(nombre)
    return faltantes, cache_hits
