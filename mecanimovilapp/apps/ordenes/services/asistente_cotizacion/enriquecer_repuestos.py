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

import copy
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
    'NGK', 'Denso', 'Delphi', 'ACDelco', 'AC Delco', 'Philips', 'Osram', 'Hella',
    'Febi', 'Lemforder', 'Lemförder', 'Moog', 'Textar', 'Ferodo', 'Jurid', 'Pagid',
    'Wix', 'Fram', 'Purflux', 'Hengst', 'Corteco', 'Elring', 'Victor Reinz',
    'ATE', 'Zimmermann', 'Pilenga', 'SNR', 'Ruville', 'Optimal',
    'Magneti Marelli', 'Champion', 'Mobis', 'Motorcraft', 'Febest', 'Nakata',
    'Cofap', 'Mando', 'TISS', 'Walker', 'CTR', 'Liqui Moly',
)

# Hasta tres palabras: "Marca: Liqui Moly" y la tabla "Marca | Liqui Moly".
# Un solo token ("Liqui", "Stp") no es la marca.
_MARCA_ETIQUETA_RE = re.compile(
    r'(?:marca(?!\s*veh[ií]culo)(?:\s+del\s+producto)?|fabricante|brand)\s*[:|\-]\s*'
    r'([A-Za-z][A-Za-z0-9.\-]{1,39}(?:\s+[A-Za-z][A-Za-z0-9.\-]{1,39}){0,2})',
    re.I,
)
_MARCA_ETIQUETA_BASURA = frozenset({
    'image', 'slider', 'logo', 'icon', 'foto', 'photo', 'vehiculo', 'auto',
    'producto', 'repuesto', 'original', 'oem', 'generico',
})
# La etiqueta sigue con el campo de al lado: "Marca: Stp Origen: China".
_CAMPOS_FICHA_MARCA = frozenset({
    'origen', 'tipo', 'calidad', 'precio', 'pais', 'procedencia', 'china',
    'alemania', 'japon', 'japan', 'original', 'alternativo', 'oem', 'sintetico',
    'semisintetico', 'mineral',
})

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
# Piezas de taller diario: el nombre IA suele ser más largo que el de la ficha.
_PIEZAS_COMUNES = (
    'filtro', 'aceite', 'refrigerante', 'anticongelante', 'bujia', 'pastilla',
    'disco', 'correa', 'bateria', 'amortiguador', 'termostato', 'bomba',
    'radiador', 'liquido', 'balata', 'sensor', 'bujias', 'pastillas',
)

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


def _linea_tiene_ficha_tienda(rep: dict) -> bool:
    """True si el monto ya viene de una casa. Un precio asumido sin tienda no."""
    fuente = str(rep.get('fuente_marketplace') or '').strip().lower()
    unit = _to_int_clp(rep.get('precio_unitario_clp'))
    if fuente in ('web', 'ml', 'mercadolibre'):
        if unit > 0:
            return True
        if _to_int_clp(rep.get('precio_min_clp')) > 0 or _to_int_clp(rep.get('precio_max_clp')) > 0:
            return True
    if str(rep.get('certeza') or '') == 'confirmado' and unit > 0:
        return True
    return False


def linea_necesita_busqueda_web(rep: Any) -> bool:
    """True si falta una ficha de tienda.

    Un unitario sin tienda ($55.000, certeza asumido o sin_precio) sigue
    buscándose: si no aparece ficha, ese monto se conserva. Catálogo,
    historial, un precio confirmado y una banda que ya viene de una tienda
    no se recotizan.
    """
    if not isinstance(rep, dict):
        return False
    if not nombre_repuesto_buscable(str(rep.get('nombre') or '')):
        return False
    fuente = str(rep.get('fuente_marketplace') or '').strip().lower()
    if fuente in ('catalogo', 'historial', 'proveedor'):
        return False
    if _linea_tiene_ficha_tienda(rep):
        return False
    return True


def anotar_busqueda_sin_ficha(
    rep: dict,
    nota: dict | None,
    *,
    marca: str = '',
    modelo: str = '',
    anio: Any = None,
    tipo_motor: str = '',
    cilindraje: Any = None,
) -> dict:
    """Deja la nota corta del mecánico. No borra el unitario ni la banda de la IA."""
    crudo = str((nota or {}).get('detalle') or '').strip()
    descarte = str((nota or {}).get('descarte') or '').strip()
    if crudo and not (_es_nota_mecanico(crudo) and len(crudo) <= _NOTA_MAX):
        logger.info(
            'nota_busqueda_tecnica linea=%s detalle=%s',
            str(rep.get('nombre') or '')[:80],
            crudo[:500],
        )
        if not descarte:
            descarte = _descarte_desde_texto(crudo)
        crudo = ''
    if not crudo:
        crudo = nota_sin_tienda(
            modelo=modelo,
            anio=anio,
            tipo_motor=tipo_motor,
            cilindraje=cilindraje,
            descarte=descarte,
        )
    detalle = recortar_nota(crudo)
    if detalle:
        rep['motivo_seleccion'] = detalle
        # La descripción de la pieza ("Juego completo…") no es la búsqueda.
        if not str(rep.get('comentario') or '').strip() or nota_de_busqueda(rep.get('comentario')):
            rep['comentario'] = detalle
    if _to_int_clp(rep.get('precio_unitario_clp')) > 0:
        return rep
    if _to_int_clp(rep.get('precio_min_clp')) > 0 or _to_int_clp(rep.get('precio_max_clp')) > 0:
        return rep
    rep['certeza'] = 'sin_precio'
    rep['motivo_sin_precio'] = str((nota or {}).get('motivo') or 'sin_ficha')[:40]
    return rep


def limpiar_precio_para_nueva_busqueda(rep: dict) -> dict:
    """Quita monto, banda y fuente para que la línea vuelva a cotizarse."""
    next_rep = dict(rep)
    next_rep['precio_unitario_clp'] = 0
    next_rep['precio_min_clp'] = 0
    next_rep['precio_max_clp'] = 0
    next_rep['certeza'] = 'sin_precio'
    next_rep['motivo_sin_precio'] = 'sin_referencia'
    for key in (
        'precio_referencia_mercado',
        'fuente_marketplace',
        'fuentes_detalle',
        'fuentes_n',
        'url_producto',
        'nombre_producto',
        'proveedor_nombre',
        'proveedor_id',
        'precio_marketplace_clp',
        'tienda_ml',
    ):
        next_rep.pop(key, None)
    return next_rep


def _inferir_marca_desde_nombre(nombre: str) -> str:
    raw = nombre or ''
    # La más larga primero: "Liqui Moly" gana sobre un token suelto.
    for marca in sorted(_MARCAS_REPUESTO_CONOCIDAS, key=len, reverse=True):
        if re.search(rf'\b{re.escape(marca)}\b', raw, flags=re.IGNORECASE):
            return marca if marca != 'Luk' else 'LuK'
    return ''


