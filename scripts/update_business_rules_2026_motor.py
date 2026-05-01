"""
Actualización idempotente de reglas de negocio 2026 (motor de créditos y planes).

Incluye:
  - Precios de planes en BRUTO Mercado Pago para lograr una liquidación neta mensual objetivo.
  - Precio por crédito (Tienda) en BRUTO para neto objetivo por crédito (NETO_OBJETIVO_POR_CREDITO_TOPUP).
  - Créditos por servicio según arquetipos de ticket (`pricing_arquetipos`), con tope por postulación.

Ejecutar desde la raíz del backend (con venv activo):
  cd mecanimovil-backend && python scripts/update_business_rules_2026_motor.py

Simulación sin BD:
  python scripts/simular_pricing_arquetipos.py --precio-bruto 520

Mercado Pago: ver `mercado_pago_pricing` (3,19% + IVA sobre esa comisión).
"""
import os
import sys
from decimal import Decimal, ROUND_HALF_UP

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
from mecanimovilapp.apps.suscripciones.mercado_pago_pricing import (  # noqa: E402
    monto_bruto_para_neto_pesos_enteros,
    monto_bruto_para_neto,
)
from mecanimovilapp.apps.suscripciones.pricing_arquetipos import (  # noqa: E402
    arquetipos_por_id,
    creditos_requeridos_por_servicio_desde_arquetipos,
    creditos_sugeridos_para_ticket,
    filas_simulacion,
    ARQUETIPOS_DEFAULT,
)
from mecanimovilapp.apps.servicios.models import Servicio  # noqa: E402

NOMBRES_PLANES_CANONICOS = ('Plan Básico', 'Plan Profesional', 'Plan Premium')

# Objetivo de liquidación neta mensual (CLP); en BD se guarda precio BRUTO vía MP.
PLANS_DATA = [
    {
        'nombre': 'Plan Básico',
        'precio_neto_objetivo': Decimal('22990'),
        'creditos': 80,
        'descripcion': 'Ideal para mecánicos independientes que inician.',
        'orden': 1,
        'destacado': False,
    },
    {
        'nombre': 'Plan Profesional',
        'precio_neto_objetivo': Decimal('51990'),
        'creditos': 225,
        'descripcion': 'El plan más equilibrado para talleres medianos.',
        'orden': 2,
        'destacado': True,
    },
    {
        'nombre': 'Plan Premium',
        'precio_neto_objetivo': Decimal('102990'),
        'creditos': 450,
        'descripcion': 'Máxima visibilidad y volumen de leads para expertos.',
        'orden': 3,
        'destacado': False,
    },
]

# Neto objetivo por crédito (Tienda / fórmula); el bruto en MP se calcula con `monto_bruto_para_neto`.
NETO_OBJETIVO_POR_CREDITO_TOPUP = Decimal('500')


def _precio_bruto_credito_actual() -> Decimal:
    return monto_bruto_para_neto(NETO_OBJETIVO_POR_CREDITO_TOPUP)


def update_planes():
    print('\n1. Planes de suscripción (preservando mp_preapproval_plan_id en filas existentes)...')
    PlanSuscripcion.objects.exclude(nombre__in=NOMBRES_PLANES_CANONICOS).update(activo=False)

    for data in PLANS_DATA:
        precio_bruto = monto_bruto_para_neto_pesos_enteros(data['precio_neto_objetivo'])
        plan, created = PlanSuscripcion.objects.update_or_create(
            nombre=data['nombre'],
            defaults={
                'precio': precio_bruto,
                'creditos_mensuales': data['creditos'],
                'descripcion': data.get('descripcion', ''),
                'orden': data.get('orden', 0),
                'destacado': data.get('destacado', False),
                'activo': True,
            },
        )
        mp_hint = f"mp_plan={plan.mp_preapproval_plan_id!r}" if plan.mp_preapproval_plan_id else 'sin mp_preapproval_plan_id'
        print(
            f"   - {'Creado' if created else 'Actualizado'}: {plan.nombre} "
            f"(bruto ${plan.precio:,.0f} / neto ref. ~${data['precio_neto_objetivo']:,.0f}, "
            f"{plan.creditos_mensuales} cr/mes) [{mp_hint}]"
        )


