"""
Comando de management para poblar componentes de salud iniciales
Ejecutar: python manage.py populate_health_components

Incluye componentes diferenciados para motores Gasolina y Diésel
"""
from django.core.management.base import BaseCommand
from mecanimovilapp.apps.vehiculos.models_health import ComponenteSaludConfig
from mecanimovilapp.apps.servicios.models import Servicio


class Command(BaseCommand):
    help = 'Pobla la base de datos con componentes de salud iniciales (Gasolina y Diésel)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Eliminar todos los componentes existentes antes de cargar (usar con precaución)'
        )

    def handle(self, *args, **options):
        self.stdout.write('Iniciando población de componentes de salud...\n')
        
        if options['clear']:
            count = ComponenteSaludConfig.objects.count()
            ComponenteSaludConfig.objects.all().delete()
            self.stdout.write(self.style.WARNING(f'⚠️  Eliminados {count} componentes existentes\n'))
        
        # =================================================================
        # COMPONENTES COMUNES (TODOS los tipos de motor)
        # =================================================================
        componentes_comunes = [
            {
                'nombre': 'Aceite Motor',
                'descripcion': 'Aceite del motor - requiere cambio periódico',
                'tipo_motor_aplicable': 'TODOS',
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
                'tipo_motor_aplicable': 'TODOS',
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
                'tipo_motor_aplicable': 'TODOS',
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
                'nombre': 'Batería',
                'descripcion': 'Batería del vehículo',
                'tipo_motor_aplicable': 'TODOS',
                'tipo_medicion': 'TIEMPO',
                'beta': 1.5,
                'eta': 48,
                'km_critico': None,
                'meses_critico': 48,
                'factor_edad_vehiculo': 0.08,
                'icono': 'battery-charging-outline',
                'orden_visualizacion': 10,
            },
            {
                'nombre': 'Neumáticos',
                'descripcion': 'Neumáticos del vehículo',
                'tipo_motor_aplicable': 'TODOS',
                'tipo_medicion': 'KILOMETRAJE',
                'beta': 2.2,
                'eta': 40000,
                'km_critico': 40000,
                'meses_critico': None,
                'factor_edad_vehiculo': 0.05,
                'icono': 'disc-outline',
                'orden_visualizacion': 11,
            },
            {
                'nombre': 'Pastillas de Freno',
                'descripcion': 'Pastillas de freno delanteras y traseras',
                'tipo_motor_aplicable': 'TODOS',
                'tipo_medicion': 'KILOMETRAJE',
                'beta': 3.5,
                'eta': 35000,
                'km_critico': 35000,
                'meses_critico': None,
                'factor_edad_vehiculo': 0.05,
                'icono': 'stop-circle-outline',
                'orden_visualizacion': 12,
            },
            {
                'nombre': 'Discos de Freno',
                'descripcion': 'Discos de freno delanteros y traseros',
                'tipo_motor_aplicable': 'TODOS',
                'tipo_medicion': 'KILOMETRAJE',
                'beta': 2.8,
                'eta': 70000,
                'km_critico': 70000,
                'meses_critico': None,
                'factor_edad_vehiculo': 0.05,
                'icono': 'disc-outline',
                'orden_visualizacion': 13,
            },
            {
                'nombre': 'Amortiguadores',
                'descripcion': 'Amortiguadores del vehículo',
                'tipo_motor_aplicable': 'TODOS',
                'tipo_medicion': 'KILOMETRAJE',
                'beta': 2.5,
                'eta': 80000,
                'km_critico': 80000,
                'meses_critico': None,
                'factor_edad_vehiculo': 0.06,
                'icono': 'pulse-outline',
                'orden_visualizacion': 14,
            },
            {
                'nombre': 'Líquido de Frenos',
                'descripcion': 'Líquido de frenos',
                'tipo_motor_aplicable': 'TODOS',
                'tipo_medicion': 'MIXTO',
                'beta': 1.8,
                'eta': 30000,
                'km_critico': 30000,
                'meses_critico': 24,
                'factor_edad_vehiculo': 0.05,
                'icono': 'water-outline',
                'orden_visualizacion': 15,
            },
            {
                'nombre': 'Refrigerante',
                'descripcion': 'Líquido refrigerante del motor',
                'tipo_motor_aplicable': 'TODOS',
                'tipo_medicion': 'MIXTO',
                'beta': 1.8,
                'eta': 40000,
                'km_critico': 40000,
                'meses_critico': 24,
                'factor_edad_vehiculo': 0.05,
                'icono': 'thermometer-outline',
                'orden_visualizacion': 16,
            },
        ]
        
        # =================================================================
        # COMPONENTES ESPECÍFICOS PARA GASOLINA
        # =================================================================
        componentes_gasolina = [
            {
                'nombre': 'Bujías',
                'descripcion': 'Bujías de encendido del motor a gasolina',
                'tipo_motor_aplicable': 'GASOLINA',
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
                'nombre': 'Filtro de Bencina',
                'descripcion': 'Filtro de combustible para motor a gasolina',
                'tipo_motor_aplicable': 'GASOLINA',
                'tipo_medicion': 'KILOMETRAJE',
                'beta': 2.0,
                'eta': 40000,
                'km_critico': 40000,
                'meses_critico': None,
                'factor_edad_vehiculo': 0.05,
                'icono': 'filter-outline',
                'orden_visualizacion': 5,
            },
            {
                'nombre': 'Correa de Distribución',
                'descripcion': 'Correa de distribución del motor a gasolina',
                'tipo_motor_aplicable': 'GASOLINA',
                'tipo_medicion': 'KILOMETRAJE',
                'beta': 3.0,
                'eta': 100000,
                'km_critico': 100000,
                'meses_critico': None,
                'factor_edad_vehiculo': 0.05,
                'icono': 'sync-outline',
                'orden_visualizacion': 6,
            },
        ]
        
        # =================================================================
        # COMPONENTES ESPECÍFICOS PARA DIÉSEL
        # =================================================================
        componentes_diesel = [
            {
                'nombre': 'Bujías Incandescentes',
                'descripcion': 'Bujías de precalentamiento para motor diésel - durabilidad mayor que bujías convencionales',
                'tipo_motor_aplicable': 'DIESEL',
                'tipo_medicion': 'KILOMETRAJE',
                'beta': 2.0,
                'eta': 100000,  # Las bujías incandescentes duran mucho más (80,000-150,000 km)
                'km_critico': 100000,
                'meses_critico': None,
                'factor_edad_vehiculo': 0.03,  # Menor degradación por edad
                'icono': 'flame-outline',
                'orden_visualizacion': 4,
            },
            {
                'nombre': 'Filtro de Petróleo',
                'descripcion': 'Filtro de combustible para motor diésel - requiere cambios más frecuentes que gasolina',
                'tipo_motor_aplicable': 'DIESEL',
                'tipo_medicion': 'KILOMETRAJE',
                'beta': 2.5,
                'eta': 20000,  # Los filtros diésel se cambian más frecuentemente (15,000-25,000 km)
                'km_critico': 20000,
                'meses_critico': None,
                'factor_edad_vehiculo': 0.05,
                'icono': 'filter-outline',
                'orden_visualizacion': 5,
            },
            {
                'nombre': 'Correa de Distribución',
                'descripcion': 'Correa de distribución del motor diésel - intervalo similar a gasolina',
                'tipo_motor_aplicable': 'DIESEL',
                'tipo_medicion': 'KILOMETRAJE',
                'beta': 3.0,
                'eta': 120000,  # Los diésel suelen tener intervalos ligeramente mayores
                'km_critico': 120000,
                'meses_critico': None,
                'factor_edad_vehiculo': 0.05,
                'icono': 'sync-outline',
                'orden_visualizacion': 6,
            },
            {
                'nombre': 'Filtro de Partículas (DPF)',
                'descripcion': 'Filtro de partículas diésel - componente exclusivo de motores diésel modernos',
                'tipo_motor_aplicable': 'DIESEL',
                'tipo_medicion': 'KILOMETRAJE',
                'beta': 2.0,
                'eta': 150000,  # Los DPF duran 120,000-200,000 km aproximadamente
                'km_critico': 150000,
                'meses_critico': None,
                'factor_edad_vehiculo': 0.04,
                'icono': 'leaf-outline',
                'orden_visualizacion': 7,
            },
            {
                'nombre': 'Inyectores Diésel',
                'descripcion': 'Inyectores de combustible diésel - componente crítico del sistema de inyección',
                'tipo_motor_aplicable': 'DIESEL',
                'tipo_medicion': 'KILOMETRAJE',
                'beta': 2.5,
                'eta': 200000,  # Los inyectores diésel duran 150,000-250,000 km
                'km_critico': 200000,
                'meses_critico': None,
                'factor_edad_vehiculo': 0.03,
                'icono': 'water-outline',
                'orden_visualizacion': 8,
            },
            {
                'nombre': 'Válvula EGR',
                'descripcion': 'Válvula de recirculación de gases de escape - común en motores diésel',
                'tipo_motor_aplicable': 'DIESEL',
                'tipo_medicion': 'KILOMETRAJE',
                'beta': 2.2,
                'eta': 80000,  # La EGR suele dar problemas entre 60,000-100,000 km
                'km_critico': 80000,
                'meses_critico': None,
                'factor_edad_vehiculo': 0.05,
                'icono': 'repeat-outline',
                'orden_visualizacion': 9,
            },
        ]
        
        # Combinar todos los componentes
        todos_componentes = componentes_comunes + componentes_gasolina + componentes_diesel
        
        created_count = 0
        updated_count = 0
        
        for comp_data in todos_componentes:
            # Intentar buscar servicio asociado por nombre
            servicio_asociado = None
            nombre_servicio = comp_data['nombre'].lower()
            
            # Mapeo de nombres de componentes a servicios
            servicio_mapping = {
                'aceite motor': ['cambio de aceite', 'aceite'],
                'filtro de aire': ['filtro de aire', 'filtro aire'],
                'filtro de aceite': ['filtro de aceite', 'filtro aceite'],
                'bujías': ['cambio de bujías', 'bujías', 'bujias'],
                'bujías incandescentes': ['bujías incandescentes', 'calentadores', 'precalentadores'],
                'batería': ['cambio de batería', 'batería', 'bateria'],
                'neumáticos': ['cambio de neumáticos', 'neumáticos', 'llantas'],
                'pastillas de freno': ['cambio de pastillas', 'pastillas de freno'],
                'discos de freno': ['cambio de discos', 'discos de freno'],
                'amortiguadores': ['cambio de amortiguadores', 'amortiguadores'],
                'correa de distribución': ['cambio de correa', 'correa de distribución'],
                'líquido de frenos': ['cambio de líquido de frenos', 'líquido de frenos'],
                'refrigerante': ['cambio de refrigerante', 'refrigerante'],
                'filtro de bencina': ['filtro de bencina', 'filtro de combustible', 'filtro gasolina'],
                'filtro de petróleo': ['filtro de petróleo', 'filtro de combustible', 'filtro diesel'],
                'filtro de partículas (dpf)': ['filtro de partículas', 'dpf', 'limpieza dpf'],
                'inyectores diésel': ['inyectores', 'limpieza inyectores'],
                'válvula egr': ['egr', 'limpieza egr', 'válvula egr'],
            }
            
            if nombre_servicio in servicio_mapping:
                keywords = servicio_mapping[nombre_servicio]
                servicio_asociado = Servicio.objects.filter(
                    nombre__icontains=keywords[0]
                ).first()
            
            comp_data['servicio_asociado'] = servicio_asociado
            
            # Usar get_or_create con nombre y tipo_motor_aplicable
            componente, created = ComponenteSaludConfig.objects.update_or_create(
                nombre=comp_data['nombre'],
                tipo_motor_aplicable=comp_data['tipo_motor_aplicable'],
                defaults=comp_data
            )
            
            tipo_motor_str = f" ({componente.get_tipo_motor_aplicable_display()})" if comp_data['tipo_motor_aplicable'] != 'TODOS' else ""
            
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'✓ Creado: {componente.nombre}{tipo_motor_str}')
                )
            else:
                updated_count += 1
                self.stdout.write(
                    self.style.WARNING(f'↻ Actualizado: {componente.nombre}{tipo_motor_str}')
                )
        
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(
            self.style.SUCCESS(
                f'✅ Proceso completado: {created_count} creados, {updated_count} actualizados'
            )
        )
        self.stdout.write('')
        
        # Resumen por tipo de motor
        comunes = len(componentes_comunes)
        gasolina = len(componentes_gasolina)
        diesel = len(componentes_diesel)
        
        self.stdout.write(self.style.HTTP_INFO(f'📊 Resumen:'))
        self.stdout.write(f'   - Componentes comunes (todos): {comunes}')
        self.stdout.write(f'   - Componentes solo Gasolina:   {gasolina}')
        self.stdout.write(f'   - Componentes solo Diésel:     {diesel}')
        self.stdout.write(f'   - Total:                       {comunes + gasolina + diesel}')
        self.stdout.write('')
        self.stdout.write('🔧 Los componentes están listos para usar en el sistema de salud vehicular.')
        self.stdout.write('   El sistema seleccionará automáticamente los componentes según el tipo de motor del vehículo.')