def _marca_canonica(marca: str | None, texto: str = '') -> str:
    """Marca de la pieza con su nombre completo, o '' si el token está cortado.

    'Liqui' junto a 'Liqui Moly' queda 'Liqui Moly'. 'Stp' o 'Liqui' solos
    no se pegan al nombre de la línea. NGK, ATE y el resto de la lista
    conservan su grafía. Una marca de varias palabras que no está en la
    lista (Repstock no entra: es una sola palabra larga) se conserva.
    """
    base = _marca_repuesto_valida(marca)
    blob = f'{texto or ""} {base}'.strip()
    if not blob:
        return ''
    for conocida in sorted(_MARCAS_REPUESTO_CONOCIDAS, key=len, reverse=True):
        if not re.search(rf'\b{re.escape(conocida)}\b', blob, flags=re.IGNORECASE):
            continue
        canon = 'LuK' if conocida == 'Luk' else conocida
        if not base:
            return canon
        nb, nk = _norm(base), _norm(conocida)
        if nk == nb or nk.startswith(f'{nb} ') or nb.startswith(nk):
            return canon
    if not base:
        return ''
    if len(base.split()) == 1:
        nb = _norm(base)
        conocidas_norm = {_norm(item) for item in _MARCAS_REPUESTO_CONOCIDAS}
        if any(_norm(item).startswith(f'{nb} ') for item in _MARCAS_REPUESTO_CONOCIDAS):
            return ''
        if len(nb) <= 4 and nb not in conocidas_norm:
            return ''
    return base


def _marca_desde_etiqueta(texto: str, marca_vehiculo: str = '') -> str:
    """Lee 'Marca: Bosch' / 'Marca | Liqui Moly' y descarta la marca del auto."""
    veh = _norm(marca_vehiculo)
    for match in _MARCA_ETIQUETA_RE.finditer(texto or ''):
        palabras = []
        for palabra in match.group(1).split():
            if palabras and _norm(palabra) in _CAMPOS_FICHA_MARCA:
                break
            palabras.append(palabra)
        cand = _marca_canonica(' '.join(palabras), texto)
        if not cand or _norm(cand) in _MARCA_ETIQUETA_BASURA:
            continue
        if veh and (_norm(cand) == veh or veh in _norm(cand)):
            continue
        return cand
    return ''


def _nombre_con_marca(nombre: str, marca: str | None, texto: str = '') -> str:
    """Incluye la marca en el nombre visible al cliente si aún no está.

    'Discos de freno delanteros' + 'Repstock' → 'Discos de freno delanteros Repstock'.
    'Aceite de motor' + 'Liqui' no agrega el token cortado. Si el texto de la
    ficha dice 'Liqui Moly', el nombre queda con la marca completa.
    """
    base = str(nombre or '').strip()
    marca_ok = _marca_canonica(marca, f'{texto} {marca or ""}')
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


