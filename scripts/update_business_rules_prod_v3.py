from decimal import Decimal
from mecanimovilapp.apps.suscripciones.models import PlanSuscripcion, ConfiguracionCreditosServicio
from mecanimovilapp.apps.servicios.models import Servicio

def run_update():
    print("--- [INICIO] Actualización de Reglas de Negocio ---")
    
    # 1. ACTUALIZAR PLANES
    print("\n1. Gestionando Planes de Suscripción...")
    PlanSuscripcion.objects.all().update(activo=False)
    print("   - Todos los planes antiguos han sido desactivados.")

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
                'activo': True
            }
        )
        print(f"   - {'✅ Creado' if created else '🔄 Actualizado'}: {plan.nombre} (${plan.precio:,.0f})")

    # 2. ACTUALIZAR CRÉDITOS POR SERVICIO
    print("\n2. Actualizando Mapeo de Créditos por Servicio...")
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
    
    # Desactivar configuraciones no mapeadas
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
            print(f"   - Serv: {service_name:30} -> {credits} cr")
        else:
            print(f"   - ⚠️  NO ENCONTRADO: {service_name}")

    print("\n--- [FIN] Actualización completada con éxito ---")

# Ejecutar inmediatamente
run_update()
