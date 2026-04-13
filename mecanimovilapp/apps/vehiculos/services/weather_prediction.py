"""
Servicio de predicción de desgaste vehicular basado en clima.
Consume la API pública de boostr.cl para obtener meteorología
y aplica el algoritmo IA-Weather-Telemetry de Mecanimóvil.
"""
import logging
import requests
from datetime import datetime
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

WEATHER_API_URL = "https://api.boostr.cl/weather/{code}.json"
WEATHER_CACHE_TTL = 60 * 5  # 5 minutos — balance between freshness and not saturating API

STATION_MAP = {
    'SCFA': 'Antofagasta',
    'SCAR': 'Arica',
    'SCBA': 'Balmaceda',
    'SCCF': 'Calama',
    'SCAT': 'Caldera',
    'SCCH': 'Chillán',
    'SCIE': 'Concepción',
    'SCCY': 'Coyhaique',
    'SCIC': 'Curicó',
    'SCFT': 'Futaleufú',
    'SCDA': 'Iquique',
    'SCIP': 'Isla de Pascua',
    'SCSE': 'La Serena',
    'SCMK': 'Melinka',
    'SCJO': 'Osorno',
    'SCTE': 'Puerto Montt',
    'SCCI': 'Punta Arenas',
    'SCON': 'Quellón',
    'SCSN': 'San Antonio',
    'SCQN': 'Santiago',
    'SCEL': 'Santiago',
    'SCQP': 'Temuco',
    'SCVD': 'Valdivia',
    'SCVM': 'Viña del Mar',
    'SCIR': 'Juan Fernández',
    'SCRM': 'Antártica',
    'SCGZ': 'Puerto Williams',
    'SCFM': 'Porvenir',
    'SCRG': 'Rancagua',
    'SCGE': 'Los Ángeles',
    'SCTN': 'Chaitén',
    'SCCC': 'Chile Chico',
    'SCHR': 'Cochrane',
    'SCNT': 'Puerto Natales',
}