def min_score_web_para(nombre: str) -> int:
    """Umbral más bajo en consumibles: 'Filtro de aceite Rexton' vs 'filtro aceite'."""
    n = _norm(nombre)
    if any(p in n for p in _PIEZAS_COMUNES):
        return 40
    return _MIN_SCORE_WEB


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
    q_core = set(query_key.split()[:2])
    c_core = set(candidate_key.split()[:2])
    if q_core and q_core <= c_tokens:
        return 70
    if c_core and c_core <= q_tokens:
        return 70
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
    calidad: str = '',
    pais_origen: str = '',
) -> dict[str, Any]:
    out = {
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
    listing = (nombre or '').strip()[:200]
    if listing:
        out['nombre_producto'] = listing
    cal = str(calidad or '').strip().lower()
    if cal in ('original', 'oem', 'alternativo'):
        out['calidad'] = cal
    pais = str(pais_origen or '').strip()[:40]
    if pais:
        out['pais_origen'] = pais
    return out


def _validar_tipo_parte(nombre_repuesto: str, producto_matched: str) -> bool:
    """Rechaza mismatches obvios por tipo de parte incompatible.
    
    Evita que "aceite de motor" matche con "enfriador de aceite" (oil cooler),
    o "pastillas" con "discos", etc.
    
    Returns:
        True si el match es válido, False si debe rechazarse
    """
    rep_norm = _norm(nombre_repuesto)
    prod_norm = _norm(producto_matched)
    
    # Lógica especial para aceite vs filtro de aceite: son mutuamente exclusivos
    rep_tiene_filtro = 'filtro' in rep_norm
    prod_tiene_filtro = 'filtro' in prod_norm
    rep_tiene_aceite = 'aceite' in rep_norm
    prod_tiene_aceite = 'aceite' in prod_norm
    
    # Caso 1: Si repuesto es "aceite" (sin filtro), NO debe matchear con producto "filtro de aceite"
    if rep_tiene_aceite and not rep_tiene_filtro:
        if prod_tiene_filtro:
            return False  # "aceite de motor" NO matcha "filtro de aceite"
    
    # Caso 2: Si repuesto es "filtro de aceite", NO debe matchear con producto "aceite" (sin filtro)
    if rep_tiene_filtro and rep_tiene_aceite:
        if prod_tiene_aceite and not prod_tiene_filtro:
            return False  # "filtro de aceite" NO matcha "aceite sintético"
    
    # Lógica especial para otros filtros: deben coincidir en tipo
    if 'filtro' in rep_norm or 'filtro' in prod_norm:
        tipos_filtro_rep = set()
        tipos_filtro_prod = set()
        
        for tipo in ['aceite', 'aire', 'combustible', 'polen', 'cabina', 'gasolina', 'diesel', 'particulas']:
            if tipo in rep_norm:
                tipos_filtro_rep.add(tipo)
            if tipo in prod_norm:
                tipos_filtro_prod.add(tipo)
        
        # Si ambos mencionan filtro y tienen tipos, deben compartir al menos uno
        if tipos_filtro_rep and tipos_filtro_prod:
            if not tipos_filtro_rep & tipos_filtro_prod:
                return False
    
    # "Bomba de aceite", "cárter", "enfriador": el sustantivo es otra pieza.
    # La viscosidad y el envase se exigen en _ficha_es_aceite_de_motor, no aquí:
    # un "Aceite 5W40" sin litros no corta la escalera, se sigue buscando el bidón.
    if _es_linea_aceite_motor(nombre_repuesto) and prod_norm:
        if _titulo_es_otra_pieza_de_aceite(producto_matched):
            return False

    # Pares mutuamente exclusivos: A no puede matchear con B, ni B con A
    exclusiones_bidireccionales = [
        # Aceites
        (['aceite motor', 'aceite'], ['enfriador', 'cooler', 'radiador', 'deposito']),
        
        # Frenos
        (['pastilla'], ['disco', 'tambor', 'campana', 'caliper', 'mordaza']),
        (['disco freno'], ['pastilla', 'zapata', 'tambor', 'caliper']),
        (['zapata'], ['disco', 'pastilla', 'caliper']),
        
        # Encendido
        (['bujia'], ['bobina', 'cable', 'modulo encendido']),
        (['bobina encendido', 'bobina'], ['bujia', 'cable']),
        
        # Suspensión
        (['amortiguador'], ['resorte', 'espiral', 'barra estabilizadora']),
        (['resorte', 'espiral'], ['amortiguador', 'barra']),
        
        # Embrague
        (['kit embrague'], ['volante', 'bimasa', 'dual mass', 'flywheel']),
        (['piola embrague', 'cable embrague', 'guaya embrague'], ['kit embrague', 'disco embrague', 'prensa']),
        
        # Motor
        (['correa distribucion', 'kit distribucion'], ['tensor', 'bomba agua', 'polea']),
        (['tensor'], ['correa', 'polea', 'bomba']),
    ]
    
    # Verificar exclusiones en ambas direcciones
    for grupo_a, grupo_b in exclusiones_bidireccionales:
        # Si repuesto tiene términos de grupo A, producto NO debe tener términos de grupo B
        if any(termino in rep_norm for termino in grupo_a):
            if any(prohibido in prod_norm for prohibido in grupo_b):
                return False
        
        # Y viceversa: si repuesto tiene términos de grupo B, producto NO debe tener términos de grupo A
        if any(termino in rep_norm for termino in grupo_b):
            if any(prohibido in prod_norm for prohibido in grupo_a):
                return False
    
    return True


_OTRA_PIEZA_DEL_ACEITE = (
    'bomba', 'enfriador', 'cooler', 'carter', 'tapa', 'tapon', 'sensor',
    'radiador', 'filtro', 'junta', 'reten', 'deposito', 'varilla', 'sello',
    'empaque', 'valvula', 'manguera', 'intercooler', 'ciguenal', 'multiple',
    'refrigerante', 'anticongelante', 'compresor', 'condensador',
)


def _es_linea_aceite_motor(nombre: str) -> bool:
    """Lubricante del motor. No el filtro, la bomba ni el aceite de caja."""
    n = _norm(nombre)
    if 'aceite' not in n or 'filtro' in n:
        return False
    if any(k in n for k in (
        'caja', 'transmision', 'diferencial', 'direccion', 'hidraulic', 'bomba',
    )):
        return False
    return True


def _es_bravo_14_tjet(
    modelo: str = '',
    tipo_motor: str = '',
    cilindraje: str = '',
) -> bool:
    """Bravo II 1.4 T-Jet. Un Bravo sin T-Jet, o un 1.6, no usa esta capacidad."""
    from .busqueda_web_repuestos import _bravo_tjet

    if not _bravo_tjet(modelo, tipo_motor):
        return False
    cil = _norm(cilindraje)
    if not cil:
        return True
    return '1 4' in f' {cil} ' or cil in ('14', '1400', '1400cc')


def cantidad_aceite_segun_motor(
    nombre: str,
    *,
    marca: str = '',
    modelo: str = '',
    cilindraje: str = '',
    tipo_motor: str = '',
) -> int | None:
    """Litros de servicio de este motor. None si no hay ficha de capacidad.

    Fiat Bravo 1.4 T-Jet: el cárter con filtro lleva unos 3,5 L y el
    llenado de taller es 4 L. El envase de la ficha (1 L, 4 L, 5 L) no entra.
    """
    del marca
    if not _es_linea_aceite_motor(nombre):
        return None
    if not _es_bravo_14_tjet(modelo, tipo_motor, cilindraje):
        return None
    return 4


def aplicar_cantidad_aceite_motor(
    rep: dict[str, Any],
    *,
    marca: str = '',
    modelo: str = '',
    cilindraje: str = '',
    tipo_motor: str = '',
) -> dict[str, Any]:
    """Deja la cantidad del aceite en la capacidad del motor, no en el bidón."""
    if not isinstance(rep, dict):
        return rep
    litros = cantidad_aceite_segun_motor(
        str(rep.get('nombre') or ''),
        marca=marca,
        modelo=modelo,
        cilindraje=cilindraje,
        tipo_motor=tipo_motor,
    )
    if litros is None:
        return rep
    rep['cantidad'] = litros
    return rep


def _titulo_es_otra_pieza_de_aceite(titulo: str) -> bool:
    n = _norm(titulo)
    if not n:
        return False
    return any(
        re.search(rf'\b{re.escape(pieza)}\b', n)
        for pieza in _OTRA_PIEZA_DEL_ACEITE
    )


def _ficha_es_aceite_de_motor(titulo: str) -> bool:
    """True solo si el título es el lubricante: viscosidad o 'aceite motor', y envase."""
    n = _norm(titulo)
    if not n:
        return True
    if _titulo_es_otra_pieza_de_aceite(titulo):
        return False
    viscosidad = re.search(r'\b\d{1,2}\s*w\s*\d{2}\b', n)
    dice_aceite_motor = 'aceite' in n and 'motor' in n
    if not (viscosidad or dice_aceite_motor):
        return False
    from .busqueda_web_repuestos import litros_envase

    return litros_envase(titulo) > 0


_NOTA_MAX = 160

_NOTA_COLA = (
    'Precio estimado. No pudimos consultar tiendas; confirma precio y tienda.'
)


def recortar_nota(texto: str, maximo: int = _NOTA_MAX) -> str:
    """Corta en un espacio y deja la frase en una sola línea."""
    t = re.sub(r'\s+', ' ', str(texto or '')).strip()
    if len(t) <= maximo:
        return t
    corte = t[:maximo].rsplit(' ', 1)[0].rstrip(' ,;.')
    if len(corte) < 40:
        corte = t[: maximo - 1].rstrip(' ,;.')
    if not corte.endswith('.'):
        if len(corte) + 1 <= maximo:
            corte += '.'
        else:
            corte = corte[: maximo - 1].rstrip(' ,;.') + '.'
    return corte


def _titulo_visible(palabra: str) -> str:
    p = str(palabra or '').strip(' .,')
    if not p:
        return ''
    if p.isupper() and len(p) <= 3:
        return p
    if p.isupper() or p.islower():
        return p.capitalize()
    return p


def _tokens_modelo_visibles(modelo: str) -> list[str]:
    raw = re.split(r'\s+', str(modelo or '').strip())
    out: list[str] = []
    i = 0
    while i < len(raw):
        tok = raw[i].strip('.,')
        low = tok.lower()
        if low in ('t-jet', 'tjet') or low.replace('-', '') == 'tjet':
            i += 1
            continue
        if low == 't' and i + 1 < len(raw) and raw[i + 1].lower().strip('.,') == 'jet':
            i += 2
            continue
        if re.fullmatch(r'\d+[.,]\d+', tok) or re.fullmatch(r'\d{3,4}', tok):
            i += 1
            continue
        visible = _titulo_visible(tok)
        if visible:
            out.append(visible)
        i += 1
    return out


def etiqueta_auto(
    *,
    marca: str = '',
    modelo: str = '',
    anio: Any = None,
    tipo_motor: str = '',
    cilindraje: Any = None,
    incluir_marca: bool = False,
    incluir_anio: bool = False,
) -> str:
    """Cómo nombra el taller al auto: 'Fiat Bravo 1.4 T-Jet' o 'Bravo 1.4 T-Jet 2010'."""
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
        _anio_vehiculo_int,
        _auto_es_tjet,
        _cilindraje_litros,
    )

    partes: list[str] = []
    if incluir_marca:
        marca_visible = _titulo_visible(marca)
        if marca_visible:
            partes.append(marca_visible)
    partes.extend(_tokens_modelo_visibles(modelo))
    litros = _cilindraje_litros(cilindraje) or _cilindraje_litros(modelo)
    if litros and litros not in partes:
        partes.append(litros)
    if _auto_es_tjet(modelo, tipo_motor) and 'T-Jet' not in partes:
        partes.append('T-Jet')
    if incluir_anio:
        year = _anio_vehiculo_int(anio)
        if year:
            partes.append(str(year))
    return ' '.join(partes)


