#!/usr/bin/env python
"""
Login via actual endpoint and test authenticated requests.
Uses DRF TokenAuthentication (NOT JWT).
"""
import os
import sys
import django
import requests
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')
django.setup()

from django.contrib.auth import get_user_model
from mecanimovilapp.apps.usuarios.models import Taller, MiembroTaller, Cliente
from mecanimovilapp.apps.vehiculos.models import Vehiculo, MarcaVehiculo, Modelo
from mecanimovilapp.apps.ordenes.models import SolicitudServicio
from decimal import Decimal
from datetime import date, time, timedelta

User = get_user_model()

BASE_URL = "http://localhost:8000"


def ensure_test_data():
    """Ensure test users and data exist."""
    print("=== Ensuring Test Data ===\n")
    
    # Taller owner (mandante)
    user_taller, created = User.objects.get_or_create(
        username='test_taller_http',
        defaults={
            'email': 'taller_http@test.com',
            'first_name': 'Taller',
            'last_name': 'HTTP'
        }
    )
    if created or not user_taller.check_password('test123'):
        user_taller.set_password('test123')
        user_taller.save()
        print(f"✓ Created/updated taller user: {user_taller.username}")
    
    taller, _ = Taller.objects.get_or_create(
        usuario=user_taller,
        defaults={
            'nombre': 'Taller HTTP Test',
            'rut': '88888888-8',
            'telefono': '+56988888888',
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
    
    # Mechanic
    user_mec, created = User.objects.get_or_create(
        username='test_mec_http',
        defaults={'email': 'mec_http@test.com'}
    )
    if created or not user_mec.check_password('test123'):
        user_mec.set_password('test123')
        user_mec.save()
    
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
        username='test_cli_http',
        defaults={'email': 'cli_http@test.com'}
    )
    if created or not user_cliente.check_password('test123'):
        user_cliente.set_password('test123')
        user_cliente.save()
    
    cliente, _ = Cliente.objects.get_or_create(
        usuario=user_cliente,
        defaults={
            'nombre': 'Cliente',
            'apellido': 'HTTP',
            'email': 'cli_http@test.com',
            'telefono': '+56900000002'
        }
    )
    
    # Vehículo
    marca, _ = MarcaVehiculo.objects.get_or_create(nombre='Ford')
    modelo, _ = Modelo.objects.get_or_create(marca=marca, nombre='Focus')
    vehiculo, _ = Vehiculo.objects.get_or_create(
        cliente=cliente,
        patente='HTTP02',
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
    
    print(f"✓ Taller: {taller.id}")
    print(f"✓ Mandante: {mandante.id}")
    print(f"✓ Mechanic: {mecanico.id}")
    print(f"✓ Orders: {orden1.id}, {orden2.id}\n")
    
    return {
        'taller_user': user_taller.username,
        'mec_user': user_mec.username,
        'cliente_user': user_cliente.username,
        'taller_id': taller.id,
        'mecanico_id': mecanico.id,
        'orden_pending_id': orden1.id,
        'orden_accepted_id': orden2.id
    }


def login(username, password, endpoint='/api/usuarios/login-proveedor/'):
    """Login and return token."""
    url = f"{BASE_URL}{endpoint}"
    data = {'username': username, 'password': password}
    
    print(f"🔐 Logging in as {username} via {endpoint}")
    try:
        resp = requests.post(url, json=data, timeout=5)
        print(f"   Status: {resp.status_code}")
        
        if resp.status_code == 200:
            token = resp.json().get('token')
            print(f"   ✓ Token received: {token[:20]}...\n")
            return token
        else:
            print(f"   ✗ Error: {resp.text}\n")
            return None
    except Exception as e:
        print(f"   ✗ Exception: {e}\n")
        return None


def test_authenticated_request(token, endpoint, method='GET', data=None):
    """Test authenticated request."""
    url = f"{BASE_URL}{endpoint}"
    headers = {'Authorization': f'Token {token}'}
    
    print(f"📡 {method} {endpoint}")
    print(f"   Header: Authorization: Token {token[:20]}...")
    
    try:
        if method == 'GET':
            resp = requests.get(url, headers=headers, timeout=5)
        elif method == 'POST':
            headers['Content-Type'] = 'application/json'
            resp = requests.post(url, headers=headers, json=data, timeout=5)
        else:
            print(f"   ✗ Unsupported method: {method}\n")
            return False
        
        print(f"   Status: {resp.status_code}")
        
        if resp.status_code in [200, 201]:
            print(f"   ✓ Success\n")
            return True
        else:
            print(f"   ✗ Error: {resp.text[:200]}\n")
            return False
    except Exception as e:
        print(f"   ✗ Exception: {e}\n")
        return False


if __name__ == '__main__':
    print("=" * 80)
    print("HTTP Authentication Test - DRF TokenAuthentication")
    print("=" * 80)
    print()
    
    # Ensure test data
    data = ensure_test_data()
    
    # Test 1: Login as taller owner
    print("=" * 80)
    print("TEST 1: Login as Taller Owner (Mandante)")
    print("=" * 80)
    token_taller = login(data['taller_user'], 'test123')
    if not token_taller:
        print("✗ FAILED: Could not login as taller owner\n")
        sys.exit(1)
    
    # Test 2: List orders
    print("=" * 80)
    print("TEST 2: List Orders (Authenticated)")
    print("=" * 80)
    if not test_authenticated_request(token_taller, '/api/ordenes/proveedor-ordenes/'):
        print("✗ FAILED: Could not list orders\n")
        sys.exit(1)
    
    # Test 3: Accept order
    print("=" * 80)
    print("TEST 3: Accept Order")
    print("=" * 80)
    accept_url = f"/api/ordenes/proveedor-ordenes/{data['orden_pending_id']}/aceptar/"
    if not test_authenticated_request(token_taller, accept_url, method='POST'):
        print("✗ FAILED: Could not accept order\n")
        sys.exit(1)
    
    # Test 4: Assign technician
    print("=" * 80)
    print("TEST 4: Assign Technician")
    print("=" * 80)
    assign_url = f"/api/ordenes/proveedor-ordenes/{data['orden_pending_id']}/asignar_tecnico/"
    assign_data = {'mecanico_id': data['mecanico_id']}
    test_authenticated_request(token_taller, assign_url, method='POST', data=assign_data)
    
    # Test 5: Login as mechanic
    print("=" * 80)
    print("TEST 5: Login as Mechanic")
    print("=" * 80)
    token_mec = login(data['mec_user'], 'test123')
    if not token_mec:
        print("⚠ WARNING: Could not login as mechanic (may not have proveedor endpoint access)\n")
    else:
        # Test mechanic can see orders
        test_authenticated_request(token_mec, '/api/ordenes/proveedor-ordenes/')
    
    print("=" * 80)
    print("✓ HTTP Authentication Tests Complete")
    print("=" * 80)
    print("\n✅ All critical tests passed with DRF TokenAuthentication")
    print(f"   Format: Authorization: Token <key>")
    print(f"   Login: POST /api/usuarios/login-proveedor/")
    print(f"   Response: {{ \"token\": \"<key>\", \"user\": {{...}} }}")