# Mapeo de comunas → código de estación.
# Las comunas se normalizan a minúsculas sin tildes para matching flexible.
COMUNA_TO_STATION = {
    # Arica y Parinacota
    'arica': 'SCAR', 'putre': 'SCAR', 'camarones': 'SCAR',
    'general lagos': 'SCAR',
    # Tarapacá
    'iquique': 'SCDA', 'alto hospicio': 'SCDA', 'pozo almonte': 'SCDA',
    'pica': 'SCDA', 'huara': 'SCDA',
    # Antofagasta
    'antofagasta': 'SCFA', 'mejillones': 'SCFA', 'taltal': 'SCFA',
    'tocopilla': 'SCFA', 'maria elena': 'SCFA', 'sierra gorda': 'SCFA',
    'calama': 'SCCF', 'san pedro de atacama': 'SCCF', 'ollague': 'SCCF',
    'caldera': 'SCAT', 'copiapo': 'SCAT', 'tierra amarilla': 'SCAT',
    'diego de almagro': 'SCAT', 'chanaral': 'SCAT', 'freirina': 'SCAT',
    'vallenar': 'SCAT', 'huasco': 'SCAT',
    # Coquimbo
    'la serena': 'SCSE', 'coquimbo': 'SCSE', 'andacollo': 'SCSE',
    'la higuera': 'SCSE', 'ovalle': 'SCSE', 'monte patria': 'SCSE',
    'combarbala': 'SCSE', 'punitaqui': 'SCSE', 'rio hurtado': 'SCSE',
    'illapel': 'SCSE', 'salamanca': 'SCSE', 'los vilos': 'SCSE',
    'canela': 'SCSE', 'vicuna': 'SCSE', 'paiguano': 'SCSE',
    # Valparaíso
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
    # Metropolitana
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
    # O'Higgins
    'rancagua': 'SCRG', 'machali': 'SCRG', 'graneros': 'SCRG',
    'san fernando': 'SCRG', 'santa cruz': 'SCRG', 'rengo': 'SCRG',
    'requinoa': 'SCRG', 'olivar': 'SCRG', 'coinco': 'SCRG',
    'coltauco': 'SCRG', 'donihue': 'SCRG', 'las cabras': 'SCRG',
    'peumo': 'SCRG', 'pichidegua': 'SCRG', 'mostazal': 'SCRG',
    'codegua': 'SCRG', 'chimbarongo': 'SCRG', 'nancagua': 'SCRG',
    'placilla': 'SCRG', 'chepica': 'SCRG', 'lolol': 'SCRG',
    'pichilemu': 'SCRG', 'litueche': 'SCRG', 'marchihue': 'SCRG',
    'navidad': 'SCRG', 'la estrella': 'SCRG', 'paredones': 'SCRG',
    # Maule
    'curico': 'SCIC', 'talca': 'SCIC', 'linares': 'SCIC',
    'cauquenes': 'SCIC', 'constitucion': 'SCIC', 'molina': 'SCIC',
    'sagrada familia': 'SCIC', 'teno': 'SCIC', 'romeral': 'SCIC',
    'hualane': 'SCIC', 'licanten': 'SCIC', 'vichuquen': 'SCIC',
    'san clemente': 'SCIC', 'maule': 'SCIC', 'pelarco': 'SCIC',
    'rio claro': 'SCIC', 'pencahue': 'SCIC', 'curepto': 'SCIC',
    'san javier': 'SCIC', 'villa alegre': 'SCIC', 'yerbas buenas': 'SCIC',
    'colbun': 'SCIC', 'longavi': 'SCIC', 'parral': 'SCIC',
    'retiro': 'SCIC', 'pelluhue': 'SCIC', 'chanco': 'SCIC',
    # Ñuble
    'chillan': 'SCCH', 'chillan viejo': 'SCCH', 'san carlos': 'SCCH',
    'bulnes': 'SCCH', 'coihueco': 'SCCH', 'el carmen': 'SCCH',
    'ninhue': 'SCCH', 'pinto': 'SCCH', 'quillon': 'SCCH',
    'quirihue': 'SCCH', 'ranquil': 'SCCH', 'san fabian': 'SCCH',
    'san ignacio': 'SCCH', 'san nicolas': 'SCCH', 'treguaco': 'SCCH',
    'yungay': 'SCCH', 'cobquecura': 'SCCH', 'portezuelo': 'SCCH',
    'coelemu': 'SCCH', 'pemuco': 'SCCH',
    # Biobío
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
    # Araucanía
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
    # Los Ríos
    'valdivia': 'SCVD', 'corral': 'SCVD', 'lanco': 'SCVD',
    'mariquina': 'SCVD', 'mafil': 'SCVD', 'los lagos': 'SCVD',
    'panguipulli': 'SCVD', 'la union': 'SCVD', 'rio bueno': 'SCVD',
    'paillaco': 'SCVD', 'futrono': 'SCVD', 'lago ranco': 'SCVD',
    # Los Lagos
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
    # Aysén
    'coyhaique': 'SCCY', 'aysen': 'SCCY', 'cisnes': 'SCCY',
    'guaitecas': 'SCMK', 'melinka': 'SCMK',
    'chile chico': 'SCCC', 'rio ibanez': 'SCCC',
    'cochrane': 'SCHR', 'ohiggins': 'SCHR', 'tortel': 'SCHR',
    'lago verde': 'SCCY',
    # Magallanes
    'punta arenas': 'SCCI', 'rio verde': 'SCCI', 'laguna blanca': 'SCCI',
    'san gregorio': 'SCCI', 'cabo de hornos': 'SCCI',
    'puerto natales': 'SCNT', 'torres del paine': 'SCNT',
    'porvenir': 'SCFM', 'primavera': 'SCFM', 'timaukel': 'SCFM',
    'puerto williams': 'SCGZ', 'antartica': 'SCRM',
}


# Matriz de coeficientes de desgaste según algoritmo IA-Weather-Telemetry
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