def _base_sin_tienda(auto: str) -> str:
    auto = str(auto or '').strip()
    if auto:
        return (
            f'Precio estimado. No encontramos este repuesto para tu auto ({auto}); '
            'confirma precio y tienda.'
        )
    return (
        'Precio estimado. No encontramos este repuesto para tu auto; '
        'confirma precio y tienda.'
    )


def _clausula_descarte(descarte: str) -> str:
    texto = re.sub(r'\s+', ' ', str(descarte or '')).strip().rstrip('.')
    if not texto:
        return ''
    return f'{texto}.'


def nota_sin_tienda(
    *,
    marca: str = '',
    modelo: str = '',
    anio: Any = None,
    tipo_motor: str = '',
    cilindraje: Any = None,
    descarte: str = '',
) -> str:
    """Sin ficha de tienda. Una frase, y como mucho un porqué genérico."""
    del marca  # El ejemplo sin tienda nombra el modelo, no la marca.
    auto = etiqueta_auto(
        modelo=modelo,
        anio=anio,
        tipo_motor=tipo_motor,
        cilindraje=cilindraje,
        incluir_marca=False,
        incluir_anio=True,
    )
    clausula = _clausula_descarte(descarte)
    while True:
        base = _base_sin_tienda(auto)
        if clausula and len(base) + 1 + len(clausula) <= _NOTA_MAX:
            return f'{base} {clausula}'
        if len(base) <= _NOTA_MAX:
            return base
        if not auto:
            return recortar_nota(base)
        auto = auto.rsplit(' ', 1)[0]


def nombre_tienda_visible(nombre: str) -> str:
    """Nombre de la casa, no el dominio pegado. «Comercialramirezspa» → «Comercial Ramírez»."""
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
        _canon_nombre_tienda,
    )

    return _canon_nombre_tienda(nombre)


def nota_con_tienda(
    tienda: str,
    *,
    marca: str = '',
    modelo: str = '',
    anio: Any = None,
    tipo_motor: str = '',
    cilindraje: Any = None,
) -> str:
    """Con ficha: la casa, el auto y que es el mejor precio hallado."""
    del anio
    casa = nombre_tienda_visible(tienda) or re.sub(r'\s+', ' ', str(tienda or '')).strip()
    auto = etiqueta_auto(
        marca=marca,
        modelo=modelo,
        tipo_motor=tipo_motor,
        cilindraje=cilindraje,
        incluir_marca=True,
        incluir_anio=False,
    )
    while auto and casa:
        texto = f'{casa}: compatible con {auto}, mejor precio encontrado.'
        if len(texto) <= _NOTA_MAX:
            return texto
        auto = auto.rsplit(' ', 1)[0]
    if casa:
        return recortar_nota(f'{casa}: mejor precio encontrado.')
    return 'Mejor precio encontrado.'


def _formatear_pesos(monto: int) -> str:
    return '$' + f'{int(monto):,}'.replace(',', '.')


def nota_oferta(tienda: str, precio_normal: int) -> str:
    """El precio cobrado está bajo el de lista."""
    casa = nombre_tienda_visible(tienda) or re.sub(r'\s+', ' ', str(tienda or '')).strip() or 'Tienda'
    return recortar_nota(
        f'{casa}, precio en oferta (normal {_formatear_pesos(precio_normal)}).'
    )


def nota_cola_caida() -> str:
    return _NOTA_COLA


def _es_nota_mecanico(texto: str) -> bool:
    bajo = str(texto or '').strip().lower()
    return (
        bajo.startswith('precio estimado')
        or bajo.startswith('no pudimos consultar')
        or 'mejor precio encontrado' in bajo
        or 'precio en oferta' in bajo
        or 'precio a consultar' in bajo
        or 'especialista ' in bajo
        or 'solo en línea' in bajo
        or 'tiene todos los repuestos' in bajo
    )


def _descarte_desde_texto(texto: str) -> str:
    """Un solo resumen, si el texto viejo decía por qué se botó lo encontrado."""
    bajo = str(texto or '').lower()
    if (
        'otros años' in bajo
        or 'otro modelo' in bajo
        or 'otro motor' in bajo
        or 'otro año' in bajo
    ):
        return 'Lo encontrado era para otro año o modelo.'
    if 'no es esa pieza' in bajo or 'otra pieza' in bajo:
        return 'Lo encontrado era otra pieza.'
    return ''


def nota_de_busqueda(texto: str) -> str:
    """Nota de la búsqueda web, vieja o corta. La descripción de la pieza no lo es."""
    t = str(texto or '').strip()
    bajo = t.lower()
    if (
        bajo.startswith('se busc')
        or bajo.startswith('no se pudo consultar')
        or bajo.startswith('sin ficha de')
        or _es_nota_mecanico(t)
    ):
        return t
    return ''


def nota_visible_con_tienda(
    rep: dict,
    motivo_interno: str = '',
    *,
    marca: str = '',
    modelo: str = '',
    anio: Any = None,
    tipo_motor: str = '',
    cilindraje: Any = None,
) -> str:
    """La frase de la línea cuando ya hay casa. El motivo interno queda en el log."""
    tienda = str(
        rep.get('proveedor_nombre') or rep.get('casa_repuesto_nombre') or ''
    ).strip()
    normal = _to_int_clp(rep.get('precio_normal_clp'))
    if tienda and normal > 0:
        nota = nota_oferta(tienda, normal)
    else:
        nota = nota_con_tienda(
            tienda,
            marca=marca,
            modelo=modelo,
            tipo_motor=tipo_motor,
            cilindraje=cilindraje,
        )
    interno = str(motivo_interno or '').strip()
    if interno and interno != nota:
        logger.info(
            'nota_tienda linea=%s tienda=%s motivo_interno=%s nota=%s',
            str(rep.get('nombre') or '')[:80],
            tienda[:80],
            interno[:240],
            nota,
        )
    return nota


def nota_visible_sin_tienda(
    rep: dict,
    *,
    marca: str = '',
    modelo: str = '',
    anio: Any = None,
    tipo_motor: str = '',
    cilindraje: Any = None,
) -> str:
    """Conserva una nota corta ya escrita. Una nota larga se reemplaza."""
    previo = nota_de_busqueda(rep.get('comentario')) or nota_de_busqueda(
        rep.get('motivo_seleccion'),
    )
    if previo and _es_nota_mecanico(previo) and len(previo) <= _NOTA_MAX:
        return previo
    if previo:
        logger.info(
            'nota_busqueda_tecnica linea=%s detalle=%s',
            str(rep.get('nombre') or '')[:80],
            previo[:500],
        )
    return nota_sin_tienda(
        modelo=modelo,
        anio=anio,
        tipo_motor=tipo_motor,
        cilindraje=cilindraje,
        descarte=_descarte_desde_texto(previo),
    )


