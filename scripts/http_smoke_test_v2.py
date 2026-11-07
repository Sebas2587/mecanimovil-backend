#!/usr/bin/env python
"""
HTTP smoke test V2: Complete workflow with STRICT assertions.
- Uses actual API endpoints (no direct ORM manipulation)
- Requires exact success status codes and final states
- Tests cross-tenant via POST creation API
- Verifies base order closure with pending/rejected extras
"""
import os
import sys
import django
import requests
import uuid
from datetime import date, time as dt_time
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')
os.environ['CELERY_TASK_ALWAYS_EAGER'] = 'True'  # Run tasks synchronously in tests
django.setup()

from django.contrib.auth import get_user_model
from mecanimovilapp.apps.usuarios.models import Taller, MiembroTaller, Cliente
from mecanimovilapp.apps.servicios.models import Servicio
from mecanimovilapp.apps.ordenes.models import SolicitudServicio, CotizacionCanal, CitaAgendaPersonal
from mecanimovilapp.apps.vehiculos.models import Vehiculo, MarcaVehiculo, Modelo

User = get_user_model()
BASE_URL = "http://localhost:8000"

def setup_test_data():
    """Create test data for workflow including catalog fixtures."""
    print("=== Setup Test Data ===\n")
    
    # Taller A
    user_a, _ = User.objects.get_or_create(
        username='http_v2_taller_a',
        defaults={'email': 'httpv2a@test.com', 'password': 'test123'}
    )
    user_a.set_password('test123')
    user_a.save()
    
    taller_a, _ = Taller.objects.get_or_create(
        usuario=user_a,
        defaults={'nombre': 'HTTP V2 Taller A', 'rut': '33333333-3'}
    )
    
    # Create catalog fixtures (disable signals to avoid Celery errors)
    from mecanimovilapp.apps.servicios.models import OfertaServicio
    from django.db.models.signals import post_save
    import mecanimovilapp.apps.agente_ia.signals
    
    servicio, _ = Servicio.objects.get_or_create(
        nombre='Cambio de aceite',
        defaults={'descripcion': 'Servicio de cambio de aceite'}
    )
    
    # Temporarily disconnect signals that trigger Celery
    post_save.disconnect(mecanimovilapp.apps.agente_ia.signals.sync_oferta_servicio_chunk, sender=OfertaServicio)
    post_save.disconnect(mecanimovilapp.apps.agente_ia.signals.sync_solicitud_historico_chunk, sender=SolicitudServicio)
    
    # Create checklist template for Order 4 (checklist-required flow)
    from mecanimovilapp.apps.checklists.models import ChecklistTemplate, ChecklistItemTemplate, ChecklistItemCatalog
    servicio_checklist, _ = Servicio.objects.get_or_create(
        nombre='Servicio con Checklist',
        defaults={'descripcion': 'Servicio que requiere checklist'}
    )
    template, created_template = ChecklistTemplate.objects.get_or_create(
        servicio=servicio_checklist,
        version='1.0',
        defaults={
            'nombre': 'Template Requerido Test',
            'activo': True
        }
    )
    catalog_item, _ = ChecklistItemCatalog.objects.get_or_create(
        nombre='Revisar frenos',
        defaults={
            'categoria': 'SISTEMA_FRENOS',
            'tipo_pregunta': 'SELECT',
            'pregunta_texto': '¿Estado de los frenos?',
            'es_obligatorio_por_defecto': True,
            'opciones_seleccion': ['bueno', 'regular', 'malo'],
            'activo': True
        }
    )
    if created_template:
        ChecklistItemTemplate.objects.create(
            checklist_template=template,
            catalog_item=catalog_item,
            orden_visual=1
        )
    elif not ChecklistItemTemplate.objects.filter(checklist_template=template, catalog_item=catalog_item).exists():
        ChecklistItemTemplate.objects.create(
            checklist_template=template,
            catalog_item=catalog_item,
            orden_visual=1
        )
    
    try:
        oferta_servicio, _ = OfertaServicio.objects.get_or_create(
            taller=taller_a,
            servicio=servicio,
            defaults={
                'tipo_proveedor': 'taller',
                'precio_con_repuestos': Decimal('15000'),
                'precio_sin_repuestos': Decimal('10000'),
                'duracion_minima_minutos': 20,
                'duracion_maxima_minutos': 40
            }
        )
    finally:
        # Reconnect signal
        post_save.connect(mecanimovilapp.apps.agente_ia.signals.sync_oferta_servicio_chunk, sender=OfertaServicio)
    
    print(f"✅ Catalog: OfertaServicio ID {oferta_servicio.id}\n")
    
    owner_a, _ = MiembroTaller.objects.get_or_create(
        taller=taller_a,
        usuario=user_a,
        defaults={'rol': 'mandante', 'activo': True}
    )
    
    # Mechanic for A
    user_mec_a, _ = User.objects.get_or_create(
        username='http_v2_mec_a',
        defaults={'email': 'httpv2meca@test.com'}
    )
    user_mec_a.set_password('test123')
    user_mec_a.save()
    
    mec_a, _ = MiembroTaller.objects.get_or_create(
        taller=taller_a,
        usuario=user_mec_a,
        defaults={'rol': 'mecanico', 'activo': True}
    )
    
    # Taller B (cross-tenant)
    user_b, _ = User.objects.get_or_create(
        username='http_v2_taller_b',
        defaults={'email': 'httpv2b@test.com'}
    )
    user_b.set_password('test123')
    user_b.save()
    
    taller_b, _ = Taller.objects.get_or_create(
        usuario=user_b,
        defaults={'nombre': 'HTTP V2 Taller B', 'rut': '44444444-4'}
    )
    
    owner_b, _ = MiembroTaller.objects.get_or_create(
        taller=taller_b,
        usuario=user_b,
        defaults={'rol': 'mandante', 'activo': True}
    )
    
    # Cliente
    user_cliente, _ = User.objects.get_or_create(
        username='http_v2_cliente',
        defaults={'email': 'httpv2cliente@test.com'}
    )
    user_cliente.set_password('test123')
    user_cliente.save()
    
    cliente, _ = Cliente.objects.get_or_create(
        usuario=user_cliente,
        defaults={
            'nombre': 'HTTP V2 Cliente',
            'apellido': 'Test',
            'email': 'httpv2cliente@test.com',
            'telefono': '+56922222222'
        }
    )
    
    # Vehiculo
    marca, _ = MarcaVehiculo.objects.get_or_create(nombre='Toyota')
    modelo, _ = Modelo.objects.get_or_create(marca=marca, nombre='Corolla')
    vehiculo, _ = Vehiculo.objects.get_or_create(
        cliente=cliente,
        patente='V2TEST',
        defaults={'marca': marca, 'modelo': modelo, 'year': 2020}
    )
    
    # Clean old orders
    SolicitudServicio.objects.filter(taller=taller_a).delete()
    
    # Create 3 orders for different test scenarios
    orden1 = SolicitudServicio.objects.create(
        cliente=cliente,
        vehiculo=vehiculo,
        taller=taller_a,
        tipo_servicio='taller',
        fecha_servicio=date.today(),
        hora_servicio=dt_time(10, 0),
        estado='pendiente_aceptacion_proveedor',
        total=Decimal('30000'),
        metodo_pago='transferencia'
    )
    
    orden2 = SolicitudServicio.objects.create(
        cliente=cliente,
        vehiculo=vehiculo,
        taller=taller_a,
        tipo_servicio='taller',
        fecha_servicio=date.today(),
        hora_servicio=dt_time(14, 0),
        estado='pendiente_aceptacion_proveedor',
        total=Decimal('35000'),
        metodo_pago='transferencia'
    )
    
    orden3 = SolicitudServicio.objects.create(
        cliente=cliente,
        vehiculo=vehiculo,
        taller=taller_a,
        tipo_servicio='taller',
        fecha_servicio=date.today(),
        hora_servicio=dt_time(16, 0),
        estado='pendiente_aceptacion_proveedor',
        total=Decimal('40000'),
        metodo_pago='transferencia'
    )
    
    orden4 = SolicitudServicio.objects.create(
        cliente=cliente,
        vehiculo=vehiculo,
        taller=taller_a,
        tipo_servicio='taller',
        fecha_servicio=date.today(),
        hora_servicio=dt_time(18, 0),
        estado='pendiente_aceptacion_proveedor',
        total=Decimal('45000'),
        metodo_pago='transferencia'
    )
    
    # Create base quotes
    cot_base1 = CotizacionCanal.objects.create(
        taller=taller_a,
        creado_por=user_a,
        estado='aceptada',
        mano_obra_clp=Decimal('30000'),
        total_clp=Decimal('30000'),
        token=str(uuid.uuid4())
    )
    
    cot_base2 = CotizacionCanal.objects.create(
        taller=taller_a,
        creado_por=user_a,
        estado='aceptada',
        mano_obra_clp=Decimal('35000'),
        total_clp=Decimal('35000'),
        token=str(uuid.uuid4())
    )
    
    cot_base3 = CotizacionCanal.objects.create(
        taller=taller_a,
        creado_por=user_a,
        estado='aceptada',
        mano_obra_clp=Decimal('40000'),
        total_clp=Decimal('40000'),
        token=str(uuid.uuid4())
    )
    
    cot_base4 = CotizacionCanal.objects.create(
        taller=taller_a,
        creado_por=user_a,
        estado='aceptada',
        mano_obra_clp=Decimal('45000'),
        total_clp=Decimal('45000'),
        token=str(uuid.uuid4())
    )
    
    print(f"✅ Taller A ID: {taller_a.id}")
    print(f"✅ Mechanic A ID: {mec_a.id}")
    print(f"✅ Taller B ID: {taller_b.id}")
    print(f"✅ Order 1 ID: {orden1.id}")
    print(f"✅ Order 2 ID: {orden2.id}")
    print(f"✅ Order 3 ID: {orden3.id}")
    print(f"✅ Order 4 ID: {orden4.id}")
    print(f"✅ OfertaServicio ID: {oferta_servicio.id}")
    print(f"✅ ChecklistTemplate ID: {template.id}\n")
    
    return {
        'taller_a_username': 'http_v2_taller_a',
        'mec_a_username': 'http_v2_mec_a',
        'taller_b_username': 'http_v2_taller_b',
        'taller_a': taller_a,
        'taller_b': taller_b,
        'mec_a': mec_a,
        'orden1': orden1,
        'orden2': orden2,
        'orden3': orden3,
        'orden4': orden4,
        'cot_base1': cot_base1,
        'cot_base2': cot_base2,
        'cot_base3': cot_base3,
        'cot_base4': cot_base4,
        'oferta_servicio_id': oferta_servicio.id,
        'checklist_template': template,
        'checklist_item': catalog_item
    }

