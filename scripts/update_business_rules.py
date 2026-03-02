import os
import django
from decimal import Decimal

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')
django.setup()

from mecanimovilapp.apps.suscripciones.models import PlanSuscripcion, ConfiguracionCreditosServicio
from mecanimovilapp.apps.servicios.models import Servicio

def update_plans():
    plans_data = [
        {'nombre': 'Plan Básico', 'precio': 9990, 'creditos': 15},
        {'nombre': 'Plan Profesional', 'precio': 24990, 'creditos': 50},
        {'nombre': 'Plan Premium', 'precio': 49900, 'creditos': 120},
    ]
    
    for data in plans_data:
        plan, created = PlanSuscripcion.objects.update_or_create(
            nombre=data['nombre'],
            defaults={
                'precio': Decimal(data['precio']),
                'creditos_mensuales': data['creditos'],
                'activo': True
            }
        )
        print(f"{'Created' if created else 'Updated'} Plan: {plan.nombre} - ${plan.precio} - {plan.creditos_mensuales} cr")

def update_service_credits():
    # Mapping based on typical ticket value in Chile
    # Low (3 cr), Medium (10 cr), High (25 cr)
    mapping = {
        'Lavado a domicilio': 3,
        'Cambio de ampolletas': 3,
        'Cambio de batería': 3,
        'Cambio de pastillas de frenos y rectificado': 10,
        'Cambio de pastillas y discos de freno': 10,
        'Cambio de pastillas de frenos': 10,
        'Cambio de bujías': 10,
        'Mantenimiento por kilometraje': 25,
        'Cambio aceite motor y filtro': 10,
        'Cambio de filtro habitáculo': 3,
        'Cambio de filtro de aire': 3,
        'Cambio de aceite motor': 10,
        'Revisión técnica': 3,
        'Revisión precompra': 10,
        'Servicio escáner automotriz': 3,
        'Diagnóstico electromecánico': 10,
        'Diagnóstico mecánico': 10,
    }
    
    for service_name, credits in mapping.items():
        servicio = Servicio.objects.filter(nombre__iexact=service_name).first()
        if servicio:
            config, created = ConfiguracionCreditosServicio.objects.update_or_create(
                servicio=servicio,
                defaults={
                    'creditos_requeridos': credits,
                    'activo': True
                }
            )
            print(f"{'Created' if created else 'Updated'} Config for {service_name}: {credits} cr")
        else:
            print(f"Service NOT FOUND: {service_name}")

if __name__ == '__main__':
    print("Updating Subscription Plans...")
    update_plans()
    print("\nUpdating Service Credit Mapping...")
    update_service_credits()
