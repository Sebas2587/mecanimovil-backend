"""
Servicio de predicción de desgaste vehicular basado en clima.
Fuente primaria: Open-Meteo (actualiza cada 15 min, coords directas).
Fallback: boostr.cl (datos SYNOP, actualiza cada 6h).
Aplica el algoritmo IA-Weather-Telemetry de Mecanimóvil.

Límites API pública (no comercial): ~600 req/min, 5000/h, 10k/día por IP
(ver https://open-meteo.com/en/pricing ). Tras 429, cooldown en Redis para
no insistir. Producción: opcional OPEN_METEO_API_KEY → customer-api (sin
límite por minuto en planes de pago).
"""
import logging
import os
import time
import random
import requests
from datetime import datetime
from urllib.parse import quote
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

BOOSTR_API_URL = "https://api.boostr.cl/weather/{code}.json"

WEATHER_CACHE_TTL = 60 * 15  # 15 min — Open-Meteo updates every 15 min
# Copia de respaldo si Open-Meteo responde 429 o falla temporalmente (no satura reintentos).
OPENMETEO_LAST_GOOD_TTL = 60 * 60 * 12
# Redondeo de grilla: el GPS “tiembla” en 4+ decimales y fragmentaba la cache → muchas URLs a Open-Meteo.
WEATHER_GRID_DECIMALS = 3
# Antiráfaga: un solo fetch a Open-Meteo por celda cada pocos segundos al expirar la cache.
OPENMETEO_FETCH_LOCK_SECONDS = 10
OPENMETEO_FETCH_WAIT_ATTEMPTS = 30
OPENMETEO_FETCH_WAIT_STEP = 0.2
# boostr actualiza ~cada 6h; cachear más tiempo evita martillar su API cuando Open-Meteo falla.
BOOSTR_WEATHER_CACHE_TTL = 60 * 30
# Tras un 429, no volver a llamar a Open-Meteo (pública) por esta celda durante unos minutos.
OPENMETEO_429_COOLDOWN_SECONDS = int(os.environ.get('OPEN_METEO_429_COOLDOWN', '180'))

OPEN_METEO_HTTP_HEADERS = {
    'User-Agent': 'Mecanimovil/1.0 (+https://mecanimovil-api.onrender.com; weather)',
    'Accept': 'application/json',
}


def _open_meteo_api_key():
    return os.environ.get('OPEN_METEO_API_KEY', '').strip()


def _build_open_meteo_url(lat, lng):
    """API pública sin key; con OPEN_METEO_API_KEY usa customer-api (recomendado en producción)."""
    key = _open_meteo_api_key()
    if key:
        root = os.environ.get(
            'OPEN_METEO_API_BASE',
            'https://customer-api.open-meteo.com/v1/forecast',
        ).strip()
    else:
        root = 'https://api.open-meteo.com/v1/forecast'
    url = (
        f'{root}?latitude={lat}&longitude={lng}'
        '&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m'
        '&timezone=America/Santiago'
    )
    if key:
        url += f'&apikey={quote(key, safe="")}'
    return url


# ── WMO weather codes → Spanish condition text ──
WMO_CONDITIONS = {
    0: 'Despejado',
    1: 'Mayormente despejado', 2: 'Parcialmente nublado', 3: 'Nublado',
    45: 'Neblina', 48: 'Neblina con escarcha',
    51: 'Llovizna ligera', 53: 'Llovizna moderada', 55: 'Llovizna intensa',
    56: 'Llovizna helada ligera', 57: 'Llovizna helada intensa',
    61: 'Lluvia ligera', 63: 'Lluvia moderada', 65: 'Lluvia intensa',
    66: 'Lluvia helada ligera', 67: 'Lluvia helada intensa',
    71: 'Nevada ligera', 73: 'Nevada moderada', 75: 'Nevada intensa',
    77: 'Granizo fino',
    80: 'Chubascos ligeros', 81: 'Chubascos moderados', 82: 'Chubascos intensos',
    85: 'Nevada ligera con chubascos', 86: 'Nevada intensa con chubascos',
    95: 'Tormenta eléctrica', 96: 'Tormenta con granizo ligero', 99: 'Tormenta con granizo',
}

# Códigos WMO que implican lluvia/precipitación
WMO_RAIN_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}

# ── Station maps (kept for boostr fallback and address-based lookups) ──
STATION_MAP = {
    'SCFA': 'Antofagasta', 'SCAR': 'Arica', 'SCBA': 'Balmaceda',
    'SCCF': 'Calama', 'SCAT': 'Caldera', 'SCCH': 'Chillán',
    'SCIE': 'Concepción', 'SCCY': 'Coyhaique', 'SCIC': 'Curicó',
    'SCFT': 'Futaleufú', 'SCDA': 'Iquique', 'SCIP': 'Isla de Pascua',
    'SCSE': 'La Serena', 'SCMK': 'Melinka', 'SCJO': 'Osorno',
    'SCTE': 'Puerto Montt', 'SCCI': 'Punta Arenas', 'SCON': 'Quellón',
    'SCSN': 'San Antonio', 'SCQN': 'Santiago', 'SCEL': 'Santiago',
    'SCQP': 'Temuco', 'SCVD': 'Valdivia', 'SCVM': 'Viña del Mar',
    'SCIR': 'Juan Fernández', 'SCRM': 'Antártica', 'SCGZ': 'Puerto Williams',
    'SCFM': 'Porvenir', 'SCRG': 'Rancagua', 'SCGE': 'Los Ángeles',
    'SCTN': 'Chaitén', 'SCCC': 'Chile Chico', 'SCHR': 'Cochrane',
    'SCNT': 'Puerto Natales',
}