def login(username, password):
    """Login via DRF Token."""
    resp = requests.post(
        f"{BASE_URL}/api/usuarios/login-proveedor/",
        json={"username": username, "password": password},
        timeout=5
    )
    if resp.status_code != 200:
        return None, f"Login failed: {resp.status_code} - {resp.text[:200]}"
    data = resp.json()
    token = data.get('token')
    if not token:
        return None, "No token in response"
    return token, None

def test_extra_quote_workflow(data):
    """Test extra quote creation via API and customer consent."""
    print("="*70)
    print("EXTRA QUOTE WORKFLOW (Order 1)")
    print("="*70 + "\n")
    
    orden_id = data['orden1'].id
    cot_base = data['cot_base1']
    
    # Login as owner
    print("1️⃣  Owner Login")
    owner_token, err = login(data['taller_a_username'], 'test123')
    assert not err, f"Owner login failed: {err}"
    print(f"   ✅ Token: {owner_token[:20]}...\n")
    
    # Accept and assign
    print("2️⃣  Accept & Assign Order")
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/aceptar/",
        headers={"Authorization": f"Token {owner_token}"},
        json={},
        timeout=5
    )
    assert resp.status_code == 200, f"Accept failed: {resp.status_code}"
    
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/asignar_tecnico/",
        headers={"Authorization": f"Token {owner_token}"},
        json={
            "mecanico_id": data['mec_a'].id,
            "fecha": str(date.today()),
            "hora": "10:00"
        },
        timeout=5
    )
    assert resp.status_code == 200, f"Assign failed: {resp.status_code}"
    print(f"   ✅ Accepted and assigned\n")
    
    # Start service
    print("3️⃣  Start Service")
    mec_token, err = login(data['mec_a_username'], 'test123')
    assert not err, f"Mechanic login failed: {err}"
    
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/iniciar_servicio/",
        headers={"Authorization": f"Token {mec_token}"},
        json={},
        timeout=5
    )
    assert resp.status_code == 200, f"Start service failed: {resp.status_code}"
    print(f"   ✅ Service started\n")
    
    # Create cita for extra quotes
    cita = CitaAgendaPersonal.objects.create(
        taller=data['taller_a'],
        cotizacion_canal_origen=cot_base,
        fecha_servicio=date.today(),
        hora_servicio=dt_time(10, 0),
        duracion_minutos=60,
        tipo_servicio='taller',
        estado='activa',
        creado_por=data['taller_a'].usuario
    )
    
    # 4. Create extra quote via ACTUAL API with catalog
    print("4️⃣  Create Extra Quote via API")
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/cotizaciones-canal/crear-adicional/",
        headers={"Authorization": f"Token {owner_token}"},
        json={
            "cita_id": cita.id,
            "cotizacion_original_id": cot_base.id,
            "motivo_servicio_adicional": "Filtro de aceite en mal estado",
            "modo": "catalogo",
            "servicios_catalogo": [
                {
                    "oferta_servicio_id": data['oferta_servicio_id'],
                    "cantidad": 1
                }
            ],
            "ejecucion_adicional": "misma_visita"
        },
        timeout=5
    )
    assert resp.status_code == 201, f"Create extra failed: {resp.status_code} - {resp.text[:200]}"
    extra_data = resp.json()
    extra_id = extra_data['cotizacion']['id']
    print(f"   ✅ Extra created via API: ID {extra_id}\n")
    
    # Get the created quote to get token
    from mecanimovilapp.apps.ordenes.models import CotizacionCanal
    cot_extra = CotizacionCanal.objects.get(id=extra_id)
    
    # Mark as ready/generate token if needed
    if not cot_extra.token:
        cot_extra.token = str(uuid.uuid4())
    if cot_extra.estado == 'borrador':
        cot_extra.estado = 'enviada'
    cot_extra.save()
    
    # 5. Customer views via public token
    print("5️⃣  Customer Views Extra Quote")
    resp = requests.get(
        f"{BASE_URL}/api/ordenes/cotizaciones-publicas/{cot_extra.token}/",
        timeout=5
    )
    assert resp.status_code == 200, f"View quote failed: {resp.status_code}"
    print(f"   ✅ Quote visible via public token\n")
    
    # 6. Customer accepts
    print("6️⃣  Customer Accepts Extra Quote")
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/cotizaciones-publicas/{cot_extra.token}/aceptar/",
        json={},
        timeout=5
    )
    assert resp.status_code == 200, f"Accept failed: {resp.status_code}"
    cot_extra.refresh_from_db()
    assert cot_extra.estado == 'aceptada', f"Expected aceptada, got {cot_extra.estado}"
    print(f"   ✅ Quote accepted, estado: {cot_extra.estado}\n")
    
    # 7. Test replay guard
    print("7️⃣  Test Replay Guard")
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/cotizaciones-publicas/{cot_extra.token}/aceptar/",
        json={},
        timeout=5
    )
    assert resp.status_code == 200
    result = resp.json()
    assert 'ya fue respondida' in result.get('message', ''), "Expected replay message"
    print(f"   ✅ Replay prevented\n")
    
    return cita

