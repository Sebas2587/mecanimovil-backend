from django.core.management.base import BaseCommand
from mecanimovilapp.apps.servicios.models import Servicio, Repuesto, ServicioRepuesto
from mecanimovilapp.apps.vehiculos.models import Marca, Modelo

class Command(BaseCommand):
    help = 'Carga datos de ejemplo para repuestos y servicios'

    def handle(self, *args, **options):
        self.stdout.write('🔧 Creando repuestos de ejemplo...')
        
        # Crear repuestos básicos
        repuestos_data = [
            {
                'nombre': 'Aceite Motor 5W-30',
                'descripcion': 'Aceite sintético de alta calidad para motor',
                'marca': 'Castrol',
                'categoria_repuesto': 'aceites',
                'precio_referencia': 25000,
                'codigo_fabricante': 'CTL-5W30-4L'
            },
            {
                'nombre': 'Filtro de Aceite',
                'descripcion': 'Filtro de aceite original',
                'marca': 'Mann Filter',
                'categoria_repuesto': 'filtros',
                'precio_referencia': 8000,
                'codigo_fabricante': 'MF-W712-23'
            },
            {
                'nombre': 'Filtro de Aire',
                'descripcion': 'Filtro de aire para motor',
                'marca': 'Bosch',
                'categoria_repuesto': 'filtros',
                'precio_referencia': 12000,
                'codigo_fabricante': 'BSH-AF123'
            },
            {
                'nombre': 'Pastillas de Freno Delanteras',
                'descripcion': 'Pastillas de freno cerámicas de alta performance',
                'marca': 'Brembo',
                'categoria_repuesto': 'frenos',
                'precio_referencia': 45000,
                'codigo_fabricante': 'BRM-PD789'
            },
            {
                'nombre': 'Discos de Freno Delanteros',
                'descripcion': 'Discos de freno ventilados',
                'marca': 'Brembo',
                'categoria_repuesto': 'frenos',
                'precio_referencia': 80000,
                'codigo_fabricante': 'BRM-DD456'
            },
            {
                'nombre': 'Batería 12V 60Ah',
                'descripcion': 'Batería libre de mantenimiento',
                'marca': 'Bosch',
                'categoria_repuesto': 'electrico',
                'precio_referencia': 90000,
                'codigo_fabricante': 'BSH-BAT60'
            }
        ]
        
        repuestos_creados = []
        for repuesto_data in repuestos_data:
            repuesto, created = Repuesto.objects.get_or_create(
                nombre=repuesto_data['nombre'],
                defaults=repuesto_data
            )
            if created:
                repuestos_creados.append(repuesto)
                self.stdout.write(f'  ✅ Creado repuesto: {repuesto.nombre}')
            else:
                self.stdout.write(f'  ⚠️ Ya existe: {repuesto.nombre}')
        
        self.stdout.write('🔧 Asociando repuestos con servicios...')
        
        # Buscar servicios existentes y asociar repuestos
        servicios_repuestos = [
            {
                'servicio_nombre': 'Cambio de Aceite',
                'repuestos': [
                    {'nombre': 'Aceite Motor 5W-30', 'cantidad': 1, 'opcional': False},
                    {'nombre': 'Filtro de Aceite', 'cantidad': 1, 'opcional': False}
                ]
            },
            {
                'servicio_nombre': 'Mantenimiento Básico',
                'repuestos': [
                    {'nombre': 'Aceite Motor 5W-30', 'cantidad': 1, 'opcional': False},
                    {'nombre': 'Filtro de Aceite', 'cantidad': 1, 'opcional': False},
                    {'nombre': 'Filtro de Aire', 'cantidad': 1, 'opcional': False}
                ]
            },
            {
                'servicio_nombre': 'Revisión de Frenos',
                'repuestos': [
                    {'nombre': 'Pastillas de Freno Delanteras', 'cantidad': 1, 'opcional': True},
                    {'nombre': 'Discos de Freno Delanteros', 'cantidad': 1, 'opcional': True}
                ]
            },
            {
                'servicio_nombre': 'Cambio de Pastillas de Freno',
                'repuestos': [
                    {'nombre': 'Pastillas de Freno Delanteras', 'cantidad': 1, 'opcional': False}
                ]
            }
        ]
        
        for servicio_data in servicios_repuestos:
            try:
                servicio = Servicio.objects.get(nombre__icontains=servicio_data['servicio_nombre'])
                
                for repuesto_info in servicio_data['repuestos']:
                    try:
                        repuesto = Repuesto.objects.get(nombre=repuesto_info['nombre'])
                        
                        servicio_repuesto, created = ServicioRepuesto.objects.get_or_create(
                            servicio=servicio,
                            repuesto=repuesto,
                            defaults={
                                'cantidad_estimada': repuesto_info['cantidad'],
                                'es_opcional': repuesto_info['opcional'],
                                'notas': f'Repuesto necesario para {servicio.nombre}'
                            }
                        )
                        
                        if created:
                            self.stdout.write(f'  ✅ Asociado: {servicio.nombre} -> {repuesto.nombre}')
                        else:
                            self.stdout.write(f'  ⚠️ Ya asociado: {servicio.nombre} -> {repuesto.nombre}')
                            
                    except Repuesto.DoesNotExist:
                        self.stdout.write(f'  ❌ Repuesto no encontrado: {repuesto_info["nombre"]}')
                        
            except Servicio.DoesNotExist:
                self.stdout.write(f'  ❌ Servicio no encontrado: {servicio_data["servicio_nombre"]}')
        
        self.stdout.write(self.style.SUCCESS('✅ Datos de repuestos cargados exitosamente!')) 