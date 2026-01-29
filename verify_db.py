import os
import django
import sys

import os
import django
import sys

# Add the project root to sys.path (current directory)
sys.path.append(os.getcwd())

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')
django.setup()

from mecanimovilapp.apps.vehiculos.models import Vehiculo

def verify():
    print("--- Verificando campos del modelo Vehiculo ---")
    field_names = [f.name for f in Vehiculo._meta.get_fields()]
    
    expected_fields = ['vin', 'numero_motor', 'version', 'puertas', 'mes_revision_tecnica', 'transmision', 'color']
    missing = [f for f in expected_fields if f not in field_names]
    
    if missing:
        print(f"❌ FALTAN CAMPOS EN LA BASE DE DATOS: {missing}")
    else:
        print("✅ Todos los campos esperados existen en el modelo.")

    count = Vehiculo.objects.count()
    print(f"\n--- Verificando últimos 5 vehículos (Total: {count}) ---")
    
    # Obtener los últimos 5, ordenados por ID descendente
    last_vehicles = Vehiculo.objects.all().order_by('-id')[:5]
    
    if last_vehicles:
        for v in last_vehicles:
            print(f"\n🚗 ID: {v.id} | Patente: {v.patente} | Creado: {v.fecha_creacion}")
            data = {
                'vin': v.vin,
                'numero_motor': v.numero_motor,
                'version': v.version,
                'puertas': v.puertas,
                'mes_revision_tecnica': v.mes_revision_tecnica,
                'transmision': v.transmision,
                'color': v.color
            }
            for k, val in data.items():
                if val:
                    print(f"  ✅ {k}: {val}")
                else:
                    print(f"  ❌ {k}: None")
    else:
        print("No hay vehículos registrados.")

if __name__ == '__main__':
    verify()