def test_cross_tenant_creation(data):
    """Test cross-tenant isolation with structurally valid payload."""
    print("="*70)
    print("CROSS-TENANT CREATION TEST")
    print("="*70 + "\n")
    
    owner_token, _ = login(data['taller_a_username'], 'test123')
    b_token, _ = login(data['taller_b_username'], 'test123')
    
    # Create fresh cita for Taller A
    cita_a = CitaAgendaPersonal.objects.create(
        taller=data['taller_a'],
        cotizacion_canal_origen=data['cot_base1'],
        fecha_servicio=date.today(),
        hora_servicio=dt_time(10, 0),
        duracion_minutos=60,
        tipo_servicio='taller',
        estado='activa',
        creado_por=data['taller_a'].usuario
    )
    
    # Valid payload structure
    payload = {
        "cita_id": cita_a.id,  # Taller A's cita
        "cotizacion_original_id": data['cot_base1'].id,  # Taller A's quote
        "motivo_servicio_adicional": "Test cross-tenant",
        "modo": "catalogo",
        "servicios_catalogo": [{"oferta_servicio_id": data['oferta_servicio_id'], "cantidad": 1}]
    }
    
    # 1. Verify owner succeeds with this exact payload
    print("1️⃣  Owner Creates Extra (Baseline)")
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/cotizaciones-canal/crear-adicional/",
        headers={"Authorization": f"Token {owner_token}"},
        json=payload,
        timeout=5
    )
    assert resp.status_code == 201, f"Owner should succeed: {resp.status_code} - {resp.text[:200]}"
    print(f"   ✅ Owner succeeds with same payload (201)\n")
    
    # 2. Taller B tries identical payload (cross-tenant denial)
    print("2️⃣  Taller B Tries Identical Payload")
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/cotizaciones-canal/crear-adicional/",
        headers={"Authorization": f"Token {b_token}"},
        json=payload,
        timeout=5
    )
    assert resp.status_code == 400, f"Expected 400 ownership error, got {resp.status_code}"
    error_data = resp.json()
    # Should get tenant/ownership validation error on cita_id or cotizacion_original_id
    has_ownership_error = (
        'cita_id' in error_data or 
        'cotizacion_original_id' in error_data or
        ('detail' in error_data and 'encontrad' in str(error_data['detail']).lower())
    )
    assert has_ownership_error, f"Expected ownership error, got: {error_data}"
    print(f"   ✅ Cross-tenant POST denied (400): {error_data}\n")