def update_configuracion_creditos_globales():
    print('\n2. ConfiguracionCreditos global (top-up: bruto MP ≈ neto tras comisión + IVA sobre comisión)...')
    precio_bruto_credito = _precio_bruto_credito_actual()
    aov_para_bruto = (precio_bruto_credito * Decimal('20') / Decimal('0.1')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    cfg = ConfiguracionCreditos.objects.order_by('-fecha_creacion').first()
    if cfg:
        ConfiguracionCreditos.objects.exclude(pk=cfg.pk).update(activo=False)
        cfg.aov_promedio = aov_para_bruto
        cfg.tasa_comision = Decimal('0.1000')
        cfg.k_promedio = 20
        cfg.activo = True
        cfg.save()
        print(
            f'   - Actualizado id={cfg.pk}: precio_credito_base (bruto)={cfg.precio_credito_base} '
            f'(neto ref. crédito ${NETO_OBJETIVO_POR_CREDITO_TOPUP:,.0f}, AOV={cfg.aov_promedio})'
        )
    else:
        n = ConfiguracionCreditos.objects.create(
            aov_promedio=aov_para_bruto,
            tasa_comision=Decimal('0.1000'),
            k_promedio=20,
            activo=True,
        )
        print(
            f'   - Creado id={n.pk}: precio_credito_base (bruto)={n.precio_credito_base} '
            f'(neto ref. crédito ${NETO_OBJETIVO_POR_CREDITO_TOPUP:,.0f})'
        )


def update_creditos_por_servicio():
    precio_bruto_credito = _precio_bruto_credito_actual()
    max_cr = 25
    service_credit_mapping = creditos_requeridos_por_servicio_desde_arquetipos(
        precio_bruto_credito,
        max_creditos=max_cr,
    )

    print('\n3. ConfiguracionCreditosServicio (arquetipos de ticket; tope 25 cr/postulación)...')
    print(f'   (precio bruto/crédito de referencia: ${precio_bruto_credito:,.2f})\n')

    ConfiguracionCreditosServicio.objects.all().update(activo=False)

    processed_ids: set[int] = set()

    for service_name, credits in service_credit_mapping.items():
        servicio = Servicio.objects.filter(nombre__iexact=service_name).first()
        if servicio:
            _row, created = ConfiguracionCreditosServicio.objects.update_or_create(
                servicio=servicio,
                defaults={
                    'creditos_requeridos': credits,
                    'activo': True,
                },
            )
            processed_ids.add(servicio.pk)
            label = 'Creado' if created else 'Actualizado'
            print(f'   - {label}: {service_name[:40]:40} -> {credits} cr')
        else:
            print(f'   - NO ENCONTRADO (servicios.Servicio): {service_name}')

    # Servicios en catálogo sin entrada en SERVICIO_A_ARQUETIPO (p. ej. nuevos en BD).
    arq_medio = arquetipos_por_id()['medio']
    cred_fallback = creditos_sugeridos_para_ticket(
        arq_medio.ticket_referencia_clp,
        arq_medio.fraccion_captura_objetivo,
        precio_bruto_credito,
        min_creditos=1,
        max_creditos=max_cr,
    )
    extra = Servicio.objects.exclude(pk__in=processed_ids).order_by('nombre')
    if extra.exists():
        print(f'\n   [Fallback arquetipo "medio" → {cred_fallback} cr] servicios sin mapeo explícito:')
    for servicio in extra:
        _row, created = ConfiguracionCreditosServicio.objects.update_or_create(
            servicio=servicio,
            defaults={
                'creditos_requeridos': cred_fallback,
                'activo': True,
            },
        )
        label = 'Creado' if created else 'Actualizado'
        print(f'   - {label} (fallback): {servicio.nombre[:44]:44} -> {cred_fallback} cr')


def run_update():
    print('--- [INICIO] Actualización reglas de negocio 2026 ---')
    pb = _precio_bruto_credito_actual()
    print('\n0. Vista rápida arquetipos (postulación, bruto sobre ticket):')
    for row in filas_simulacion(pb, ARQUETIPOS_DEFAULT):
        print(
            f"   - {row['id']}: ticket ${int(row['ticket_clp']):,} → "
            f"{row['creditos_sugeridos']} cr/post (~{float(row['fraccion_ticket_bruta_efectiva']) * 100:.1f}% ticket bruto)"
        )
    update_planes()
    update_configuracion_creditos_globales()
    update_creditos_por_servicio()
    print('\n--- [FIN] Completado ---\n')


if __name__ == '__main__':
    run_update()