def normalize_text(text):
    """Normaliza texto eliminando tildes y convirtiendo a minúsculas."""
    import unicodedata
    if not text:
        return ''
    nfkd = unicodedata.normalize('NFKD', text.lower().strip())
    return ''.join(c for c in nfkd if not unicodedata.combining(c))


def resolve_station_from_coords(lat, lng):
    """
    Convierte coordenadas GPS → estación meteorológica usando Nominatim.
    Retorna (station_code, station_city, address_text) o (None, None, None).
    """
    cache_key = f'nominatim_reverse_{round(lat, 2)}_{round(lng, 2)}'
    cached = cache.get(cache_key)
    if cached:
        return cached['station_code'], cached['station_city'], cached['address_text']

    try:
        # zoom=14 = nivel comuna/suburb (zoom=10 devuelve solo "Santiago" para toda la RM)
        url = (
            f'https://nominatim.openstreetmap.org/reverse'
            f'?lat={lat}&lon={lng}&format=json&addressdetails=1&accept-language=es&zoom=14'
        )
        resp = requests.get(url, headers={'User-Agent': 'MecaniMovil/1.0'}, timeout=6)
        resp.raise_for_status()
        data = resp.json()

        addr = data.get('address', {})

        # En Chile, la "comuna" aparece en suburb para Nominatim zoom=14.
        # Intentar suburb primero (más específico), luego city_district, luego city.
        comuna = (
            addr.get('suburb') or
            addr.get('city_district') or
            addr.get('municipality') or
            addr.get('town') or
            addr.get('village') or
            ''
        )
        # city suele ser "Santiago" genérico en la RM — solo usar si no hay comuna
        city = addr.get('city') or ''
        province = addr.get('state') or addr.get('region') or ''
        display = data.get('display_name', '')

        address_text = ', '.join(filter(None, [comuna or city, province, 'Chile']))

        # Intentar resolver estación primero solo con la comuna
        station_code, station_city = None, None
        if comuna:
            station_code, station_city = resolve_station_from_address(comuna)

        # Si no matchea la comuna, probar comuna + city
        if not station_code and comuna and city and comuna != city:
            station_code, station_city = resolve_station_from_address(f'{comuna} {city}')

        # Probar con city sola
        if not station_code and city:
            station_code, station_city = resolve_station_from_address(city)

        # Probar con province
        if not station_code and province:
            station_code, station_city = resolve_station_from_address(province)

        # Último recurso: display_name completo
        if not station_code:
            station_code, station_city = resolve_station_from_address(display)

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
    """
    Intenta encontrar la estación meteorológica más cercana
    a partir del texto de la dirección del usuario.
    Retorna (station_code, station_city) o (None, None).
    """
    if not address_text:
        return None, None

    normalized = normalize_text(address_text)

    # Búsqueda exacta en comunas mapeadas
    for comuna, station_code in COMUNA_TO_STATION.items():
        if normalize_text(comuna) in normalized:
            return station_code, STATION_MAP.get(station_code, comuna)

    # Búsqueda en nombres de estaciones
    for code, city in STATION_MAP.items():
        if normalize_text(city) in normalized:
            return code, city

    return None, None


def fetch_weather(station_code, force_refresh=False):
    """
    Consulta la API de boostr.cl con cache de 5 min.
    Retorna dict con temperature, humidity, condition, city o None.
    """
    cache_key = f'boostr_weather_{station_code}'
    if not force_refresh:
        cached = cache.get(cache_key)
        if cached:
            return cached

    try:
        url = WEATHER_API_URL.format(code=station_code)
        response = requests.get(url, headers={'accept': 'application/json'}, timeout=8)
        response.raise_for_status()
        payload = response.json()

        if payload.get('status') != 'success' or not payload.get('data'):
            logger.warning("API boostr respuesta inesperada para %s: %s", station_code, payload)
            return None

        data = payload['data']
        raw_updated_at = data.get('updated_at', '')
        report_age_min = _calc_report_age_minutes(raw_updated_at)

        result = {
            'station_code': station_code,
            'city': data.get('city', ''),
            'temperature': _safe_int(data.get('temperature')),
            'humidity': _safe_int(data.get('humidity')),
            'condition': data.get('condition', ''),
            'updated_at': raw_updated_at,
            'report_age_min': report_age_min,
        }
        cache.set(cache_key, result, WEATHER_CACHE_TTL)
        return result
    except requests.RequestException as exc:
        logger.error("Error consultando API boostr (%s): %s", station_code, exc)
        return None