COMUNA_TO_STATION = {
    'arica': 'SCAR', 'putre': 'SCAR', 'camarones': 'SCAR',
    'general lagos': 'SCAR',
    'iquique': 'SCDA', 'alto hospicio': 'SCDA', 'pozo almonte': 'SCDA',
    'pica': 'SCDA', 'huara': 'SCDA',
    'antofagasta': 'SCFA', 'mejillones': 'SCFA', 'taltal': 'SCFA',
    'tocopilla': 'SCFA', 'maria elena': 'SCFA', 'sierra gorda': 'SCFA',
    'calama': 'SCCF', 'san pedro de atacama': 'SCCF', 'ollague': 'SCCF',
    'caldera': 'SCAT', 'copiapo': 'SCAT', 'tierra amarilla': 'SCAT',
    'diego de almagro': 'SCAT', 'chanaral': 'SCAT', 'freirina': 'SCAT',
    'vallenar': 'SCAT', 'huasco': 'SCAT',
    'la serena': 'SCSE', 'coquimbo': 'SCSE', 'andacollo': 'SCSE',
    'la higuera': 'SCSE', 'ovalle': 'SCSE', 'monte patria': 'SCSE',
    'combarbala': 'SCSE', 'punitaqui': 'SCSE', 'rio hurtado': 'SCSE',
    'illapel': 'SCSE', 'salamanca': 'SCSE', 'los vilos': 'SCSE',
    'canela': 'SCSE', 'vicuna': 'SCSE', 'paiguano': 'SCSE',
    'valparaiso': 'SCVM', 'vina del mar': 'SCVM', 'quilpue': 'SCVM',
    'villa alemana': 'SCVM', 'concon': 'SCVM', 'quintero': 'SCVM',
    'puchuncavi': 'SCVM', 'casablanca': 'SCVM', 'limache': 'SCVM',
    'olmue': 'SCVM', 'quillota': 'SCVM', 'la calera': 'SCVM',
    'hijuelas': 'SCVM', 'la cruz': 'SCVM', 'nogales': 'SCVM',
    'san antonio': 'SCSN', 'cartagena': 'SCSN', 'el tabo': 'SCSN',
    'el quisco': 'SCSN', 'algarrobo': 'SCSN', 'santo domingo': 'SCSN',
    'san felipe': 'SCVM', 'los andes': 'SCVM', 'catemu': 'SCVM',
    'panquehue': 'SCVM', 'putaendo': 'SCVM', 'santa maria': 'SCVM',
    'rinconada': 'SCVM', 'calle larga': 'SCVM', 'san esteban': 'SCVM',
    'isla de pascua': 'SCIP', 'juan fernandez': 'SCIR',
    'petorca': 'SCVM', 'la ligua': 'SCVM', 'cabildo': 'SCVM',
    'papudo': 'SCVM', 'zapallar': 'SCVM',
    'santiago': 'SCQN', 'santiago centro': 'SCQN',
    'providencia': 'SCQN', 'las condes': 'SCQN', 'vitacura': 'SCQN',
    'lo barnechea': 'SCQN', 'nunoa': 'SCQN', 'la reina': 'SCQN',
    'macul': 'SCQN', 'penalolen': 'SCQN', 'la florida': 'SCQN',
    'san joaquin': 'SCQN', 'san miguel': 'SCQN', 'pedro aguirre cerda': 'SCQN',
    'lo espejo': 'SCQN', 'la cisterna': 'SCQN', 'el bosque': 'SCQN',
    'san bernardo': 'SCQN', 'la granja': 'SCQN', 'san ramon': 'SCQN',
    'la pintana': 'SCQN', 'puente alto': 'SCQN', 'pirque': 'SCQN',
    'san jose de maipo': 'SCQN', 'buin': 'SCQN', 'paine': 'SCQN',
    'calera de tango': 'SCQN',
    'maipu': 'SCEL', 'cerrillos': 'SCEL', 'estacion central': 'SCEL',
    'lo prado': 'SCEL', 'pudahuel': 'SCEL', 'cerro navia': 'SCEL',
    'quinta normal': 'SCEL', 'renca': 'SCEL', 'quilicura': 'SCEL',
    'huechuraba': 'SCEL', 'conchali': 'SCEL', 'independencia': 'SCEL',
    'recoleta': 'SCEL', 'colina': 'SCEL', 'lampa': 'SCEL',
    'til til': 'SCEL', 'padre hurtado': 'SCEL', 'peñaflor': 'SCEL',
    'talagante': 'SCEL', 'el monte': 'SCEL', 'isla de maipo': 'SCEL',
    'melipilla': 'SCEL', 'san pedro': 'SCEL', 'alhue': 'SCEL',
    'curacavi': 'SCEL', 'maria pinto': 'SCEL',
    'rancagua': 'SCRG', 'machali': 'SCRG', 'graneros': 'SCRG',
    'san fernando': 'SCRG', 'santa cruz': 'SCRG', 'rengo': 'SCRG',
    'requinoa': 'SCRG', 'olivar': 'SCRG', 'coinco': 'SCRG',
    'coltauco': 'SCRG', 'donihue': 'SCRG', 'las cabras': 'SCRG',
    'peumo': 'SCRG', 'pichidegua': 'SCRG', 'mostazal': 'SCRG',
    'codegua': 'SCRG', 'chimbarongo': 'SCRG', 'nancagua': 'SCRG',
    'placilla': 'SCRG', 'chepica': 'SCRG', 'lolol': 'SCRG',
    'pichilemu': 'SCRG', 'litueche': 'SCRG', 'marchihue': 'SCRG',
    'navidad': 'SCRG', 'la estrella': 'SCRG', 'paredones': 'SCRG',
    'curico': 'SCIC', 'talca': 'SCIC', 'linares': 'SCIC',
    'cauquenes': 'SCIC', 'constitucion': 'SCIC', 'molina': 'SCIC',
    'sagrada familia': 'SCIC', 'teno': 'SCIC', 'romeral': 'SCIC',
    'hualane': 'SCIC', 'licanten': 'SCIC', 'vichuquen': 'SCIC',
    'san clemente': 'SCIC', 'maule': 'SCIC', 'pelarco': 'SCIC',
    'rio claro': 'SCIC', 'pencahue': 'SCIC', 'curepto': 'SCIC',
    'san javier': 'SCIC', 'villa alegre': 'SCIC', 'yerbas buenas': 'SCIC',
    'colbun': 'SCIC', 'longavi': 'SCIC', 'parral': 'SCIC',
    'retiro': 'SCIC', 'pelluhue': 'SCIC', 'chanco': 'SCIC',
    'chillan': 'SCCH', 'chillan viejo': 'SCCH', 'san carlos': 'SCCH',
    'bulnes': 'SCCH', 'coihueco': 'SCCH', 'el carmen': 'SCCH',
    'ninhue': 'SCCH', 'pinto': 'SCCH', 'quillon': 'SCCH',
    'quirihue': 'SCCH', 'ranquil': 'SCCH', 'san fabian': 'SCCH',
    'san ignacio': 'SCCH', 'san nicolas': 'SCCH', 'treguaco': 'SCCH',
    'yungay': 'SCCH', 'cobquecura': 'SCCH', 'portezuelo': 'SCCH',
    'coelemu': 'SCCH', 'pemuco': 'SCCH',
    'concepcion': 'SCIE', 'talcahuano': 'SCIE', 'hualpen': 'SCIE',
    'chiguayante': 'SCIE', 'san pedro de la paz': 'SCIE', 'coronel': 'SCIE',
    'lota': 'SCIE', 'penco': 'SCIE', 'tome': 'SCIE', 'hualqui': 'SCIE',
    'florida': 'SCIE', 'santa juana': 'SCIE', 'arauco': 'SCIE',
    'curanilahue': 'SCIE', 'lebu': 'SCIE', 'canete': 'SCIE',
    'contulmo': 'SCIE', 'tirua': 'SCIE', 'los alamos': 'SCIE',
    'los angeles': 'SCGE', 'nacimiento': 'SCGE', 'laja': 'SCGE',
    'san rosendo': 'SCGE', 'yumbel': 'SCGE', 'cabrero': 'SCGE',
    'tucapel': 'SCGE', 'antuco': 'SCGE', 'quilleco': 'SCGE',
    'santa barbara': 'SCGE', 'alto biobio': 'SCGE', 'mulchen': 'SCGE',
    'negrete': 'SCGE', 'quilaco': 'SCGE',
    'temuco': 'SCQP', 'padre las casas': 'SCQP', 'villarrica': 'SCQP',
    'pucon': 'SCQP', 'freire': 'SCQP', 'pitrufquen': 'SCQP',
    'gorbea': 'SCQP', 'loncoche': 'SCQP', 'tolten': 'SCQP',
    'curarrehue': 'SCQP', 'cunco': 'SCQP',
    'nueva imperial': 'SCQP', 'carahue': 'SCQP', 'saavedra': 'SCQP',
    'teodoro schmidt': 'SCQP', 'cholchol': 'SCQP',
    'angol': 'SCQP', 'renaico': 'SCQP', 'collipulli': 'SCQP',
    'ercilla': 'SCQP', 'los sauces': 'SCQP', 'puren': 'SCQP',
    'traiguen': 'SCQP', 'lumaco': 'SCQP', 'victoria': 'SCQP',
    'curacautin': 'SCQP', 'lonquimay': 'SCQP', 'melipeuco': 'SCQP',
    'vilcun': 'SCQP', 'lautaro': 'SCQP', 'perquenco': 'SCQP',
    'galvarino': 'SCQP',
    'valdivia': 'SCVD', 'corral': 'SCVD', 'lanco': 'SCVD',
    'mariquina': 'SCVD', 'mafil': 'SCVD', 'los lagos': 'SCVD',
    'panguipulli': 'SCVD', 'la union': 'SCVD', 'rio bueno': 'SCVD',
    'paillaco': 'SCVD', 'futrono': 'SCVD', 'lago ranco': 'SCVD',
    'osorno': 'SCJO', 'san pablo': 'SCJO', 'puyehue': 'SCJO',
    'rio negro': 'SCJO', 'purranque': 'SCJO', 'entre lagos': 'SCJO',
    'san juan de la costa': 'SCJO',
    'puerto montt': 'SCTE', 'puerto varas': 'SCTE', 'llanquihue': 'SCTE',
    'fresia': 'SCTE', 'frutillar': 'SCTE', 'los muermos': 'SCTE',
    'calbuco': 'SCTE', 'maullin': 'SCTE', 'cochamo': 'SCTE',
    'castro': 'SCTE', 'ancud': 'SCTE', 'dalcahue': 'SCTE',
    'curaco de velez': 'SCTE', 'quinchao': 'SCTE', 'quemchi': 'SCTE',
    'chonchi': 'SCTE', 'queilen': 'SCTE', 'puqueldon': 'SCTE',
    'quellon': 'SCON', 'chaiten': 'SCTN', 'hualaihue': 'SCTN',
    'futaleufu': 'SCFT', 'palena': 'SCFT',
    'coyhaique': 'SCCY', 'aysen': 'SCCY', 'cisnes': 'SCCY',
    'guaitecas': 'SCMK', 'melinka': 'SCMK',
    'chile chico': 'SCCC', 'rio ibanez': 'SCCC',
    'cochrane': 'SCHR', 'ohiggins': 'SCHR', 'tortel': 'SCHR',
    'lago verde': 'SCCY',
    'punta arenas': 'SCCI', 'rio verde': 'SCCI', 'laguna blanca': 'SCCI',
    'san gregorio': 'SCCI', 'cabo de hornos': 'SCCI',
    'puerto natales': 'SCNT', 'torres del paine': 'SCNT',
    'porvenir': 'SCFM', 'primavera': 'SCFM', 'timaukel': 'SCFM',
    'puerto williams': 'SCGZ', 'antartica': 'SCRM',
}

