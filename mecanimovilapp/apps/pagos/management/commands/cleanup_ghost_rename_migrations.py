#!/usr/bin/env python
"""Elimina registros de migraciones RenameIndex auto-generadas que rompen deploys en Render."""

from django.core.management.base import BaseCommand
from django.db import connection

GHOST_PATTERNS = (
    ('pagos', '0004_rename_%'),
    ('valoracion_mercado', '0005_rename_%'),
)


class Command(BaseCommand):
    help = 'Quita migraciones rename fantasma antes de migrate (idempotente).'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            for app, pattern in GHOST_PATTERNS:
                cursor.execute(
                    'DELETE FROM django_migrations WHERE app = %s AND name LIKE %s',
                    [app, pattern],
                )
                if cursor.rowcount:
                    self.stdout.write(
                        self.style.WARNING(
                            f'Eliminados {cursor.rowcount} registro(s) fantasma en {app} ({pattern})',
                        ),
                    )
        self.stdout.write(self.style.SUCCESS('Limpieza de migraciones rename completada.'))
