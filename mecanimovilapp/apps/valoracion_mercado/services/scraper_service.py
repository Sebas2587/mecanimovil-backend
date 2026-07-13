"""
Scraper de listados externos (MercadoLibre + Chileautos).
Adaptado desde experiments/marketplace-patente-search/scrape_marketplaces.py
"""
from __future__ import annotations

import hashlib
import logging
import random
import re
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from django.utils import timezone

logger = logging.getLogger(__name__)

ML_LISTADO = 'https://listado.mercadolibre.cl/listado'
ML_CATEGORY_AUTOS = 'MLC1743'
DEFAULT_CHILEAUTOS = 'https://www.chileautos.cl'


@dataclass
class ListingScraped:
    fuente: str
    external_id: str
    url: str
    titulo_raw: str
    precio: int
    year: int | None = None
    kilometraje: int | None = None
    region: str = ''
    marca_texto: str = ''
    modelo_texto: str = ''


@dataclass
class ScrapeResult:
    marca: str
    modelo: str
    year_bucket: int | None
    listings: list[ListingScraped] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _slug_url(s: str) -> str:
    s = unicodedata.normalize('NFD', s.strip().lower())
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return s or 'x'


def _parse_price(text: str) -> int | None:
    if not text:
        return None
    digits = re.sub(r'[^\d]', '', text)
    if not digits:
        return None
    val = int(digits)
    return val if val > 100_000 else None


def _parse_year_from_title(title: str) -> int | None:
    m = re.search(r'\b(19|20)\d{2}\b', title or '')
    if m:
        y = int(m.group(0))
        if 1980 <= y <= timezone.now().year + 1:
            return y
    return None


def _parse_km_from_title(title: str) -> int | None:
    m = re.search(r'(\d{1,3}(?:\.\d{3})*)\s*km', (title or '').lower())
    if m:
        km = int(re.sub(r'[^\d]', '', m.group(1)))
        return km if 0 < km < 2_000_000 else None
    return None


def _external_id_from_url(url: str, titulo: str, fuente: str) -> str:
    if url:
        m = re.search(r'MLC-(\d+)', url)
        if m:
            return m.group(1)
        m = re.search(r'/(\d{6,})', url)
        if m:
            return m.group(1)
    digest = hashlib.sha1(f'{fuente}:{titulo}'.encode()).hexdigest()[:16]
    return digest


def _jitter_sleep(min_s: float = 2.0, max_s: float = 6.0) -> None:
    time.sleep(random.uniform(min_s, max_s))


def _titulos_ml_playwright(page) -> list[tuple[str, str, str]]:
    """Retorna lista de (titulo, url, precio_text)."""
    from playwright.sync_api import TimeoutError as PWTimeout

    selectors = [
        'a.poly-component__title',
        '.poly-card a.poly-component__title',
        '.ui-search-item__title a',
        'li.ui-search-layout__item a h2',
    ]
    rows: list[tuple[str, str, str]] = []
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=12_000)
        except PWTimeout:
            continue
        for loc in page.locator(sel).all()[:40]:
            try:
                t = loc.inner_text().strip()
                href = loc.get_attribute('href') or ''
            except Exception:
                continue
            if t and len(t) > 5:
                rows.append((t, href, ''))
        if rows:
            break

    price_sel = '.andes-money-amount__fraction, .poly-price__current .andes-money-amount__fraction'
    prices = page.locator(price_sel).all()[:40]
    out: list[tuple[str, str, str]] = []
    for i, (t, href, _) in enumerate(rows):
        ptxt = ''
        if i < len(prices):
            try:
                ptxt = prices[i].inner_text().strip()
            except Exception:
                pass
        out.append((t, href, ptxt))
    return out


def scrape_mercadolibre(marca: str, modelo: str, headless: bool = True) -> list[ListingScraped]:
    query = re.sub(r'\s+', ' ', f'{marca} {modelo}').strip()
    params = urllib.parse.urlencode({'q': query, 'category_id': ML_CATEGORY_AUTOS})
    url = f'{ML_LISTADO}?{params}'
    listings: list[ListingScraped] = []

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning('playwright no instalado; omitiendo MercadoLibre')
        return listings

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            ctx = browser.new_context(
                locale='es-CL',
                user_agent=(
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                ),
                viewport={'width': 1366, 'height': 900},
            )
            page = ctx.new_page()
            page.goto(url, wait_until='domcontentloaded', timeout=60_000)
            page.wait_for_timeout(3500)
            rows = _titulos_ml_playwright(page)
            browser.close()
    except Exception as exc:
        logger.warning('MercadoLibre scrape falló: %s', exc)
        return listings

    m_cf = marca.casefold()
    mo_cf = modelo.casefold()
    seen: set[str] = set()
    for titulo, href, ptxt in rows:
        if m_cf not in titulo.casefold() or mo_cf not in titulo.casefold():
            continue
        precio = _parse_price(ptxt) or _parse_price(titulo)
        if not precio:
            continue
        eid = _external_id_from_url(href, titulo, 'mercadolibre')
        if eid in seen:
            continue
        seen.add(eid)
        listings.append(
            ListingScraped(
                fuente='mercadolibre',
                external_id=eid,
                url=href or url,
                titulo_raw=titulo,
                precio=precio,
                year=_parse_year_from_title(titulo),
                kilometraje=_parse_km_from_title(titulo),
                marca_texto=marca,
                modelo_texto=modelo,
            )
        )
    return listings