# ── Wear matrix & insights ──
WEAR_MATRIX = {
    'frenos':       {'rain': 1.8, 'heat': 1.2, 'cold': 1.0},
    'neumaticos':   {'rain': 1.3, 'heat': 1.5, 'cold': 1.4},
    'bateria':      {'rain': 1.0, 'heat': 1.6, 'cold': 1.9},
    'refrigerante': {'rain': 1.0, 'heat': 1.8, 'cold': 1.5},
}

AI_INSIGHTS = {
    'rain': 'Evita frenados bruscos. La humedad actual reduce la vida útil de tus pastillas más rápido que en seco.',
    'heat': 'Calor extremo detectado. Revisa presión de neumáticos y nivel de refrigerante con mayor frecuencia.',
    'cold': 'Bajas temperaturas detectadas. La batería pierde capacidad y el caucho se endurece. Precalienta el motor.',
    'normal': 'Condiciones climáticas óptimas. Mantén tu calendario de mantenimiento regular.',
}


def _norm_component_slug(slug):
    if not slug:
        return ''
    return str(slug).strip().lower().replace('_', '-')


# Slugs por grupo climático (catálogo init_smart_health + alias español / legacy).
# Cualquier slug listado en WEATHER_SLUG_EXCLUDE nunca se agrupa aunque el nombre
# contenga palabras clave (evita líquido de frenos / embrague en «frenos»).
WEATHER_SLUG_GROUPS = {
    'frenos': frozenset({
        'brakes', 'brake', 'brake-pads', 'brake-pad', 'brakepads',
        'pastillas-freno', 'pastillas-de-freno', 'pastilla-freno',
        'discos-freno', 'discos-de-freno', 'disco-freno',
        'brake-discs', 'brake-disc', 'brakediscs',
    }),
    'neumaticos': frozenset({
        'tires', 'tire', 'tyres', 'tyre',
        'neumaticos', 'neumatico', 'neumáticos', 'neumático',
        'cubiertas', 'cubierta',
    }),
    'bateria': frozenset({
        'battery', 'bateria', 'batería', 'baterias',
    }),
    'refrigerante': frozenset({
        'coolant', 'refrigerante', 'anticongelante', 'refrigeracion',
    }),
}

