"""
Actualización idempotente de reglas de negocio 2026 (motor de créditos y planes).

Ejecutar desde la raíz del backend (con venv activo):
  cd mecanimovil-backend && python scripts/update_business_rules_2026_motor.py

Staging / producción:
  - Hacer backup o snapshot de BD antes de correr.
  - Verificar después: GET planes (app prov), estadísticas de créditos (precio unitario),
    y que los servicios mapeados tengan 5 / 7 / 10 créditos según tabla.

Mercado Pago (suscripciones y compra de créditos):
  - PlanSuscripcion: solo se usa update_or_create por `nombre`. Los defaults NO incluyen
    `mp_preapproval_plan_id` ni otros campos MP, para no borrar vínculos existentes.
  - Se desactivan planes que no están en la lista canónica (mismo patrón que v3);
    las filas de PlanSuscripcion se reutilizan por nombre, conservando IDs y MP.
  - Compra de créditos (top-up) usa ConfiguracionCreditos vía creditos_services; aquí
    se deja una sola configuración activa con fórmula que da ~400 CLP/crédito.
"""
import os
import sys
from decimal import Decimal

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')

import django  # noqa: E402

django.setup()

from mecanimovilapp.apps.suscripciones.models import (  # noqa: E402
    PlanSuscripcion,
    ConfiguracionCreditosServicio,
    ConfiguracionCreditos,
)
from mecanimovilapp.apps.servicios.models import Servicio  # noqa: E402

NOMBRES_PLANES_CANONICOS = ('Plan Básico', 'Plan Profesional', 'Plan Premium')

PLANS_DATA = [
    {
        'nombre': 'Plan Básico',
        'precio': 19990,
        'creditos': 80,
        'descripcion': 'Ideal para mecánicos independientes que inician.',
        'orden': 1,
        'destacado': False,
    },
    {
        'nombre': 'Plan Profesional',
        'precio': 44990,
        'creditos': 225,
        'descripcion': 'El plan más equilibrado para talleres medianos.',
        'orden': 2,
        'destacado': True,
    },
    {
        'nombre': 'Plan Premium',
        'precio': 89990,
        'creditos': 450,
        'descripcion': 'Máxima visibilidad y volumen de leads para expertos.',
        'orden': 3,
        'destacado': False,
    },
]

SERVICE_CREDITS_MAPPING = {
    'Lavado a domicilio': 5,
    'Cambio de ampolletas': 5,
    'Cambio de batería': 5,
    'Cambio de filtro habitáculo': 5,
    'Cambio de filtro de aire': 5,
    'Revisión técnica': 5,
    'Servicio escáner automotriz': 5,
    'Cambio de pastillas de frenos y rectificado': 7,
    'Cambio de pastillas y discos de freno': 7,
    'Cambio de pastillas de frenos': 7,
    'Cambio de bujías': 7,
    'Cambio aceite motor y filtro': 7,
    'Cambio de aceite motor': 7,
    'Revisión precompra': 7,
    'Diagnóstico electromecánico': 7,
    'Diagnóstico mecánico': 10,
    'Mantenimiento por kilometraje': 10,
}


def update_planes():
    print('\n1. Planes de suscripción (preservando mp_preapproval_plan_id en filas existentes)...')
    PlanSuscripcion.objects.exclude(nombre__in=NOMBRES_PLANES_CANONICOS).update(activo=False)

    for data in PLANS_DATA:
        plan, created = PlanSuscripcion.objects.update_or_create(
            nombre=data['nombre'],
            defaults={
                'precio': Decimal(str(data['precio'])),
                'creditos_mensuales': data['creditos'],
                'descripcion': data.get('descripcion', ''),
                'orden': data.get('orden', 0),
                'destacado': data.get('destacado', False),
                'activo': True,
            },
        )
        mp_hint = f"mp_plan={plan.mp_preapproval_plan_id!r}" if plan.mp_preapproval_plan_id else 'sin mp_preapproval_plan_id'
        print(f"   - {'Creado' if created else 'Actualizado'}: {plan.nombre} (${plan.precio:,.0f}, {plan.creditos_mensuales} cr/mes) [{mp_hint}]")


def update_configuracion_creditos_globales():
    print('\n2. ConfiguracionCreditos global (top-up / precio unitario)...')
    cfg = ConfiguracionCreditos.objects.order_by('-fecha_creacion').first()
    if cfg:
        ConfiguracionCreditos.objects.exclude(pk=cfg.pk).update(activo=False)
        cfg.aov_promedio = Decimal('80000')
        cfg.tasa_comision = Decimal('0.1000')
        cfg.k_promedio = 20
        cfg.activo = True
        cfg.save()
        print(f'   - Actualizado registro id={cfg.pk}: precio_credito_base={cfg.precio_credito_base}')
    else:
        n = ConfiguracionCreditos.objects.create(
            aov_promedio=Decimal('80000'),
            tasa_comision=Decimal('0.1000'),
            k_promedio=20,
            activo=True,
        )
        print(f'   - Creado registro id={n.pk}: precio_credito_base={n.precio_credito_base}')


def update_creditos_por_servicio():
    print('\n3. ConfiguracionCreditosServicio (banda 5 / 7 / 10)...')
    ConfiguracionCreditosServicio.objects.all().update(activo=False)

    for service_name, credits in SERVICE_CREDITS_MAPPING.items():
        servicio = Servicio.objects.filter(nombre__iexact=service_name).first()
        if servicio:
            row, created = ConfiguracionCreditosServicio.objects.update_or_create(
                servicio=servicio,
                defaults={
                    'creditos_requeridos': credits,
                    'activo': True,
                },
            )
            label = 'Creado' if created else 'Actualizado'
            print(f'   - {label}: {service_name[:40]:40} -> {credits} cr')
        else:
            print(f'   - NO ENCONTRADO (servicios.Servicio): {service_name}')


def run_update():
    print('--- [INICIO] Actualización reglas de negocio 2026 ---')
    update_planes()
    update_configuracion_creditos_globales()
    update_creditos_por_servicio()
    print('\n--- [FIN] Completado ---\n')


if __name__ == '__main__':
    run_update()
