from django.apps import AppConfig


class OrdenesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mecanimovilapp.apps.ordenes'
    verbose_name = 'Órdenes'

    def ready(self):
        import mecanimovilapp.apps.ordenes.signals_agendamiento_ia  # noqa: F401