WEATHER_SLUG_EXCLUDE = frozenset({
    'brake-fluid', 'brakefluid', 'liquido-frenos', 'liquido-de-frenos',
    'embrague', 'clutch', 'clutch-kit', 'kit-embreaje',
    'master-cylinder', 'cilindro-maestro', 'abs-pump',
})


def normalize_text(text):
    """Normaliza texto eliminando tildes y convirtiendo a minúsculas."""
    import unicodedata
    if not text:
        return ''
    nfkd = unicodedata.normalize('NFKD', text.lower().strip())
    return ''.join(c for c in nfkd if not unicodedata.combining(c))


def _weather_grid(lat, lng):
    """Coordenadas normalizadas para cache y llamadas a Open-Meteo (menos keys = menos 429)."""
    return round(float(lat), WEATHER_GRID_DECIMALS), round(float(lng), WEATHER_GRID_DECIMALS)


def _openmeteo_cache_keys(lat_g, lng_g):
    base = f'{lat_g}_{lng_g}'
    return (
        f'openmeteo_{base}',
        f'openmeteo_lastgood_{base}',
        f'openmeteo_lock_{base}',
        f'openmeteo_rl_cooldown_{base}',
    )


# ─────────────────────────────────────────────────────────────
# Weather fetching: Open-Meteo (primary) → boostr.cl (fallback)
# ─────────────────────────────────────────────────────────────

