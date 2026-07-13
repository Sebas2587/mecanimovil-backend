from django.core.management.base import BaseCommand

from mecanimovilapp.apps.valoracion_mercado.models import CurvaDepreciacionSegmento

DEFAULT_CURVES = [
    ('LIVIANO', 7.0),
    ('SEDAN', 7.0),
    ('SUV', 6.5),
    ('CAMIONETA', 5.5),
    ('HATCHBACK', 7.5),
    ('COUPE', 8.0),
]


class Command(BaseCommand):
    help = 'Carga curvas de depreciación por categoría de vehículo'

    def handle(self, *args, **options):
        for tipo, tasa in DEFAULT_CURVES:
            CurvaDepreciacionSegmento.objects.update_or_create(
                tipo_vehiculo=tipo,
                defaults={'tasa_anual_pct': tasa, 'activo': True},
            )
        self.stdout.write(self.style.SUCCESS(f'Curvas cargadas: {len(DEFAULT_CURVES)}'))
