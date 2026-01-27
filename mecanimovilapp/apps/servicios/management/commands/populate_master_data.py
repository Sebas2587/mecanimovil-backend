from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from mecanimovilapp.apps.servicios.models import CategoriaServicio, Servicio, OfertaServicio
from mecanimovilapp.apps.usuarios.models import MecanicoDomicilio, Taller, MechanicServiceArea
from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo, Modelo
from django.contrib.gis.geos import Point
import random
from decimal import Decimal

Usuario = get_user_model()

class Command(BaseCommand):
    help = 'Populates the database with master data for services, categories, mechanics, workshops, brands and service zones'

    def handle(self, *args, **kwargs):
        self.stdout.write('Starting data population (v2)...')

        # 0. Create Brands and Models (if not exist)
        brands_data = [
            ('Mazda', ['CX-5', '3', 'CX-3']),
            ('Toyota', ['Corolla', 'Yaris', 'RAV4', 'Hilux']),
            ('Chevrolet', ['Sail', 'Spark', 'Cruze']),
            ('Hyundai', ['Accent', 'Tucson', 'Santa Fe']),
            ('Kia', ['Rio', 'Sportage', 'Morning']),
            ('Fiat', ['Mobi', 'Argo', 'Cronos', 'Pulse'])
        ]
        
        all_brands = []
        for brand_name, models_list in brands_data:
            # Try case-insensitive get first
            brand = MarcaVehiculo.objects.filter(nombre__iexact=brand_name).first()
            if not brand:
                brand = MarcaVehiculo.objects.create(nombre=brand_name)
                self.stdout.write(f'Created brand: {brand_name}')
            else:
                self.stdout.write(f'Found existing brand: {brand.nombre} (matches {brand_name})')
                
            all_brands.append(brand)
            
            for model_name in models_list:
                Modelo.objects.get_or_create(nombre=model_name, marca=brand)

        # 1. Create Categories
        categories_data = [
            'Diagnóstico e Inspección',
            'Mantención Preventiva y Motor',
            'Frenos y Seguridad',
            'Electricidad y Luces',
            'Estética y Limpieza'
        ]
        
        categories = {}
        for cat_name in categories_data:
            cat, created = CategoriaServicio.objects.get_or_create(nombre=cat_name)
            categories[cat_name] = cat
        
        # 2. Create Services
        # Format: (Name, Category Name, Reference Price)
        services_data = [
            ('Lavado a domicilio', 'Estética y Limpieza', 25000),
            ('Cambio de ampolletas', 'Electricidad y Luces', 15000),
            ('Cambio de batería', 'Electricidad y Luces', 20000),
            ('Cambio de pastillas de frenos y rectificado', 'Frenos y Seguridad', 60000),
            ('Cambio de pastillas y discos de freno', 'Frenos y Seguridad', 80000),
            ('Cambio de pastillas de frenos', 'Frenos y Seguridad', 40000),
            ('Cambio de bujías', 'Mantención Preventiva y Motor', 35000),
            ('Mantenimiento por kilometraje', 'Mantención Preventiva y Motor', 120000),
            ('Cambio aceite motor y filtro', 'Mantención Preventiva y Motor', 45000),
            ('Cambio de filtro habitáculo', 'Mantención Preventiva y Motor', 15000),
            ('Cambio de filtro de aire', 'Mantención Preventiva y Motor', 15000),
            ('Cambio de aceite motor', 'Mantención Preventiva y Motor', 35000),
            ('Revisión técnica', 'Diagnóstico e Inspección', 30000),
            ('Revisión precompra', 'Diagnóstico e Inspección', 50000),
            ('Servicio escáner automotriz', 'Diagnóstico e Inspección', 25000),
            ('Diagnóstico electromecánico', 'Diagnóstico e Inspección', 45000),
            ('Diagnóstico mecánico', 'Diagnóstico e Inspección', 40000),
        ]

        created_services = []
        for srv_name, cat_name, price in services_data:
            service, created = Servicio.objects.get_or_create(
                nombre=srv_name,
                defaults={
                    'precio_referencia': price,
                    'requiere_repuestos': True
                }
            )
            
            # Associate category
            if cat_name in categories:
                service.categorias.add(categories[cat_name])
            
            created_services.append(service)

        # 3. Create Mechanics (Updated with Location and Bio)
        # Assuming Santiago coordinates as base
        SANTIAGO_CENTER = (-33.4489, -70.6693)
        
        mechanics_data = [
            ('mecanico1', 'Juan Pérez', 'juan.perez@example.com', 'Especialista en Mazda y Toyota con 10 años de experiencia.', -33.4500, -70.6500), # Near Santiago Centro
            ('mecanico2', 'Pedro Rodríguez', 'pedro.rodriguez@example.com', 'Experto en frenos y suspensión. Certificado por Chevrolet y Fiat.', -33.4200, -70.6000), # Providencia/Las Condes area
            ('mecanico3', 'Carlos González', 'carlos.gonzalez@example.com', 'Diagnóstico electrónico avanzado. Equipos de última generación.', -33.5000, -70.7000), # Maipú/Cerrillos area
        ]

        mechanic_objects = []
        for username, setup_name, email, bio, lat, lng in mechanics_data:
            # Create User
            if not Usuario.objects.filter(username=username).exists():
                user = Usuario.objects.create_user(username=username, email=email, password='password123')
                user.es_mecanico = True
                user.first_name = setup_name.split(' ')[0]
                user.last_name = ' '.join(setup_name.split(' ')[1:])
                user.save()
            else:
                user = Usuario.objects.get(username=username)

            # Create Mechanic Profile
            mech, created = MecanicoDomicilio.objects.get_or_create(
                usuario=user,
                defaults={
                    'nombre': setup_name,
                    'disponible': True,
                    'calificacion_promedio': round(random.uniform(4.0, 5.0), 1),
                    'numero_de_calificaciones': random.randint(5, 50),
                    'descripcion': bio,
                    'experiencia_anos': random.randint(5, 15),
                    'radio_cobertura': 15.0, # 15km coverage
                    'ubicacion': Point(lng, lat), # Django uses (lng, lat)
                    'verificado': True,
                    'estado_verificacion': 'aprobado',
                    'activo': True
                }
            )
            
            # Update verification status explicitly
            mech.verificado = True
            mech.estado_verificacion = 'aprobado'
            mech.activo = True
            
            # Update location if it wasn't set or to ensure it matches
            mech.ubicacion = Point(lng, lat)
            mech.descripcion = bio
            mech.save()
            
            # Assign Brands (Randomly assign 2-3 brands)
            mech.marcas_atendidas.set(random.sample(all_brands, min(3, len(all_brands))))
            
            # Create Service Area (Crucial for filtering)
            if not MechanicServiceArea.objects.filter(mechanic=mech).exists():
                MechanicServiceArea.objects.create(
                    mechanic=mech,
                    name='Gran Santiago',
                    area_type='COMMUNE',
                    commune_names=[
                        'Santiago', 'Providencia', 'Las Condes', 'Ñuñoa', 'La Reina', 
                        'Macul', 'Peñalolén', 'La Florida', 'Maipú', 'Estación Central'
                    ],
                    is_active=True
                )
                self.stdout.write(f'Created Service Area for {setup_name}')

            mechanic_objects.append(mech)
            self.stdout.write(f'Processed mechanic: {setup_name}')

        # 4. Create Workshops (Talleres)
        workshops_data = [
            ('taller1', 'Taller Los Profesionales', 'taller1@example.com', -33.4300, -70.6200),
            ('taller2', 'Servicio Automotriz Master', 'taller2@example.com', -33.4600, -70.6800),
        ]

        workshop_objects = []
        for username, setup_name, email, lat, lng in workshops_data:
            # Create User
            if not Usuario.objects.filter(username=username).exists():
                user = Usuario.objects.create_user(username=username, email=email, password='password123')
                user.save()
            else:
                user = Usuario.objects.get(username=username)

            # Create Workshop Profile
            workshop, created = Taller.objects.get_or_create(
                usuario=user,
                defaults={
                    'nombre': setup_name,
                    'horario_atencion': 'Lun-Vie 09:00 - 18:00',
                    'calificacion_promedio': round(random.uniform(4.0, 5.0), 1),
                    'numero_de_calificaciones': random.randint(10, 100),
                    'ubicacion': Point(lng, lat),
                    'direccion_fisica': {'latitud': lat, 'longitud': lng}, # Fallback
                    'verificado': True,
                    'estado_verificacion': 'aprobado',
                    'activo': True
                }
            )
            
            workshop.ubicacion = Point(lng, lat)
            workshop.verificado = True
            workshop.estado_verificacion = 'aprobado' 
            workshop.activo = True
            # Assign Brands
            workshop.marcas_atendidas.set(random.sample(all_brands, min(4, len(all_brands))))
            workshop.save()
            
            workshop_objects.append(workshop)
            self.stdout.write(f'Processed workshop: {setup_name}')

        # 5. Associate Services to Mechanics and Workshops
        # Link services to Mechanics
        for mech in mechanic_objects:
            for service in created_services:
                if random.random() > 0.3: # 70% chance
                    base_price = float(service.precio_referencia)
                    final_price = round(base_price * random.uniform(0.9, 1.2), -3)
                    
                    OfertaServicio.objects.update_or_create(
                        mecanico=mech,
                        servicio=service,
                        tipo_proveedor='mecanico',
                        defaults={
                            'precio_con_repuestos': final_price,
                            'precio_sin_repuestos': final_price * 0.6,
                            'disponible': True,
                            'tipo_servicio': 'con_repuestos'
                        }
                    )
                    
        # Link services to Workshops
        for workshop in workshop_objects:
            for service in created_services:
                if random.random() > 0.2: # 80% chance
                    base_price = float(service.precio_referencia)
                    final_price = round(base_price * random.uniform(1.0, 1.4), -3)
                    
                    OfertaServicio.objects.update_or_create(
                        taller=workshop,
                        servicio=service,
                        tipo_proveedor='taller',
                        defaults={
                            'precio_con_repuestos': final_price,
                            'precio_sin_repuestos': final_price * 0.6,
                            'disponible': True,
                            'tipo_servicio': 'con_repuestos'
                        }
                    )

        self.stdout.write(self.style.SUCCESS('Population script v2 completed successfully!'))