def fetch_weather_by_coords(lat, lng, force_refresh=False):
    """
    Obtiene clima actual via Open-Meteo (coords directas, actualiza cada 15 min).
    Fallback a boostr.cl si Open-Meteo falla.
    Retorna dict compatible con el resto del pipeline o None.
    """
    lat_g, lng_g = _weather_grid(lat, lng)
    cache_key, last_good_key, lock_key, rl_cooldown_key = _openmeteo_cache_keys(lat_g, lng_g)

    if not force_refresh:
        cached = cache.get(cache_key)
        if cached:
            return cached
    else:
        cache.delete(cache_key)

    # Evitar tormenta de peticiones cuando expira el TTL y muchos workers pegan a la vez.
    got_lock = cache.add(lock_key, 1, OPENMETEO_FETCH_LOCK_SECONDS)
    if not got_lock:
        for _ in range(OPENMETEO_FETCH_WAIT_ATTEMPTS):
            time.sleep(OPENMETEO_FETCH_WAIT_STEP)
            hit = cache.get(cache_key)
            if hit:
                return hit
        # Si nadie completó el fetch, seguimos nosotros (sin lock) para no dejar al usuario sin datos.

    if cache.get(rl_cooldown_key):
        logger.info(
            "Open-Meteo omitido (cooldown post-429) para grilla (%s, %s)",
            lat_g,
            lng_g,
        )
        result, err_kind = None, 'rate_limited'
    else:
        result, err_kind = _fetch_open_meteo(lat_g, lng_g)

    if result:
        cache.set(cache_key, result, WEATHER_CACHE_TTL)
        cache.set(last_good_key, result, OPENMETEO_LAST_GOOD_TTL)
        cache.delete(rl_cooldown_key)
        return result

    if err_kind == 'rate_limited':
        cache.set(rl_cooldown_key, 1, OPENMETEO_429_COOLDOWN_SECONDS)
        logger.warning(
            "Open-Meteo 429 o cooldown para grilla (%s, %s); usando cache extendida o fallback",
            lat_g,
            lng_g,
        )

    stale = cache.get(last_good_key)
    if stale:
        stale = {**stale, 'served_from_stale_cache': True}
        cache.set(cache_key, stale, min(WEATHER_CACHE_TTL, 60 * 5))
        return stale

    logger.warning("Open-Meteo falló para (%s, %s), intentando boostr fallback", lat_g, lng_g)
    return _fetch_boostr_fallback(lat_g, lng_g, force_refresh)


