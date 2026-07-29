#!/usr/bin/env python
"""Elimina registros de migraciones RenameIndex auto-generadas que rompen deploys en Render."""

import time

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.utils import OperationalError

GHOST_PATTERNS = (
    ('pagos', '0004_rename_%'),
    ('valoracion_mercado', '0005_rename_%'),
    ('suscripciones', '0011_rename_%'),
)


class Command(BaseCommand):
    help = 'Quita migraciones rename fantasma antes de migrate (idempotente).'

    def handle(self, *args, **options):
        last_error = None
        for attempt in range(1, 5):
            try:
                connection.close_if_unusable_or_obsolete()
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
                return
            except OperationalError as exc:
                last_error = exc
                self.stderr.write(
                    self.style.WARNING(
                        f'Postgres no disponible en cleanup (intento {attempt}/4): {exc}',
                    ),
                )
                time.sleep(5 * attempt)

        raise last_error  # type: ignore[misc]
