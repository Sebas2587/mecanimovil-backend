import os
import django
from django.conf import settings

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')
django.setup()

from mecanimovilapp.apps.usuarios.models import Usuario, Cliente, Proveedor
from mecanimovilapp.apps.ordenes.models import SolicitudServicio, SolicitudServicioPublica, OfertaProveedor

try:
    user = Usuario.objects.get(email='marthatest@gmail.com')
    cliente = Cliente.objects.get(usuario=user)
    print(f"Cliente encontrado: {cliente}")

    # Find active public requests
    solicitudes = SolicitudServicioPublica.objects.filter(cliente=cliente).exclude(estado='cancelada')
    
    if not solicitudes.exists():
        print("No active public requests found for this user.")
        # Try to find standard requests that might be convertible or check if I need to look elsewhere
        solicitudes_std = SolicitudServicio.objects.filter(cliente=cliente).exclude(estado='cancelada')
        print(f"Standard requests found: {solicitudes_std.count()}")
    else:
        print(f"Found {solicitudes.count()} public requests.")
        for s in solicitudes:
            print(f"ID: {s.id}, Estado: {s.estado}, Servicios: {[serv.nombre for serv in s.servicios_solicitados.all()]}")

    # List some providers
    proveedores = Proveedor.objects.all()[:5]
    print(f"\nPotential Providers ({proveedores.count()}):")
    for p in proveedores:
        print(f"ID: {p.id}, Nombre: {p.nombre_fantasia or p.usuario.first_name}, Tipo: {p.tipo_proveedor}")

except Usuario.DoesNotExist:
    print("User marthatest@gmail.com not found.")
except Exception as e:
    print(f"Error: {e}")
