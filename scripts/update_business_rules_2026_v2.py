"""
Actualización idempotente de planes v2 (2026): precios más altos + cuotas de features.

Ejecutar desde la raíz del backend:
  cd mecanimovil-backend && python scripts/update_business_rules_2026_v2.py

Incluye cuotas mensuales de IA, patente y mensajería según tabla comercial acordada.
Preserva mp_preapproval_plan_id existente; revisar manualmente en MP si cambió el monto.
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

from mecanimovilapp.apps.suscripciones.models import PlanSuscripcion, SuscripcionProveedor  # noqa: E402
from mecanimovilapp.apps.suscripciones.mercado_pago_pricing import monto_bruto_para_neto_pesos_enteros  # noqa: E402

NOMBRES_PLANES_CANONICOS = ('Plan Básico', 'Plan Profesional', 'Plan Premium')

PLANS_DATA = [
    {
        'nombre': 'Plan Básico',
        'precio_neto_objetivo': Decimal('29990'),
        'creditos': 80,
        'descripcion': (
            'Entrada al ecosistema Mecanimovil: marketplace, WhatsApp, cotizaciones IA '
            'y herramientas esenciales para talleres que inician.'
        ),
        'orden': 1,
        'destacado': False,
        'cotizaciones_ia_mensuales': 20,
        'diagnosticos_ia_mensuales': 12,
        'consultas_patente_mensuales': 12,
        'canales_mensajeria_max': 1,
        'conversaciones_salientes_max': 300,
        'overage_cotizaciones_por_credito': 3,
        'overage_diagnosticos_por_credito': 4,
        'overage_patentes_por_credito': 3,
        'acceso_endpoints_patente_pro': False,
    },
    {
        'nombre': 'Plan Profesional',
        'precio_neto_objetivo': Decimal('69990'),
        'creditos': 225,
        'descripcion': (
            'Para talleres en crecimiento: más créditos, IA generosa, dos canales '
            'de mensajería y mayor volumen de conversaciones.'
        ),
        'orden': 2,
        'destacado': True,
        'cotizaciones_ia_mensuales': 80,
        'diagnosticos_ia_mensuales': 50,
        'consultas_patente_mensuales': 50,
        'canales_mensajeria_max': 2,
        'conversaciones_salientes_max': 1000,
        'overage_cotizaciones_por_credito': 4,
        'overage_diagnosticos_por_credito': 5,
        'overage_patentes_por_credito': 4,
        'acceso_endpoints_patente_pro': False,
    },
    {
        'nombre': 'Plan Premium',
        'precio_neto_objetivo': Decimal('139990'),
        'creditos': 450,
        'descripcion': (
            'Máximo rendimiento: todos los canales, endpoints avanzados de patente '
            'y cuotas ampliadas de IA y mensajería.'
        ),
        'orden': 3,
        'destacado': False,
        'cotizaciones_ia_mensuales': 200,
        'diagnosticos_ia_mensuales': 130,
        'consultas_patente_mensuales': 130,
        'canales_mensajeria_max': 3,
        'conversaciones_salientes_max': 3000,
        'overage_cotizaciones_por_credito': 5,
        'overage_diagnosticos_por_credito': 6,
        'overage_patentes_por_credito': 5,
        'acceso_endpoints_patente_pro': True,
    },
]


def update_planes():
    print('\n1. Planes de suscripción v2 (cuotas + precios)...')
    PlanSuscripcion.objects.exclude(nombre__in=NOMBRES_PLANES_CANONICOS).update(activo=False)

    for data in PLANS_DATA:
        precio_bruto = monto_bruto_para_neto_pesos_enteros(data['precio_neto_objetivo'])
        defaults = {
            'precio': precio_bruto,
            'creditos_mensuales': data['creditos'],
            'descripcion': data.get('descripcion', ''),
            'orden': data.get('orden', 0),
            'destacado': data.get('destacado', False),
            'activo': True,
            'cotizaciones_ia_mensuales': data['cotizaciones_ia_mensuales'],
            'diagnosticos_ia_mensuales': data['diagnosticos_ia_mensuales'],
            'consultas_patente_mensuales': data['consultas_patente_mensuales'],
            'canales_mensajeria_max': data['canales_mensajeria_max'],
            'conversaciones_salientes_max': data['conversaciones_salientes_max'],
            'overage_cotizaciones_por_credito': data['overage_cotizaciones_por_credito'],
            'overage_diagnosticos_por_credito': data['overage_diagnosticos_por_credito'],
            'overage_patentes_por_credito': data['overage_patentes_por_credito'],
            'acceso_endpoints_patente_pro': data['acceso_endpoints_patente_pro'],
        }
        plan, created = PlanSuscripcion.objects.update_or_create(
            nombre=data['nombre'],
            defaults=defaults,
        )
        mp_hint = f"mp_plan={plan.mp_preapproval_plan_id!r}" if plan.mp_preapproval_plan_id else 'sin mp_preapproval_plan_id'
        print(
            f"   - {'Creado' if created else 'Actualizado'}: {plan.nombre} "
            f"(bruto ${plan.precio:,.0f} / neto ref. ~${data['precio_neto_objetivo']:,.0f}, "
            f"{plan.creditos_mensuales} cr/mes, "
            f"IA cot={plan.cotizaciones_ia_mensuales}, canales={plan.canales_mensajeria_max}) "
            f"[{mp_hint}]"
        )


def advertir_suscripciones_activas():
    print('\n2. Suscripciones activas (revisar monto en Mercado Pago)...')
    activas = SuscripcionProveedor.objects.filter(estado__in=['activa', 'pausada']).select_related('plan')
    if not activas.exists():
        print('   - No hay suscripciones activas/pausadas.')
        return
    for sub in activas:
        print(
            f"   - proveedor={sub.proveedor_id} plan={sub.plan.nombre} "
            f"precio_bd=${sub.plan.precio:,.0f} mp_preapproval={sub.mp_preapproval_id!r}"
        )
    print(
        '   ⚠ Si el monto en MP difiere del precio en BD, crear nuevos Preapproval Plans '
        'en MP o actualizar el monto vía API antes de activar PLAN_CUOTAS_ENFORCEMENT_ENABLED.'
    )


def run_update():
    print('--- [INICIO] Actualización planes v2 (cuotas features) ---')
    update_planes()
    advertir_suscripciones_activas()
    print('\n--- [FIN] Completado ---\n')


if __name__ == '__main__':
    run_update()
