# Esto asegura que la app de Celery se cargue cuando Django inicie
# Solo importar si celery está instalado
try:
    from .celery import app as celery_app
    __all__ = ('celery_app',)
except ImportError:
    # Celery no está instalado, continuar sin él
    __all__ = ()

