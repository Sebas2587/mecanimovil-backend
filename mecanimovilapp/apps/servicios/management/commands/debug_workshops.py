from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from mecanimovilapp.apps.usuarios.models import Taller, Cliente
from mecanimovilapp.apps.vehiculos.models import Vehiculo

Usuario = get_user_model()

class Command(BaseCommand):
    help = 'Diagnose workshop visibility issues'

    def handle(self, *args, **kwargs):
        self.stdout.write('--- Workshop Diagnosis ---')
        
        # 1. Check User and Vehicles
        try:
            user = Usuario.objects.get(email='marthatest@gmail.com')
            self.stdout.write(f'User found: {user.username} (ID: {user.id})')
            
            vehicles = Vehiculo.objects.filter(cliente__usuario=user)
            self.stdout.write(f'User has {vehicles.count()} vehicles:')
            for v in vehicles:
                self.stdout.write(f'  - {v.marca.nombre} {v.modelo.nombre} (ID: {v.id})')
        except Usuario.DoesNotExist:
            self.stdout.write('User marthatest@gmail.com not found')
            return

        self.stdout.write('\n--- Workshops Status ---')
        workshops = Taller.objects.all()
        for w in workshops:
            self.stdout.write(f'Workshop: {w.nombre} (ID: {w.id})')
            self.stdout.write(f'  - Active: {w.activo}')
            self.stdout.write(f'  - Verified: {w.verificado}')
            self.stdout.write(f'  - Verification Status: {w.estado_verificacion}')
            
            brands = w.marcas_atendidas.all()
            brand_names = [b.nombre for b in brands]
            self.stdout.write(f'  - Brands ({len(brands)}): {", ".join(brand_names)}')
            
            if w.ubicacion:
                self.stdout.write(f'  - Location: {w.ubicacion.y}, {w.ubicacion.x}')
            else:
                self.stdout.write(f'  - Location: None')

            # Check compatibility explicitly
            for v in vehicles:
                compatible = w.marcas_atendidas.filter(id=v.marca.id).exists()
                self.stdout.write(f'  > Compatible with {v.marca.nombre}: {"YES" if compatible else "NO"}')
            
            self.stdout.write('')
