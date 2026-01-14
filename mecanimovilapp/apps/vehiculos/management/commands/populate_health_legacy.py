"""
Comando de management para poblar componentes de salud en vehículos existentes
que aún no tienen el sistema inicializado.
Ejecutar: python manage.py populate_health_legacy
"""
from django.core.management.base import BaseCommand
from django.db.models import Q
from mecanimovilapp.apps.vehiculos.models import Vehiculo
from mecanimovilapp.apps.vehiculos.models_health import ComponenteSaludConfig, ComponenteSaludVehiculo

class Command(BaseCommand):
    help = 'Inicializa componentes de salud para vehículos existentes sin historial (Legacy Support)'

    def handle(self, *args, **options):
        self.stdout.write('🚑 Iniciando reparación de salud vehicular (Legacy)...')
        
        vehiculos = Vehiculo.objects.all()
        total = vehiculos.count()
        processed = 0
        updated = 0
        skipped = 0
        
        self.stdout.write(f'📊 Total de vehículos a analizar: {total}')
        
        for vehiculo in vehiculos:
            processed += 1
            if processed % 100 == 0:
                self.stdout.write(f'   Procesando {processed}/{total}...')
                
            # Verificar si ya tiene componentes
            if vehiculo.componentes_salud.exists():
                skipped += 1
                continue
                
            # Determinar tipo de motor
            tipo_motor_map = {
                'Gasolina': 'GASOLINA',
                'Diésel': 'DIESEL',
                'Gasolina': 'GASOLINA',
                'gasolina': 'GASOLINA',
                'Diesel': 'DIESEL',
                'diesel': 'DIESEL',
            }
            # Normalizar y obtener tipo
            tipo_motor = tipo_motor_map.get(vehiculo.tipo_motor, 'GASOLINA')
            
            # Obtener configs aplicables
            configs = ComponenteSaludConfig.objects.filter(
                activo=True
            ).filter(
                Q(tipo_motor_aplicable='TODOS') | Q(tipo_motor_aplicable=tipo_motor)
            )
            
            if not configs.exists():
                self.stdout.write(self.style.WARNING(f'⚠️ Vehículo {vehiculo.id} ({vehiculo.patente}): No hay configs para motor {tipo_motor}'))
                continue
                
            # Crear componentes
            count_created = 0
            for config in configs:
                # Al ser legacy, asumimos lo peor: mantenimiento pendiente (CRITICO)
                # km_ultimo_servicio = 0
                ComponenteSaludVehiculo.objects.create(
                    vehiculo=vehiculo,
                    componente_config=config,
                    salud_porcentaje=0, 
                    nivel_alerta='CRITICO',
                    km_ultimo_servicio=0,
                    requiere_servicio_inmediato=True,
                    mensaje_alerta=f"⚠️ {config.nombre} requiere revisión (inicialización automática)"
                )
                count_created += 1
            
            # Recalcular para asegurar consistencia
            for comp in vehiculo.componentes_salud.all():
                comp.calcular_salud()
                
            updated += 1
            # self.stdout.write(f'   ✅ Vehículo {vehiculo.id}: Inicializados {count_created} componentes')
            
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS(f'🏁 Proceso finalizado.'))
        self.stdout.write(f'   - Analizados: {processed}')
        self.stdout.write(f'   - Actualizados (Legacy): {updated}')
        self.stdout.write(f'   - Omitidos (Ya tenían datos): {skipped}')
