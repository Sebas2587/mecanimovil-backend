"""
Limpia vínculos genéricos incorrectos en ComponenteSalud.servicios_asociados.
No asigna «Mantenimiento por kilometraje» ni «Diagnóstico mecánico» a componentes
específicos (neumáticos, correa, DPF, etc.) — eso generaba cards duplicadas/erróneas.
"""
from django.core.management.base import BaseCommand

from mecanimovilapp.apps.servicios.models import Servicio
from mecanimovilapp.apps.vehiculos.models_health import ComponenteSalud

# Servicios demasiado genéricos para asignar como única sugerencia M2M
GENERIC_SERVICE_NAMES = (
    'Mantenimiento por kilometraje',
    'Diagnóstico mecánico',
    'Diagnóstico electromecánico',
)

# slug → nombres de servicio específicos a vincular si el componente queda sin M2M
SLUG_SPECIFIC_SERVICES = {
    'tires': [],  # sin servicio de neumáticos en catálogo → card genérica ML
    'adblue': [],
    'exhaust': [],
    'timing-belt': [],
}


class Command(BaseCommand):
    help = 'Limpia y corrige servicios_asociados de componentes de salud'

    def handle(self, *args, **options):
        generic_ids = set(
            Servicio.objects.filter(nombre__in=GENERIC_SERVICE_NAMES).values_list('id', flat=True)
        )
        removed = 0
        added = 0

        for comp in ComponenteSalud.objects.all():
            linked = list(comp.servicios_asociados.values_list('id', 'nombre'))
            to_remove = [sid for sid, _ in linked if sid in generic_ids]
            if to_remove:
                comp.servicios_asociados.remove(*to_remove)
                removed += len(to_remove)
                self.stdout.write(
                    self.style.WARNING(
                        f'  {comp.slug}: removidos {len(to_remove)} servicio(s) genérico(s)'
                    )
                )

            if not comp.servicios_asociados.exists():
                for nombre in SLUG_SPECIFIC_SERVICES.get(comp.slug, []):
                    servicio = Servicio.objects.filter(nombre=nombre).first()
                    if servicio:
                        comp.servicios_asociados.add(servicio)
                        added += 1
                        self.stdout.write(
                            self.style.SUCCESS(f'  {comp.slug} ← {servicio.nombre}')
                        )
                        break

        self.stdout.write(
            self.style.SUCCESS(
                f'Listo: {removed} vínculo(s) genérico(s) removidos, {added} específico(s) añadidos'
            )
        )