_FRASES_PROHIBIDAS = (
    'se buscó',
    'se busco',
    'sin ficha de',
    'cubre otros años',
    'nombra otro motor',
    'nombra otro modelo',
    'única casa con stock',
    'unica casa con stock',
    'única casa consultada',
    'unica casa consultada',
)

# Identidad de la pieza. Una nota larga no se escribe encima del nombre ni de la URL.
_CLAVES_INTOCABLES = frozenset({
    'id',
    'nombre',
    'nombre_producto',
    'url_producto',
    'imagen_url',
    'marca_repuesto',
    'fuente_marketplace',
    'fuente_repuesto',
    'calidad',
    'pais_origen',
    'unidad_medida',
    'especificacion',
    'tienda_ml',
    'proveedor_nombre',
    'codigo_parte',
    'categoria',
    'compatibilidad',
    'motivo_sin_precio',
    'certeza',
    'precio_capturado_en',
    'seleccion_cliente_en',
    'familia_sensible',
    'casa_repuesto_nombre',
    'motivo_seleccion',
    'comentario',
})


def contiene_nota_prohibida(texto: str) -> bool:
    bajo = str(texto or '').lower()
    return any(frase in bajo for frase in _FRASES_PROHIBIDAS)


def _es_nota_de_selector(texto: str) -> bool:
    bajo = str(texto or '').strip().lower()
    if not bajo:
        return False
    return (
        contiene_nota_prohibida(bajo)
        or bajo.startswith('cotizado:')
        or bajo.startswith('cotizado por ')
        or 'única casa' in bajo
        or 'unica casa' in bajo
        or bajo.startswith('mejor precio con stock')
        or bajo.startswith('balance precio')
        or bajo.startswith('proveedor confiable')
        or bajo.startswith('stock inmediato')
        or bajo.startswith('consolidado')
        or 'una sola casa' in bajo
        or bajo.startswith('no se encontraron proveedores')
        or bajo.startswith('no hay opciones')
    )


def nota_visible_debe_reemplazarse(texto: str) -> bool:
    """True si el texto es una nota que no puede verse. La descripción de la pieza no."""
    t = str(texto or '').strip()
    if not t:
        return False
    if t.lower().startswith('precio del taller'):
        return contiene_nota_prohibida(t) or len(t) > _NOTA_MAX
    if contiene_nota_prohibida(t) or _es_nota_de_selector(t):
        return True
    if _es_nota_mecanico(t):
        return len(t) > _NOTA_MAX
    if nota_de_busqueda(t):
        return True
    return False


def _hay_tienda_en_linea(rep: dict) -> bool:
    """Hay casa si el nombre no es el placeholder Estimado. Un precio solo no alcanza."""
    casa = str(rep.get('proveedor_nombre') or rep.get('casa_repuesto_nombre') or '').strip()
    if not casa or casa.lower() == 'estimado':
        return False
    fuente = str(rep.get('fuente_marketplace') or rep.get('fuente_repuesto') or '').strip().lower()
    if fuente == 'estimado' and not str(rep.get('url_producto') or '').strip():
        return False
    return True


def _nota_corta_para_linea(
    rep: dict,
    *,
    marca: str,
    modelo: str,
    anio: Any,
    tipo_motor: str,
    cilindraje: Any,
    motivo_interno: str = '',
) -> str:
    if rep.get('precio_a_consultar'):
        from mecanimovilapp.apps.ordenes.casas_especialistas import (
            nota_especialista,
            perfil_de,
        )

        casa = nombre_tienda_visible(str(rep.get('casa_repuesto_nombre') or ''))
        if casa and perfil_de(casa):
            return recortar_nota(nota_especialista(
                casa, marca, cubre_todo=False, a_consultar=True,
            ))
    if _hay_tienda_en_linea(rep):
        return nota_visible_con_tienda(
            rep,
            motivo_interno,
            marca=marca,
            modelo=modelo,
            anio=anio,
            tipo_motor=tipo_motor,
            cilindraje=cilindraje,
        )
    return nota_visible_sin_tienda(
        rep,
        marca=marca,
        modelo=modelo,
        anio=anio,
        tipo_motor=tipo_motor,
        cilindraje=cilindraje,
    )


def _nota_empieza_con_tienda(texto: str, tienda: str) -> bool:
    """«TodoAuto: …» sí. «Todoautochile: …» no, aunque empiece por las mismas letras."""
    bajo = str(texto or '').strip().lower()
    casa = str(tienda or '').strip().lower()
    if not bajo or not casa or not bajo.startswith(casa):
        return False
    resto = bajo[len(casa):]
    return resto[:1] in ('', ':', ',', '.', ' ')


def _motivo_ya_es_corto(texto: str, *, tienda: str, hay_tienda: bool) -> bool:
    t = str(texto or '').strip()
    if not t:
        return True
    if t.lower().startswith('precio del taller'):
        return len(t) <= _NOTA_MAX and not contiene_nota_prohibida(t)
    if not (_es_nota_mecanico(t) and len(t) <= _NOTA_MAX and not contiene_nota_prohibida(t)):
        return False
    if hay_tienda and tienda:
        return _nota_empieza_con_tienda(t, tienda)
    return True


def _reemplazar_frases_prohibidas(valor: Any, nota: str) -> Any:
    if isinstance(valor, str):
        if contiene_nota_prohibida(valor):
            return nota
        return valor
    if isinstance(valor, dict):
        for clave, item in list(valor.items()):
            if clave in _CLAVES_INTOCABLES:
                continue
            valor[clave] = _reemplazar_frases_prohibidas(item, nota)
        return valor
    if isinstance(valor, list):
        return [_reemplazar_frases_prohibidas(item, nota) for item in valor]
    return valor