def _fetch_open_meteo(lat, lng):
    """Llama Open-Meteo y normaliza la respuesta. (lat,lng) ya en grilla estable."""
    url = _build_open_meteo_url(lat, lng)
    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.get(url, timeout=10, headers=OPEN_METEO_HTTP_HEADERS)
            if resp.status_code == 429:
                if attempt < max_attempts:
                    delay = 2.0 + random.random()
                    logger.warning(
                        "Open-Meteo 429 intento %s/%s (%s, %s); reintento en %.1fs",
                        attempt,
                        max_attempts,
                        lat,
                        lng,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                return None, 'rate_limited'
            resp.raise_for_status()
            data = resp.json()

            current = data.get('current')
            if not current:
                return None, 'empty'

            temp = current.get('temperature_2m')
            humidity = current.get('relative_humidity_2m')
            wmo_code = current.get('weather_code', 0)
            condition = WMO_CONDITIONS.get(wmo_code, 'Despejado')
            report_time = current.get('time', '')

            report_age_min = _calc_open_meteo_age(report_time)

            return {
                'source': 'open-meteo-customer' if _open_meteo_api_key() else 'open-meteo',
                'station_code': None,
                'city': '',
                'temperature': round(temp) if temp is not None else None,
                'humidity': round(humidity) if humidity is not None else None,
                'condition': condition,
                'weather_code': wmo_code,
                'updated_at': report_time,
                'report_age_min': report_age_min,
            }, None
        except Exception as exc:
            logger.error("Error Open-Meteo (%s, %s): %s", lat, lng, exc)
            return None, 'error'
    return None, 'error'


def _calc_open_meteo_age(time_str):
    """
    Calcula minutos desde el timestamp ISO de Open-Meteo.
    time_str example: '2026-04-13T18:15'
    """
    if not time_str:
        return None
    try:
        report_naive = datetime.strptime(time_str[:16], '%Y-%m-%dT%H:%M')
        now_local = timezone.localtime()
        report_local = now_local.replace(
            year=report_naive.year, month=report_naive.month,
            day=report_naive.day, hour=report_naive.hour,
            minute=report_naive.minute, second=0, microsecond=0,
        )
        delta = int((now_local - report_local).total_seconds() / 60)
        return max(delta, 0)
    except Exception:
        return None


def _fetch_boostr_fallback(lat, lng, force_refresh=False):
    """Intenta resolver estación desde coords y consultar boostr."""
    station_code, station_city, _ = resolve_station_from_coords(lat, lng)
    if not station_code:
        return None
    return fetch_weather_boostr(station_code, force_refresh=force_refresh)


def fetch_weather_boostr(station_code, force_refresh=False):
    """
    Consulta la API de boostr.cl (datos SYNOP, actualiza cada ~6h).
    Retorna dict normalizado o None.
    """
    cache_key = f'boostr_weather_{station_code}'
    if not force_refresh:
        cached = cache.get(cache_key)
        if cached:
            return cached

    try:
        url = BOOSTR_API_URL.format(code=station_code)
        response = requests.get(url, headers={'accept': 'application/json'}, timeout=8)
        response.raise_for_status()
        payload = response.json()

        if payload.get('status') != 'success' or not payload.get('data'):
            logger.warning("API boostr respuesta inesperada para %s: %s", station_code, payload)
            return None

        data = payload['data']
        raw_updated_at = data.get('updated_at', '')

        result = {
            'source': 'boostr',
            'station_code': station_code,
            'city': data.get('city', ''),
            'temperature': _safe_int(data.get('temperature')),
            'humidity': _safe_int(data.get('humidity')),
            'condition': data.get('condition', ''),
            'weather_code': None,
            'updated_at': raw_updated_at,
            'report_age_min': _calc_boostr_age(raw_updated_at),
        }
        cache.set(cache_key, result, BOOSTR_WEATHER_CACHE_TTL)
        return result
    except requests.RequestException as exc:
        logger.error("Error consultando API boostr (%s): %s", station_code, exc)
        return None


def _calc_boostr_age(updated_at_str):
    """Calcula minutos desde el ciclo SYNOP (formato HH:MM:SS UTC)."""
    if not updated_at_str:
        return None
    try:
        now_utc = timezone.now()
        h, m, s = (int(x) for x in updated_at_str.split(':'))
        report_dt = now_utc.replace(hour=h, minute=m, second=s, microsecond=0)
        if report_dt > now_utc:
            report_dt -= timezone.timedelta(days=1)
        return int((now_utc - report_dt).total_seconds() / 60)
    except Exception:
        return None


# ── Station resolution (for boostr fallback & address-based lookups) ──

def resolve_station_from_coords(lat, lng):
    """
    Coordenadas GPS → estación meteorológica via Nominatim reverse geocoding.
    Retorna (station_code, station_city, address_text) o (None, None, None).
    """
    cache_key = f'nominatim_reverse_{round(lat, 2)}_{round(lng, 2)}'
    cached = cache.get(cache_key)
    if cached:
        return cached['station_code'], cached['station_city'], cached['address_text']

    try:
        url = (
            f'https://nominatim.openstreetmap.org/reverse'
            f'?lat={lat}&lon={lng}&format=json&addressdetails=1&accept-language=es&zoom=14'
        )
        resp = requests.get(url, headers={'User-Agent': 'MecaniMovil/1.0'}, timeout=6)
        resp.raise_for_status()
        data = resp.json()

        addr = data.get('address', {})
        comuna = (
            addr.get('suburb') or addr.get('city_district') or
            addr.get('municipality') or addr.get('town') or
            addr.get('village') or ''
        )
        city = addr.get('city') or ''
        province = addr.get('state') or addr.get('region') or ''
        display = data.get('display_name', '')

        address_text = ', '.join(filter(None, [comuna or city, province, 'Chile']))

        station_code, station_city = None, None
        for text_attempt in [comuna, f'{comuna} {city}', city, province, display]:
            if text_attempt and text_attempt.strip():
                station_code, station_city = resolve_station_from_address(text_attempt)
                if station_code:
                    break

        result = {
            'station_code': station_code,
            'station_city': station_city,
            'address_text': address_text,
        }
        cache.set(cache_key, result, 60 * 30)
        return station_code, station_city, address_text

    except Exception as exc:
        logger.error("Error reverse geocoding Nominatim (%s, %s): %s", lat, lng, exc)
        return None, None, None


def resolve_station_from_address(address_text):
    """Resuelve texto de dirección → (station_code, station_city) o (None, None)."""
    if not address_text:
        return None, None

    normalized = normalize_text(address_text)

    for comuna, station_code in COMUNA_TO_STATION.items():
        if normalize_text(comuna) in normalized:
            return station_code, STATION_MAP.get(station_code, comuna)

    for code, city in STATION_MAP.items():
        if normalize_text(city) in normalized:
            return code, city

    return None, None


def _resolve_city_name(lat, lng):
    """Obtiene nombre de ciudad desde coords usando cache de Nominatim si existe."""
    cache_key = f'nominatim_reverse_{round(lat, 2)}_{round(lng, 2)}'
    cached = cache.get(cache_key)
    if cached:
        return cached.get('station_city') or cached.get('address_text', '')

    # Light reverse geocode solo para nombre de ciudad
    try:
        url = (
            f'https://nominatim.openstreetmap.org/reverse'
            f'?lat={lat}&lon={lng}&format=json&addressdetails=1&accept-language=es&zoom=10'
        )
        resp = requests.get(url, headers={'User-Agent': 'MecaniMovil/1.0'}, timeout=4)
        resp.raise_for_status()
        addr = resp.json().get('address', {})
        return (
            addr.get('city') or addr.get('town') or
            addr.get('municipality') or addr.get('suburb') or ''
        )
    except Exception:
        return ''


# ── Helpers ──

def _safe_int(val):
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def determine_climate_condition(weather):
    """Clasifica condición climática para la matriz de desgaste."""
    if not weather:
        return 'normal'

    wmo_code = weather.get('weather_code')
    if wmo_code is not None and wmo_code in WMO_RAIN_CODES:
        return 'rain'

    condition_lower = normalize_text(weather.get('condition', ''))
    rain_keywords = ['lluvia', 'llovizna', 'chubascos', 'tormenta', 'precipita']
    if any(kw in condition_lower for kw in rain_keywords):
        return 'rain'

    temp = weather.get('temperature')
    if temp is not None and temp > 30:
        return 'heat'
    if temp is not None and temp < 5:
        return 'cold'
    return 'normal'


def calculate_component_risk(component_type, climate_cond, telemetry=None):
    """
    Calcula riesgo de conducción para un componente considerando salud + clima.
    Retorna (driving_risk, climate_extra_pct, cw).

    Si la telemetría incluye ``salud_porcentaje`` (motor de salud del vehículo),
    el desgaste base es **solo** ``100 - salud``: mezclar además km restantes / vida
    útil duplicaba señal y podía marcar riesgo ~100 % con salud óptima al 100 %.
    """
    matrix_entry = WEAR_MATRIX.get(component_type)
    if not matrix_entry:
        return 0, 0, 1.0

    cw = 1.0 if climate_cond == 'normal' else matrix_entry.get(climate_cond, 1.0)
    climate_delta = max(0, cw - 1.0)

    if telemetry and telemetry.get('salud_porcentaje') is not None:
        try:
            salud = float(telemetry['salud_porcentaje'])
        except (TypeError, ValueError):
            salud = 0.0
        salud = max(0.0, min(100.0, salud))
        desgaste_base = max(0.0, 100.0 - salud)

        driving_risk = desgaste_base * cw
        climate_extra = desgaste_base * climate_delta

    elif telemetry and telemetry.get('current_odometer', 0) > 0:
        avg_daily_km = telemetry.get('avg_daily_km', 30)
        driving_factor = telemetry.get('driving_profile_factor', 1.0)
        estimated_life_km = telemetry.get('estimated_life_km', 50000)

        distancia_real_dia = avg_daily_km * driving_factor
        vida_remanente = max(estimated_life_km * 0.5, 500)
        base_daily_risk = (distancia_real_dia / vida_remanente) * 100
        driving_risk = base_daily_risk * cw
        climate_extra = base_daily_risk * climate_delta
    else:
        driving_risk = round(climate_delta * 50)
        climate_extra = driving_risk

    driving_risk = min(max(round(driving_risk), 0), 100)
    climate_extra = min(max(round(climate_extra), 0), 100)
    return driving_risk, climate_extra, round(cw, 2)


def _risk_level_and_label(driving_risk, salud=None):
    if salud is not None and salud <= 5:
        return 'critico', 'Requiere cambio inmediato'
    if driving_risk >= 80:
        return 'critico', 'Riesgo alto — evita conducir'
    if driving_risk >= 50:
        return 'alto', 'Precaución al conducir'
    if driving_risk >= 25:
        return 'moderado', 'Riesgo moderado'
    if driving_risk > 0:
        return 'bajo', 'Riesgo bajo'
    return 'optimo', 'Condiciones óptimas'


# ─────────────────────────────────────────────────────────────
# Public prediction pipelines
# ─────────────────────────────────────────────────────────────

def get_prediction_for_coords(lat, lng, vehicle=None, force_refresh=False):
    """Pipeline: coords → Open-Meteo (direct) → predicción."""
    weather = fetch_weather_by_coords(lat, lng, force_refresh=force_refresh)
    if not weather:
        return {
            'available': False,
            'reason': 'No se pudo obtener datos climáticos para tu ubicación.',
        }

    city_name = weather.get('city') or ''
    if not city_name:
        city_name = _resolve_city_name(lat, lng)
        weather['city'] = city_name

    return _build_prediction(weather, vehicle, source='gps', address_info={
        'id': None,
        'direccion': city_name or f'{round(lat, 4)}, {round(lng, 4)}',
        'etiqueta': 'Ubicación actual',
    })


def get_prediction_for_address(address_text, vehicle=None, force_refresh=False):
    """Pipeline: dirección texto → estación → boostr → predicción."""
    station_code, station_city = resolve_station_from_address(address_text)

    if not station_code:
        return {
            'available': False,
            'reason': 'No hay estación meteorológica disponible para esta ubicación.',
        }

    weather = fetch_weather_boostr(station_code, force_refresh=force_refresh)
    if not weather:
        return {
            'available': False,
            'reason': 'No se pudo obtener datos climáticos en este momento.',
        }

    return _build_prediction(weather, vehicle)


def _build_prediction(weather, vehicle, source=None, address_info=None):
    """Construye respuesta de predicción completa a partir de datos climáticos."""
    climate_cond = determine_climate_condition(weather)

    telemetry_data = None
    if vehicle:
        telemetry_data = {
            'avg_daily_km': 30,
            'driving_profile_factor': 1.0,
            'current_odometer': vehicle.kilometraje or 0,
        }

    components = []
    total_risk = 0
    for comp_type, labels in [
        ('frenos', {'name': 'Frenos', 'icon': 'disc'}),
        ('neumaticos', {'name': 'Neumáticos', 'icon': 'wind'}),
        ('bateria', {'name': 'Batería', 'icon': 'zap'}),
        ('refrigerante', {'name': 'Refrigerante', 'icon': 'droplets'}),
    ]:
        comp_telemetry = None
        if telemetry_data and vehicle:
            comp_telemetry = _enrich_telemetry_for_component(telemetry_data, vehicle, comp_type)

        driving_risk, climate_extra, cw = calculate_component_risk(
            comp_type, climate_cond, comp_telemetry
        )
        reason = _build_reason(comp_type, climate_cond, weather)

        salud_val = None
        if comp_telemetry and comp_telemetry.get('salud_porcentaje') is not None:
            salud_val = comp_telemetry['salud_porcentaje']

        risk_level, risk_label = _risk_level_and_label(driving_risk, salud_val)

        comp_entry = {
            'type': comp_type,
            'name': labels['name'],
            'icon': labels['icon'],
            'driving_risk': driving_risk,
            'wear_increase': climate_extra,
            'risk_level': risk_level,
            'risk_label': risk_label,
            'coefficient': cw,
            'reason': reason,
        }
        if salud_val is not None:
            comp_entry['salud_actual'] = round(salud_val, 1)
            comp_entry['nivel_alerta'] = comp_telemetry.get('nivel_alerta', '')
            comp_entry['km_restantes'] = comp_telemetry.get('km_estimados_restantes', 0)

        components.append(comp_entry)
        total_risk += driving_risk

    avg_risk = round(total_risk / len(components)) if components else 0
    overall_level, overall_label = _risk_level_and_label(avg_risk)
    now = timezone.localtime()

    result = {
        'available': True,
        'weather': {
            'source': weather.get('source', 'unknown'),
            'station_code': weather.get('station_code'),
            'city': weather.get('city', ''),
            'temperature': weather['temperature'],
            'humidity': weather['humidity'],
            'condition': weather['condition'],
            'updated_at': weather.get('updated_at', ''),
            'report_age_min': weather.get('report_age_min'),
        },
        'climate_condition': climate_cond,
        'total_wear_risk': avg_risk,
        'risk_level': overall_level,
        'risk_label': overall_label,
        'components': components,
        'ai_insight': AI_INSIGHTS.get(climate_cond, AI_INSIGHTS['normal']),
        'fetched_at': now.strftime('%H:%M'),
        'fetched_at_iso': now.isoformat(),
    }

    if source:
        result['source'] = source
    if address_info:
        result['address'] = address_info

    return result


def _enrich_telemetry_for_component(base_telemetry, vehicle, comp_type):
    """
    Enriquece la telemetría con datos reales de salud del componente.

    Usa WEATHER_SLUG_GROUPS + slug normalizado (guiones, minúsculas) y
    WEATHER_SLUG_EXCLUDE para no mezclar fluidos/embrague con frenos de fricción.
    Respaldo por nombre solo si no hay slug excluido.
    Varios candidatos: salud = promedio; km/vida del peor caso.
    """
    try:
        from mecanimovilapp.apps.vehiculos.models_health import ComponenteSaludVehiculo

        comp_qs = (
            ComponenteSaludVehiculo.objects
            .filter(vehiculo=vehicle)
            .select_related('componente')
        )

        priority_slugs = WEATHER_SLUG_GROUPS.get(comp_type, frozenset())
        keywords = {
            'frenos': ['pastilla', 'balata', 'discos de freno', 'disco de freno', 'disco freno'],
            'neumaticos': ['neum', 'goma', 'llanta', 'tire', 'cubierta'],
            'bateria': ['bater', 'battery'],
            'refrigerante': ['refrige', 'coolant', 'anticongelante'],
        }.get(comp_type, [])

        slug_matches = []
        name_matches = []
        for comp in comp_qs:
            if not comp.componente or comp.salud_porcentaje is None:
                continue
            slug = _norm_component_slug(comp.componente.slug)
            if slug in WEATHER_SLUG_EXCLUDE:
                continue
            name_low = (comp.componente.nombre or '').lower()

            if slug in priority_slugs:
                slug_matches.append(comp)
            elif any(kw in name_low for kw in keywords):
                name_matches.append(comp)

        candidates = slug_matches if slug_matches else name_matches
        if not candidates:
            return base_telemetry

        worst = min(candidates, key=lambda c: float(c.salud_porcentaje))
        avg_salud = sum(float(c.salud_porcentaje) for c in candidates) / len(candidates)

        enriched = dict(base_telemetry)
        enriched['salud_porcentaje'] = round(avg_salud, 1)
        enriched['km_ultimo_servicio'] = worst.km_ultimo_servicio or 0
        enriched['km_estimados_restantes'] = worst.km_estimados_restantes or 0
        enriched['vida_util_proyectada'] = worst.vida_util_proyectada or 0
        enriched['nivel_alerta'] = worst.nivel_alerta
        return enriched

    except Exception as exc:
        logger.debug("No se pudo enriquecer telemetría para %s: %s", comp_type, exc)

    return base_telemetry


def _build_reason(comp_type, climate_cond, weather):
    """Genera razón legible para desgaste de un componente."""
    temp = weather.get('temperature')
    humidity = weather.get('humidity')

    reasons = {
        'rain': {
            'frenos': f'Humedad al {humidity}% reduce adherencia de pastillas',
            'neumaticos': f'Lluvia: baja tracción asfáltica ({humidity}% humedad)',
            'bateria': 'Condición de lluvia sin impacto significativo',
            'refrigerante': 'Condición de lluvia sin impacto significativo',
        },
        'heat': {
            'frenos': f'Calor ({temp}°C) incrementa temperatura del disco',
            'neumaticos': f'Asfalto caliente ({temp}°C) acelera desgaste del caucho',
            'bateria': f'Alta temperatura ({temp}°C) reduce vida del electrolito',
            'refrigerante': f'El motor exige más refrigeración a {temp}°C',
        },
        'cold': {
            'frenos': f'Baja temperatura ({temp}°C) sin impacto mayor',
            'neumaticos': f'Frío ({temp}°C) endurece el caucho y reduce agarre',
            'bateria': f'Baja temperatura ({temp}°C) reduce capacidad de la batería',
            'refrigerante': f'El refrigerante es exigido a {temp}°C',
        },
        'normal': {
            'frenos': 'Condiciones óptimas',
            'neumaticos': 'Condiciones óptimas',
            'bateria': 'Condiciones óptimas',
            'refrigerante': 'Condiciones óptimas',
        },
    }
    return reasons.get(climate_cond, reasons['normal']).get(comp_type, 'Sin datos')
