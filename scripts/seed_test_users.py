#!/usr/bin/env python
"""
Seed test users and return JWT tokens for HTTP testing.
Usage: ./run_django.sh scripts/seed_test_users.py
"""
import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')
django.setup()

from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from mecanimovilapp.apps.usuarios.models import Taller, MiembroTaller, Cliente
from mecanimovilapp.apps.vehiculos.models import Vehiculo, MarcaVehiculo, Modelo
from mecanimovilapp.apps.ordenes.models import SolicitudServicio
from decimal import Decimal
from datetime import date, time, timedelta

User = get_user_model()


def get_or_create_test_data():
    """Create test users and return auth tokens."""
    print("=== Seeding Test Data ===\n")
    
    # Taller owner (mandante)
    user_taller, created = User.objects.get_or_create(
        username='test_taller',
        defaults={
            'email': 'test_taller@mecanimovil.test',
            'first_name': 'Taller',
            'last_name': 'Test'
        }
    )
    if created:
        user_taller.set_password('test123')
        user_taller.save()
        print(f"✓ Created taller user: {user_taller.username}")
    else:
        print(f"✓ Using existing taller user: {user_taller.username}")
    
    taller, _ = Taller.objects.get_or_create(
        usuario=user_taller,
        defaults={
            'nombre': 'Taller Test HTTP',
            'rut': '99999999-9',
            'telefono': '+56900000000',
            'estado_verificacion': 'aprobado'
        }
    )
    
    mandante, _ = MiembroTaller.objects.get_or_create(
        taller=taller,
        usuario=user_taller,
        defaults={
            'nombre': 'Mandante HTTP',
            'rol': 'mandante',
            'activo': True,
            'permisos': {'servicios': True}
        }
    )
    
    # Supervisor
    user_super, created = User.objects.get_or_create(
        username='test_supervisor',
        defaults={
            'email': 'test_supervisor@mecanimovil.test',
            'first_name': 'Supervisor',
            'last_name': 'Test'
        }
    )
    if created:
        user_super.set_password('test123')
        user_super.save()
        print(f"✓ Created supervisor user: {user_super.username}")
    else:
        print(f"✓ Using existing supervisor: {user_super.username}")
    
    supervisor, _ = MiembroTaller.objects.get_or_create(
        taller=taller,
        usuario=user_super,
        defaults={
            'nombre': 'Supervisor HTTP',
            'rol': 'supervisor',
            'activo': True,
            'permisos': {'servicios': True}
        }
    )
    
    # Mechanic
    user_mec, created = User.objects.get_or_create(
        username='test_mecanico',
        defaults={
            'email': 'test_mecanico@mecanimovil.test',
            'first_name': 'Mecanico',
            'last_name': 'Test'
        }
    )
    if created:
        user_mec.set_password('test123')
        user_mec.save()
        print(f"✓ Created mechanic user: {user_mec.username}")
    else:
        print(f"✓ Using existing mechanic: {user_mec.username}")
    
    mecanico, _ = MiembroTaller.objects.get_or_create(
        taller=taller,
        usuario=user_mec,
        defaults={
            'nombre': 'Mecánico HTTP',
            'rol': 'mecanico',
            'activo': True
        }
    )
    
    # Cliente
    user_cliente, created = User.objects.get_or_create(
        username='test_cliente',
        defaults={
            'email': 'test_cliente@mecanimovil.test',
            'first_name': 'Cliente',
            'last_name': 'Test'
        }
    )
    if created:
        user_cliente.set_password('test123')
        user_cliente.save()
        print(f"✓ Created cliente user: {user_cliente.username}")
    else:
        print(f"✓ Using existing cliente: {user_cliente.username}")
    
    cliente, _ = Cliente.objects.get_or_create(
        usuario=user_cliente,
        defaults={
            'nombre': 'Cliente',
            'apellido': 'HTTP Test',
            'email': 'test_cliente@mecanimovil.test',
            'telefono': '+56911111111'
        }
    )
    
    # Vehiculo
    marca, _ = MarcaVehiculo.objects.get_or_create(nombre='Toyota')
    modelo, _ = Modelo.objects.get_or_create(marca=marca, nombre='Corolla')
    vehiculo, _ = Vehiculo.objects.get_or_create(
        cliente=cliente,
        patente='HTTP01',
        defaults={
            'marca': marca,
            'modelo': modelo,
            'year': 2023
        }
    )
    
    # Test orders
    orden1, _ = SolicitudServicio.objects.get_or_create(
        cliente=cliente,
        vehiculo=vehiculo,
        taller=taller,
        estado='pendiente_aceptacion_proveedor',
        defaults={
            'tipo_servicio': 'taller',
            'fecha_servicio': date.today() + timedelta(days=1),
            'hora_servicio': time(10, 0),
            'metodo_pago': 'efectivo',
            'total': Decimal('50000.00')
        }
    )
    
    orden2, _ = SolicitudServicio.objects.get_or_create(
        cliente=cliente,
        vehiculo=vehiculo,
        taller=taller,
        estado='aceptada_por_proveedor',
        defaults={
            'tipo_servicio': 'taller',
            'fecha_servicio': date.today() + timedelta(days=2),
            'hora_servicio': time(14, 0),
            'metodo_pago': 'efectivo',
            'total': Decimal('75000.00')
        }
    )
    
    print(f"\n✓ Created test orders: {orden1.id}, {orden2.id}")
    
    # Generate JWT tokens
    print("\n=== JWT Tokens ===\n")
    
    tokens = {}
    for user, role in [(user_taller, 'mandante'), (user_super, 'supervisor'), 
                       (user_mec, 'mecanico'), (user_cliente, 'cliente')]:
        refresh = RefreshToken.for_user(user)
        tokens[role] = {
            'username': user.username,
            'access': str(refresh.access_token),
            'refresh': str(refresh)
        }
        print(f"{role.upper()}:")
        print(f"  Username: {user.username}")
        print(f"  Password: test123")
        print(f"  Access Token: {tokens[role]['access']}")
        print()
    
    return {
        'taller_id': taller.id,
        'orden_pending_id': orden1.id,
        'orden_accepted_id': orden2.id,
        'mecanico_id': mecanico.id,
        'tokens': tokens
    }


if __name__ == '__main__':
    data = get_or_create_test_data()
    
    print("=== Test Environment Ready ===")
    print(f"Taller ID: {data['taller_id']}")
    print(f"Pending Order ID: {data['orden_pending_id']}")
    print(f"Accepted Order ID: {data['orden_accepted_id']}")
    print(f"Mechanic ID: {data['mecanico_id']}")
    print("\nUse tokens above for HTTP requests")
    print("Example: curl -H 'Authorization: Bearer <access_token>' http://localhost:8000/api/ordenes/proveedor-ordenes/")
