"""
Comando de management para poblar componentes de salud iniciales
Ejecutar: python manage.py populate_health_components
"""
from django.core.management.base import BaseCommand
from mecanimovilapp.apps.vehiculos.models_health import ComponenteSaludConfig
from mecanimovilapp.apps.servicios.models import Servicio


class Command(BaseCommand):
    help = 'Pobla la base de datos con componentes de salud iniciales'

    def handle(self, *args, **options):
        self.stdout.write('Iniciando población de componentes de salud...')
        
        # Definir componentes con sus configuraciones
        componentes_data = [
            {
                'nombre': 'Aceite Motor',
                'descripcion': 'Aceite del motor - requiere cambio periódico',
                'tipo_medicion': 'KILOMETRAJE',
                'beta': 2.5,
                'eta': 10000,
                'km_critico': 10000,
                'meses_critico': None,
                'factor_edad_vehiculo': 0.05,
                'icono': 'water-outline',
                'orden_visualizacion': 1,
            },
            {
                'nombre': 'Filtro de Aire',
                'descripcion': 'Filtro de aire del motor',
                'tipo_medicion': 'KILOMETRAJE',
                'beta': 2.0,
                'eta': 15000,
                'km_critico': 15000,
                'meses_critico': None,
                'factor_edad_vehiculo': 0.05,
                'icono': 'air-outline',
                'orden_visualizacion': 2,
            },
            {
                'nombre': 'Filtro de Aceite',
                'descripcion': 'Filtro de aceite del motor',
                'tipo_medicion': 'KILOMETRAJE',
                'beta': 2.5,
                'eta': 10000,
                'km_critico': 10000,
                'meses_critico': None,
                'factor_edad_vehiculo': 0.05,
                'icono': 'funnel-outline',
                'orden_visualizacion': 3,
            },
            {
                'nombre': 'Bujías',
                'descripcion': 'Bujías del motor',
                'tipo_medicion': 'KILOMETRAJE',
                'beta': 3.0,
                'eta': 30000,
                'km_critico': 30000,
                'meses_critico': None,
                'factor_edad_vehiculo': 0.05,
                'icono': 'flash-outline',
                'orden_visualizacion': 4,
            },
            {
                'nombre': 'Batería',
                'descripcion': 'Batería del vehículo',
                'tipo_medicion': 'TIEMPO',
                'beta': 1.5,
                'eta': 48,
                'km_critico': None,
                'meses_critico': 48,
                'factor_edad_vehiculo': 0.08,
                'icono': 'battery-charging-outline',
                'orden_visualizacion': 5,
            },
            {
                'nombre': 'Neumáticos',
                'descripcion': 'Neumáticos del vehículo',
                'tipo_medicion': 'KILOMETRAJE',
                'beta': 2.2,
                'eta': 40000,
                'km_critico': 40000,
                'meses_critico': None,
                'factor_edad_vehiculo': 0.05,
                'icono': 'disc-outline',
                'orden_visualizacion': 6,
            },
            {
                'nombre': 'Pastillas de Freno',
                'descripcion': 'Pastillas de freno delanteras y traseras',
                'tipo_medicion': 'KILOMETRAJE',
                'beta': 3.5,
                'eta': 35000,
                'km_critico': 35000,
                'meses_critico': None,
                'factor_edad_vehiculo': 0.05,
                'icono': 'stop-circle-outline',
                'orden_visualizacion': 7,
            },
            {
                'nombre': 'Discos de Freno',
                'descripcion': 'Discos de freno delanteros y traseros',
                'tipo_medicion': 'KILOMETRAJE',
                'beta': 2.8,
                'eta': 70000,
                'km_critico': 70000,
                'meses_critico': None,
                'factor_edad_vehiculo': 0.05,
                'icono': 'disc-outline',
                'orden_visualizacion': 8,
            },
            {
                'nombre': 'Amortiguadores',
                'descripcion': 'Amortiguadores del vehículo',
                'tipo_medicion': 'KILOMETRAJE',
                'beta': 2.5,
                'eta': 80000,
                'km_critico': 80000,
                'meses_critico': None,
                'factor_edad_vehiculo': 0.06,
                'icono': 'pulse-outline',
                'orden_visualizacion': 9,
            },
            {
                'nombre': 'Correa de Distribución',
                'descripcion': 'Correa de distribución del motor',
                'tipo_medicion': 'KILOMETRAJE',
                'beta': 3.0,
                'eta': 100000,
                'km_critico': 100000,
                'meses_critico': None,
                'factor_edad_vehiculo': 0.05,
                'icono': 'sync-outline',
                'orden_visualizacion': 10,
            },
            {
                'nombre': 'Líquido de Frenos',
                'descripcion': 'Líquido de frenos',
                'tipo_medicion': 'MIXTO',
                'beta': 1.8,
                'eta': 30000,
                'km_critico': 30000,
                'meses_critico': 24,
                'factor_edad_vehiculo': 0.05,
                'icono': 'water-outline',
                'orden_visualizacion': 11,
            },
            {
                'nombre': 'Refrigerante',
                'descripcion': 'Líquido refrigerante del motor',
                'tipo_medicion': 'MIXTO',
                'beta': 1.8,
                'eta': 40000,
                'km_critico': 40000,
                'meses_critico': 24,
                'factor_edad_vehiculo': 0.05,
                'icono': 'thermometer-outline',
                'orden_visualizacion': 12,
            },
        ]
        
        created_count = 0
        updated_count = 0
        
        for comp_data in componentes_data:
            # Intentar buscar servicio asociado por nombre
            servicio_asociado = None
            nombre_servicio = comp_data['nombre'].lower()
            
            # Mapeo de nombres de componentes a servicios
            servicio_mapping = {
                'aceite motor': ['cambio de aceite', 'aceite'],
                'filtro de aire': ['filtro de aire', 'filtro aire'],
                'filtro de aceite': ['filtro de aceite', 'filtro aceite'],
                'bujías': ['cambio de bujías', 'bujías', 'bujias'],
                'batería': ['cambio de batería', 'batería', 'bateria'],
                'neumáticos': ['cambio de neumáticos', 'neumáticos', 'llantas'],
                'pastillas de freno': ['cambio de pastillas', 'pastillas de freno'],
                'discos de freno': ['cambio de discos', 'discos de freno'],
                'amortiguadores': ['cambio de amortiguadores', 'amortiguadores'],
                'correa de distribución': ['cambio de correa', 'correa de distribución'],
                'líquido de frenos': ['cambio de líquido de frenos', 'líquido de frenos'],
                'refrigerante': ['cambio de refrigerante', 'refrigerante'],
            }
            
            if nombre_servicio in servicio_mapping:
                keywords = servicio_mapping[nombre_servicio]
                servicio_asociado = Servicio.objects.filter(
                    nombre__icontains=keywords[0]
                ).first()
            
            comp_data['servicio_asociado'] = servicio_asociado
            
            componente, created = ComponenteSaludConfig.objects.update_or_create(
                nombre=comp_data['nombre'],
                defaults=comp_data
            )
            
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'✓ Creado: {componente.nombre}')
                )
            else:
                updated_count += 1
                self.stdout.write(
                    self.style.WARNING(f'↻ Actualizado: {componente.nombre}')
                )
        
        self.stdout.write('')
        self.stdout.write(
            self.style.SUCCESS(
                f'✅ Proceso completado: {created_count} creados, {updated_count} actualizados'
            )
        )
        self.stdout.write('')
        self.stdout.write('Los componentes están listos para usar en el sistema de salud vehicular.')

