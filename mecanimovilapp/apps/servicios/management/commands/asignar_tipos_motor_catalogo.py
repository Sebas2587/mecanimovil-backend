"""
Asigna tipos_motor_compatibles al catálogo maestro según nombre de servicio/repuesto.
"""
from django.core.management.base import BaseCommand

from mecanimovilapp.apps.servicios.models import Repuesto, Servicio

# Servicios solo gasolina (sin bujías en diésel, etc.)
SERVICIOS_SOLO_GASOLINA = {
    'Cambio de bujías',
}

# Servicios solo diésel
SERVICIOS_SOLO_DIESEL = set()

# Servicios de combustión interna (gasolina + diésel)
SERVICIOS_COMBUSTION = {
    'Cambio de aceite motor',
    'Cambio aceite motor y filtro',
    'Cambio de aceite motor y filtro',
    'Cambio de filtro de aire',
    'Cambio de filtro habitáculo',
    'Mantenimiento por kilometraje',
    'Cambio de pastillas de frenos',
    'Cambio de pastillas y discos de freno',
    'Cambio de pastillas de frenos y rectificado',
    'Cambio de batería',
    'Cambio de ampolletas',
}

REPUESTOS_SOLO_GASOLINA = {
    'Bujías (Juego de 4)',
    'Aceite Motor 5W-30 Sintético (4L)',
    'Aceite Motor 10W-40 Semi-Sintético (4L)',
}

REPUESTOS_SOLO_DIESEL = set()

REPUESTOS_COMBUSTION = {
    'Filtro de Aceite',
    'Filtro de Aire Motor',
    'Filtro de Aire Habitáculo',
    'Pastillas de Freno Delanteras',
    'Pastillas de Freno Traseras',
    'Discos de Freno Delanteros (Par)',
    'Discos de Freno Traseros (Par)',
    'Batería 12V 60Ah',
    'Ampolleta H4 Halógena',
    'Ampolleta H7 Halógena',
}


class Command(BaseCommand):
    help = 'Asigna tipos_motor_compatibles a servicios y repuestos del catálogo maestro'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Muestra cambios sin guardar',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        actualizados_servicios = 0
        actualizados_repuestos = 0

        for servicio in Servicio.objects.all():
            tipos = self._tipos_para_servicio(servicio.nombre)
            if tipos is None:
                continue
            if (servicio.tipos_motor_compatibles or []) == tipos:
                continue
            self.stdout.write(f'Servicio "{servicio.nombre}" → {tipos or "[] (todos)"}')
            if not dry_run:
                servicio.tipos_motor_compatibles = tipos
                servicio.save(update_fields=['tipos_motor_compatibles'])
            actualizados_servicios += 1

        for repuesto in Repuesto.objects.all():
            tipos = self._tipos_para_repuesto(repuesto.nombre)
            if tipos is None:
                continue
            if (repuesto.tipos_motor_compatibles or []) == tipos:
                continue
            self.stdout.write(f'Repuesto "{repuesto.nombre}" → {tipos or "[] (todos)"}')
            if not dry_run:
                repuesto.tipos_motor_compatibles = tipos
                repuesto.save(update_fields=['tipos_motor_compatibles'])
            actualizados_repuestos += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Listo: {actualizados_servicios} servicios, {actualizados_repuestos} repuestos'
                + (' (dry-run)' if dry_run else '')
            )
        )

    def _tipos_para_servicio(self, nombre: str) -> list[str] | None:
        if nombre in SERVICIOS_SOLO_GASOLINA:
            return ['GASOLINA']
        if nombre in SERVICIOS_SOLO_DIESEL:
            return ['DIESEL']
        if nombre in SERVICIOS_COMBUSTION:
            return ['GASOLINA', 'DIESEL']
        return None

    def _tipos_para_repuesto(self, nombre: str) -> list[str] | None:
        if nombre in REPUESTOS_SOLO_GASOLINA:
            return ['GASOLINA']
        if nombre in REPUESTOS_SOLO_DIESEL:
            return ['DIESEL']
        if nombre in REPUESTOS_COMBUSTION:
            return ['GASOLINA', 'DIESEL']
        return None
