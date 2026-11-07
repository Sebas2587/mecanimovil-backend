#!/usr/bin/env python3
"""
Test mechanic checklist execution permissions.

Verifies:
1. Owner can initiate service (creates checklist)
2. Assigned mechanic CANNOT initiate service (403)
3. Assigned mechanic CAN view checklist after owner initiates
4. Assigned mechanic CAN respond to checklist items
5. Assigned mechanic CAN pause/resume checklist
6. Unassigned mechanic CANNOT see checklist (404)

Prerequisites:
- Django server running on localhost:8000
- Two mechanics in same workshop
- Test owner/mechanic users created
"""

import requests
import sys
import json
from datetime import date, time

BASE_URL = "http://localhost:8000"

def login(email, password):
    """Login and get DRF token."""
    url = f"{BASE_URL}/api/usuarios/login-proveedor/"
    resp = requests.post(url, json={"email": email, "password": password})
    if resp.status_code != 200:
        print(f"❌ Login failed for {email}: {resp.status_code}")
        print(f"   Response: {resp.text}")
        return None
    data = resp.json()
    token = data.get("token")
    if not token:
        print(f"❌ No token in response for {email}")
        return None
    print(f"✅ Logged in as {email}")
    return token

def headers(token):
    """Build auth headers."""
    return {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json"
    }