def sanear_notas_linea(
    rep: dict,
    *,
    marca: str = '',
    modelo: str = '',
    anio: Any = None,
    tipo_motor: str = '',
    cilindraje: Any = None,
) -> dict:
    """Deja la línea sin el párrafo largo ni el motivo interno del selector.

    Devuelve una copia. No pisa el nombre, la URL ni una descripción de la pieza.
    """
    if not isinstance(rep, dict):
        return rep
    linea = copy.deepcopy(rep)
    casa_vis = nombre_tienda_visible(str(linea.get('casa_repuesto_nombre') or ''))
    prov_vis = nombre_tienda_visible(str(linea.get('proveedor_nombre') or ''))
    if casa_vis:
        linea['casa_repuesto_nombre'] = casa_vis
    if prov_vis and str(linea.get('proveedor_nombre') or '').strip():
        linea['proveedor_nombre'] = prov_vis
    elif not casa_vis and prov_vis:
        linea['casa_repuesto_nombre'] = prov_vis
        casa_vis = prov_vis
    if not casa_vis and prov_vis:
        casa_vis = prov_vis
        if not str(linea.get('casa_repuesto_nombre') or '').strip():
            linea['casa_repuesto_nombre'] = casa_vis
    tienda = casa_vis or prov_vis
    hay = _hay_tienda_en_linea(linea)
    for fuente in linea.get('fuentes_detalle') or []:
        if isinstance(fuente, dict) and str(fuente.get('tienda') or '').strip():
            fuente['tienda'] = nombre_tienda_visible(str(fuente.get('tienda') or '')) or fuente['tienda']
    if str(linea.get('tienda_ml') or '').strip():
        linea['tienda_ml'] = nombre_tienda_visible(str(linea.get('tienda_ml') or '')) or linea['tienda_ml']
    if str(linea.get('referencia_tienda') or '').strip():
        linea['referencia_tienda'] = (
            nombre_tienda_visible(str(linea.get('referencia_tienda') or ''))
            or linea['referencia_tienda']
        )
    motivo = str(linea.get('motivo_seleccion') or '')
    if not _motivo_ya_es_corto(motivo, tienda=tienda, hay_tienda=hay):
        linea['motivo_seleccion'] = _nota_corta_para_linea(
            linea,
            marca=marca,
            modelo=modelo,
            anio=anio,
            tipo_motor=tipo_motor,
            cilindraje=cilindraje,
            motivo_interno=motivo,
        )
    comentario = str(linea.get('comentario') or '')
    nota_con_slug = (
        hay and tienda and _es_nota_mecanico(comentario)
        and not _nota_empieza_con_tienda(comentario, tienda)
    )
    if nota_visible_debe_reemplazarse(comentario) or nota_con_slug:
        linea['comentario'] = str(linea.get('motivo_seleccion') or '') or _nota_corta_para_linea(
            linea,
            marca=marca,
            modelo=modelo,
            anio=anio,
            tipo_motor=tipo_motor,
            cilindraje=cilindraje,
        )
    nota = str(linea.get('motivo_seleccion') or linea.get('comentario') or '')
    if nota:
        for clave, valor in list(linea.items()):
            if clave in _CLAVES_INTOCABLES:
                continue
            linea[clave] = _reemplazar_frases_prohibidas(valor, nota)
    return linea


def contexto_nota_cotizacion(cot: Any) -> dict[str, Any]:
    """Marca, modelo y motor de la cotización, para armar la nota al leer o al guardar."""
    tipo = ' '.join(
        parte for parte in (
            str(getattr(cot, 'tipo_motor', '') or ''),
            str(getattr(cot, 'tipo_motor_label', '') or ''),
        ) if parte
    )
    return {
        'marca': getattr(cot, 'vehiculo_marca', '') or '',
        'modelo': getattr(cot, 'vehiculo_modelo', '') or '',
        'anio': getattr(cot, 'vehiculo_anio', None),
        'tipo_motor': tipo,
        'cilindraje': getattr(cot, 'vehiculo_cilindraje', '') or '',
    }


_STOP_PIEZA = frozenset({
    'de', 'del', 'la', 'el', 'los', 'las', 'un', 'una', 'y', 'para', 'con',
    'motor', 'delantero', 'delantera', 'delanteros', 'delanteras',
    'trasero', 'trasera', 'traseros', 'traseras', 'juego', 'kit', 'par',
    'original', 'alternativo', 'sintetico', 'mineral',
})


def _stem_pieza(token: str) -> str:
    t = _norm(token)
    if len(t) > 4 and t.endswith('es'):
        return t[:-2]
    if len(t) > 3 and t.endswith('s'):
        return t[:-1]
    return t


def _keywords_pieza(nombre: str) -> list[str]:
    """Sustantivos que la ficha tiene que nombrar. 'Repuestos Fiat Bravo' no califica."""
    from .familias_sensibles import FAMILIAS_SENSIBLES, detectar_familia_sensible

    claves: list[str] = []
    fam = detectar_familia_sensible(nombre)
    if fam:
        for key in FAMILIAS_SENSIBLES[fam].get('keywords') or ():
            stem = _stem_pieza(str(key))
            if stem and stem not in claves:
                claves.append(stem)
        return claves
    for tok in _norm(nombre).split():
        if len(tok) < 4 or tok in _STOP_PIEZA:
            continue
        stem = _stem_pieza(tok)
        if stem and stem not in claves:
            claves.append(stem)
    return claves[:3]


def _producto_menciona_pieza(nombre_repuesto: str, producto_matched: str) -> bool:
    """True si el título nombra la pieza pedida.

    Un listado genérico ('Repuestos Fiat Bravo | Mundo Repuestos Chile') no
    trae 'pastilla' ni 'filtro' y no puede cotizar esa línea.
    """
    producto = str(producto_matched or '').strip()
    if not producto:
        return True
    if _norm(producto) == _norm(nombre_repuesto):
        return True
    keywords = _keywords_pieza(nombre_repuesto)
    if not keywords:
        return True
    prod = _norm(producto)
    return any(k in prod for k in keywords)


def _familia_de(nombre: str) -> str:
    """Familia de la pieza. Vacío si el texto no nombra una familia conocida."""
    from .familias_sensibles import detectar_familia_sensible

    fam = detectar_familia_sensible(nombre) or ''
    if fam:
        return fam
    if 'filtro' in _norm(nombre):
        return 'filtro'
    return ''


def _familia_distinta(linea: str, otro: str) -> bool:
    """True si los dos textos son piezas distintas (pastillas contra aceite)."""
    a = _familia_de(linea)
    b = _familia_de(otro)
    return bool(a and b and a != b)


def _producto_es_la_pieza(nombre_repuesto: str, producto_matched: str, *, fuente: str = '') -> bool:
    """Tipo de parte + keyword. Rechaza enfriador-por-aceite y listados genéricos."""
    producto = str(producto_matched or '').strip()
    if not _validar_tipo_parte(nombre_repuesto, producto):
        logger.warning(
            'ordenes[enrich] mismatch_tipo_rechazado repuesto=%s producto=%s fuente=%s',
            (nombre_repuesto or '')[:50],
            producto[:50],
            (fuente or '')[:15],
        )
        return False
    if (
        producto
        and _es_linea_aceite_motor(nombre_repuesto)
        and not _ficha_es_aceite_de_motor(producto)
    ):
        logger.warning(
            'ordenes[enrich] ficha_aceite_rechazada repuesto=%s producto=%s fuente=%s',
            (nombre_repuesto or '')[:50],
            producto[:50],
            (fuente or '')[:15],
        )
        return False
    if fuente in ('web', 'historial', '') and not _producto_menciona_pieza(nombre_repuesto, producto):
        logger.warning(
            'ordenes[enrich] listado_generico_rechazado repuesto=%s producto=%s fuente=%s',
            (nombre_repuesto or '')[:50],
            producto[:50],
            (fuente or '')[:15],
        )
        return False
    return True


