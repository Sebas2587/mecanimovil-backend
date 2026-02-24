import os
import django
from decimal import Decimal

# Este script está diseñado para ejecutarse vía 'python manage.py shell < scripts/update_business_rules_prod.py'
# o directamente si se encuentra en el PYTHONPATH correcto.

from mecanimovilapp.apps.suscripciones.models import PlanSuscripcion, ConfiguracionCreditosServicio
from mecanimovilapp.apps.servicios.models import Servicio

def update_plans():
    print("--- Actualizando Planes de Suscripción ---")
    plans_data = [
        {'nombre': 'Plan Básico', 'precio': 9990, 'creditos': 30},
        {'nombre': 'Plan Profesional', 'precio': 24990, 'creditos': 100},
        {'nombre': 'Plan Premium', 'precio': 49900, 'creditos': 250},
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
        print(f"{'Creado' if created else 'Actualizado'} Plan: {plan.nombre} - ${plan.precio:,.0f} - {plan.creditos_mensuales} créditos")

def update_service_credits():
    print("\n--- Actualizando Mapeo de Créditos por Servicio ---")
    # Mapeo balanceado para permitir más intentos (bullets) por plan
    mapping = {
        # Categoría 1 (Bajo Ticket): 2 Créditos
        'Lavado a domicilio': 2,
        'Cambio de ampolletas': 2,
        'Cambio de batería': 2,
        'Cambio de filtro habitáculo': 2,
        'Cambio de filtro de aire': 2,
        'Revisión técnica': 2,
        'Servicio escáner automotriz': 2,
        
        # Categoría 2 (Ticket Medio): 5 Créditos
        'Cambio de pastillas de frenos y rectificado': 5,
        'Cambio de pastillas y discos de freno': 5,
        'Cambio de pastillas de frenos': 5,
        'Cambio de bujías': 5,
        'Cambio aceite motor y filtro': 5,
        'Cambio de aceite motor': 5,
        'Revisión precompra': 5,
        'Diagnóstico electromecánico': 5,
        'Diagnóstico mecánico': 10,  # Se mantiene un poco más alto por valor técnico
        
        # Categoría 3 (Alto Ticket): 15 Créditos
        'Mantenimiento por kilometraje': 15,
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
            print(f"{'Creado' if created else 'Actualizado'} Config para {service_name}: {credits} créditos")
        else:
            print(f"SERVICIO NO ENCONTRADO: {service_name}")

if __name__ == '__main__':
    try:
        update_plans()
        update_service_credits()
        print("\n¡Actualización completada con éxito!")
    except Exception as e:
        print(f"\nERROR durante la actualización: {str(e)}")
