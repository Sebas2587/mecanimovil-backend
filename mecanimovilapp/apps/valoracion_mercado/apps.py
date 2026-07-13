from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ValoracionMercadoConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mecanimovilapp.apps.valoracion_mercado'
    verbose_name = _('Valoración de mercado')
