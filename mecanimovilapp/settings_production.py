"""
Configuración de Django para producción en Render
Este archivo extiende settings.py con configuraciones específicas para producción.
"""

import os
from .settings import *

# ============================================
# CONFIGURACIÓN BASE PARA PRODUCCIÓN
# ============================================
DEBUG = False

# Asistente IA en creación de solicitudes (Render: AGENDAMIENTO_IA_ASISTIDO en render.yaml)
AGENDAMIENTO_IA_ASISTIDO = os.environ.get(
    'AGENDAMIENTO_IA_ASISTIDO', 'False'
).lower() in ('true', '1', 'yes')

AGENDAMIENTO_IA_SEMANTICO_ENABLED = os.environ.get(
    'AGENDAMIENTO_IA_SEMANTICO_ENABLED', 'True'
).lower() in ('true', '1', 'yes')
AGENDAMIENTO_IA_SEMANTICO_PROVEEDOR = os.environ.get(
    'AGENDAMIENTO_IA_SEMANTICO_PROVEEDOR', 'lexico'
)
AGENDAMIENTO_IA_SEMANTICO_TIMEOUT = int(os.environ.get('AGENDAMIENTO_IA_SEMANTICO_TIMEOUT', '15'))
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-3.1-flash-lite')
GEMINI_LIMITE_TOKENS_MENSUAL = int(os.environ.get('GEMINI_LIMITE_TOKENS_MENSUAL', '1000000'))
ASISTENTE_DIAGNOSTICO_IA_ENABLED = os.environ.get(
    'ASISTENTE_DIAGNOSTICO_IA_ENABLED', 'False'
).lower() in ('true', '1', 'yes')
ASISTENTE_DIAGNOSTICO_GEMINI_MODEL = os.environ.get(
    'ASISTENTE_DIAGNOSTICO_GEMINI_MODEL',
    'gemini-3.1-flash-lite',
)
ASISTENTE_DIAGNOSTICO_IA_TIMEOUT = int(os.environ.get('ASISTENTE_DIAGNOSTICO_IA_TIMEOUT', '12'))
GEMINI_RETRY_MAX = int(os.environ.get('GEMINI_RETRY_MAX', '2'))
HUGGINGFACE_API_TOKEN = os.environ.get('HUGGINGFACE_API_TOKEN', '')
HUGGINGFACE_MODEL = os.environ.get('HUGGINGFACE_MODEL', 'Qwen/Qwen2.5-1.5B-Instruct')
OLLAMA_BASE_URL = os.environ.get('OLLAMA_BASE_URL', '')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'llama3.2')

# Configuración de hosts permitidos para producción
# Se configura desde variable de entorno ALLOWED_HOSTS
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '').split(',')
ALLOWED_HOSTS = [host.strip() for host in ALLOWED_HOSTS if host.strip()]

# Agregar hosts de Render automáticamente
RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

# ============================================
# CONFIGURACIÓN DE CORS PARA PRODUCCIÓN
# ============================================
# IMPORTANTE: Sobrescribir completamente la configuración de CORS de settings.py
# Permitir todos los orígenes si está configurado (útil para apps móviles)
CORS_ALLOW_ALL_ORIGINS = os.environ.get('CORS_ALLOW_ALL_ORIGINS', 'False').lower() == 'true'

# Configurar CORS_ALLOWED_ORIGINS según la configuración
# SIEMPRE sobrescribir para evitar conflictos con settings.py
if CORS_ALLOW_ALL_ORIGINS:
    # Si se permite todos los orígenes, definir lista vacía explícitamente
    # django-cors-headers usará CORS_ALLOW_ALL_ORIGINS cuando esta lista esté vacía
    CORS_ALLOWED_ORIGINS = []
else:
    # Si no se permite todos los orígenes, usar la lista específica
    # Leer directamente de os.environ para evitar conflictos con config() de settings.py
    cors_origins_str = os.environ.get(
        'CORS_ALLOWED_ORIGINS',
        'https://mecanimovilapp.com,https://app.mecanimovil.com,https://proveedores.mecanimovil.com'
    )
    # Filtrar valores inválidos como 'True', 'False', etc.
    CORS_ALLOWED_ORIGINS = [
        origin.strip() 
        for origin in cors_origins_str.split(',') 
        if origin.strip() and origin.strip().lower() not in ('true', 'false') and '://' in origin.strip()
    ]

