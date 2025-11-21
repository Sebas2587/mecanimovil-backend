import random
import datetime
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.gis.geos import Point

# Importar modelos
from django.contrib.auth import get_user_model
from mecanimovilapp.apps.usuarios.models import Cliente, MecanicoDomicilio, Taller
from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo, Modelo, Vehiculo
from mecanimovilapp.apps.servicios.models import CategoriaServicio, Servicio, PrecioServicioTaller, PrecioServicioMecanico
from mecanimovilapp.apps.ordenes.models import Disponibilidad, SolicitudServicio, LineaServicio

Usuario = get_user_model()

class Command(BaseCommand):
    help = 'Carga datos iniciales para la aplicaciu00f3n MecaniMovil'

    def handle(self, *args, **options):
        self.stdout.write('Cargando datos iniciales para MecaniMovil...')
        
        # Llamar a mu00e9todos de carga de datos
        self.crear_usuarios()
        self.crear_categorias_servicios()
        self.crear_talleres()
        self.crear_mecanicos()
        self.crear_servicios()
        self.crear_disponibilidades()
        self.crear_vehiculos()
        self.crear_solicitudes()
        
        self.stdout.write(self.style.SUCCESS('Datos iniciales cargados con u00e9xito.'))
    
    def crear_usuarios(self):
        self.stdout.write('Creando usuarios...')
        
        # Crear usuarios de tipo cliente
        clientes_data = [
            {
                'username': 'cliente1',
                'email': 'cliente1@example.com',
                'password': 'password123',
                'first_name': 'Juan',
                'last_name': 'Pu00e9rez',
                'nombre': 'Juan',
                'apellido': 'Pu00e9rez',
                'telefono': '5551234567',
                'direccion': 'Calle Principal 123, Ciudad de Mu00e9xico',
                'ubicacion': Point(-99.1332, 19.4326),  # CDMX centro
            },
            {
                'username': 'cliente2',
                'email': 'cliente2@example.com',
                'password': 'password123',
                'first_name': 'Ana',
                'last_name': 'Gu00f3mez',
                'nombre': 'Ana',
                'apellido': 'Gu00f3mez',
                'telefono': '5557654321',
                'direccion': 'Av. Reforma 456, Ciudad de Mu00e9xico',
                'ubicacion': Point(-99.1674, 19.4200),  # Reforma
            },
            {
                'username': 'cliente3',
                'email': 'cliente3@example.com',
                'password': 'password123',
                'first_name': 'Carlos',
                'last_name': 'Lara',
                'nombre': 'Carlos',
                'apellido': 'Lara',
                'telefono': '5559876543',
                'direccion': 'Calle Sur 789, Ciudad de Mu00e9xico',
                'ubicacion': Point(-99.1590, 19.3810),  # Coyoacu00e1n
            },
        ]
        
        for cliente_data in clientes_data:
            username = cliente_data.pop('username')
            email = cliente_data.pop('email')
            password = cliente_data.pop('password')
            first_name = cliente_data.pop('first_name')
            last_name = cliente_data.pop('last_name')
            nombre = cliente_data.pop('nombre')
            apellido = cliente_data.pop('apellido')
            telefono = cliente_data.pop('telefono')
            direccion = cliente_data.pop('direccion')
            ubicacion = cliente_data.pop('ubicacion')
            
            # Crear usuario
            user, created = Usuario.objects.get_or_create(
                username=username,
                defaults={
                    'email': email,
                    'first_name': first_name,
                    'last_name': last_name,
                    'telefono': telefono,
                    'direccion': direccion,
                }
            )
            
            if created:
                user.set_password(password)
                user.save()
                self.stdout.write(self.style.SUCCESS(f'Usuario creado: {username}'))
            
            # Crear cliente asociado
            cliente, created = Cliente.objects.get_or_create(
                usuario=user,
                defaults={
                    'nombre': nombre,
                    'apellido': apellido,
                    'email': email,
                    'telefono': telefono,
                    'direccion': direccion,
                    'ubicacion': ubicacion
                }
            )
            
            if created:
                self.stdout.write(self.style.SUCCESS(f'Cliente creado: {nombre} {apellido}'))
    
    def crear_categorias_servicios(self):
        self.stdout.write('Creando categoru00edas de servicios...')
        
        categorias_data = [
            "Mantenimiento preventivo",
            "Reparaciu00f3n de motor",
            "Sistema de frenos",
            "Sistema de suspenciu00f3n",
            "Sistema elu00e9ctrico",
            "Aire acondicionado",
            "Transmiciu00f3n",
            "Diagnu00f3stico general",
            "Afinaciones",
            "Cambio de aceite",
            "Alineaciu00f3n y balanceo",
            "Reparaciu00f3n de carroceru00eda",
        ]
        
        for nombre in categorias_data:
            categoria, created = CategoriaServicio.objects.get_or_create(nombre=nombre)
            
            if created:
                self.stdout.write(self.style.SUCCESS(f'Categoru00eda creada: {nombre}'))

    def crear_talleres(self):
        self.stdout.write('Creando talleres...')
        
        talleres_data = [
            {
                'nombre': 'Taller Mu00e9canico Central',
                'direccion': 'Av. Universidad 3000, Coyoacu00e1n, CDMX',
                'ubicacion': Point(-99.1740, 19.3185),
                'telefono': '5551234567',
                'horario_atencion': 'Lunes a Viernes 9:00 - 18:00, Su00e1bado 9:00 - 14:00',
            },
            {
                'nombre': 'Servicio Express Automotriz',
                'direccion': 'Calzada de Tlalpan 2345, Iztapalapa, CDMX',
                'ubicacion': Point(-99.1118, 19.3576),
                'telefono': '5552345678',
                'horario_atencion': 'Lunes a Su00e1bado 8:00 - 20:00',
            },
            {
                'nombre': 'Taller Mu00e9canico del Norte',
                'direccion': 'Av. Insurgentes Norte 480, Atlampa, CDMX',
                'ubicacion': Point(-99.1520, 19.4582),
                'telefono': '5553456789',
                'horario_atencion': 'Lunes a Viernes 8:30 - 19:00, Su00e1bado 9:00 - 15:00',
            },
        ]
        
        for taller_data in talleres_data:
            taller, created = Taller.objects.get_or_create(
                nombre=taller_data['nombre'],
                defaults={
                    'direccion': taller_data['direccion'],
                    'ubicacion': taller_data['ubicacion'],
                    'telefono': taller_data['telefono'],
                    'horario_atencion': taller_data['horario_atencion'],
                }
            )
            
            if created:
                self.stdout.write(self.style.SUCCESS(f'Taller creado: {taller.nombre}'))
    
    def crear_mecanicos(self):
        self.stdout.write('Creando mecu00e1nicos a domicilio...')
        
        mecanicos_data = [
            {
                'username': 'mecanico1',
                'email': 'mecanico1@example.com',
                'password': 'password123',
                'first_name': 'Roberto',
                'last_name': 'Mu00e9ndez',
                'nombre': 'Roberto Mu00e9ndez',
                'telefono': '5554567890',
                'ubicacion': Point(-99.1453, 19.4240),  # Zona centro
                'disponible': True,
                'especialidades': ["Mantenimiento preventivo", "Diagnu00f3stico general", "Cambio de aceite"],
            },
            {
                'username': 'mecanico2',
                'email': 'mecanico2@example.com',
                'password': 'password123',
                'first_name': 'Miguel',
                'last_name': 'Zu00fau00f1iga',
                'nombre': 'Miguel Zu00fau00f1iga',
                'telefono': '5555678901',
                'ubicacion': Point(-99.2034, 19.3729),  # Zona sur
                'disponible': True,
                'especialidades': ["Sistema de frenos", "Sistema de suspenciu00f3n", "Alineaciu00f3n y balanceo"],
            },
            {
                'username': 'mecanico3',
                'email': 'mecanico3@example.com',
                'password': 'password123',
                'first_name': 'Laura',
                'last_name': 'Ramos',
                'nombre': 'Laura Ramos',
                'telefono': '5556789012',
                'ubicacion': Point(-99.1280, 19.4773),  # Zona norte
                'disponible': True,
                'especialidades': ["Sistema elu00e9ctrico", "Aire acondicionado", "Diagnu00f3stico general"],
            },
        ]
        
        for mecanico_data in mecanicos_data:
            username = mecanico_data.pop('username')
            email = mecanico_data.pop('email')
            password = mecanico_data.pop('password')
            first_name = mecanico_data.pop('first_name')
            last_name = mecanico_data.pop('last_name')
            nombre = mecanico_data.pop('nombre')
            telefono = mecanico_data.pop('telefono')
            ubicacion = mecanico_data.pop('ubicacion')
            disponible = mecanico_data.pop('disponible')
            especialidades_nombres = mecanico_data.pop('especialidades')
            
            # Crear usuario
            user, created = Usuario.objects.get_or_create(
                username=username,
                defaults={
                    'email': email,
                    'first_name': first_name,
                    'last_name': last_name,
                    'es_mecanico': True,
                    'telefono': telefono,
                }
            )
            
            if created:
                user.set_password(password)
                user.save()
                self.stdout.write(self.style.SUCCESS(f'Usuario mecu00e1nico creado: {username}'))
            
            # Crear mecu00e1nico asociado
            mecanico, created = MecanicoDomicilio.objects.get_or_create(
                usuario=user,
                defaults={
                    'nombre': nombre,
                    'telefono': telefono,
                    'ubicacion': ubicacion,
                    'disponible': disponible,
                }
            )
            
            if created:
                # Asociar especialidades
                for esp_nombre in especialidades_nombres:
                    try:
                        categoria = CategoriaServicio.objects.get(nombre=esp_nombre)
                        mecanico.especialidades.add(categoria)
                    except CategoriaServicio.DoesNotExist:
                        self.stdout.write(self.style.WARNING(f'Categoru00eda no encontrada: {esp_nombre}'))
                
                self.stdout.write(self.style.SUCCESS(f'Mecu00e1nico creado: {nombre}')) 

    def crear_servicios(self):
        self.stdout.write('Creando servicios...')
        
        servicios_data = [
            {
                'nombre': 'Cambio de aceite y filtro',
                'descripcion': 'Cambio completo de aceite y filtro de aceite',
                'categoria': 'Mantenimiento preventivo',
                'duracion_aprox': 45,  # en minutos
            },
            {
                'nombre': 'Afinación básica',
                'descripcion': 'Incluye cambio de bujías, filtro de aire y revisión de sistemas',
                'categoria': 'Afinaciones',
                'duracion_aprox': 120,  # en minutos
            },
            {
                'nombre': 'Afinación mayor',
                'descripcion': 'Afinación completa con cambio de cables, bujías, filtros y limpieza de inyectores',
                'categoria': 'Afinaciones',
                'duracion_aprox': 180,  # en minutos
            },
            {
                'nombre': 'Diagnóstico computarizado',
                'descripcion': 'Revisión completa con equipo de diagnóstico para detectar fallas',
                'categoria': 'Diagnóstico general',
                'duracion_aprox': 60,  # en minutos
            },
            {
                'nombre': 'Cambio de pastillas de freno',
                'descripcion': 'Sustitución de pastillas de freno delanteras o traseras',
                'categoria': 'Sistema de frenos',
                'duracion_aprox': 90,  # en minutos
            },
            {
                'nombre': 'Cambio de discos de freno',
                'descripcion': 'Reemplazo de discos de freno desgastados',
                'categoria': 'Sistema de frenos',
                'duracion_aprox': 120,  # en minutos
            },
            {
                'nombre': 'Reparación de alternador',
                'descripcion': 'Diagnóstico y reparación del sistema de carga',
                'categoria': 'Sistema eléctrico',
                'duracion_aprox': 150,  # en minutos
            },
            {
                'nombre': 'Alineación y balanceo',
                'descripcion': 'Alineación de dirección y balanceo de ruedas',
                'categoria': 'Alineación y balanceo',
                'duracion_aprox': 60,  # en minutos
            },
            {
                'nombre': 'Recarga de aire acondicionado',
                'descripcion': 'Recarga de gas refrigerante y revisión del sistema',
                'categoria': 'Aire acondicionado',
                'duracion_aprox': 90,  # en minutos
            },
            {
                'nombre': 'Cambio de amortiguadores',
                'descripcion': 'Sustitución de amortiguadores delanteros o traseros',
                'categoria': 'Sistema de suspensión',
                'duracion_aprox': 180,  # en minutos
            },
        ]
        
        for servicio_data in servicios_data:
            categoria_nombre = servicio_data.pop('categoria')
            duracion_minutos = servicio_data.pop('duracion_aprox')
            
            # Convertir duración de minutos a formato de tiempo
            horas = duracion_minutos // 60
            minutos = duracion_minutos % 60
            duracion = datetime.time(hour=horas, minute=minutos)
            
            try:
                categoria = CategoriaServicio.objects.get(nombre=categoria_nombre)
                
                # Crear servicio sin relaciones m2m
                servicio, created = Servicio.objects.get_or_create(
                    nombre=servicio_data['nombre'],
                    defaults={
                        'descripcion': servicio_data['descripcion'],
                        'duracion_estimada': duracion,
                    }
                )
                
                if created:
                    self.stdout.write(self.style.SUCCESS(f'Servicio creado: {servicio.nombre}'))
                    
                    # Asociar categoría al servicio
                    from mecanimovilapp.apps.servicios.models import ServicioCategoria
                    ServicioCategoria.objects.get_or_create(
                        servicio=servicio,
                        categoria=categoria
                    )
                    
                    # Crear relaciones con talleres
                    talleres = Taller.objects.all()
                    for taller in talleres:
                        # Asociar servicio con taller
                        from mecanimovilapp.apps.servicios.models import ServicioTaller
                        servicio_taller, _ = ServicioTaller.objects.get_or_create(
                            servicio=servicio,
                            taller=taller
                        )
                        
                        # Generar precios base + variación aleatoria
                        base_precio_con = random.randint(800, 3500)
                        base_precio_sin = random.randint(500, 3000)
                        precio_con_repuestos = Decimal(base_precio_con + random.randint(-100, 300))
                        precio_sin_repuestos = Decimal(base_precio_sin + random.randint(-100, 300))
                        
                        # Crear precio para el servicio y taller
                        PrecioServicioTaller.objects.get_or_create(
                            servicio=servicio,
                            taller=taller,
                            defaults={
                                'precio_con_repuestos': precio_con_repuestos,
                                'precio_sin_repuestos': precio_sin_repuestos,
                            }
                        )
                    
                    # Crear relaciones con mecánicos a domicilio
                    mecanicos = MecanicoDomicilio.objects.all()
                    for mecanico in mecanicos:
                        # Solo crear si la categoría está en sus especialidades
                        if categoria in mecanico.especialidades.all():
                            # Asociar servicio con mecánico
                            from mecanimovilapp.apps.servicios.models import ServicioMecanico
                            servicio_mecanico, _ = ServicioMecanico.objects.get_or_create(
                                servicio=servicio,
                                mecanico=mecanico
                            )
                            
                            # Precio un poco mayor por ser a domicilio (10-15% más)
                            base_precio_con = random.randint(1000, 4000)
                            base_precio_sin = random.randint(600, 3500)
                            precio_con_repuestos = Decimal(base_precio_con + random.randint(-50, 400))
                            precio_sin_repuestos = Decimal(base_precio_sin + random.randint(-50, 400))
                            
                            # Crear precio para el servicio y mecánico
                            PrecioServicioMecanico.objects.get_or_create(
                                servicio=servicio,
                                mecanico=mecanico,
                                defaults={
                                    'precio_con_repuestos': precio_con_repuestos,
                                    'precio_sin_repuestos': precio_sin_repuestos,
                                }
                            )
                
            except CategoriaServicio.DoesNotExist:
                self.stdout.write(self.style.WARNING(f'Categoría no encontrada: {categoria_nombre}')) 

    def crear_disponibilidades(self):
        self.stdout.write('Creando disponibilidades...')
        
        # Fechas para la próxima semana
        hoy = timezone.now().date()
        fechas = [hoy + datetime.timedelta(days=i) for i in range(1, 8)]  # Próximos 7 días
        
        # Crear disponibilidades para talleres
        talleres = Taller.objects.all()
        for taller in talleres:
            self.stdout.write(f'Creando disponibilidades para taller: {taller.nombre}')
            
            for fecha in fechas:
                # De lunes a viernes
                if fecha.weekday() < 5:  # 0-4 son lunes a viernes
                    # Crear slots de horarios típicos de taller
                    horarios = [
                        {'hora_inicio': '09:00', 'hora_fin': '11:00'},
                        {'hora_inicio': '11:00', 'hora_fin': '13:00'},
                        {'hora_inicio': '13:00', 'hora_fin': '15:00'},
                        {'hora_inicio': '15:00', 'hora_fin': '17:00'},
                        {'hora_inicio': '17:00', 'hora_fin': '19:00'},
                    ]
                # Sábado
                elif fecha.weekday() == 5:
                    horarios = [
                        {'hora_inicio': '09:00', 'hora_fin': '11:00'},
                        {'hora_inicio': '11:00', 'hora_fin': '13:00'},
                        {'hora_inicio': '13:00', 'hora_fin': '15:00'},
                    ]
                # Domingo (algunos talleres)
                else:
                    if random.choice([True, False]):  # 50% chance de estar abierto en domingo
                        horarios = [
                            {'hora_inicio': '10:00', 'hora_fin': '12:00'},
                            {'hora_inicio': '12:00', 'hora_fin': '14:00'},
                        ]
                    else:
                        horarios = []
                
                for horario in horarios:
                    # 80% de probabilidad de que el slot esté disponible
                    if random.random() < 0.8:
                        fecha_str = fecha.strftime('%Y-%m-%d')
                        hora_inicio = datetime.datetime.strptime(f"{fecha_str} {horario['hora_inicio']}", '%Y-%m-%d %H:%M')
                        hora_fin = datetime.datetime.strptime(f"{fecha_str} {horario['hora_fin']}", '%Y-%m-%d %H:%M')
                        
                        # Convertir a timezone-aware
                        hora_inicio = timezone.make_aware(hora_inicio)
                        hora_fin = timezone.make_aware(hora_fin)
                        
                        disponibilidad, created = Disponibilidad.objects.get_or_create(
                            taller=taller,
                            fecha=fecha,
                            hora_inicio=hora_inicio,
                            hora_fin=hora_fin,
                            defaults={
                                'disponible': True,
                                'mecanico': None
                            }
                        )
                        
                        if created:
                            self.stdout.write(self.style.SUCCESS(
                                f'Disponibilidad creada para {taller.nombre} - {fecha} - {horario["hora_inicio"]} a {horario["hora_fin"]}'
                            ))
        
        # Crear disponibilidades para mecánicos a domicilio
        mecanicos = MecanicoDomicilio.objects.all()
        for mecanico in mecanicos:
            self.stdout.write(f'Creando disponibilidades para mecánico: {mecanico.nombre}')
            
            for fecha in fechas:
                # Los mecánicos tienen horarios más variables que los talleres
                
                # De lunes a viernes
                if fecha.weekday() < 5:
                    if random.random() < 0.9:  # 90% chance de trabajar días entre semana
                        horarios = [
                            {'hora_inicio': '08:00', 'hora_fin': '10:00'},
                            {'hora_inicio': '10:00', 'hora_fin': '12:00'},
                            {'hora_inicio': '12:00', 'hora_fin': '14:00'},
                            {'hora_inicio': '16:00', 'hora_fin': '18:00'},
                            {'hora_inicio': '18:00', 'hora_fin': '20:00'},
                        ]
                    else:
                        horarios = []  # Día libre
                # Sábado
                elif fecha.weekday() == 5:
                    if random.random() < 0.7:  # 70% chance de trabajar sábados
                        horarios = [
                            {'hora_inicio': '09:00', 'hora_fin': '11:00'},
                            {'hora_inicio': '11:00', 'hora_fin': '13:00'},
                            {'hora_inicio': '13:00', 'hora_fin': '15:00'},
                        ]
                    else:
                        horarios = []  # Día libre
                # Domingo
                else:
                    if random.random() < 0.4:  # 40% chance de trabajar domingos
                        horarios = [
                            {'hora_inicio': '10:00', 'hora_fin': '12:00'},
                            {'hora_inicio': '12:00', 'hora_fin': '14:00'},
                        ]
                    else:
                        horarios = []  # Día libre
                
                for horario in horarios:
                    # 70% de probabilidad de que el slot esté disponible
                    if random.random() < 0.7:
                        fecha_str = fecha.strftime('%Y-%m-%d')
                        hora_inicio = datetime.datetime.strptime(f"{fecha_str} {horario['hora_inicio']}", '%Y-%m-%d %H:%M')
                        hora_fin = datetime.datetime.strptime(f"{fecha_str} {horario['hora_fin']}", '%Y-%m-%d %H:%M')
                        
                        # Convertir a timezone-aware
                        hora_inicio = timezone.make_aware(hora_inicio)
                        hora_fin = timezone.make_aware(hora_fin)
                        
                        disponibilidad, created = Disponibilidad.objects.get_or_create(
                            mecanico=mecanico,
                            fecha=fecha,
                            hora_inicio=hora_inicio,
                            hora_fin=hora_fin,
                            defaults={
                                'disponible': True,
                                'taller': None
                            }
                        )
                        
                        if created:
                            self.stdout.write(self.style.SUCCESS(
                                f'Disponibilidad creada para {mecanico.nombre} - {fecha} - {horario["hora_inicio"]} a {horario["hora_fin"]}'
                            )) 

    def crear_vehiculos(self):
        self.stdout.write('Creando vehículos para clientes...')
        
        # Crear algunas marcas y modelos
        marcas_data = {
            'Toyota': ['Corolla', 'Camry', 'RAV4', 'Hilux'],
            'Nissan': ['Sentra', 'Versa', 'X-Trail', 'Frontier'],
            'Volkswagen': ['Jetta', 'Golf', 'Tiguan', 'Amarok'],
            'Honda': ['Civic', 'Accord', 'CR-V', 'Pilot'],
            'Chevrolet': ['Aveo', 'Cruze', 'Spark', 'Suburban'],
            'Ford': ['Focus', 'Fiesta', 'Escape', 'Ranger'],
            'Mazda': ['3', '6', 'CX-5', 'CX-30'],
            'Hyundai': ['Elantra', 'Accent', 'Tucson', 'Santa Fe'],
            'Kia': ['Rio', 'Forte', 'Sportage', 'Seltos'],
            'BMW': ['Serie 3', 'Serie 5', 'X3', 'X5'],
        }
        
        for marca_nombre, modelos in marcas_data.items():
            marca, created = MarcaVehiculo.objects.get_or_create(nombre=marca_nombre)
            if created:
                self.stdout.write(self.style.SUCCESS(f'Marca creada: {marca_nombre}'))
            
            for modelo_nombre in modelos:
                modelo, created = Modelo.objects.get_or_create(
                    nombre=modelo_nombre,
                    marca=marca
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f'Modelo creado: {marca_nombre} {modelo_nombre}'))
        
        # Crear vehículos para clientes
        clientes = Cliente.objects.all()
        modelos = Modelo.objects.all()
        colores = ['Rojo', 'Blanco', 'Negro', 'Gris', 'Azul', 'Plata', 'Verde', 'Amarillo', 'Beige', 'Café']
        
        # Cada cliente tendrá entre 1 y 3 vehículos
        for cliente in clientes:
            num_vehiculos = random.randint(1, 3)
            
            for i in range(num_vehiculos):
                modelo = random.choice(modelos)
                year = random.randint(2000, 2023)
                color = random.choice(colores)
                vin = f'VIN{random.randint(1000000, 9999999)}'
                patente = f'{random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}{random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}{random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}{random.randint(100, 999)}{random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}'
                tipo_motor = random.choice(['Gasolina', 'Diésel', 'Eléctrico', 'Híbrido'])
                
                vehiculo, created = Vehiculo.objects.get_or_create(
                    cliente=cliente,
                    modelo=modelo,
                    year=year,
                    defaults={
                        'marca': modelo.marca,
                        'patente': patente,
                        'kilometraje': random.randint(5000, 200000),
                        'tipo_motor': tipo_motor,
                        'cilindraje': f'{random.choice(["1.6", "2.0", "2.5", "3.0", "1.8", "1.4", "2.2", "4.0"])} L',
                    }
                )
                
                if created:
                    self.stdout.write(self.style.SUCCESS(
                        f'Vehículo creado para {cliente.nombre} {cliente.apellido}: {modelo.marca.nombre} {modelo.nombre} {year}'
                    )) 

    def crear_solicitudes(self):
        self.stdout.write('Creando solicitudes de servicio...')
        
        # Obtener datos necesarios
        clientes = Cliente.objects.all()
        talleres = Taller.objects.all()
        mecanicos = MecanicoDomicilio.objects.all()
        servicios = Servicio.objects.all()
        
        # Estados posibles de solicitud
        estados = [
            'pendiente',
            'en_proceso',
            'completado',
            'cancelado',
        ]
        
        # Crear entre 10 y 20 solicitudes
        num_solicitudes = random.randint(10, 20)
        
        for i in range(num_solicitudes):
            # Seleccionar cliente y obtener uno de sus vehículos
            cliente = random.choice(clientes)
            vehiculos = Vehiculo.objects.filter(cliente=cliente)
            
            if not vehiculos.exists():
                continue  # Saltar si el cliente no tiene vehículos
                
            vehiculo = random.choice(vehiculos)
            
            # Decidir si es servicio en taller o a domicilio (60% taller, 40% domicilio)
            if random.random() < 0.6:
                taller = random.choice(talleres)
                mecanico = None
                ubicacion_servicio = taller.direccion
                tipo_servicio = 'taller'
            else:
                taller = None
                mecanico = random.choice(mecanicos)
                ubicacion_servicio = cliente.direccion
                tipo_servicio = 'domicilio'
            
            # Generar fecha y hora aleatoria en los últimos 30 días
            dias_atras = random.randint(0, 30)
            fecha_creacion = timezone.now() - datetime.timedelta(days=dias_atras)
            
            # Si la fecha es futura, los estados posibles son más limitados
            fecha_servicio = fecha_creacion + datetime.timedelta(days=random.randint(1, 7))
            hora_servicio = datetime.time(
                hour=random.randint(9, 17),
                minute=random.choice([0, 30])
            )
            
            # Estados según la fecha
            if fecha_servicio.date() > timezone.now().date():
                posibles_estados = ['pendiente']
                estado = 'pendiente'
            else:
                # Para fechas pasadas, puede tener cualquier estado
                estado = random.choice(estados)
            
            # Método de pago aleatorio
            metodo_pago = random.choice(['efectivo', 'debito', 'credito', 'transferencia'])
            
            try:
                # Crear la solicitud (el total se calcula al final)
                solicitud = SolicitudServicio.objects.create(
                    cliente=cliente,
                    vehiculo=vehiculo,
                    taller=taller,
                    mecanico=mecanico,
                    tipo_servicio=tipo_servicio,
                    fecha_hora_solicitud=fecha_creacion,
                    fecha_servicio=fecha_servicio.date(),
                    hora_servicio=hora_servicio,
                    estado=estado,
                    ubicacion_servicio=ubicacion_servicio,
                    metodo_pago=metodo_pago,
                    total=Decimal('0.00'),  # Se actualiza después
                )
                
                self.stdout.write(self.style.SUCCESS(
                    f'Solicitud creada: {solicitud.id} - Cliente: {cliente.nombre} - Estado: {estado}'
                ))
                
                # Crear entre 1 y 3 líneas de servicio para esta solicitud
                num_lineas = random.randint(1, 3)
                
                # Calcular precio total
                precio_total = Decimal('0.00')
                
                for j in range(num_lineas):
                    # Seleccionar un servicio aleatorio
                    servicio = random.choice(servicios)
                    
                    # Determinar precio según el tipo de servicio
                    precio_servicio_taller = None
                    precio_servicio_mecanico = None
                    con_repuestos = random.choice([True, False])
                    
                    if tipo_servicio == 'taller':
                        try:
                            # Buscar precio existente
                            precio_ref = PrecioServicioTaller.objects.filter(
                                servicio=servicio,
                                taller=taller
                            ).first()
                            
                            if precio_ref:
                                precio_servicio_taller = precio_ref
                                # Determinar precio según si lleva repuestos o no
                                if con_repuestos:
                                    precio_final = precio_ref.precio_con_repuestos
                                else:
                                    precio_final = precio_ref.precio_sin_repuestos
                            else:
                                # Si no hay precio, generar uno aleatorio
                                precio_final = Decimal(str(random.randint(500, 3000)))
                        except Exception as e:
                            # En caso de error, generar precio aleatorio
                            precio_final = Decimal(str(random.randint(500, 3000)))
                            self.stdout.write(self.style.WARNING(f'Error al obtener precio para taller: {e}'))
                    else:
                        try:
                            # Buscar precio existente para mecánico
                            precio_ref = PrecioServicioMecanico.objects.filter(
                                servicio=servicio,
                                mecanico=mecanico
                            ).first()
                            
                            if precio_ref:
                                precio_servicio_mecanico = precio_ref
                                # Determinar precio según si lleva repuestos o no
                                if con_repuestos:
                                    precio_final = precio_ref.precio_con_repuestos
                                else:
                                    precio_final = precio_ref.precio_sin_repuestos
                            else:
                                # Si no hay precio, generar uno aleatorio
                                precio_final = Decimal(str(random.randint(700, 3500)))
                        except Exception as e:
                            # En caso de error, generar precio aleatorio
                            precio_final = Decimal(str(random.randint(700, 3500)))
                            self.stdout.write(self.style.WARNING(f'Error al obtener precio para mecánico: {e}'))
                    
                    # Crear la línea de servicio
                    linea = LineaServicio.objects.create(
                        solicitud=solicitud,
                        servicio=servicio,
                        precio_servicio_taller=precio_servicio_taller,
                        precio_servicio_mecanico=precio_servicio_mecanico,
                        con_repuestos=con_repuestos,
                        precio_final=precio_final,
                    )
                    
                    precio_total += precio_final
                    
                    self.stdout.write(self.style.SUCCESS(
                        f'  - Línea de servicio creada: {servicio.nombre} - Precio: ${precio_final}'
                    ))
                
                # Actualizar el precio total de la solicitud
                solicitud.total = precio_total
                solicitud.save()
                
                self.stdout.write(self.style.SUCCESS(
                    f'  Precio total de la solicitud: ${precio_total}'
                ))
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error al crear solicitud: {e}')) 