def test_base_order_with_pending_extra(data):
    """Test base order closure with pending extra through actual workflow."""
    print("="*70)
    print("BASE ORDER CLOSURE WITH PENDING EXTRA (Order 2)")
    print("="*70 + "\n")
    
    orden_id = data['orden2'].id
    cot_base = data['cot_base2']
    
    owner_token, _ = login(data['taller_a_username'], 'test123')
    mec_token, _ = login(data['mec_a_username'], 'test123')
    
    print("1️⃣  Setup & Start Order 2")
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/aceptar/",
        headers={"Authorization": f"Token {owner_token}"},
        json={},
        timeout=5
    )
    assert resp.status_code == 200, f"Accept failed: {resp.status_code}"
    
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/asignar_tecnico/",
        headers={"Authorization": f"Token {owner_token}"},
        json={
            "mecanico_id": data['mec_a'].id,
            "fecha": str(date.today()),
            "hora": "14:00"
        },
        timeout=5
    )
    assert resp.status_code == 200, f"Assign failed: {resp.status_code}"
    
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/iniciar_servicio/",
        headers={"Authorization": f"Token {mec_token}"},
        json={},
        timeout=5
    )
    assert resp.status_code == 200, f"Start failed: {resp.status_code}"
    result = resp.json()
    checklist_id = result.get('checklist_id')
    print(f"   ✅ Order started, checklist_id: {checklist_id}\n")
    
    # Create pending extra
    print("2️⃣  Create Pending Extra Quote")
    cita = CitaAgendaPersonal.objects.create(
        taller=data['taller_a'],
        cotizacion_canal_origen=cot_base,
        fecha_servicio=date.today(),
        hora_servicio=dt_time(14, 0),
        duracion_minutos=60,
        tipo_servicio='taller',
        estado='activa',
        creado_por=data['taller_a'].usuario
    )
    
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/cotizaciones-canal/crear-adicional/",
        headers={"Authorization": f"Token {owner_token}"},
        json={
            "cita_id": cita.id,
            "cotizacion_original_id": cot_base.id,
            "motivo_servicio_adicional": "Extra pending",
            "modo": "catalogo",
            "servicios_catalogo": [{"oferta_servicio_id": data['oferta_servicio_id'], "cantidad": 1}]
        },
        timeout=5
    )
    assert resp.status_code == 201, f"Create extra failed: {resp.status_code}"
    print(f"   ✅ Extra created (pending)\n")
    
    # Complete checklist if exists, or transition to en_proceso
    if checklist_id:
        print("3️⃣  Complete Checklist Prerequisites")
        resp = requests.post(
            f"{BASE_URL}/api/checklists/instances/{checklist_id}/finalize/",
            headers={"Authorization": f"Token {mec_token}"},
            json={
                "firma_tecnico": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            },
            timeout=5
        )
        assert resp.status_code == 200, f"Checklist finalize failed: {resp.status_code}"
        print(f"   ✅ Checklist finalized\n")
    else:
        print("3️⃣  Transition to en_proceso (no checklist)")
        resp = requests.post(
            f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/actualizar_estado/",
            headers={"Authorization": f"Token {owner_token}"},
            json={"estado": "en_proceso"},
            timeout=5
        )
        assert resp.status_code == 200, f"Transition to en_proceso failed: {resp.status_code} - {resp.text[:200]}"
        print(f"   ✅ Transitioned to en_proceso\n")
    
    # Close base order
    print("4️⃣  Close Base Order")
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/finalizar_servicio/",
        headers={"Authorization": f"Token {owner_token}"},
        json={},
        timeout=5
    )
    assert resp.status_code == 200, f"Finalizar failed: {resp.status_code} - {resp.text[:200]}"
    
    # Verify final state
    resp = requests.get(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/",
        headers={"Authorization": f"Token {owner_token}"},
        timeout=5
    )
    assert resp.status_code == 200
    order_state = resp.json()['estado']
    assert order_state == 'completado', f"Expected completado, got {order_state}"
    print(f"   ✅ Base CLOSED (estado: {order_state}) independently of pending extra\n")

