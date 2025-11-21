from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Limpia la tabla de migraciones para empezar de cero'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            # Limpiar la tabla de migraciones completamente
            cursor.execute('DELETE FROM django_migrations')
            self.stdout.write(self.style.SUCCESS('Tabla de migraciones limpiada con éxito.'))
            self.stdout.write(self.style.WARNING('Ahora puedes ejecutar makemigrations y migrate --fake-initial')) 