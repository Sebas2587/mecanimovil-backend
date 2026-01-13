"""
Comando de management para cargar las 10 marcas más comerciales de Chile
y sus modelos más populares según ventas en Chile (2024-2025)
"""
from django.core.management.base import BaseCommand
from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo, Modelo


class Command(BaseCommand):
    help = 'Carga las 10 marcas más vendidas en Chile y sus modelos más populares'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Eliminar marcas y modelos existentes antes de cargar (usar con precaución)',
        )

    def handle(self, *args, **options):
        # Datos basados en las marcas y modelos más vendidos en Chile (2024-2025)
        # Fuente: Estadísticas de ventas de automóviles en Chile
        marcas_data = [
            {
                "nombre": "Suzuki",
                "modelos": [
                    "Swift",
                    "Baleno HB",
                    "S-Cross",
                    "Vitara",
                    "Jimny",
                    "Ertiga",
                    "S-Presso",
                    "Celerio"
                ]
            },
            {
                "nombre": "Kia",
                "modelos": [
                    "Soluto",
                    "Morning",
                    "Rio",
                    "Sportage",
                    "Sorento",
                    "Picanto",
                    "Seltos",
                    "Carnival"
                ]
            },
            {
                "nombre": "Toyota",
                "modelos": [
                    "Yaris",
                    "Corolla",
                    "Hilux",
                    "RAV4",
                    "Camry",
                    "Fortuner",
                    "Land Cruiser",
                    "Prado"
                ]
            },
            {
                "nombre": "Hyundai",
                "modelos": [
                    "Grand i10 HB",
                    "Accent",
                    "Tucson",
                    "Creta",
                    "Elantra",
                    "Kona",
                    "Santa Fe",
                    "i20"
                ]
            },
            {
                "nombre": "Chevrolet",
                "modelos": [
                    "Sail",
                    "Spark",
                    "Trax",
                    "Equinox",
                    "Cruze",
                    "Silverado",
                    "Onix",
                    "Tracker"
                ]
            },
            {
                "nombre": "Ford",
                "modelos": [
                    "Ranger",
                    "Focus",
                    "Territory",
                    "F-150",
                    "Escape",
                    "Explorer",
                    "Mustang",
                    "Edge"
                ]
            },
            {
                "nombre": "Peugeot",
                "modelos": [
                    "208",
                    "308",
                    "2008",
                    "3008",
                    "5008",
                    "Partner",
                    "Expert",
                    "Traveller"
                ]
            },
            {
                "nombre": "Mitsubishi",
                "modelos": [
                    "L-200",
                    "Outlander",
                    "ASX",
                    "Montero",
                    "Eclipse Cross",
                    "Pajero",
                    "Triton",
                    "Xpander"
                ]
            },
            {
                "nombre": "GWM",
                "modelos": [
                    "Poer",
                    "Haval H6",
                    "Tank 300",
                    "Haval Jolion",
                    "Haval H2",
                    "Wingle",
                    "Cannon",
                    "Tank 500"
                ]
            },
            {
                "nombre": "Changan",
                "modelos": [
                    "CS35",
                    "CS75",
                    "Alsvin",
                    "CS55",
                    "Uni-T",
                    "Eado",
                    "CS95",
                    "Honor"
                ]
            }
        ]

        if options['clear']:
            self.stdout.write(self.style.WARNING('⚠️  Eliminando marcas y modelos existentes...'))
            Modelo.objects.all().delete()
            MarcaVehiculo.objects.all().delete()
            self.stdout.write(self.style.SUCCESS('✅ Marcas y modelos eliminados'))

        # Contadores
        marcas_creadas = 0
        marcas_existentes = 0
        modelos_creados = 0
        modelos_existentes = 0

        # Crear marcas y modelos
        for marca_data in marcas_data:
            marca_nombre = marca_data["nombre"]
            
            # Crear o obtener marca
            marca, created = MarcaVehiculo.objects.get_or_create(nombre=marca_nombre)
            if created:
                marcas_creadas += 1
                self.stdout.write(self.style.SUCCESS(f'✅ Marca creada: {marca_nombre}'))
            else:
                marcas_existentes += 1
                self.stdout.write(self.style.WARNING(f'⚠️  Marca ya existe: {marca_nombre}'))
            
            # Crear modelos para esta marca
            for modelo_nombre in marca_data["modelos"]:
                modelo, created = Modelo.objects.get_or_create(
                    nombre=modelo_nombre,
                    marca=marca
                )
                if created:
                    modelos_creados += 1
                    self.stdout.write(f'   ✅ Modelo creado: {modelo_nombre}')
                else:
                    modelos_existentes += 1
                    self.stdout.write(f'   ⚠️  Modelo ya existe: {modelo_nombre}')

        # Resumen final
        total_marcas = MarcaVehiculo.objects.count()
        total_modelos = Modelo.objects.count()
        
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('📊 RESUMEN DE CARGA'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS(f'✅ Marcas nuevas creadas: {marcas_creadas}'))
        self.stdout.write(self.style.WARNING(f'⚠️  Marcas que ya existían: {marcas_existentes}'))
        self.stdout.write(self.style.SUCCESS(f'✅ Modelos nuevos creados: {modelos_creados}'))
        self.stdout.write(self.style.WARNING(f'⚠️  Modelos que ya existían: {modelos_existentes}'))
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'📈 Total de marcas en la base de datos: {total_marcas}'))
        self.stdout.write(self.style.SUCCESS(f'📈 Total de modelos en la base de datos: {total_modelos}'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        
        if marcas_creadas > 0 or modelos_creados > 0:
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('✅ ¡Datos cargados exitosamente!'))
        else:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('⚠️  Todos los datos ya existían. Usa --clear si quieres eliminar y volver a cargar.'))