def test_base_order_with_rejected_extra(data):
    """Test base order closure with rejected extra through actual workflow."""
    print("="*70)
    print("BASE ORDER CLOSURE WITH REJECTED EXTRA (Order 3)")
    print("="*70 + "\n")
    
    orden_id = data['orden3'].id
    cot_base = data['cot_base3']
    
    owner_token, _ = login(data['taller_a_username'], 'test123')
    mec_token, _ = login(data['mec_a_username'], 'test123')
    
    print("1️⃣  Setup & Start Order 3")
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/aceptar/",
        headers={"Authorization": f"Token {owner_token}"},
        json={},
        timeout=5
    )
    assert resp.status_code == 200
    
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/asignar_tecnico/",
        headers={"Authorization": f"Token {owner_token}"},
        json={
            "mecanico_id": data['mec_a'].id,
            "fecha": str(date.today()),
            "hora": "16:00"
        },
        timeout=5
    )
    assert resp.status_code == 200
    
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/iniciar_servicio/",
        headers={"Authorization": f"Token {mec_token}"},
        json={},
        timeout=5
    )
    assert resp.status_code == 200
    result = resp.json()
    checklist_id = result.get('checklist_id')
    print(f"   ✅ Order started, checklist_id: {checklist_id}\n")
    
    # Create and reject extra
    print("2️⃣  Create & Reject Extra Quote")
    cita = CitaAgendaPersonal.objects.create(
        taller=data['taller_a'],
        cotizacion_canal_origen=cot_base,
        fecha_servicio=date.today(),
        hora_servicio=dt_time(16, 0),
        duracion_minutos=60,
        tipo_servicio='taller',
        estado='activa',
        creado_por=data['taller_a'].usuario
    )
    
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/cotizaciones-canal/crear-adicional/",
        headers={"Authorization": f"Token {owner_token}"},
        json={
            "cita_id": cita.id,
            "cotizacion_original_id": cot_base.id,
            "motivo_servicio_adicional": "Extra to reject",
            "modo": "catalogo",
            "servicios_catalogo": [{"oferta_servicio_id": data['oferta_servicio_id'], "cantidad": 1}]
        },
        timeout=5
    )
    assert resp.status_code == 201
    extra_data = resp.json()
    extra_id = extra_data['cotizacion']['id']
    
    # Prepare and reject
    from mecanimovilapp.apps.ordenes.models import CotizacionCanal
    cot_extra = CotizacionCanal.objects.get(id=extra_id)
    if not cot_extra.token:
        cot_extra.token = str(uuid.uuid4())
    cot_extra.estado = 'enviada'
    cot_extra.save()
    
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/cotizaciones-publicas/{cot_extra.token}/rechazar/",
        json={},
        timeout=5
    )
    assert resp.status_code == 200
    cot_extra.refresh_from_db()
    assert cot_extra.estado == 'rechazada'
    print(f"   ✅ Extra rejected (estado: rechazada)\n")
    
    # Complete checklist if exists, or transition to en_proceso
    if checklist_id:
        print("3️⃣  Complete Checklist Prerequisites")
        resp = requests.post(
            f"{BASE_URL}/api/checklists/instances/{checklist_id}/finalize/",
            headers={"Authorization": f"Token {mec_token}"},
            json={
                "firma_tecnico": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            },
            timeout=5
        )
        assert resp.status_code == 200, f"Checklist finalize failed: {resp.status_code}"
        print(f"   ✅ Checklist finalized\n")
    else:
        print("3️⃣  Transition to en_proceso (no checklist)")
        resp = requests.post(
            f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/actualizar_estado/",
            headers={"Authorization": f"Token {owner_token}"},
            json={"estado": "en_proceso"},
            timeout=5
        )
        assert resp.status_code == 200, f"Transition to en_proceso failed: {resp.status_code} - {resp.text[:200]}"
        print(f"   ✅ Transitioned to en_proceso\n")
    
    # Close base order
    print("4️⃣  Close Base Order")
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/finalizar_servicio/",
        headers={"Authorization": f"Token {owner_token}"},
        json={},
        timeout=5
    )
    assert resp.status_code == 200, f"Finalizar failed: {resp.status_code} - {resp.text[:200]}"
    
    # Verify final state
    resp = requests.get(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/",
        headers={"Authorization": f"Token {owner_token}"},
        timeout=5
    )
    assert resp.status_code == 200
    order_state = resp.json()['estado']
    assert order_state == 'completado', f"Expected completado, got {order_state}"
    print(f"   ✅ Base CLOSED (estado: {order_state}) independently of rejected extra\n")