def _safe_int(val):
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _calc_report_age_minutes(updated_at_str):
    """
    Calcula cuántos minutos han pasado desde el ciclo SYNOP reportado por boostr.
    updated_at_str viene en formato "HH:MM:SS" en UTC (la API boostr usa UTC).
    Retorna entero de minutos o None si no se puede parsear.
    """
    if not updated_at_str:
        return None
    try:
        now_utc = timezone.now()  # siempre UTC cuando USE_TZ=True
        h, m, s = (int(x) for x in updated_at_str.split(':'))
        report_dt = now_utc.replace(hour=h, minute=m, second=s, microsecond=0)
        # Si la hora del reporte es futura respecto a ahora (UTC), pertenece al día anterior
        if report_dt > now_utc:
            report_dt -= timezone.timedelta(days=1)
        delta_min = int((now_utc - report_dt).total_seconds() / 60)
        return delta_min
    except Exception:
        return None


def determine_climate_condition(weather):
    """Clasifica la condición climática para seleccionar columna de la matriz."""
    if not weather:
        return 'normal'

    condition_lower = normalize_text(weather.get('condition', ''))
    temp = weather.get('temperature')

    rain_keywords = ['lluvia', 'llovizna', 'chubascos', 'tormenta', 'precipita']
    is_raining = any(kw in condition_lower for kw in rain_keywords)

    if is_raining:
        return 'rain'
    if temp is not None and temp > 30:
        return 'heat'
    if temp is not None and temp < 5:
        return 'cold'
    return 'normal'


def calculate_component_risk(component_type, climate_cond, telemetry=None):
    """
    Calcula riesgo de conducción para un componente considerando salud + clima.

    Retorna (driving_risk, climate_extra_pct, cw):
    - driving_risk: 0..100 — riesgo total de conducir hoy con este componente.
      Basado en desgaste actual del componente, amplificado por clima.
    - climate_extra_pct: 0..100 — cuántos puntos EXTRAS agrega el clima.
    - cw: coeficiente climático crudo.

    Lógica:
      desgaste_base = 100 - salud (cuánto se ha gastado)
      driving_risk = desgaste_base * cw (el clima amplifica el riesgo existente)
      climate_extra = desgaste_base * (cw - 1.0) (solo la parte que agrega el clima)

    Ejemplos (neumáticos, heat cw=1.5):
      salud=0%  → desgaste=100, risk=100*1.5=150→100, extra=100*0.5=50
      salud=80% → desgaste=20,  risk=20*1.5=30,       extra=20*0.5=10
      salud=0%  normal cw=1.0 → risk=100*1.0=100,     extra=0
      salud=100% heat  cw=1.5 → risk=0*1.5=0,         extra=0
    """
    matrix_entry = WEAR_MATRIX.get(component_type)
    if not matrix_entry:
        return 0, 0, 1.0

    if climate_cond == 'normal':
        cw = 1.0
    else:
        cw = matrix_entry.get(climate_cond, 1.0)

    climate_delta = max(0, cw - 1.0)

    if telemetry and telemetry.get('salud_porcentaje') is not None:
        salud = telemetry['salud_porcentaje']
        desgaste_base = max(0, 100 - salud)

        # Si hay km restantes reales, ponderar desgaste con urgencia km
        km_restantes = telemetry.get('km_estimados_restantes', 0)
        vida_util = telemetry.get('vida_util_proyectada', 0)
        if vida_util > 0 and km_restantes > 0:
            km_desgaste = max(0, 100 - (km_restantes / vida_util * 100))
            desgaste_base = (desgaste_base * 0.6) + (km_desgaste * 0.4)

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
    """
    Genera nivel semántico y texto claro para el usuario.
    Evita que "100%" se interprete como bueno — explicita que es peligro.
    """
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