def scrape_chileautos(marca: str, modelo: str, headless: bool = True) -> list[ListingScraped]:
    query = re.sub(r'\s+', ' ', f'{marca} {modelo}').strip()
    base = DEFAULT_CHILEAUTOS.rstrip('/')
    slug_combo = _slug_url(f'{marca} {modelo}')
    q_enc = urllib.parse.quote(query)
    listings: list[ListingScraped] = []

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning('playwright no instalado; omitiendo Chileautos')
        return listings

    urls = [
        f'{base}/vehiculos/buscar/?Keywords={q_enc}',
        f'{base}/vehiculos/autos-veh%C3%ADculo/{slug_combo}/',
    ]

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            ctx = browser.new_context(
                locale='es-CL',
                user_agent=(
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                ),
                viewport={'width': 1366, 'height': 900},
            )
            page = ctx.new_page()
            titles: list[tuple[str, str]] = []
            for u in urls:
                try:
                    page.goto(u, wait_until='domcontentloaded', timeout=50_000)
                except Exception:
                    continue
                page.wait_for_timeout(3000)
                for sel in ('article h2 a', 'article h2', "main a[href*='/vehiculos/']"):
                    loc = page.locator(sel)
                    try:
                        n = min(loc.count(), 40)
                    except Exception:
                        continue
                    for i in range(n):
                        try:
                            t = loc.nth(i).inner_text(timeout=2000).strip()
                            href = ''
                            if 'a' in sel:
                                href = loc.nth(i).get_attribute('href') or ''
                        except Exception:
                            continue
                        if len(t) > 10:
                            titles.append((t, href))
                    if titles:
                        break
                if titles:
                    break
            browser.close()
    except Exception as exc:
        logger.warning('Chileautos scrape falló: %s', exc)
        return listings

    m_cf = marca.casefold()
    mo_cf = modelo.casefold()
    seen: set[str] = set()
    for titulo, href in titles:
        if m_cf not in titulo.casefold() or mo_cf not in titulo.casefold():
            continue
        precio = _parse_price(titulo)
        if not precio:
            continue
        eid = _external_id_from_url(href, titulo, 'chileautos')
        if eid in seen:
            continue
        seen.add(eid)
        listings.append(
            ListingScraped(
                fuente='chileautos',
                external_id=eid,
                url=href or urls[0],
                titulo_raw=titulo,
                precio=precio,
                year=_parse_year_from_title(titulo),
                kilometraje=_parse_km_from_title(titulo),
                marca_texto=marca,
                modelo_texto=modelo,
            )
        )
    return listings


def scrape_segmento(marca: str, modelo: str, year_bucket: int | None = None) -> ScrapeResult:
    """Scrapea ML + Chileautos para un segmento marca/modelo."""
    result = ScrapeResult(marca=marca, modelo=modelo, year_bucket=year_bucket)
    headless = True
    try:
        ml = scrape_mercadolibre(marca, modelo, headless=headless)
        _jitter_sleep()
        ca = scrape_chileautos(marca, modelo, headless=headless)
        result.listings = ml + ca
    except Exception as exc:
        result.errors.append(str(exc))
        logger.exception('scrape_segmento error')
    if year_bucket:
        y_min, y_max = year_bucket - 1, year_bucket + 1
        filtered = [
            l for l in result.listings
            if l.year is None or (y_min <= l.year <= y_max)
        ]
        if filtered:
            result.listings = filtered
    return result


def upsert_listings(
    listings: list[ListingScraped],
    marca_obj,
    modelo_obj,
    year_bucket: int | None,
) -> set[tuple[str, str]]:
    """
    Upsert avisos y retorna set de (fuente, external_id) vistos en esta corrida.
    """
    from mecanimovilapp.apps.valoracion_mercado.models import AvisoExternoVehiculo

    seen: set[tuple[str, str]] = set()
    now = timezone.now()
    for item in listings:
        key = (item.fuente, item.external_id)
        seen.add(key)
        defaults = {
            'url': item.url[:512],
            'marca_texto': item.marca_texto,
            'modelo_texto': item.modelo_texto,
            'marca': marca_obj,
            'modelo': modelo_obj,
            'year': item.year or year_bucket,
            'kilometraje': item.kilometraje,
            'precio': item.precio,
            'region': item.region,
            'titulo_raw': item.titulo_raw[:2000],
            'activo': True,
            'fecha_removido': None,
            'fecha_ultima_vista': now,
        }
        obj, created = AvisoExternoVehiculo.objects.update_or_create(
            fuente=item.fuente,
            external_id=item.external_id,
            defaults=defaults,
        )
        if created:
            obj.fecha_primera_vista = now
            obj.save(update_fields=['fecha_primera_vista'])
    return seen


def mark_removed_for_segment(marca_obj, modelo_obj, year_min: int, year_max: int, seen_keys: set) -> int:
    """Marca como inactivos los avisos del segmento no vistos en la corrida."""
    from mecanimovilapp.apps.valoracion_mercado.models import AvisoExternoVehiculo

    qs = AvisoExternoVehiculo.objects.filter(
        marca=marca_obj,
        modelo=modelo_obj,
        activo=True,
        year__gte=year_min,
        year__lte=year_max,
    )
    removed = 0
    now = timezone.now()
    for aviso in qs.only('id', 'fuente', 'external_id'):
        if (aviso.fuente, aviso.external_id) not in seen_keys:
            aviso.activo = False
            aviso.fecha_removido = now
            aviso.save(update_fields=['activo', 'fecha_removido', 'fecha_ultima_vista'])
            removed += 1
    return removed