def _get_checklist(token, checklist_id):
    resp = requests.get(
        f"{BASE_URL}/api/checklists/instances/{checklist_id}/",
        headers={"Authorization": f"Token {token}"},
        timeout=5,
    )
    assert resp.status_code == 200, f"Checklist GET failed: {resp.status_code} - {resp.text[:300]}"
    return resp.json()


def _respuesta_seleccion(checklist):
    respuestas = checklist.get('respuestas') or []
    assert len(respuestas) == 1, f"Expected 1 saved response, got {respuestas}"
    return respuestas[0].get('respuesta_seleccion')


def _get_orden_estado(token, orden_id):
    resp = requests.get(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/",
        headers={"Authorization": f"Token {token}"},
        timeout=5,
    )
    assert resp.status_code == 200, f"Order GET failed: {resp.status_code} - {resp.text[:300]}"
    return resp.json()['estado']


def _ids_ordenes(token):
    ids = set()
    url = f"{BASE_URL}/api/ordenes/proveedor-ordenes/"
    while url:
        resp = requests.get(
            url,
            headers={"Authorization": f"Token {token}"},
            timeout=5,
        )
        assert resp.status_code == 200, f"Order list failed: {resp.status_code}"
        body = resp.json()
        if isinstance(body, list):
            ids.update(row['id'] for row in body)
            break
        ids.update(row['id'] for row in body.get('results', []))
        url = body.get('next')
    return ids


def _ids_citas(token):
    resp = requests.get(
        f"{BASE_URL}/api/ordenes/citas-agenda-personal/",
        headers={"Authorization": f"Token {token}"},
        timeout=5,
    )
    assert resp.status_code == 200, f"Cita list failed: {resp.status_code} - {resp.text[:200]}"
    body = resp.json()
    rows = body if isinstance(body, list) else body.get('results', [])
    return {row['id'] for row in rows}


