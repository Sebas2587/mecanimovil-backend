"""
Anula ubicacion PostGIS del pin histórico Santiago centro (-33.4489, -70.6693).
Esos puntos no son direcciones reales y engañan distancia / detalle en usuarios.
Uso: python manage.py clear_default_santiago_pins [--dry-run]
"""
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.core.management.base import BaseCommand

from mecanimovilapp.apps.usuarios.models import MecanicoDomicilio, Taller


DEFAULT_SANTIAGO = Point(-70.6693, -33.4489, srid=4326)


class Command(BaseCommand):
    help = 'Pone ubicacion=NULL en proveedores con pin inventado Santiago centro'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        dry = options['dry_run']
        for label, model in (('Taller', Taller), ('MecanicoDomicilio', MecanicoDomicilio)):
            qs = model.objects.filter(
                ubicacion__isnull=False,
                ubicacion__dwithin=(DEFAULT_SANTIAGO, D(m=25)),
            )
            n = qs.count()
            self.stdout.write(f'{label}: {n} con pin default')
            if dry or n == 0:
                continue
            updated = qs.update(ubicacion=None)
            self.stdout.write(self.style.SUCCESS(f'  cleared={updated}'))
        self.stdout.write(self.style.SUCCESS(f'Done. dry_run={dry}'))
