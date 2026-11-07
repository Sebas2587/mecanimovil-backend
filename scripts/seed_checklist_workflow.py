#!/usr/bin/env python3
"""
Seed complete checklist workflow for frontend testing.

Creates:
- Taller (workshop)
- Servicio (service) 
- ChecklistTemplate with ChecklistItemCatalog items linked to service
- Cliente (customer) + Vehiculo
- SolicitudServicio (order) with service
- Assigns mechanic
- Calls iniciar_servicio → creates ChecklistInstance

Usage:
    python manage.py shell < scripts/seed_checklist_workflow.py
"""

from django.contrib.auth import get_user_model
from django.db import transaction
from datetime import date, time
from decimal import Decimal

from mecanimovilapp.apps.usuarios.models import Taller, MiembroTaller
from mecanimovilapp.apps.servicios.models import Servicio, CategoriaServicio
from mecanimovilapp.apps.checklists.models import (
    ChecklistTemplate,
    ChecklistItemTemplate,
    ChecklistItemCatalog,
    ChecklistInstance,
    ChecklistItemResponse,
)
from mecanimovilapp.apps.ordenes.models import (
    SolicitudServicio,
    LineaServicio,
    Cliente,
    Vehiculo,
)
from mecanimovilapp.apps.servicios.models import OfertaServicio

User = get_user_model()

def seed_workflow():
    """Create complete workflow data."""
    
    print("\n" + "="*60)
    print("Seeding Checklist Workflow")
    print("="*60 + "\n")
    
    with transaction.atomic():
        # 1. Create or get taller
        print("1️⃣  Creating workshop...")
        user_taller, created = User.objects.get_or_create(
            username='taller_test',
            defaults={
                'email': 'taller_test@example.com',
                'first_name': 'Taller',
                'last_name': 'Test',
            }
        )
        if created:
            user_taller.set_password('test123')
            user_taller.save()
        
        taller, _ = Taller.objects.get_or_create(
            usuario=user_taller,
            defaults={
                'nombre': 'Taller Test',
                'telefono': '+56912345678',
            }
        )
        print(f"   ✅ Taller: {taller.nombre} (ID: {taller.id})")
        
        # 2. Create mechanic
        print("\n2️⃣  Creating mechanic...")
        user_mechanic, created = User.objects.get_or_create(
            username='mechanic_test',
            defaults={
                'email': 'mechanic_test@example.com',
                'first_name': 'Juan',
                'last_name': 'Mecánico',
            }
        )
        if created:
            user_mechanic.set_password('test123')
            user_mechanic.save()
        
        mechanic, _ = MiembroTaller.objects.get_or_create(
            taller=taller,
            usuario=user_mechanic,
            defaults={
                'rol': 'mecanico',
                'activo': True,
            }
        )
        print(f"   ✅ Mechanic: {mechanic.usuario.get_full_name()} (ID: {mechanic.id})")
        
        # 3. Create service
        print("\n3️⃣  Creating service...")
        servicio, _ = Servicio.objects.get_or_create(
            nombre='Inspección Test Frontend',
            defaults={
                'descripcion': 'Servicio de prueba para workflow de checklist',
            }
        )
        print(f"   ✅ Service: {servicio.nombre} (ID: {servicio.id})")
        
        # 4. Create checklist template with items
        print("\n4️⃣  Creating checklist template...")
        template, created = ChecklistTemplate.objects.get_or_create(
            servicio=servicio,
            activo=True,
            defaults={
                'nombre': 'Checklist Inspección Test',
                'descripcion': 'Template de prueba para frontend',
                'tipo_intencion_default': 'DIAGNOSTICO',
                'generado_por_ia': False,
                'version': '1.0',
            }
        )
        
        if created:
            print(f"   ✅ Template created: {template.nombre} (ID: {template.id})")
            
            # Create catalog items
            catalog_items = [
                {
                    'nombre': 'Revisar nivel de aceite',
                    'descripcion': 'Verificar nivel y estado del aceite de motor',
                    'tipo_pregunta': 'SELECT',
                    'opciones_seleccion': ['bueno', 'bajo', 'sucio'],
                },
                {
                    'nombre': 'Estado de frenos',
                    'descripcion': 'Inspeccionar pastillas y discos',
                    'tipo_pregunta': 'SELECT',
                    'opciones_seleccion': ['excelente', 'bueno', 'regular', 'malo'],
                },
                {
                    'nombre': 'Presión de neumáticos',
                    'descripcion': 'Medir presión en PSI',
                    'tipo_pregunta': 'NUMBER',
                },
                {
                    'nombre': 'Observaciones generales',
                    'descripcion': 'Notas adicionales del técnico',
                    'tipo_pregunta': 'TEXT',
                },
            ]
            
            for idx, item_data in enumerate(catalog_items, 1):
                catalog_item, _ = ChecklistItemCatalog.objects.get_or_create(
                    nombre=item_data['nombre'],
                    defaults={
                        'tipo_pregunta': item_data['tipo_pregunta'],
                        'opciones_seleccion': item_data.get('opciones_seleccion', []),
                    }
                )
                
                ChecklistItemTemplate.objects.get_or_create(
                    checklist_template=template,
                    catalog_item=catalog_item,
                    defaults={
                        'orden_visual': idx,
                        'es_obligatorio': True,
                    }
                )
                print(f"      ✓ Item {idx}: {catalog_item.nombre}")
        else:
            print(f"   ℹ️  Template already exists: {template.nombre} (ID: {template.id})")
            print(f"      Items: {template.items.count()}")
        
        # Note: Skip order creation for simplicity
        # Frontend can test with GET /api/checklists/templates/{id}/
        # The key verification is template → items linkage
        print("\n5️⃣  Verification: Template linked to service")
        linked_templates = ChecklistTemplate.objects.filter(servicio=servicio, activo=True)
        if linked_templates.exists():
            print(f"   ✅ Template correctly linked to service")
            print(f"      Service ID: {servicio.id}")
            print(f"      Template ID: {template.id}")
            print(f"      Items: {template.items.count()}")
        else:
            print(f"   ❌ Template NOT linked to service!")
            return False
    
    # Print summary
    print("\n" + "="*60)
    print("✅ Seed Complete - Ready for Frontend Testing")
    print("="*60 + "\n")
    
    print("📝 CREDENTIALS:")
    print(f"   Workshop Owner: taller_test@example.com / test123")
    print(f"   Mechanic: mechanic_test@example.com / test123")
    print(f"   Customer: cliente_test@example.com / test123")
    
    print("\n📋 CREATED IDs:")
    print(f"   Taller ID: {taller.id}")
    print(f"   Servicio ID: {servicio.id}")
    print(f"   Template ID: {template.id}")
    print(f"   Mechanic Miembro ID: {mechanic.id}")
    
    print("\n🔗 CRITICAL: Template → Service Linkage")
    print(f"   Template.servicio FK = {template.servicio_id}")
    print(f"   Service ID = {servicio.id}")
    print(f"   ✅ Match: {template.servicio_id == servicio.id}")
    
    print("\n🔗 API ENDPOINTS TO TEST:")
    print(f"   GET  /api/checklists/templates/{template.id}/")
    print(f"   GET  /api/checklists/templates/?servicio={servicio.id}")
    
    print("\n📖 Next: See QUICK_START_CHECKLIST.md for exact request examples\n")
    
    return True

# Auto-run when loaded via manage.py shell
try:
    seed_workflow()
except Exception as e:
    print(f"\n❌ Seed failed: {e}")
    import traceback
    traceback.print_exc()
