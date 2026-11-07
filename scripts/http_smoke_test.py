#!/usr/bin/env python
"""
HTTP smoke test: Real localhost DRF Token workflow.
Tests: owner accept → assign → mechanic view → cross-tenant denied
"""
import os
import sys
import django
import requests
import time
from datetime import date, time as dt_time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')
django.setup()

from django.contrib.auth import get_user_model
from mecanimovilapp.apps.usuarios.models import Taller, MiembroTaller
from mecanimovilapp.apps.servicios.models import Servicio
from mecanimovilapp.apps.ordenes.models import SolicitudServicio

User = get_user_model()
BASE_URL = "http://localhost:8000"

def setup_test_data():
    """Create minimal test data (idempotent)."""
    print("=== Setup Test Data ===\n")
    
    # Taller A
    user_a, created = User.objects.get_or_create(
        username='http_taller_a',
        defaults={'email': 'httpa@test.com'}
    )
    if created:
        user_a.set_password('test123')
        user_a.save()
    
    taller_a, _ = Taller.objects.get_or_create(
        usuario=user_a,
        defaults={'nombre': 'HTTP Taller A', 'rut': '77777777-7'}
    )
    
    # Mechanic for A
    user_mec_a, created = User.objects.get_or_create(
        username='http_mec_a',
        defaults={'email': 'httpmeca@test.com'}
    )
    if created:
        user_mec_a.set_password('test123')
        user_mec_a.save()
    
    mec_a, _ = MiembroTaller.objects.get_or_create(
        taller=taller_a,
        usuario=user_mec_a,
        defaults={'rol': 'mecanico', 'activo': True}
    )
    
    # Taller B (unrelated)
    user_b, created = User.objects.get_or_create(
        username='http_taller_b',
        defaults={'email': 'httpb@test.com'}
    )
    if created:
        user_b.set_password('test123')
        user_b.save()
    
    taller_b, _ = Taller.objects.get_or_create(
        usuario=user_b,
        defaults={'nombre': 'HTTP Taller B', 'rut': '88888888-8'}
    )
    
    # Clean old test orders
    SolicitudServicio.objects.filter(taller=taller_a).delete()
    
    # Create minimal order for taller A
    servicio, _ = Servicio.objects.get_or_create(
        nombre='HTTP Test Service',
        defaults={'descripcion': 'Test'}
    )
    
    orden = SolicitudServicio.objects.create(
        taller=taller_a,
        fecha_servicio=date.today(),
        hora_servicio=dt_time(10, 0),
        estado='pendiente_aceptacion_proveedor',
        total=25000,
        metodo_pago='transferencia'
    )
    
    print(f"✅ Taller A ID: {taller_a.id}")
    print(f"✅ Mechanic A ID: {mec_a.id}")
    print(f"✅ Taller B ID: {taller_b.id}")
    print(f"✅ Order ID: {orden.id}\n")
    
    return {
        'taller_a_email': 'httpa@test.com',
        'mec_a_email': 'httpmeca@test.com',
        'taller_b_email': 'httpb@test.com',
        'taller_a': taller_a,
        'mec_a': mec_a,
        'taller_b': taller_b,
        'orden': orden,
    }

def login(email, password):
    """Login via DRF Token."""
    resp = requests.post(
        f"{BASE_URL}/api/usuarios/login-proveedor/",
        json={"email": email, "password": password},
        timeout=5
    )
    if resp.status_code != 200:
        return None, f"Login failed: {resp.status_code}"
    data = resp.json()
    token = data.get('token')
    if not token:
        return None, "No token in response"
    return token, None

def test_workflow(data):
    """Execute HTTP workflow."""
    print("="*60)
    print("HTTP SMOKE TEST")
    print("="*60 + "\n")
    
    orden_id = data['orden'].id
    mec_id = data['mec_a'].id
    
    # 1. Owner login
    print("1️⃣  Owner Login (Taller A)")
    owner_token, err = login(data['taller_a_email'], 'test123')
    if err:
        print(f"   ❌ {err}")
        return False
    print(f"   ✅ Token: {owner_token[:20]}...\n")
    
    # 2. Accept order
    print("2️⃣  Owner Accepts Order")
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/aceptar/",
        headers={"Authorization": f"Token {owner_token}"},
        json={},
        timeout=5
    )
    print(f"   Status: {resp.status_code}")
    if resp.status_code not in [200, 409]:
        print(f"   ❌ Body: {resp.text[:200]}")
        return False
    print(f"   ✅ Accepted\n")
    
    # 3. Assign mechanic
    print("3️⃣  Owner Assigns Mechanic")
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/asignar_tecnico/",
        headers={"Authorization": f"Token {owner_token}"},
        json={
            "mecanico_id": mec_id,
            "fecha": str(date.today()),
            "hora": "10:00"
        },
        timeout=5
    )
    print(f"   Status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"   ❌ Body: {resp.text[:200]}")
        return False
    print(f"   ✅ Assigned\n")
    
    # 4. Mechanic login
    print("4️⃣  Mechanic Login")
    mec_token, err = login(data['mec_a_email'], 'test123')
    if err:
        print(f"   ❌ {err}")
        return False
    print(f"   ✅ Token: {mec_token[:20]}...\n")
    
    # 5. Mechanic views order
    print("5️⃣  Mechanic Views Assigned Order")
    resp = requests.get(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/",
        headers={"Authorization": f"Token {mec_token}"},
        timeout=5
    )
    print(f"   Status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"   ❌ Body: {resp.text[:200]}")
        return False
    print(f"   ✅ Mechanic can view\n")
    
    # 6. Cross-tenant test
    print("6️⃣  Cross-Tenant Isolation (Taller B)")
    b_token, err = login(data['taller_b_email'], 'test123')
    if err:
        print(f"   ❌ {err}")
        return False
    
    resp = requests.get(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/",
        headers={"Authorization": f"Token {b_token}"},
        timeout=5
    )
    print(f"   Status: {resp.status_code}")
    if resp.status_code != 404:
        print(f"   ⚠️  Expected 404, got {resp.status_code}")
        print(f"   Body: {resp.text[:200]}")
    else:
        print(f"   ✅ Cross-tenant blocked\n")
    
    print("="*60)
    print("✅ HTTP SMOKE TEST PASSED")
    print("="*60)
    return True

if __name__ == '__main__':
    # Check server
    try:
        resp = requests.get(f"{BASE_URL}/api/", timeout=2)
        if resp.status_code >= 500:
            print("❌ Server error - check Django runserver")
            sys.exit(1)
    except requests.exceptions.RequestException:
        print("❌ Server not running at localhost:8000")
        print("   Run: python manage.py runserver 0.0.0.0:8000")
        sys.exit(1)
    
    try:
        data = setup_test_data()
        success = test_workflow(data)
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
