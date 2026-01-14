import os
import sys
import django
from datetime import datetime

# Setup paths
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mecanimovilapp.settings")
django.setup()

from django.core.management import call_command
from django.contrib.auth import get_user_model
from mecanimovilapp.apps.vehiculos.models import Vehiculo, MarcaVehiculo, Modelo
from mecanimovilapp.apps.vehiculos.models_health import ComponenteSaludConfig
from mecanimovilapp.apps.usuarios.models import Cliente

User = get_user_model()

def run_verification():
    print("🚀 Iniciando verificación de Migración Legacy...")
    
    # 1. Setup Test Data
    user, _ = User.objects.get_or_create(username="test_legacy_user", defaults={'email': "legacy@example.com"})
    cliente, _ = Cliente.objects.get_or_create(usuario=user)
    
    marca, _ = MarcaVehiculo.objects.get_or_create(nombre="TestLegacyMarca")
    modelo, _ = Modelo.objects.get_or_create(nombre="TestLegacyModelo", marca=marca)
    
    # Ensure Config exists
    config_aceite, _ = ComponenteSaludConfig.objects.update_or_create(
        nombre="Aceite Legacy Test",
        defaults={
            'tipo_motor_aplicable': 'TODOS',
            'eta': 10000,
            'beta': 2.0,
            'activo': True
        }
    )
    
    # 2. Create LEGACY Vehicle (No health components)
    patente = f'LEGACY-{datetime.now().strftime("%H%M%S")}-{os.urandom(2).hex()}'
    
    vehiculo = Vehiculo.objects.create(
        marca=marca,
        modelo=modelo,
        patente=patente,
        kilometraje=150000,
        tipo_motor='Gasolina',
        year=2015,
        cliente=cliente
    )
    print(f"📦 Vehículo Legacy creado: {vehiculo.patente} (Sin componentes de salud)")
    
    # Verify it has NO health components
    initial_count = vehiculo.componentes_salud.count()
    if initial_count == 0:
        print("   ✅ Confirmado: Vehículo no tiene componentes de salud.")
    else:
        print(f"   ❌ Error: El vehículo ya tiene {initial_count} componentes.")
        return

    # 3. Run Management Command
    print("\n🏃 Ejecutando comando populate_health_legacy...")
    call_command('populate_health_legacy')
    
    # 4. Verify Results
    vehiculo.refresh_from_db()
    final_count = vehiculo.componentes_salud.count()
    print(f"\n📊 Componentes después de migración: {final_count}")
    
    if final_count > 0:
        print("   ✅ Migración exitosa: Se crearon componentes.")
        
        # Check specific state (Should be Critical / 0 km service)
        comp = vehiculo.componentes_salud.filter(componente_config=config_aceite).first()
        if comp:
            print(f"   🔍 Estado de {comp.componente_config.nombre}:")
            print(f"      - Km Último Servicio: {comp.km_ultimo_servicio} (Esperado: 0)")
            print(f"      - Nivel Alerta: {comp.nivel_alerta} (Esperado: CRITICO)")
            
            if comp.km_ultimo_servicio == 0 and comp.nivel_alerta == 'CRITICO':
                print("      ✅ CORRECTO: Componente inicializado como crítico (seguro).")
            else:
                print("      ❌ ERROR: El componente no está en estado crítico.")
        else:
            print(f"   ❌ No se encontró el componente de prueba {config_aceite.nombre}")
            
    else:
        print("   ❌ FALLO: No se crearon componentes.")

if __name__ == "__main__":
    try:
        run_verification()
    except Exception as e:
        print(f"❌ Error fatal: {e}")
        import traceback
        traceback.print_exc()
