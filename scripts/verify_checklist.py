import os
import sys
import django
from datetime import datetime

# Setup paths
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mecanimovilapp.settings")
django.setup()

from django.test import RequestFactory
from rest_framework.test import APIRequestFactory, force_authenticate
from django.contrib.auth import get_user_model
from mecanimovilapp.apps.vehiculos.models import Vehiculo, MarcaVehiculo, Modelo
from mecanimovilapp.apps.vehiculos.models_health import ComponenteSaludConfig, ComponenteSaludVehiculo
from mecanimovilapp.apps.vehiculos.serializers import VehiculoSerializer
from mecanimovilapp.apps.usuarios.models import Cliente
from mecanimovilapp.apps.vehiculos.views import VehiculoViewSet

User = get_user_model()

def run_verification():
    print("🚀 Iniciando verificación de Checklist Inicial (DB Real)...")
    
    # 1. Setup Test Data
    # Use get_or_create to avoid IntegrityError
    user, created = User.objects.get_or_create(username="test_checklist_user", defaults={'email': "test@example.com"})
    if created:
        user.set_password("password123")
        user.save()
        print("👤 Usuario creado.")
    else:
        print("👤 Usuario existente encontrado.")
        
    cliente, _ = Cliente.objects.get_or_create(usuario=user)
    
    # Create Marca and Modelo
    marca, _ = MarcaVehiculo.objects.get_or_create(nombre="TestMarca")
    modelo, _ = Modelo.objects.get_or_create(nombre="TestModelo", marca=marca)
    
    # Ensure Configs exist
    config_aceite, _ = ComponenteSaludConfig.objects.update_or_create(
        nombre="Aceite Motor Test",
        defaults={
            'tipo_motor_aplicable': 'TODOS',
            'eta': 10000,
            'beta': 2.0,
            'activo': True
        }
    )
    config_frenos, _ = ComponenteSaludConfig.objects.update_or_create(
        nombre="Frenos Test",
        defaults={
            'tipo_motor_aplicable': 'TODOS',
            'eta': 30000,
            'beta': 2.0,
            'activo': True
        }
    )
    
    print("✅ Datos de prueba configurados")
    
    # 2. Test Checklist Endpoint (View Logic)
    print("\n🔍 Verificando Endpoint checklist_inicial...")
    factory = APIRequestFactory()
    view = VehiculoViewSet.as_view({'get': 'checklist_inicial'})
    
    # Test Gasolina
    req_gas = factory.get('/api/vehiculos/checklist-inicial/?tipo_motor=Gasolina')
    force_authenticate(req_gas, user=user)
    res_gas = view(req_gas)
    print(f"   - Gasolina: {res_gas.status_code} (Esperado: 200)")
    # Should at least find the ones we created
    if len(res_gas.data) >= 2:
        print(f"   ✅ Se recibieron {len(res_gas.data)} componentes para Gasolina.")
    else:
        print(f"   ❌ Error: Se esperaban al menos 2 componentes, se recibieron {len(res_gas.data)}")

    # 3. Test Case: Create Vehicle with Checklist
    km_vehiculo = 100000
    componentes_al_dia = [config_aceite.id]
    
    # Use unique patent for every run
    patente = f'TEST-{datetime.now().strftime("%H%M%S")}-{os.urandom(2).hex()}'
    
    data = {
        'marca': marca.id,
        'modelo': modelo.id,
        'patente': patente,
        'kilometraje': km_vehiculo,
        'tipo_motor': 'Gasolina',
        'year': 2020,
        'componentes_al_dia': componentes_al_dia,
        'cliente': cliente.id  # Required field
    }
    
    print("\n📦 Creando vehículo con datos:", data)
    
    # Needs to be APIRequest for context if needed, but for serializer data validation it matters less
    request = factory.post('/api/vehiculos/')
    request.user = user
    force_authenticate(request, user=user)
    # Mock storage to avoid actual file operations if any
    
    serializer = VehiculoSerializer(data=data, context={'request': request})
    
    if serializer.is_valid():
        try:
            vehiculo = serializer.save(cliente=cliente)
            print(f"✅ Vehículo creado: {vehiculo}")
            
            # 4. Verify Health Components
            comps = ComponenteSaludVehiculo.objects.filter(vehiculo=vehiculo)
            print(f"📊 Componentes de salud creados: {comps.count()}")
            
            comp_aceite = comps.filter(componente_config=config_aceite).first()
            comp_frenos = comps.filter(componente_config=config_frenos).first()
            
            # Verify Aceite (Should be OK)
            if comp_aceite:
                print(f"\n🛢️ Aceite (ID {config_aceite.id}) - Esperado: Al día")
                print(f"   - Km Último Servicio: {comp_aceite.km_ultimo_servicio} (Esperado: {km_vehiculo})")
                print(f"   - Salud: {comp_aceite.salud_porcentaje}%")
                
                if comp_aceite.km_ultimo_servicio == km_vehiculo:
                    print("   ✅ VERIFICACIÓN EXITOSA: Aceite está al día.")
                else:
                    print("   ❌ FALLO: El aceite debería estar al día.")
            else:
                print("   ❌ FALLO: No se creó el componente de aceite.")
                
            # Verify Frenos (Should be Critical)
            if comp_frenos:
                print(f"\n🛑 Frenos (ID {config_frenos.id}) - Esperado: Pendiente")
                print(f"   - Km Último Servicio: {comp_frenos.km_ultimo_servicio} (Esperado: 0)")
                print(f"   - Salud: {comp_frenos.salud_porcentaje}%")
                
                if comp_frenos.km_ultimo_servicio == 0:
                    print("   ✅ VERIFICACIÓN EXITOSA: Frenos están pendientes.")
                else:
                    print("   ❌ FALLO: Los frenos deberían estar pendientes.")
            else:
                print("   ❌ FALLO: No se creó el componente de frenos.")
                
        except Exception as e:
            print(f"❌ Error al guardar vehículo: {e}")
            import traceback
            traceback.print_exc()

    else:
        print("❌ Error de validación:", serializer.errors)

if __name__ == "__main__":
    try:
        run_verification()
    except Exception as e:
        print(f"❌ Error fatal: {e}")
        import traceback
        traceback.print_exc()
