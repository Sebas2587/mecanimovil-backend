"""
Asocia servicios de catálogo a ComponenteSalud sin M2M servicios_asociados.
Útil para que Mantenimiento sugerido muestre cards con servicio concreto
(neumáticos, AdBlue, DPF, correa, etc.).
"""
from django.core.management.base import BaseCommand

from mecanimovilapp.apps.servicios.models import Servicio
from mecanimovilapp.apps.vehiculos.models_health import ComponenteSalud

# slug → nombres de servicio a vincular (primer match en BD)
SLUG_SERVICIOS = {
    'tires': ['Mantenimiento por kilometraje', 'Diagnóstico mecánico'],
    'adblue': ['Diagnóstico mecánico', 'Mantenimiento por kilometraje'],
    'exhaust': ['Diagnóstico mecánico'],
    'timing-belt': ['Mantenimiento por kilometraje', 'Diagnóstico mecánico'],
}


class Command(BaseCommand):
    help = 'Vincula servicios de catálogo a componentes de salud sin servicios_asociados'

    def handle(self, *args, **options):
        linked = 0
        for slug, nombres in SLUG_SERVICIOS.items():
            comp = ComponenteSalud.objects.filter(slug=slug).first()
            if not comp:
                self.stdout.write(self.style.WARNING(f'  Sin ComponenteSalud slug={slug}'))
                continue
            if comp.servicios_asociados.exists():
                self.stdout.write(f'  {slug}: ya tiene servicios, omitido')
                continue
            servicio = None
            for nombre in nombres:
                servicio = Servicio.objects.filter(nombre=nombre).first()
                if servicio:
                    break
            if not servicio:
                self.stdout.write(self.style.WARNING(f'  {slug}: sin servicio candidato'))
                continue
            comp.servicios_asociados.add(servicio)
            linked += 1
            self.stdout.write(self.style.SUCCESS(
                f'  {slug} ← {servicio.nombre} (id={servicio.id})'
            ))
        self.stdout.write(self.style.SUCCESS(f'Listo: {linked} componente(s) actualizados'))
