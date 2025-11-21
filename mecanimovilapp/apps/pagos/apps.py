"""
Configuración de la app de pagos
"""
from django.apps import AppConfig


class PagosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mecanimovilapp.apps.pagos'
    verbose_name = 'Pagos'

