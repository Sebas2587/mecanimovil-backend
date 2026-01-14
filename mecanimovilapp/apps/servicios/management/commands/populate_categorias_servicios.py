"""
Comando de management para poblar las categorías de servicios en la base de datos.
Este comando crea las categorías principales y los servicios asociados tanto para usuarios como para proveedores.
"""
from django.core.management.base import BaseCommand
from datetime import timedelta
from mecanimovilapp.apps.servicios.models import CategoriaServicio, Servicio


class Command(BaseCommand):
    help = 'Pobla la base de datos con las categorías principales y servicios asociados'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Fuerza la actualización de categorías y servicios existentes',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Elimina todas las categorías y servicios existentes antes de crear las nuevas',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('🚀 Iniciando población de categorías y servicios...'))
        
        # Estructura de categorías principales con sus servicios
        categorias_principales = [
            {
                'nombre': '🔍 Diagnóstico e Inspección',
                'descripcion': 'Para saber qué tiene el auto',
                'icono': 'search-outline',
                'orden': 1,
                'servicios': [
                    {
                        'nombre': 'Diagnóstico mecánico',
                        'descripcion': 'Servicio de diagnóstico general del sistema mecánico del vehículo',
                        'duracion_minutos': 60,
                        'requiere_repuestos': False,
                    },
                    {
                        'nombre': 'Diagnóstico electromecánico',
                        'descripcion': 'Diagnóstico de sistemas eléctricos y mecánicos del vehículo',
                        'duracion_minutos': 90,
                        'requiere_repuestos': False,
                    },
                    {
                        'nombre': 'Servicio escáner automotriz',
                        'descripcion': 'Lectura y diagnóstico mediante escáner OBD del vehículo',
                        'duracion_minutos': 45,
                        'requiere_repuestos': False,
                    },
                    {
                        'nombre': 'Revisión precompra',
                        'descripcion': 'Inspección completa del vehículo antes de una compra',
                        'duracion_minutos': 120,
                        'requiere_repuestos': False,
                    },
                    {
                        'nombre': 'Revisión técnica',
                        'descripcion': 'Revisión técnica obligatoria para certificación del vehículo',
                        'duracion_minutos': 60,
                        'requiere_repuestos': False,
                    },
                ]
            },
            {
                'nombre': '🛠️ Mantención Preventiva y Motor',
                'descripcion': 'Para cuidar la vida útil del auto',
                'icono': 'build-outline',
                'orden': 2,
                'servicios': [
                    {
                        'nombre': 'Cambio de aceite motor',
                        'descripcion': 'Reemplazo del aceite del motor del vehículo',
                        'duracion_minutos': 30,
                        'requiere_repuestos': True,
                    },
                    {
                        'nombre': 'Cambio de filtro de aire',
                        'descripcion': 'Reemplazo del filtro de aire del motor',
                        'duracion_minutos': 20,
                        'requiere_repuestos': True,
                    },
                    {
                        'nombre': 'Cambio de filtro habitáculo',
                        'descripcion': 'Reemplazo del filtro de aire del habitáculo (cabina)',
                        'duracion_minutos': 20,
                        'requiere_repuestos': True,
                    },
                    {
                        'nombre': 'Cambio aceite motor y filtro',
                        'descripcion': 'Servicio combinado de cambio de aceite y filtro de aceite',
                        'duracion_minutos': 45,
                        'requiere_repuestos': True,
                    },
                    {
                        'nombre': 'Mantenimiento por kilometraje',
                        'descripcion': 'Servicio de mantenimiento preventivo según kilometraje del vehículo',
                        'duracion_minutos': 120,
                        'requiere_repuestos': True,
                    },
                    {
                        'nombre': 'Cambio de bujías',
                        'descripcion': 'Reemplazo de las bujías del motor',
                        'duracion_minutos': 60,
                        'requiere_repuestos': True,
                    },
                ]
            },
            {
                'nombre': '🛑 Frenos y Seguridad',
                'descripcion': 'Para seguridad crítica',
                'icono': 'car-sport-outline',
                'orden': 3,
                'servicios': [
                    {
                        'nombre': 'Cambio de pastillas de frenos',
                        'descripcion': 'Reemplazo de las pastillas de freno delanteras o traseras',
                        'duracion_minutos': 60,
                        'requiere_repuestos': True,
                    },
                    {
                        'nombre': 'Cambio de pastillas y discos de freno',
                        'descripcion': 'Reemplazo completo de pastillas y discos de freno',
                        'duracion_minutos': 90,
                        'requiere_repuestos': True,
                    },
                    {
                        'nombre': 'Cambio de pastillas de frenos y rectificado',
                        'descripcion': 'Reemplazo de pastillas de freno con rectificado de discos',
                        'duracion_minutos': 120,
                        'requiere_repuestos': True,
                    },
                ]
            },
            {
                'nombre': '⚡ Electricidad y Luces',
                'descripcion': 'Energía y visibilidad',
                'icono': 'flash-outline',
                'orden': 4,
                'servicios': [
                    {
                        'nombre': 'Cambio de batería',
                        'descripcion': 'Reemplazo de la batería del vehículo',
                        'duracion_minutos': 30,
                        'requiere_repuestos': True,
                    },
                    {
                        'nombre': 'Cambio de ampolletas',
                        'descripcion': 'Reemplazo de ampolletas de luces delanteras, traseras o interiores',
                        'duracion_minutos': 30,
                        'requiere_repuestos': True,
                    },
                ]
            },
            {
                'nombre': '✨ Estética y Limpieza',
                'descripcion': 'Cuidado visual',
                'icono': 'water-outline',
                'orden': 5,
                'servicios': [
                    {
                        'nombre': 'Lavado a domicilio',
                        'descripcion': 'Servicio de lavado y detallado del vehículo en la ubicación del cliente',
                        'duracion_minutos': 60,
                        'requiere_repuestos': False,
                    },
                ]
            },
        ]

        # Si se especifica --clear, eliminar todas las categorías y servicios existentes
        if options['clear']:
            self.stdout.write(self.style.WARNING('⚠️  Eliminando todas las categorías y servicios existentes...'))
            servicios_count = Servicio.objects.count()
            categorias_count = CategoriaServicio.objects.count()
            Servicio.objects.all().delete()
            CategoriaServicio.objects.all().delete()
            self.stdout.write(self.style.SUCCESS(f'✅ Eliminados {servicios_count} servicios y {categorias_count} categorías'))

        # Contadores
        categorias_creadas = 0
        categorias_actualizadas = 0
        categorias_existentes = 0
        servicios_creados = 0
        servicios_actualizados = 0
        servicios_existentes = 0

        # Crear categorías principales y sus servicios
        for categoria_data in categorias_principales:
            nombre_categoria = categoria_data['nombre']
            descripcion_categoria = categoria_data.get('descripcion', '')
            icono_categoria = categoria_data.get('icono', '')
            orden_categoria = categoria_data.get('orden', 0)
            servicios_data = categoria_data.get('servicios', [])

            # Crear o actualizar categoría principal
            categoria, cat_created = CategoriaServicio.objects.get_or_create(
                nombre=nombre_categoria,
                defaults={
                    'descripcion': descripcion_categoria,
                    'icono': icono_categoria,
                    'orden': orden_categoria,
                    'categoria_padre': None,  # Categoría principal sin padre
                }
            )

            if cat_created:
                categorias_creadas += 1
                self.stdout.write(self.style.SUCCESS(f'✅ Categoría creada: {nombre_categoria}'))
            elif options['force']:
                categoria.descripcion = descripcion_categoria
                categoria.icono = icono_categoria
                categoria.orden = orden_categoria
                categoria.categoria_padre = None
                categoria.save()
                categorias_actualizadas += 1
                self.stdout.write(self.style.WARNING(f'🔄 Categoría actualizada: {nombre_categoria}'))
            else:
                categorias_existentes += 1
                self.stdout.write(self.style.NOTICE(f'ℹ️  Categoría ya existe: {nombre_categoria}'))

            # Crear servicios asociados a esta categoría
            self.stdout.write(f'   📦 Creando servicios para {nombre_categoria}...')
            
            for servicio_data in servicios_data:
                nombre_servicio = servicio_data['nombre']
                descripcion_servicio = servicio_data.get('descripcion', '')
                duracion_minutos = servicio_data.get('duracion_minutos', 60)
                requiere_repuestos = servicio_data.get('requiere_repuestos', True)

                # Convertir duración de minutos a timedelta
                duracion = timedelta(minutes=duracion_minutos)

                # Crear o actualizar servicio
                servicio, serv_created = Servicio.objects.get_or_create(
                    nombre=nombre_servicio,
                    defaults={
                        'descripcion': descripcion_servicio,
                        'duracion_estimada_base': duracion,
                        'requiere_repuestos': requiere_repuestos,
                        'precio_referencia': 0,  # Se establecerá por los proveedores
                    }
                )

                if serv_created:
                    servicios_creados += 1
                    self.stdout.write(self.style.SUCCESS(f'      ✅ Servicio creado: {nombre_servicio}'))
                elif options['force']:
                    servicio.descripcion = descripcion_servicio
                    servicio.duracion_estimada_base = duracion
                    servicio.requiere_repuestos = requiere_repuestos
                    servicio.save()
                    servicios_actualizados += 1
                    self.stdout.write(self.style.WARNING(f'      🔄 Servicio actualizado: {nombre_servicio}'))
                else:
                    servicios_existentes += 1
                    self.stdout.write(self.style.NOTICE(f'      ℹ️  Servicio ya existe: {nombre_servicio}'))

                # Asociar servicio a la categoría (ManyToMany)
                if not servicio.categorias.filter(id=categoria.id).exists():
                    servicio.categorias.add(categoria)
                    self.stdout.write(self.style.SUCCESS(f'      🔗 Servicio asociado a categoría: {nombre_servicio} → {nombre_categoria}'))

        # Resumen final
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(self.style.SUCCESS('📊 RESUMEN DE POBLACIÓN DE BASE DE DATOS'))
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('📁 CATEGORÍAS:'))
        self.stdout.write(self.style.SUCCESS(f'   ✅ Creadas: {categorias_creadas}'))
        if options['force']:
            self.stdout.write(self.style.WARNING(f'   🔄 Actualizadas: {categorias_actualizadas}'))
        self.stdout.write(self.style.NOTICE(f'   ℹ️  Existentes: {categorias_existentes}'))
        self.stdout.write(self.style.SUCCESS(f'   📦 Total en base de datos: {CategoriaServicio.objects.count()}'))
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('🔧 SERVICIOS:'))
        self.stdout.write(self.style.SUCCESS(f'   ✅ Creados: {servicios_creados}'))
        if options['force']:
            self.stdout.write(self.style.WARNING(f'   🔄 Actualizados: {servicios_actualizados}'))
        self.stdout.write(self.style.NOTICE(f'   ℹ️  Existentes: {servicios_existentes}'))
        self.stdout.write(self.style.SUCCESS(f'   📦 Total en base de datos: {Servicio.objects.count()}'))
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(self.style.SUCCESS('✨ Proceso completado exitosamente!'))