def get_prediction_for_coords(lat, lng, vehicle=None, force_refresh=False):
    """
    Pipeline completo a partir de coordenadas GPS: coords → estación → clima → predicción.
    """
    station_code, station_city, address_text = resolve_station_from_coords(lat, lng)

    if not station_code:
        return {
            'available': False,
            'reason': 'No hay estación meteorológica disponible para tu ubicación GPS.',
        }

    weather = fetch_weather(station_code, force_refresh=force_refresh)
    if not weather:
        return {
            'available': False,
            'reason': 'No se pudo obtener datos climáticos en este momento.',
        }

    climate_cond = determine_climate_condition(weather)

    telemetry_data = None
    if vehicle:
        odometer = vehicle.kilometraje or 0
        telemetry_data = {
            'avg_daily_km': 30,
            'driving_profile_factor': 1.0,
            'current_odometer': odometer,
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

    return {
        'available': True,
        'source': 'gps',
        'weather': {
            'station_code': weather['station_code'],
            'city': weather['city'],
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
        'address': {
            'id': None,
            'direccion': address_text,
            'etiqueta': 'Ubicación actual',
        },
    }


def get_prediction_for_address(address_text, vehicle=None, force_refresh=False):
    """
    Pipeline completo: dirección → estación → clima → predicción.
    Retorna dict listo para la UI.
    """
    station_code, station_city = resolve_station_from_address(address_text)

    if not station_code:
        return {
            'available': False,
            'reason': 'No hay estación meteorológica disponible para esta ubicación.',
        }

    weather = fetch_weather(station_code, force_refresh=force_refresh)
    if not weather:
        return {
            'available': False,
            'reason': 'No se pudo obtener datos climáticos en este momento.',
        }

    climate_cond = determine_climate_condition(weather)

    telemetry_data = None
    if vehicle:
        odometer = vehicle.kilometraje or 0
        telemetry_data = {
            'avg_daily_km': 30,
            'driving_profile_factor': 1.0,
            'current_odometer': odometer,
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
            comp_telemetry = _enrich_telemetry_for_component(
                telemetry_data, vehicle, comp_type
            )

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
    api_updated = weather.get('updated_at', '')

    return {
        'available': True,
        'weather': {
            'station_code': weather['station_code'],
            'city': weather['city'],
            'temperature': weather['temperature'],
            'humidity': weather['humidity'],
            'condition': weather['condition'],
            'updated_at': api_updated,
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


def _enrich_telemetry_for_component(base_telemetry, vehicle, comp_type):
    """Enriquece la telemetría con datos reales de salud del componente."""
    try:
        from mecanimovilapp.apps.vehiculos.models_health import ComponenteSaludVehiculo

        comp_qs = ComponenteSaludVehiculo.objects.filter(
            vehiculo=vehicle
        ).select_related('componente')

        keyword_map = {
            'frenos': ['freno', 'fren', 'brake', 'pastilla'],
            'neumaticos': ['neum', 'goma', 'llanta', 'tire', 'cubierta'],
            'bateria': ['bater', 'battery'],
            'refrigerante': ['refrige', 'coolant', 'anticongelante'],
        }

        keywords = keyword_map.get(comp_type, [])
        for comp in comp_qs:
            name_lower = (comp.componente.nombre or '').lower()
            if any(kw in name_lower for kw in keywords):
                enriched = dict(base_telemetry)
                enriched['salud_porcentaje'] = comp.salud_porcentaje
                enriched['km_ultimo_servicio'] = comp.km_ultimo_servicio or 0
                enriched['km_estimados_restantes'] = comp.km_estimados_restantes or 0
                enriched['vida_util_proyectada'] = comp.vida_util_proyectada or 0
                enriched['nivel_alerta'] = comp.nivel_alerta
                return enriched
    except Exception as exc:
        logger.debug("No se pudo enriquecer telemetría para %s: %s", comp_type, exc)

    return base_telemetry


def _build_reason(comp_type, climate_cond, weather):
    """Genera una razón legible para el desgaste de un componente."""
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
