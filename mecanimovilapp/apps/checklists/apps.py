from django.apps import AppConfig


class ChecklistsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mecanimovilapp.apps.checklists'
    verbose_name = 'Checklists'
    
    def ready(self):
        """
        Importar signals cuando la app esté lista
        """
        import mecanimovilapp.apps.checklists.signals  # noqa 