# ============================================
# CONFIGURACIÓN DE SEGURIDAD
# ============================================
SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'True').lower() == 'true'
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# HSTS (HTTP Strict Transport Security)
SECURE_HSTS_SECONDS = 31536000  # 1 año
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Protección contra XSS y clickjacking
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# Cookies seguras
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True

# Proxy headers (para Render)
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True

# ============================================
# CONFIGURACIÓN DE BASE DE DATOS
# ============================================
import dj_database_url

DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    # conn_max_age=0: en Render/ASGI las conexiones largas suelen romperse (proxy PG,
    # límites de conexión, reinicios). Cerrar al terminar cada request evita 503 en
    # ráfagas por conexiones zombie; el costo es un connect extra por request.
    db_config = dj_database_url.config(
        default=DATABASE_URL,
        engine='django.contrib.gis.db.backends.postgis',
        conn_max_age=0,
        conn_health_checks=True,
    )
    # Agregar opciones adicionales para mejorar estabilidad
    db_config['OPTIONS'] = {
        'connect_timeout': 10,  # Timeout de conexión inicial
        'keepalives': 1,  # Habilitar keepalives TCP
        'keepalives_idle': 30,  # Enviar keepalive después de 30s de inactividad
        'keepalives_interval': 10,  # Intervalo entre keepalives
        'keepalives_count': 5,  # Número de keepalives antes de considerar la conexión muerta
    }
    DATABASES = {
        'default': db_config
    }

# ============================================
# CONFIGURACIÓN DE REDIS
# ============================================
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379')

# Separar workloads en Redis DBs distintas para evitar que LRU evicte
# claves de un workload cuando otro presiona memoria:
#   DB 0 = Channel Layer (mensajes WS efímeros)
#   DB 1 = Django Cache (health data, respuestas)
#   DB 2 = Celery Broker + Results (tareas)
REDIS_CHANNELS_URL = os.environ.get('REDIS_CHANNELS_URL', f'{REDIS_URL}/0')
REDIS_CACHE_URL = os.environ.get('REDIS_CACHE_URL', f'{REDIS_URL}/1')
REDIS_CELERY_URL = os.environ.get('REDIS_CELERY_URL', f'{REDIS_URL}/2')

# Django Channels con Redis
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [REDIS_CHANNELS_URL],
            "capacity": 1500,
            "expiry": 60,
            "group_expiry": 86400,
        },
    },
}

# Cache con Redis
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': REDIS_CACHE_URL,
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'IGNORE_EXCEPTIONS': True,
            'SOCKET_CONNECT_TIMEOUT': 5,
            'SOCKET_TIMEOUT': 5,
            'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',
        },
        'KEY_PREFIX': 'mecanimovil',
        'TIMEOUT': 300,
    }
}

# Celery con Redis
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', REDIS_CELERY_URL)
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', REDIS_CELERY_URL)

# ============================================
# CONFIGURACIÓN DE ARCHIVOS ESTÁTICOS
# ============================================
# WhiteNoise para servir archivos estáticos.
# Se usa STORAGES (Django 4.2+). STATICFILES_STORAGE está deprecated y
# es mutuamente exclusivo con STORAGES — NO definir ambos al mismo tiempo.
# El backend 'staticfiles' se hereda del STORAGES definido en settings.py.
# Si el dict STORAGES ya viene con whitenoise en 'staticfiles', no hay que tocarlo.

# ============================================
# OPTIMIZACIÓN: COMPRESIÓN GZIP DE RESPUESTAS
# ============================================
# Usamos GZipMiddleware nativo de Django (incluido en Django, no requiere paquetes externos)
# Comprime automáticamente respuestas > 200 bytes cuando el cliente acepta gzip
# IMPORTANTE: Debe ir DESPUÉS de WhiteNoise pero ANTES de CommonMiddleware
# Orden correcto: Security -> WhiteNoise -> Compression -> Sessions -> CORS -> Common -> ...
# Sobrescribir MIDDLEWARE para incluir compresión
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.gzip.GZipMiddleware',  # Compresión Gzip nativa de Django
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    # CsrfViewMiddleware removed: la API REST usa TokenAuthentication.
    # CSRF no aporta seguridad aquí y bloqueaba peticiones cross-origin
    # legítimas del web client (Vercel → onrender) bajo Daphne/ASGI.
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'mecanimovilapp.middleware.vehiculo_activo.VehiculoActivoMiddleware',
]

