"""
Comando de management para calcular salud de todos los vehículos
Ejecutar: python manage.py calcular_salud_vehiculos
"""
from django.core.management.base import BaseCommand
from mecanimovilapp.apps.vehiculos.models import Vehiculo
from mecanimovilapp.apps.vehiculos.tasks import calcular_estado_salud_interno


class Command(BaseCommand):
    help = 'Calcula la salud de todos los vehículos existentes'

    def add_arguments(self, parser):
        parser.add_argument(
            '--vehicle-id',
            type=int,
            help='ID específico de vehículo a calcular (opcional)',
        )

    def handle(self, *args, **options):
        vehicle_id = options.get('vehicle_id')
        
        if vehicle_id:
            # Calcular solo un vehículo específico
            try:
                vehiculo = Vehiculo.objects.get(id=vehicle_id)
                self.stdout.write(f'Calculando salud para vehículo {vehiculo.patente}...')
                estado = calcular_estado_salud_interno(vehicle_id)
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✅ Salud calculada: {estado.salud_general_porcentaje}%'
                    )
                )
            except Vehiculo.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'❌ Vehículo {vehicle_id} no encontrado')
                )
        else:
            # Calcular todos los vehículos
            vehiculos = Vehiculo.objects.all()
            total = vehiculos.count()
            
            self.stdout.write(f'Calculando salud para {total} vehículos...')
            
            count = 0
            for vehiculo in vehiculos:
                try:
                    calcular_estado_salud_interno(vehiculo.id)
                    count += 1
                    if count % 10 == 0:
                        self.stdout.write(f'  Procesados: {count}/{total}')
                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(
                            f'⚠️ Error calculando vehículo {vehiculo.id}: {str(e)}'
                        )
                    )
            
            self.stdout.write('')
            self.stdout.write(
                self.style.SUCCESS(
                    f'✅ Proceso completado: {count}/{total} vehículos procesados'
                )
            )

