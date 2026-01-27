from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from mecanimovilapp.apps.usuarios.models import Taller, MecanicoDomicilio, Cliente, Resena, ResenaFoto
from mecanimovilapp.apps.ordenes.models import SolicitudServicio
from mecanimovilapp.apps.vehiculos.models import Vehiculo
from mecanimovilapp.apps.servicios.models import Servicio
from django.utils import timezone
import random
from datetime import timedelta, datetime

Usuario = get_user_model()

class Command(BaseCommand):
    help = 'Populate database with dummy reviews'

    def handle(self, *args, **kwargs):
        self.stdout.write('Starting reviews population...')
        
        # 1. Get User/Client
        try:
            # Try to get marthatest or the first client
            user = Usuario.objects.filter(email='marthatest@gmail.com').first()
            if not user:
                user = Usuario.objects.filter(cliente__isnull=False).first()
                if not user:
                    self.stdout.write(self.style.ERROR('No clients found. Run populate_master_data first.'))
                    return
            
            cliente = user.cliente
            self.stdout.write(f'Using client: {cliente.nombre} {cliente.apellido}')
            
            # Get User Vehicles
            vehicles = Vehiculo.objects.filter(cliente=cliente)
            if not vehicles.exists():
                self.stdout.write(self.style.WARNING('User has no vehicles. Creating dummy vehicle context.'))
                vehicle = None
            else:
                vehicle = vehicles.first()
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error getting user info: {e}'))
            return

        # 2. Get Providers
        talleres = Taller.objects.all()
        mecanicos = MecanicoDomicilio.objects.all()
        
        if not talleres.exists() and not mecanicos.exists():
            self.stdout.write(self.style.ERROR('No providers found.'))
            return

        # Reviews Data
        reviews_data = [
            {
                'comment': 'Excelente servicio, muy profesional y rápido. Totalmente recomendado.',
                'rating': 5,
                'service_name': 'Cambio de Aceite Full Sintético',
            },
            {
                'comment': 'Buena atención, aunque demoraron un poco más de lo esperado. El trabajo quedó bien.',
                'rating': 4,
                'service_name': 'Revisión de Frenos',
            },
            {
                'comment': 'Me salvaron de una pana en mi casa. El mecánico llegó a la hora.',
                'rating': 5,
                'service_name': 'Cambio de Batería a Domicilio',
            },
            {
                'comment': 'Todo ordenado y limpio. El taller inspira confianza.',
                'rating': 5,
                'service_name': 'Mantención 10.000km',
            },
            {
                'comment': 'Un poco caro para el servicio, pero aceptable.',
                'rating': 3,
                'service_name': 'Diagnóstico Scanner',
            }
        ]

        # 3. Create Reviews for Workshops
        for taller in talleres:
            self.stdout.write(f'Adding reviews for Taller: {taller.nombre}')
            
            # Add 2-3 reviews per workshop
            for i in range(random.randint(2, 4)):
                data = random.choice(reviews_data)
                
                # Check/Create Service
                servicio, _ = Servicio.objects.get_or_create(
                    nombre=data['service_name'],
                    defaults={'descripcion': 'Servicio generado automáticamente'}
                )
                
                # Create Dummy Request (Solicitud)
                solicitud = SolicitudServicio.objects.create(
                    cliente=cliente,
                    vehiculo=vehicle,
                    taller=taller, # Linked to Taller
                    tipo_servicio='taller',
                    fecha_servicio=timezone.now().date() - timedelta(days=random.randint(1, 60)),
                    hora_servicio=datetime.now().time(),
                    estado='completado',
                    metodo_pago='transferencia',
                    total=50000
                )
                # Hack: associate service to solicitud if possible (depends on model structure, assuming via oferta or direct)
                # Since Solicitud doesn't show direct 'servicio' FK in previous `view_file` (it showed `tipo_servicio`), 
                # but `ResenaSerializer` implementation details suggested accessing `solicitud.servicio`...
                # Let's attach it purely for the Review context if the model supports it.
                # If SolicitudServicio doesn't have 'servicio' field, we skip trying to set it directly.
                # Checking `view_file` output again: `SolicitudServicio` didn't show `servicio` FK in lines 1-100.
                # It might be derived via `OfertaServicio` or it might be `servicio` FK further down.
                # I will try to set it dynamically if it exists, otherwise ignore.
                try:
                    solicitud.servicio = servicio
                    solicitud.save()
                except:
                    pass

                # Create Review
                resena = Resena.objects.create(
                    cliente=cliente,
                    taller=taller,
                    solicitud=solicitud,
                    calificacion=data['rating'],
                    comentario=data['comment'],
                    fecha_hora_resena=timezone.now() - timedelta(days=random.randint(0, 30))
                )
                self.stdout.write(f'  - Created review: {data["rating"]} stars')

            # Update Average
            taller_resenas = Resena.objects.filter(taller=taller)
            avg = sum(r.calificacion for r in taller_resenas) / taller_resenas.count()
            taller.calificacion_promedio = avg
            taller.numero_de_calificaciones = taller_resenas.count()
            taller.save()

        # 4. Create Reviews for Mechanics
        for mecanico in mecanicos:
            self.stdout.write(f'Adding reviews for Mechanic: {mecanico.nombre}')
            
            for i in range(random.randint(2, 4)):
                data = random.choice(reviews_data)
                
                 # Create Dummy Request
                solicitud = SolicitudServicio.objects.create(
                    cliente=cliente,
                    vehiculo=vehicle,
                    mecanico=mecanico, # Linked to Mechanic
                    tipo_servicio='domicilio',
                    fecha_servicio=timezone.now().date() - timedelta(days=random.randint(1, 60)),
                    hora_servicio=datetime.now().time(),
                    estado='completado',
                    metodo_pago='efectivo',
                    total=35000
                )
                
                # Create Review
                resena = Resena.objects.create(
                    cliente=cliente,
                    mecanico=mecanico,
                    solicitud=solicitud,
                    calificacion=data['rating'],
                    comentario=data['comment'],
                    fecha_hora_resena=timezone.now() - timedelta(days=random.randint(0, 30))
                )
                self.stdout.write(f'  - Created review: {data["rating"]} stars')
            
            # Update Average
            mec_resenas = Resena.objects.filter(mecanico=mecanico)
            avg = sum(r.calificacion for r in mec_resenas) / mec_resenas.count()
            mecanico.calificacion_promedio = avg
            mecanico.numero_de_calificaciones = mec_resenas.count()
            mecanico.save()

        self.stdout.write(self.style.SUCCESS('Successfully populated dummy reviews!'))
