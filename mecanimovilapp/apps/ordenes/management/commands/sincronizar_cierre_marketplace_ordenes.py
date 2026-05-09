"""
Repara desincronización: orden `completado` pero oferta/solicitud pública siguen
`en_ejecucion` (p. ej. firma cliente antes del deploy del fix).

Uso en Render Shell:
    python manage.py sincronizar_cierre_marketplace_ordenes --dry-run
    python manage.py sincronizar_cierre_marketplace_ordenes
"""
from django.core.management.base import BaseCommand

from mecanimovilapp.apps.ordenes.models import SolicitudServicio
from mecanimovilapp.apps.ordenes.services.cierre_servicio_marketplace import (
    sincronizar_cierre_marketplace,
)


class Command(BaseCommand):
    help = 'Alinea oferta y solicitud pública con órdenes ya marcadas como completadas.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Listar IDs afectados sin escribir en la base de datos',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        candidatas = (
            SolicitudServicio.objects.filter(
                estado='completado',
                oferta_proveedor__isnull=False,
            )
            .filter(
                oferta_proveedor__estado='en_ejecucion'
            )
            .values_list('id', flat=True)
        )
        ids = list(candidatas)
        self.stdout.write(self.style.NOTICE(f'Órdenes candidatas: {len(ids)}'))
        for oid in ids:
            self.stdout.write(f'  - orden_id={oid}')
        if dry_run:
            self.stdout.write(self.style.WARNING('Dry-run: sin cambios.'))
            return
        arregladas = 0
        for oid in ids:
            hubo, _ = sincronizar_cierre_marketplace(oid)
            if hubo:
                arregladas += 1
        self.stdout.write(self.style.SUCCESS(f'Filas actualizadas (hubo cambio): {arregladas}'))