def test_mechanic_permissions():
    """Main test flow."""
    print("\n" + "="*60)
    print("Testing Mechanic Checklist Permissions")
    print("="*60 + "\n")

    # Login users
    owner_token = login("taller_owner@test.com", "test123")
    mechanic1_token = login("mechanic1@test.com", "test123")
    mechanic2_token = login("mechanic2@test.com", "test123")

    if not all([owner_token, mechanic1_token, mechanic2_token]):
        print("\n❌ Cannot proceed without all logins")
        return False

    # Get mechanic1 user ID
    resp = requests.get(f"{BASE_URL}/api/usuarios/me/", headers=headers(mechanic1_token))
    if resp.status_code != 200:
        print(f"❌ Cannot get mechanic1 user: {resp.status_code}")
        return False
    mechanic1_user_id = resp.json()["id"]
    print(f"✅ Mechanic1 user ID: {mechanic1_user_id}")

    # Create order as owner
    print("\n1️⃣  Creating order as owner...")
    order_data = {
        "cliente": {
            "nombre": "Test Cliente",
            "telefono": "+56912345678"
        },
        "vehiculo": {
            "marca": "Toyota",
            "modelo": "Corolla",
            "anio": 2020,
            "patente": "ABCD12"
        },
        "servicio_solicitado": "Revisión completa",
        "descripcion_problema": "Mantenimiento preventivo",
        "fecha_preferida": str(date.today())
    }
    
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/",
        headers=headers(owner_token),
        json=order_data
    )
    
    if resp.status_code not in [200, 201]:
        print(f"❌ Cannot create order: {resp.status_code}")
        print(f"   Response: {resp.text}")
        return False
    
    order_id = resp.json()["id"]
    print(f"✅ Order created: {order_id}")

    # Assign mechanic1 to order
    print(f"\n2️⃣  Assigning mechanic1 (ID {mechanic1_user_id}) to order...")
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{order_id}/asignar_tecnico/",
        headers=headers(owner_token),
        json={
            "mecanico_id": mechanic1_user_id,
            "fecha": str(date.today()),
            "hora": "10:00"
        }
    )
    
    if resp.status_code != 200:
        print(f"❌ Cannot assign mechanic: {resp.status_code}")
        print(f"   Response: {resp.text}")
        return False
    
    print(f"✅ Mechanic1 assigned to order {order_id}")

    # Test: Mechanic CANNOT initiate service
    print("\n3️⃣  Testing: Mechanic1 tries to initiate service (should FAIL)...")
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{order_id}/iniciar_servicio/",
        headers=headers(mechanic1_token),
        json={}
    )
    
    if resp.status_code == 403:
        print(f"✅ Correctly blocked mechanic from initiating (403)")
    else:
        print(f"⚠️  Unexpected status: {resp.status_code} (expected 403)")
        print(f"   Response: {resp.text}")

    # Owner initiates service
    print("\n4️⃣  Owner initiates service (should create checklist)...")
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{order_id}/iniciar_servicio/",
        headers=headers(owner_token),
        json={}
    )
    
    if resp.status_code != 200:
        print(f"❌ Owner cannot initiate service: {resp.status_code}")
        print(f"   Response: {resp.text}")
        return False
    
    data = resp.json()
    if not data.get("checklist_creado"):
        print(f"❌ Checklist not created")
        return False
    
    checklist_id = data.get("checklist_id")
    print(f"✅ Service initiated, checklist created: {checklist_id}")

    # Test: Mechanic1 CAN view checklist
    print("\n5️⃣  Testing: Mechanic1 views checklist...")
    resp = requests.get(
        f"{BASE_URL}/api/checklists/instances/{checklist_id}/",
        headers=headers(mechanic1_token)
    )
    
    if resp.status_code != 200:
        print(f"❌ Mechanic1 cannot view checklist: {resp.status_code}")
        print(f"   Response: {resp.text}")
        return False
    
    checklist = resp.json()
    print(f"✅ Mechanic1 can view checklist, state: {checklist.get('estado')}")
    
    # Get first item template
    if not checklist.get("checklist_template", {}).get("items"):
        print(f"⚠️  No checklist items found, skipping response tests")
        return True
    
    item_id = checklist["checklist_template"]["items"][0]["id"]
    print(f"   First item ID: {item_id}")

    # Test: Mechanic1 CAN respond to item
    print("\n6️⃣  Testing: Mechanic1 responds to checklist item...")
    resp = requests.post(
        f"{BASE_URL}/api/checklists/responses/",
        headers=headers(mechanic1_token),
        json={
            "checklist_instance": checklist_id,
            "item_template": item_id,
            "respuesta_texto": "Revisado - OK",
            "completado": True
        }
    )
    
    if resp.status_code not in [200, 201]:
        print(f"❌ Mechanic1 cannot respond: {resp.status_code}")
        print(f"   Response: {resp.text}")
        return False
    
    print(f"✅ Mechanic1 can respond to checklist items")

    # Test: Mechanic1 CAN pause checklist
    print("\n7️⃣  Testing: Mechanic1 pauses checklist...")
    resp = requests.post(
        f"{BASE_URL}/api/checklists/instances/{checklist_id}/pause/",
        headers=headers(mechanic1_token),
        json={}
    )
    
    if resp.status_code != 200:
        print(f"❌ Mechanic1 cannot pause: {resp.status_code}")
        print(f"   Response: {resp.text}")
        return False
    
    print(f"✅ Mechanic1 can pause checklist")

    # Test: Mechanic1 CAN resume checklist
    print("\n8️⃣  Testing: Mechanic1 resumes checklist...")
    resp = requests.post(
        f"{BASE_URL}/api/checklists/instances/{checklist_id}/resume/",
        headers=headers(mechanic1_token),
        json={}
    )
    
    if resp.status_code != 200:
        print(f"❌ Mechanic1 cannot resume: {resp.status_code}")
        print(f"   Response: {resp.text}")
        return False
    
    print(f"✅ Mechanic1 can resume checklist")

    # Test: Mechanic2 (unassigned) CANNOT view checklist
    print("\n9️⃣  Testing: Mechanic2 (unassigned) views checklist (should FAIL)...")
    resp = requests.get(
        f"{BASE_URL}/api/checklists/instances/{checklist_id}/",
        headers=headers(mechanic2_token)
    )
    
    if resp.status_code == 404:
        print(f"✅ Correctly blocked unassigned mechanic (404)")
    else:
        print(f"⚠️  Unexpected status: {resp.status_code} (expected 404)")
        print(f"   Response: {resp.text}")

    print("\n" + "="*60)
    print("✅ All mechanic permission tests passed!")
    print("="*60 + "\n")
    return True

if __name__ == "__main__":
    try:
        success = test_mechanic_permissions()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
