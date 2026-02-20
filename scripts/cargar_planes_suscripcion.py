"""
Script de carga inicial de datos para la base de datos de producción en Render.
Crea los planes de suscripción mensual por defecto en MecaniMovil.

INSTRUCCIONES DE USO EN RENDER:
1. Ve a tu servicio web en render.com
2. Shell tab → abre la shell del servicio
3. Ejecuta: python scripts/cargar_planes_suscripcion.py

O desde la máquina local con la DATABASE_URL de producción:
   DATABASE_URL=<URL_RENDER> python scripts/cargar_planes_suscripcion.py

ALTERNATIVA (más segura) - usando Django management command:
   python manage.py shell < scripts/cargar_planes_suscripcion.py
"""
import os
import sys
import django

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')

# Agregar el directorio base al path si se ejecuta directamente
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

django.setup()

# ─────────────────────────────────────────────────────────────
# Importar modelo
# ─────────────────────────────────────────────────────────────
from mecanimovilapp.apps.suscripciones.models import PlanSuscripcion

# ─────────────────────────────────────────────────────────────
# Definición de planes
# ─────────────────────────────────────────────────────────────
PLANES = [
    {
        'nombre': 'Plan Básico',
        'descripcion': 'Ideal para mecánicos que están comenzando. Recibe 20 créditos cada mes para responder solicitudes de servicio.',
        'precio': 4990,               # CLP
        'creditos_mensuales': 20,
        'activo': True,
        'destacado': False,
        'orden': 1,
        'mp_preapproval_plan_id': '', # Opcional: ID del plan en MP (dejar vacío para ad-hoc)
    },
    {
        'nombre': 'Plan Profesional',
        'descripcion': 'El más popular entre nuestros proveedores. 50 créditos mensuales para maximizar tus oportunidades de negocio.',
        'precio': 9990,               # CLP
        'creditos_mensuales': 50,
        'activo': True,
        'destacado': True,            # ← Se muestra con badge "Más popular"
        'orden': 2,
        'mp_preapproval_plan_id': '',
    },
    {
        'nombre': 'Plan Premium',
        'descripcion': 'Para talleres con alta demanda. 120 créditos mensuales con el mejor precio por crédito del mercado.',
        'precio': 19990,              # CLP
        'creditos_mensuales': 120,
        'activo': True,
        'destacado': False,
        'orden': 3,
        'mp_preapproval_plan_id': '',
    },
]

# ─────────────────────────────────────────────────────────────
# Ejecución
# ─────────────────────────────────────────────────────────────
def cargar_planes():
    print("\n🚀 Cargando planes de suscripción en la base de datos...\n")
    creados = 0
    actualizados = 0

    for plan_data in PLANES:
        mp_id = plan_data.pop('mp_preapproval_plan_id', '')
        plan, created = PlanSuscripcion.objects.update_or_create(
            nombre=plan_data['nombre'],
            defaults={**plan_data, 'mp_preapproval_plan_id': mp_id or None},
        )

        if created:
            print(f"  ✅ CREADO   → {plan.nombre} | ${plan.precio:,.0f}/mes | {plan.creditos_mensuales} créditos")
            creados += 1
        else:
            print(f"  🔄 ACTUALIZADO → {plan.nombre} | ${plan.precio:,.0f}/mes | {plan.creditos_mensuales} créditos")
            actualizados += 1

    print(f"\n📊 Resultado: {creados} creados, {actualizados} actualizados")
    print(f"📋 Total planes en BD: {PlanSuscripcion.objects.count()}")

    print("\n✅ ¡Planes cargados correctamente!\n")
    print("💡 Puedes editar los precios y créditos desde el panel Admin:")
    print("   https://<tu-dominio-render>.onrender.com/admin/suscripciones/plansuscripcion/\n")


if __name__ == '__main__':
    cargar_planes()
