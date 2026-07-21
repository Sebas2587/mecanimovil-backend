"""Anonimiza coordenadas GPS antiguas (retención Ley 21.719, ≤5 años)."""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from mecanimovilapp.apps.vehiculos.models import ViajeRegistrado


class Command(BaseCommand):
    help = 'Anonimiza coordenadas de viajes registrados con más de 5 años de antigüedad.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Solo reporta cuántos registros se anonimizarían.',
        )

    def handle(self, *args, **options):
        limite = timezone.now() - timedelta(days=365 * 5)
        qs = ViajeRegistrado.objects.filter(
            fecha_registro__lt=limite,
        ).exclude(
            coordenadas_inicio={},
            coordenadas_fin={},
        )
        total = qs.count()
        if options['dry_run']:
            self.stdout.write(self.style.WARNING(f'[dry-run] Se anonimizarían {total} viajes'))
            return

        anonimizados = 0
        for viaje in qs.iterator(chunk_size=200):
            viaje.coordenadas_inicio = {}
            viaje.coordenadas_fin = {}
            viaje.save(update_fields=['coordenadas_inicio', 'coordenadas_fin'])
            anonimizados += 1

        self.stdout.write(self.style.SUCCESS(f'Anonimizados {anonimizados} viajes GPS antiguos'))
