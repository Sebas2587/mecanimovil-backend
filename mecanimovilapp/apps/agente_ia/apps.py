from django.apps import AppConfig


class AgenteIaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mecanimovilapp.apps.agente_ia'
    verbose_name = 'Agente IA conversacional'

    def ready(self):
        import mecanimovilapp.apps.agente_ia.signals  # noqa: F401
