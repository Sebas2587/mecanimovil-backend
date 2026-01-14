#!/usr/bin/env python
"""
Script para verificar que el endpoint de checklist inicial funciona correctamente
y que hay componentes activos en la base de datos.
"""
import os
import sys
import django

# Configurar Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')
django.setup()

from mecanimovilapp.apps.vehiculos.models_health import ComponenteSaludConfig
from django.db.models import Q

def verificar_checklist():
    print("=" * 60)
    print("🔍 VERIFICACIÓN DEL CHECKLIST DE ONBOARDING")
    print("=" * 60)
    
    # 1. Verificar componentes activos para Gasolina
    print("\n1️⃣ Verificando componentes para GASOLINA:")
    componentes_gasolina = ComponenteSaludConfig.objects.filter(
        activo=True
    ).filter(
        Q(tipo_motor_aplicable='TODOS') | Q(tipo_motor_aplicable='GASOLINA')
    )
    
    print(f"   Total encontrados: {componentes_gasolina.count()}")
    if componentes_gasolina.exists():
        print("   Componentes:")
        for comp in componentes_gasolina.values('id', 'nombre', 'tipo_motor_aplicable'):
            print(f"      - ID: {comp['id']}, Nombre: {comp['nombre']}, Tipo: {comp['tipo_motor_aplicable']}")
    else:
        print("   ⚠️  NO HAY COMPONENTES ACTIVOS PARA GASOLINA")
        print("   Ejecuta: python manage.py populate_health_components")
    
    # 2. Verificar componentes activos para Diésel
    print("\n2️⃣ Verificando componentes para DIESEL:")
    componentes_diesel = ComponenteSaludConfig.objects.filter(
        activo=True
    ).filter(
        Q(tipo_motor_aplicable='TODOS') | Q(tipo_motor_aplicable='DIESEL')
    )
    
    print(f"   Total encontrados: {componentes_diesel.count()}")
    if componentes_diesel.exists():
        print("   Componentes:")
        for comp in componentes_diesel.values('id', 'nombre', 'tipo_motor_aplicable'):
            print(f"      - ID: {comp['id']}, Nombre: {comp['nombre']}, Tipo: {comp['tipo_motor_aplicable']}")
    else:
        print("   ⚠️  NO HAY COMPONENTES ACTIVOS PARA DIESEL")
        print("   Ejecuta: python manage.py populate_health_components")
    
    # 3. Verificar componentes TODOS
    print("\n3️⃣ Verificando componentes para TODOS los motores:")
    componentes_todos = ComponenteSaludConfig.objects.filter(
        activo=True,
        tipo_motor_aplicable='TODOS'
    )
    
    print(f"   Total encontrados: {componentes_todos.count()}")
    if componentes_todos.exists():
        print("   Componentes:")
        for comp in componentes_todos.values('id', 'nombre'):
            print(f"      - ID: {comp['id']}, Nombre: {comp['nombre']}")
    
    # 4. Resumen
    print("\n" + "=" * 60)
    print("📊 RESUMEN:")
    print("=" * 60)
    total_activos = ComponenteSaludConfig.objects.filter(activo=True).count()
    print(f"   Total componentes activos: {total_activos}")
    print(f"   Componentes para Gasolina: {componentes_gasolina.count()}")
    print(f"   Componentes para Diésel: {componentes_diesel.count()}")
    print(f"   Componentes para Todos: {componentes_todos.count()}")
    
    if total_activos == 0:
        print("\n❌ PROBLEMA DETECTADO: No hay componentes activos en la BD")
        print("   Solución: Ejecuta 'python manage.py populate_health_components'")
        return False
    elif componentes_gasolina.count() == 0:
        print("\n⚠️  ADVERTENCIA: No hay componentes para Gasolina")
        print("   El checklist no aparecerá para vehículos de gasolina")
        return False
    else:
        print("\n✅ Todo correcto: Hay componentes disponibles para el checklist")
        return True

if __name__ == "__main__":
    try:
        resultado = verificar_checklist()
        sys.exit(0 if resultado else 1)
    except Exception as e:
        print(f"\n❌ Error durante la verificación: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