# Configuración de GZipMiddleware (opcional, los defaults son suficientes)
# GZipMiddleware comprime automáticamente:
# - Respuestas > 200 bytes (GZIP_MIN_LENGTH = 200)
# - Solo content-types que no estén en GZIP_EXCLUDE_CONTENT_TYPES
# - Solo si el cliente envía Accept-Encoding: gzip
GZIP_MIN_LENGTH = 200  # Mínimo tamaño en bytes para comprimir (default: 200)

# ============================================
# CONFIGURACIÓN DE MERCADO PAGO
# ============================================
MERCADOPAGO_MODE = os.environ.get('MERCADOPAGO_MODE', 'production')
MERCADOPAGO_ACCESS_TOKEN = os.environ.get('MERCADOPAGO_ACCESS_TOKEN', '')
MERCADOPAGO_WEBHOOK_SECRET = os.environ.get('MERCADOPAGO_WEBHOOK_SECRET', '')
MERCADOPAGO_PUBLIC_KEY_PROD = os.environ.get('MERCADOPAGO_PUBLIC_KEY_PROD', '')
MERCADOPAGO_PUBLIC_KEY = MERCADOPAGO_PUBLIC_KEY_PROD

# MercadoLibre API (búsqueda de avisos /sites/MLC/search). Obligatorio desde ~2025.
# Sin token, Render recibe 403 + página "Seguridad".
MERCADOLIBRE_ACCESS_TOKEN = os.environ.get('MERCADOLIBRE_ACCESS_TOKEN', '')
MERCADOLIBRE_REFRESH_TOKEN = os.environ.get('MERCADOLIBRE_REFRESH_TOKEN', '')
MERCADOLIBRE_CLIENT_ID = os.environ.get('MERCADOLIBRE_CLIENT_ID', '')
MERCADOLIBRE_CLIENT_SECRET = os.environ.get('MERCADOLIBRE_CLIENT_SECRET', '')
# Proxy residencial opcional para Playwright (ej. http://user:pass@host:port)
PLAYWRIGHT_PROXY = os.environ.get('PLAYWRIGHT_PROXY', '')

# ============================================
# CONFIGURACIÓN DE EMAIL
# ============================================
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@mecanimovil.com')

# ============================================
# LOGGING PARA PRODUCCIÓN
# ============================================
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'channels': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
        'celery': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
        'mecanimovilapp': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}

# ============================================
# OPTIMIZACIONES DE CELERY PARA PRODUCCIÓN
# ============================================
# Optimizar conexiones usando pool 'solo' (threads) en lugar de 'prefork' (procesos)
# Esto mantiene 2 workers concurrentes pero con menos conexiones BD (1 conexión compartida)
CELERY_WORKER_CONCURRENCY = int(os.environ.get('CELERY_WORKER_CONCURRENCY', 2))  # Mantener 2 threads para procesar tareas críticas
CELERY_WORKER_POOL = 'solo'  # Usar pool 'solo' (thread) en lugar de 'prefork' (proceso) para reducir conexiones
CELERY_TASK_COMPRESSION = 'gzip'
CELERY_BROKER_POOL_LIMIT = 10
CELERY_TASK_IGNORE_RESULT = False
CELERY_TASK_STORE_EAGER_RESULT = True
CELERY_TASK_ALWAYS_EAGER = False  # No ejecutar sincrónicamente
CELERY_TASK_EAGER_PROPAGATES = True

# ============================================
# WEB PUSH (VAPID / RFC 8030)
# ============================================
# Generar con: python -c "from py_vapid import Vapid; ..."
# Ver README o documentacion interna para instrucciones de generacion.
VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY', '')
VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY', '')
VAPID_EMAIL = os.environ.get('VAPID_EMAIL', 'mailto:admin@mecanimovil.com')