def _mejor_hit(nombre: str, candidatos: list[dict[str, Any]], *, min_score: int = 50) -> dict[str, Any] | None:
    q = _clave_fuzzy(nombre)
    if not q:
        return None
    best: dict[str, Any] | None = None
    best_score = 0
    best_conf = -1.0
    for cand in candidatos:
        score = _match_score(q, cand.get('clave') or '')
        if score < min_score:
            continue
        producto_nombre = str(cand.get('nombre_producto') or cand.get('nombre') or '')
        # El aceite de la línea de al lado no se prueba contra las pastillas:
        # ese intento logueaba listado_generico y no puede ganar el match.
        if _familia_distinta(nombre, producto_nombre) or _familia_distinta(
            nombre, str(cand.get('clave') or ''),
        ):
            continue
        fuente = str(cand.get('fuente_marketplace') or '')
        if not _producto_es_la_pieza(nombre, producto_nombre, fuente=fuente):
            continue
        conf = float(cand.get('confianza') or 0)
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
    from mecanimovilapp.apps.ordenes.services.catalogo_pricing import servicios_mismo_trabajo

    if not (a or '').strip() or not (b or '').strip():
        return False
    return servicios_mismo_trabajo(a, b)


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
            from mecanimovilapp.apps.ordenes.services.catalogo_pricing import (
                repuesto_compatible_con_servicios,
            )

            for raw in (cot.repuestos or []):
                if not isinstance(raw, dict):
                    continue
                nombre = str(raw.get('nombre') or '').strip()
                if servicio_req and not repuesto_compatible_con_servicios(nombre, [servicio_req]):
                    continue
                clave = _clave_fuzzy(nombre)
                if not clave:
                    continue
                # Un borrador no llega aquí (solo enviada/aceptada). Si la línea
                # guardó una ficha web de otra pieza, no se reaprende.
                nombre_producto = str(raw.get('nombre_producto') or '').strip()
                fuente_linea = str(
                    raw.get('fuente_marketplace') or raw.get('fuente_repuesto') or '',
                ).strip()
                if nombre_producto and _familia_distinta(nombre, nombre_producto):
                    continue
                if nombre_producto and not _producto_es_la_pieza(
                    nombre, nombre_producto, fuente=fuente_linea or 'historial',
                ):
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
                if nombre_producto:
                    b.setdefault('nombres_producto', []).append(nombre_producto)
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
            # NUEVO: Preservar nombre_producto más común para validación
            nombre_prod_moda = ''
            if data.get('nombres_producto'):
                nombre_prod_moda = Counter(data['nombres_producto']).most_common(1)[0][0]
            
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
            # CRÍTICO: Agregar nombre_producto para validación
            if nombre_prod_moda:
                hit['nombre_producto'] = nombre_prod_moda
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
    bandas_min: dict[str, int] | None = None,
    bandas_max: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Hits vigentes desde PrecioRepuestoWeb (rellenado por Celery/Gemini URL Context)."""
    try:
        from mecanimovilapp.apps.ordenes.models import PrecioRepuestoWeb
        from .busqueda_web_repuestos import (
            _CACHE_RELECTURA_CUPO,
            _banda_min_de,
            _es_listado_sin_vendedor,
            _expirar_fila_cache,
            _fila_cache_utilizable,
            clave_cache_repuesto,
        )

        now = timezone.now()
        qs = PrecioRepuestoWeb.objects.filter(expira_en__gt=now)
        clave_a_nombre: dict[str, str] = {}
        if nombres:
            claves: list[str] = []
            for nom in nombres:
                if not str(nom or '').strip():
                    continue
                clave_nom = clave_cache_repuesto(
                    nom,
                    marca_vehiculo=marca_vehiculo,
                    modelo_vehiculo=modelo_vehiculo,
                    anio=anio_vehiculo,
                    tipo_motor=tipo_motor,
                    cilindraje=cilindraje,
                )
                if not clave_nom:
                    continue
                claves.append(clave_nom)
                clave_a_nombre[clave_nom] = str(nom)
            qs = qs.filter(clave__in=claves)
        qs = qs.order_by('-confianza')[:400]
        out: list[dict[str, Any]] = []
        from .vehiculo_exacto import clave_historial_cubre_vehiculo

        veh_norm = _norm(
            ' '.join(str(p) for p in (marca_vehiculo, modelo_vehiculo, anio_vehiculo or '') if p),
        )
        cupo = [_CACHE_RELECTURA_CUPO]
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
            linea_cache = clave_a_nombre.get(clave, '')
            producto_cache = str(row.nombre_producto or '').strip()
            if dominio in ('historial-taller', 'historial_taller'):
                if linea_cache and producto_cache and not _producto_es_la_pieza(
                    linea_cache, producto_cache, fuente='web',
                ):
                    _expirar_fila_cache(
                        row, now, linea=linea_cache, producto=producto_cache, motivo='otra_pieza',
                    )
                    continue
                precio_usar = int(row.precio_clp or 0)
            else:
                precio_usar = _fila_cache_utilizable(
                    row,
                    linea_cache,
                    modelo=modelo_vehiculo,
                    tipo_motor=tipo_motor,
                    banda_min=_banda_min_de(bandas_min, linea_cache),
                    banda_max=_banda_min_de(bandas_max, linea_cache),
                    anio=anio_vehiculo,
                    cilindraje=cilindraje,
                    now=now,
                    cupo=cupo,
                )
                if precio_usar is None:
                    continue
            marca = _marca_repuesto_valida(row.marca_repuesto)
            clave_nombre = clave.split('|', 1)[0] if '|' in clave else clave
            dominio = str(row.dominio or '').strip().lower()
            # Semilla post-envío (aprendizaje) → historial del taller, no marketplace web.
            if dominio in ('historial-taller', 'historial_taller'):
                fuente = 'historial'
                conf = float(row.confianza or _CONF_HISTORIAL)
                proveedor = (
                    nombre_tienda_visible(str(row.tienda or ''))
                    or 'Historial del taller'
                )[:200]
            else:
                fuente = 'web'
                conf = float(row.confianza or _CONF_WEB)
                proveedor = (nombre_tienda_visible(str(row.tienda or '')) or str(row.tienda or ''))[:200]
            hit = _hit(
                nombre=str(row.nombre_producto or '')[:200],
                marca_repuesto=marca,
                precio_unitario_clp=int(precio_usar or 0),
                fuente_marketplace=fuente,
                proveedor_nombre=proveedor,
                url_producto=str(row.url or '')[:500],
                confianza=conf if conf > 0 else (_CONF_HISTORIAL if fuente == 'historial' else _CONF_WEB),
                clave=clave_nombre or _clave_fuzzy(str(row.nombre_producto or '')),
                calidad=str(getattr(row, 'calidad', '') or ''),
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
    marca_hit = _marca_canonica(
        str(hit.get('marca_repuesto') or ''),
        f"{hit.get('nombre_producto') or ''} {hit.get('marca_repuesto') or ''}",
    )
    if marca_hit and (not marca_actual or puede_reemplazar):
        next_rep['marca_repuesto'] = marca_hit
        # El cliente ve el nombre del ítem: la marca debe ir ahí, no solo en un tag.
        next_rep['nombre'] = _nombre_con_marca(
            str(next_rep.get('nombre') or ''),
            marca_hit,
            str(hit.get('nombre_producto') or ''),
        )

    if hit.get('fuente_marketplace') and (not fuente_actual or puede_reemplazar):
        next_rep['fuente_marketplace'] = hit['fuente_marketplace']
        next_rep.pop('fuente_repuesto', None)

    proveedor_actual = str(next_rep.get('proveedor_nombre') or '').strip()
    if hit.get('proveedor_nombre') and (not proveedor_actual or puede_reemplazar):
        crudo = str(hit['proveedor_nombre'])
        next_rep['proveedor_nombre'] = (nombre_tienda_visible(crudo) or crudo)[:200]

    tienda_actual = str(next_rep.get('tienda_ml') or '').strip()
    if hit.get('tienda_ml') and (not tienda_actual or puede_reemplazar):
        next_rep['tienda_ml'] = hit['tienda_ml']
        if not str(next_rep.get('proveedor_nombre') or '').strip():
            crudo_ml = str(hit['tienda_ml'])
            next_rep['proveedor_nombre'] = (nombre_tienda_visible(crudo_ml) or crudo_ml)[:200]

    url_actual = str(next_rep.get('url_producto') or '').strip()
    if hit.get('url_producto') and (not url_actual or puede_reemplazar):
        next_rep['url_producto'] = hit['url_producto']

    listing = str(hit.get('nombre_producto') or '').strip()[:200]
    listing_actual = str(next_rep.get('nombre_producto') or '').strip()
    if listing and (not listing_actual or puede_reemplazar):
        next_rep['nombre_producto'] = listing

    if hit.get('proveedor_id') and (not next_rep.get('proveedor_id') or puede_reemplazar):
        next_rep['proveedor_id'] = hit['proveedor_id']
    if hit.get('especificacion') and (not str(next_rep.get('especificacion') or '').strip() or puede_reemplazar):
        next_rep['especificacion'] = hit['especificacion']

    cal_hit = str(hit.get('calidad') or '').strip().lower()
    cal_actual = str(next_rep.get('calidad') or '').strip().lower()
    if cal_hit in ('original', 'oem', 'alternativo') and (
        cal_actual not in ('original', 'oem', 'alternativo') or puede_reemplazar
    ):
        next_rep['calidad'] = cal_hit
        next_rep['calidad_pendiente'] = False

    pais_hit = str(hit.get('pais_origen') or '').strip()[:40]
    pais_actual = str(next_rep.get('pais_origen') or '').strip()
    if pais_hit and (not pais_actual or puede_reemplazar):
        next_rep['pais_origen'] = pais_hit


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
    urls_rechazadas: set[str] | None = None,
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
        str(r.get('nombre') or '') for r in repuestos if isinstance(r, dict)
    ]
    from .busqueda_web_repuestos import _monto_banda_por_unidad

    bandas_min: dict[str, int] = {}
    bandas_max: dict[str, int] = {}
    for r in repuestos:
        if not isinstance(r, dict):
            continue
        nombre_banda = str(r.get('nombre') or '').strip()
        if not nombre_banda:
            continue
        try:
            piso = int(r.get('precio_min_clp') or 0)
        except (TypeError, ValueError):
            piso = 0
        try:
            techo = int(r.get('precio_max_clp') or 0)
        except (TypeError, ValueError):
            techo = 0
        piso = _monto_banda_por_unidad(nombre_banda, piso, r.get('cantidad'))
        techo = _monto_banda_por_unidad(nombre_banda, techo, r.get('cantidad'))
        if piso > 0:
            bandas_min[nombre_banda] = piso
        if techo > 0:
            bandas_max[nombre_banda] = techo
    web_cands = (
        _candidatos_web_cache(
            marca_vehiculo=marca_vehiculo,
            modelo_vehiculo=modelo_vehiculo,
            anio_vehiculo=anio_vehiculo,
            tipo_motor=tipo_motor,
            cilindraje=cilindraje,
            nombres=nombres_lineas,
            bandas_min=bandas_min,
            bandas_max=bandas_max,
        )
        if usar_web
        else []
    )

    out: list[dict[str, Any]] = []
    for rep in repuestos:
        if not isinstance(rep, dict):
            continue
        next_rep = dict(rep)
        aplicar_cantidad_aceite_motor(
            next_rep,
            marca=marca_vehiculo,
            modelo=modelo_vehiculo,
            cilindraje=cilindraje,
            tipo_motor=tipo_motor,
        )
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
            from .busqueda_web_repuestos import (
                _candidato_sirve_linea,
                _monto_banda_por_unidad,
            )

            try:
                piso_linea = int(next_rep.get('precio_min_clp') or 0)
            except (TypeError, ValueError):
                piso_linea = 0
            try:
                techo_linea = int(next_rep.get('precio_max_clp') or 0)
            except (TypeError, ValueError):
                techo_linea = 0
            piso_linea = _monto_banda_por_unidad(nombre, piso_linea, next_rep.get('cantidad'))
            techo_linea = _monto_banda_por_unidad(nombre, techo_linea, next_rep.get('cantidad'))
            prohibidas = urls_rechazadas or set()
            web_ok = [
                c for c in web_cands
                if str(c.get('url_producto') or '') not in prohibidas
                and not _familia_distinta(nombre, str(c.get('clave') or ''))
                and not _familia_distinta(
                    nombre, str(c.get('nombre_producto') or c.get('nombre') or ''),
                )
                and _candidato_sirve_linea(
                    nombre,
                    {
                        'title': str(c.get('nombre_producto') or c.get('nombre') or ''),
                        'content': '',
                        'url': str(c.get('url_producto') or ''),
                        # La caché no trae el cuerpo. Un título sin el auto no pasa.
                        'ficha_leida': True,
                        'precio_snippet': int(c.get('precio_unitario_clp') or 0),
                    },
                    anio=anio_vehiculo,
                    cilindraje=cilindraje,
                    modelo=modelo_vehiculo,
                    tipo_motor=tipo_motor,
                    banda_min=piso_linea,
                    banda_max=techo_linea,
                )
            ]
            web_hit = _mejor_hit(nombre, web_ok, min_score=min_score_web_para(nombre))
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
        if str(next_rep.get('fuente_marketplace') or '') == 'web':
            from .busqueda_web_repuestos import (
                precio_unitario_desde_envase,
                precio_unitario_desde_pack,
            )

            unit, nota_envase = precio_unitario_desde_envase(
                nombre,
                _to_int_clp(next_rep.get('precio_unitario_clp')),
                str(next_rep.get('nombre_producto') or ''),
            )
            if not nota_envase:
                unit, nota_envase = precio_unitario_desde_pack(
                    nombre,
                    unit,
                    str(next_rep.get('nombre_producto') or ''),
                    next_rep.get('cantidad'),
                )
            if nota_envase and unit > 0:
                next_rep['precio_unitario_clp'] = unit
                next_rep['comentario'] = nota_envase[:300]
        from .calidad_repuesto import anotar_calidad_en_linea
        from .opciones_repuesto import poblar_opciones_en_linea

        next_rep = anotar_calidad_en_linea(next_rep, descartar_invalida=False)
        poblar_opciones_en_linea(next_rep, hits)

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
