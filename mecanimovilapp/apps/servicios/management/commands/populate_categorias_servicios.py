"""
Comando de management para poblar las categorías de servicios en la base de datos.
Este comando crea las categorías de servicios disponibles tanto para usuarios como para proveedores.
"""
from django.core.management.base import BaseCommand
from mecanimovilapp.apps.servicios.models import CategoriaServicio


class Command(BaseCommand):
    help = 'Pobla la base de datos con las categorías de servicios disponibles'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Fuerza la actualización de categorías existentes',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Elimina todas las categorías existentes antes de crear las nuevas',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('🚀 Iniciando población de categorías de servicios...'))
        
        # Lista de categorías de servicios con sus detalles
        categorias_data = [
            {
                'nombre': 'Diagnostico mecanico',
                'descripcion': 'Servicio de diagnóstico general del sistema mecánico del vehículo',
                'icono': 'build-outline',
                'orden': 1,
            },
            {
                'nombre': 'Cambio de pastillas de frenos',
                'descripcion': 'Reemplazo de las pastillas de freno delanteras o traseras',
                'icono': 'car-sport-outline',
                'orden': 2,
            },
            {
                'nombre': 'Cambio de pastillas y discos de freno',
                'descripcion': 'Reemplazo completo de pastillas y discos de freno',
                'icono': 'car-sport-outline',
                'orden': 3,
            },
            {
                'nombre': 'Cambio de aceite motor',
                'descripcion': 'Reemplazo del aceite del motor del vehículo',
                'icono': 'water-outline',
                'orden': 4,
            },
            {
                'nombre': 'Cambio de filtro de aire',
                'descripcion': 'Reemplazo del filtro de aire del motor',
                'icono': 'airplane-outline',
                'orden': 5,
            },
            {
                'nombre': 'Cambio de filtro habitaculo',
                'descripcion': 'Reemplazo del filtro de aire del habitáculo (cabina)',
                'icono': 'airplane-outline',
                'orden': 6,
            },
            {
                'nombre': 'Cambio aceite motor y filtro',
                'descripcion': 'Servicio combinado de cambio de aceite y filtro de aceite',
                'icono': 'water-outline',
                'orden': 7,
            },
            {
                'nombre': 'Diagnostico electromecanico',
                'descripcion': 'Diagnóstico de sistemas eléctricos y mecánicos del vehículo',
                'icono': 'flash-outline',
                'orden': 8,
            },
            {
                'nombre': 'Servicio escaner automotriz',
                'descripcion': 'Lectura y diagnóstico mediante escáner OBD del vehículo',
                'icono': 'hardware-chip-outline',
                'orden': 9,
            },
            {
                'nombre': 'Mantenimiento por kilometraje',
                'descripcion': 'Servicio de mantenimiento preventivo según kilometraje del vehículo',
                'icono': 'speedometer-outline',
                'orden': 10,
            },
            {
                'nombre': 'Cambio de ampolletas',
                'descripcion': 'Reemplazo de ampolletas de luces delanteras, traseras o interiores',
                'icono': 'bulb-outline',
                'orden': 11,
            },
            {
                'nombre': 'Revision precompra',
                'descripcion': 'Inspección completa del vehículo antes de una compra',
                'icono': 'search-outline',
                'orden': 12,
            },
            {
                'nombre': 'Revision tecnica',
                'descripcion': 'Revisión técnica obligatoria para certificación del vehículo',
                'icono': 'document-text-outline',
                'orden': 13,
            },
            {
                'nombre': 'Lavado a domicilio',
                'descripcion': 'Servicio de lavado y detallado del vehículo en la ubicación del cliente',
                'icono': 'water-outline',
                'orden': 14,
            },
            {
                'nombre': 'Cambio de bateria',
                'descripcion': 'Reemplazo de la batería del vehículo',
                'icono': 'battery-charging-outline',
                'orden': 15,
            },
            {
                'nombre': 'Cambio de bujias',
                'descripcion': 'Reemplazo de las bujías del motor',
                'icono': 'flash-outline',
                'orden': 16,
            },
            {
                'nombre': 'Cambio de pastillas de frenos y rectificado',
                'descripcion': 'Reemplazo de pastillas de freno con rectificado de discos',
                'icono': 'car-sport-outline',
                'orden': 17,
            },
        ]

        # Si se especifica --clear, eliminar todas las categorías existentes
        if options['clear']:
            self.stdout.write(self.style.WARNING('⚠️  Eliminando todas las categorías existentes...'))
            count = CategoriaServicio.objects.all().count()
            CategoriaServicio.objects.all().delete()
            self.stdout.write(self.style.SUCCESS(f'✅ Eliminadas {count} categorías existentes'))

        # Crear o actualizar categorías
        creadas = 0
        actualizadas = 0
        existentes = 0

        for categoria_data in categorias_data:
            nombre = categoria_data['nombre']
            descripcion = categoria_data.get('descripcion', '')
            icono = categoria_data.get('icono', '')
            orden = categoria_data.get('orden', 0)

            categoria, created = CategoriaServicio.objects.get_or_create(
                nombre=nombre,
                defaults={
                    'descripcion': descripcion,
                    'icono': icono,
                    'orden': orden,
                }
            )

            if created:
                creadas += 1
                self.stdout.write(self.style.SUCCESS(f'✅ Creada: {nombre}'))
            elif options['force']:
                # Actualizar categoría existente si se especifica --force
                categoria.descripcion = descripcion
                categoria.icono = icono
                categoria.orden = orden
                categoria.save()
                actualizadas += 1
                self.stdout.write(self.style.WARNING(f'🔄 Actualizada: {nombre}'))
            else:
                existentes += 1
                self.stdout.write(self.style.NOTICE(f'ℹ️  Ya existe: {nombre}'))

        # Resumen final
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('📊 RESUMEN DE CATEGORÍAS DE SERVICIOS'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS(f'✅ Creadas: {creadas}'))
        if options['force']:
            self.stdout.write(self.style.WARNING(f'🔄 Actualizadas: {actualizadas}'))
        self.stdout.write(self.style.NOTICE(f'ℹ️  Existentes: {existentes}'))
        self.stdout.write(self.style.SUCCESS(f'📦 Total en base de datos: {CategoriaServicio.objects.count()}'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('✨ Proceso completado exitosamente!'))
