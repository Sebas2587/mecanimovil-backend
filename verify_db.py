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

    print("\n--- Verificando datos del último vehículo ---")
    last_v = Vehiculo.objects.last()
    if last_v:
        print(f"Patente: {last_v.patente}")
        print(f"ID: {last_v.id}")
        data = {
            'vin': last_v.vin,
            'numero_motor': last_v.numero_motor,
            'version': last_v.version,
            'puertas': last_v.puertas,
            'mes_revision_tecnica': last_v.mes_revision_tecnica,
            'transmision': last_v.transmision,
            'color': last_v.color
        }
        for k, v in data.items():
            print(f"  - {k}: {v}")
    else:
        print("No hay vehículos registrados.")

if __name__ == '__main__':
    verify()