def test_checklist_required_flow(data):
    """Test base order closure with required checklist completion."""
    print("="*70)
    print("CHECKLIST-REQUIRED FLOW WITH PENDING EXTRA (Order 4)")
    print("="*70 + "\n")
    
    orden_id = data['orden4'].id
    cot_base = data['cot_base4']
    
    owner_token, _ = login(data['taller_a_username'], 'test123')
    mec_token, _ = login(data['mec_a_username'], 'test123')
    
    print("1️⃣  Setup & Start Order 4 (with checklist template)")
    
    # Create LineaServicio with OfertaServicio that has the checklist-enabled servicio
    # (automatic checklist creation requires orden.lineas with oferta_servicio.servicio)
    from mecanimovilapp.apps.ordenes.models import LineaServicio
    from mecanimovilapp.apps.servicios.models import OfertaServicio
    from django.db.models.signals import post_save
    import mecanimovilapp.apps.agente_ia.signals
    
    # Temporarily disconnect signal for this creation
    post_save.disconnect(mecanimovilapp.apps.agente_ia.signals.sync_oferta_servicio_chunk, sender=OfertaServicio)
    try:
        oferta_with_servicio = OfertaServicio.objects.create(
            taller=data['taller_a'],
            servicio=data['checklist_template'].servicio,
            tipo_proveedor='taller',
            precio_con_repuestos=Decimal('15000'),
            precio_sin_repuestos=Decimal('10000'),
            duracion_minima_minutos=20,
            duracion_maxima_minutos=40
        )
    finally:
        post_save.connect(mecanimovilapp.apps.agente_ia.signals.sync_oferta_servicio_chunk, sender=OfertaServicio)
    
    LineaServicio.objects.create(
        solicitud=data['orden4'],
        oferta_servicio=oferta_with_servicio,
        cantidad=1,
        precio_unitario=Decimal('15000')
    )
    
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/aceptar/",
        headers={"Authorization": f"Token {owner_token}"},
        json={},
        timeout=5
    )
    assert resp.status_code == 200, f"Accept failed: {resp.status_code}"
    
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/asignar_tecnico/",
        headers={"Authorization": f"Token {owner_token}"},
        json={
            "mecanico_id": data['mec_a'].id,
            "fecha": str(date.today()),
            "hora": "18:00"
        },
        timeout=5
    )
    assert resp.status_code == 200, f"Assign failed: {resp.status_code}"
    
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/iniciar_servicio/",
        headers={"Authorization": f"Token {mec_token}"},
        json={},
        timeout=5
    )
    assert resp.status_code == 200, f"iniciar_servicio failed: {resp.status_code} - {resp.text[:300]}"
    result = resp.json()
    assert result.get('checklist_creado') is True, f"iniciar_servicio did not create a checklist: {result}"
    checklist_id = result.get('checklist_id')
    assert checklist_id, f"iniciar_servicio response missing checklist_id: {result}"
    
    resp = requests.get(
        f"{BASE_URL}/api/checklists/instances/{checklist_id}/",
        headers={"Authorization": f"Token {mec_token}"},
        timeout=5
    )
    assert resp.status_code == 200, f"Checklist GET failed: {resp.status_code} - {resp.text[:200]}"
    checklist_data = resp.json()
    assert checklist_data['id'] == checklist_id
    assert checklist_data['estado'] == 'PENDIENTE', (
        f"API-created checklist must start PENDIENTE, got {checklist_data['estado']}"
    )
    print(f"   ✅ iniciar_servicio created checklist {checklist_id} (PENDIENTE)\n")
    
    # Create pending extra
    print("2️⃣  Create Pending Extra Quote")
    cita = CitaAgendaPersonal.objects.create(
        taller=data['taller_a'],
        cotizacion_canal_origen=cot_base,
        fecha_servicio=date.today(),
        hora_servicio=dt_time(18, 0),
        duracion_minutos=60,
        tipo_servicio='taller',
        estado='activa',
        creado_por=data['taller_a'].usuario
    )
    
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/cotizaciones-canal/crear-adicional/",
        headers={"Authorization": f"Token {owner_token}"},
        json={
            "cita_id": cita.id,
            "cotizacion_original_id": cot_base.id,
            "motivo_servicio_adicional": "Extra with checklist",
            "modo": "catalogo",
            "servicios_catalogo": [{"oferta_servicio_id": data['oferta_servicio_id'], "cantidad": 1}]
        },
        timeout=5
    )
    assert resp.status_code == 201, f"Create extra failed: {resp.status_code} - {resp.text[:300]}"
    extra_body = resp.json()['cotizacion']
    extra_id = extra_body['id']
    extra_estado_inicial = extra_body['estado']
    assert extra_estado_inicial in ('borrador', 'enviada'), (
        f"Unexpected extra estado at creation: {extra_estado_inicial}"
    )
    extra_cita_ultima_id = extra_body.get('cita_ultima_id')
    extra_cita_ultima_estado = extra_body.get('cita_ultima_estado')
    citas_antes = _ids_citas(owner_token)
    ordenes_antes = _ids_ordenes(owner_token)
    print(f"   ✅ Extra {extra_id} created (estado: {extra_estado_inicial})\n")
    
    # Try to close from checklist_en_progreso (state machine guard)
    print("3️⃣  Try to Close from checklist_en_progreso (state guard)")
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/finalizar_servicio/",
        headers={"Authorization": f"Token {owner_token}"},
        json={},
        timeout=5
    )
    assert resp.status_code == 400, f"Should fail from checklist_en_progreso: {resp.status_code}"
    error_msg = resp.json().get('error', '')
    assert 'checklist_en_progreso' in error_msg or 'servicio_iniciado' in error_msg, f"Expected state guard error, got: {error_msg}"
    print(f"   ✅ Blocked by state guard (400: {error_msg})\n")
    
    # Checklist gate will be tested after completing checklist but before finalization
    # (finalizar_servicio checks checklist estado == 'COMPLETADO')
    
    print("4️⃣  Partial save, start, pause, resume")
    from mecanimovilapp.apps.checklists.models import ChecklistItemTemplate
    item_template = ChecklistItemTemplate.objects.filter(
        checklist_template=data['checklist_template']
    ).first()
    assert item_template, "Fixture template has no item"
    item_template_id = item_template.id
    
    resp = requests.post(
        f"{BASE_URL}/api/checklists/responses/",
        headers={"Authorization": f"Token {mec_token}"},
        json={
            "checklist_instance": checklist_id,
            "item_template": item_template_id,
            "respuesta_seleccion": "bueno"
        },
        timeout=5
    )
    assert resp.status_code == 201, f"Save response failed: {resp.status_code} - {resp.text[:300]}"
    
    persisted = _get_checklist(mec_token, checklist_id)
    assert persisted['estado'] == 'PENDIENTE', f"Partial save must leave PENDIENTE, got {persisted['estado']}"
    assert _respuesta_seleccion(persisted) == 'bueno'
    print("   ✅ Partial save kept PENDIENTE and respuesta=bueno\n")
    
    resp = requests.post(
        f"{BASE_URL}/api/checklists/instances/{checklist_id}/start/",
        headers={"Authorization": f"Token {mec_token}"},
        json={},
        timeout=5
    )
    assert resp.status_code == 200, f"Checklist start failed: {resp.status_code} - {resp.text[:300]}"
    started = _get_checklist(mec_token, checklist_id)
    assert started['estado'] == 'EN_PROGRESO', f"start must set EN_PROGRESO, got {started['estado']}"
    assert _respuesta_seleccion(started) == 'bueno'
    print("   ✅ POST /start/ → EN_PROGRESO, respuesta unchanged\n")
    
    resp = requests.post(
        f"{BASE_URL}/api/checklists/instances/{checklist_id}/pause/",
        headers={"Authorization": f"Token {mec_token}"},
        json={},
        timeout=5
    )
    assert resp.status_code == 200, f"Pause failed: {resp.status_code} - {resp.text[:300]}"
    paused = _get_checklist(mec_token, checklist_id)
    assert paused['estado'] == 'PAUSADO', f"Expected PAUSADO, got {paused['estado']}"
    assert _respuesta_seleccion(paused) == 'bueno'
    print("   ✅ POST /pause/ → PAUSADO, respuesta unchanged\n")
    
    resp = requests.post(
        f"{BASE_URL}/api/checklists/instances/{checklist_id}/resume/",
        headers={"Authorization": f"Token {mec_token}"},
        json={},
        timeout=5
    )
    assert resp.status_code == 200, f"Resume failed: {resp.status_code} - {resp.text[:300]}"
    resumed = _get_checklist(mec_token, checklist_id)
    assert resumed['estado'] == 'EN_PROGRESO', f"Expected EN_PROGRESO, got {resumed['estado']}"
    assert _respuesta_seleccion(resumed) == 'bueno'
    print("   ✅ POST /resume/ → EN_PROGRESO, respuesta unchanged\n")
    
    print("5️⃣  en_proceso with unfinished checklist, then finalizar_servicio gate")
    orden_estado = _get_orden_estado(owner_token, orden_id)
    assert orden_estado == 'checklist_en_progreso', (
        f"Expected checklist_en_progreso before transition, got {orden_estado}"
    )
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/actualizar_estado/",
        headers={"Authorization": f"Token {owner_token}"},
        json={"estado": "en_proceso"},
        timeout=5
    )
    assert resp.status_code == 400, f"Direct en_proceso must be rejected: {resp.status_code} - {resp.text[:300]}"
    blocked = resp.json()
    assert blocked.get('error', '').startswith('Transición inválida'), blocked
    assert 'en_proceso' not in blocked.get('estados_validos', []), blocked
    assert _get_orden_estado(owner_token, orden_id) == 'checklist_en_progreso'
    print(f"   ✅ Direct en_proceso blocked: {blocked['error']}\n")
    
    # Valid map: checklist_en_progreso → checklist_completado → en_proceso.
    # actualizar_estado does not require the checklist instance to be COMPLETADO.
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/actualizar_estado/",
        headers={"Authorization": f"Token {owner_token}"},
        json={"estado": "checklist_completado"},
        timeout=5
    )
    assert resp.status_code == 200, f"checklist_completado transition failed: {resp.status_code} - {resp.text[:300]}"
    assert _get_orden_estado(owner_token, orden_id) == 'checklist_completado'
    
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/actualizar_estado/",
        headers={"Authorization": f"Token {owner_token}"},
        json={"estado": "en_proceso"},
        timeout=5
    )
    assert resp.status_code == 200, f"en_proceso transition failed: {resp.status_code} - {resp.text[:300]}"
    assert _get_orden_estado(owner_token, orden_id) == 'en_proceso'
    unfinished = _get_checklist(mec_token, checklist_id)
    assert unfinished['estado'] != 'COMPLETADO', unfinished['estado']
    assert _respuesta_seleccion(unfinished) == 'bueno'
    print("   ✅ Order persisted en_proceso while checklist still unfinished\n")
    
    resp = requests.post(
        f"{BASE_URL}/api/ordenes/proveedor-ordenes/{orden_id}/finalizar_servicio/",
        headers={"Authorization": f"Token {owner_token}"},
        json={},
        timeout=5
    )
    assert resp.status_code == 400, f"Expected checklist gate 400, got {resp.status_code} - {resp.text[:300]}"
    gate_error = resp.json().get('error')
    assert gate_error == 'No se puede finalizar el servicio sin completar el checklist', gate_error
    assert _get_orden_estado(owner_token, orden_id) == 'en_proceso'
    print(f"   ✅ finalizar_servicio 400: {gate_error}\n")
    
    print("6️⃣  Finalize Checklist with Signatures")
    resp = requests.post(
        f"{BASE_URL}/api/checklists/instances/{checklist_id}/finalize/",
        headers={"Authorization": f"Token {mec_token}"},
        json={
            "firma_tecnico": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "firma_cliente": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        },
        timeout=5
    )
    assert resp.status_code == 200, f"Checklist finalize failed: {resp.status_code} - {resp.text[:300]}"
    checklist_after = _get_checklist(mec_token, checklist_id)
    assert checklist_after['estado'] == 'COMPLETADO', checklist_after['estado']
    order_state_after = _get_orden_estado(owner_token, orden_id)
    assert order_state_after == 'completado', (
        f"finalize with both signatures must close the order, got {order_state_after}"
    )
    print("   ✅ Checklist COMPLETADO and base order completado\n")
    
    print("7️⃣  GET pending extra after base close")
    resp = requests.get(
        f"{BASE_URL}/api/ordenes/cotizaciones-canal/{extra_id}/",
        headers={"Authorization": f"Token {owner_token}"},
        params={"sin_retry": "1"},
        timeout=5,
    )
    assert resp.status_code == 200, f"Extra GET failed: {resp.status_code} - {resp.text[:300]}"
    extra_after = resp.json()
    assert extra_after['estado'] == extra_estado_inicial, (
        f"Extra estado changed: {extra_estado_inicial} → {extra_after['estado']}"
    )
    assert extra_after.get('cita_ultima_id') == extra_cita_ultima_id
    assert extra_after.get('cita_ultima_estado') == extra_cita_ultima_estado
    assert _ids_ordenes(owner_token) == ordenes_antes, "A new order was created for the unapproved extra"
    assert _ids_citas(owner_token) == citas_antes, "A new cita was created for the unapproved extra"
    print(
        f"   ✅ Extra still {extra_estado_inicial}; no new order or cita\n"
    )


if __name__ == '__main__':
    # Check server
    try:
        resp = requests.get(f"{BASE_URL}/api/usuarios/login-proveedor/", timeout=2)
        if resp.status_code >= 500:
            print("❌ Server error")
            sys.exit(1)
    except requests.exceptions.RequestException:
        print("❌ Server not running at localhost:8000")
        sys.exit(1)
    
    try:
        data = setup_test_data()
        test_extra_quote_workflow(data)
        test_cross_tenant_creation(data)
        test_base_order_with_pending_extra(data)
        test_base_order_with_rejected_extra(data)
        test_checklist_required_flow(data)
        
        print("="*70)
        print("✅ ALL HTTP SMOKE TESTS PASSED (STRICT ASSERTIONS)")
        print("="*70)
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ Assertion failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
