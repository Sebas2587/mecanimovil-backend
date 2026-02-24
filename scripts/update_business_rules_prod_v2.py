import os
import django
from decimal import Decimal

# Este script está diseñado para ejecutarse vía 'python manage.py shell < scripts/update_business_rules_prod_v2.py'

from mecanimovilapp.apps.suscripciones.models import PlanSuscripcion, ConfiguracionCreditosServicio, PaqueteCreditos
from mecanimovilapp.apps.servicios.models import Servicio

def cleanup_and_update_plans():
    print("--- Limpiando y Actualizando Planes de Suscripción ---")
    
    # 1. Desactivar todos los planes actuales para evitar duplicados/confusión
    PlanSuscripcion.objects.all().update(activo=False)
    print("Se han desactivado temporalmente todos los planes existentes.")

    plans_data = [
        {
            'nombre': 'Plan Básico', 
            'precio': 9990, 
            'creditos': 30, 
            'descripcion': 'Ideal para mecánicos independientes que inician.',
            'orden': 1
        },
        {
            'nombre': 'Plan Profesional', 
            'precio': 24990, 
            'creditos': 100, 
            'descripcion': 'El plan más equilibrado para talleres medianos.',
            'orden': 2,
            'destacado': True
        },
        {
            'nombre': 'Plan Premium', 
            'precio': 49900, 
            'creditos': 250, 
            'descripcion': 'Máxima visibilidad y volumen de leads para expertos.',
            'orden': 3
        },
    ]
    
    for data in plans_data:
        plan, created = PlanSuscripcion.objects.update_or_create(
            nombre=data['nombre'],
            defaults={
                'precio': Decimal(data['precio']),
                'creditos_mensuales': data['creditos'],
                'descripcion': data.get('descripcion', ''),
                'orden': data.get('orden', 0),
                'destacado': data.get('destacado', False),
                'activo': True  # Solo activamos los nuevos
            }
        )
        print(f"{'Creado' if created else 'Actualizado y Activado'} Plan: {plan.nombre} - ${plan.precio:,.0f} - {plan.creditos_mensuales} créditos")

def update_service_credits():
    print("\n--- Actualizando Mapeo de Créditos por Servicio ---")
    mapping = {
        'Lavado a domicilio': 2,
        'Cambio de ampolletas': 2,
        'Cambio de batería': 2,
        'Cambio de filtro habitáculo': 2,
        'Cambio de filtro de aire': 2,
        'Revisión técnica': 2,
        'Servicio escáner automotriz': 2,
        'Cambio de pastillas de frenos y rectificado': 5,
        'Cambio de pastillas y discos de freno': 5,
        'Cambio de pastillas de frenos': 5,
        'Cambio de bujías': 5,
        'Cambio aceite motor y filtro': 5,
        'Cambio de aceite motor': 5,
        'Revisión precompra': 5,
        'Diagnóstico electromecánico': 5,
        'Diagnóstico mecánico': 10,
        'Mantenimiento por kilometraje': 15,
    }
    
    # Desactivar configuraciones viejas primero
    ConfiguracionCreditosServicio.objects.all().update(activo=False)

    for service_name, credits in mapping.items():
        servicio = Servicio.objects.filter(nombre__iexact=service_name).first()
        if servicio:
            ConfiguracionCreditosServicio.objects.update_or_create(
                servicio=servicio,
                defaults={
                    'creditos_requeridos': credits,
                    'activo': True
                }
            )
            print(f"Configurado {service_name}: {credits} créditos")
        else:
            print(f"SERVICIO NO ENCONTRADO: {service_name}")

if __name__ == '__main__':
    try:
        cleanup_and_update_plans()
        update_service_credits()
        print("\n¡Actualización completada con éxito! Revisa la app ahora.")
    except Exception as e:
        print(f"\nERROR durante la actualización: {str(e)}")
