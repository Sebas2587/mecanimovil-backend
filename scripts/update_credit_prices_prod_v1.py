import os
import django
from decimal import Decimal

# Este script está diseñado para ejecutarse vía 'python manage.py shell < scripts/update_credit_prices_prod_v1.py'

from mecanimovilapp.apps.suscripciones.models import PaqueteCreditos, ConfiguracionCreditos

def run_update():
    print("--- [INICIO] Actualización de Precios de Créditos Individuales ---")
    
    # 1. ACTUALIZAR CONFIGURACIÓN GLOBAL
    print("\n1. Actualizando Configuración Global de Créditos...")
    config = ConfiguracionCreditos.objects.filter(activo=True).first()
    if config:
        config.tasa_comision = Decimal('0.01')  # 1%
        config.k_promedio = 5
        config.save()
        print(f"   - ✅ Configuración actualizada: Tasa={config.tasa_comision*100}%, K={config.k_promedio}, Precio Base=${config.precio_credito_base:,.0f}")
    else:
        print("   - ⚠️ No se encontró configuración activa para actualizar.")

    # 2. GESTIONAR PAQUETES DE CRÉDITOS
    print("\n2. Gestionando Paquetes de Créditos Individuales (Top-ups)...")
    
    # Desactivar paquetes actuales
    PaqueteCreditos.objects.all().update(activo=False)
    print("   - Todos los paquetes antiguos han sido desactivados.")

    paquetes_data = [
        {
            'nombre': 'Pack Mini',
            'cantidad_creditos': 5,
            'precio': 2490,
            'bonificacion_creditos': 0,
            'orden': 1,
            'destacado': False
        },
        {
            'nombre': 'Pack Básico',
            'cantidad_creditos': 20,
            'precio': 7990,
            'bonificacion_creditos': 0,
            'orden': 2,
            'destacado': False
        },
        {
            'nombre': 'Pack Pro',
            'cantidad_creditos': 50,
            'precio': 16990,
            'bonificacion_creditos': 5,
            'orden': 3,
            'destacado': True
        },
        {
            'nombre': 'Pack Premium',
            'cantidad_creditos': 100,
            'precio': 29990,
            'bonificacion_creditos': 15,
            'orden': 4,
            'destacado': False
        },
        {
            'nombre': 'Pack Ultra',
            'cantidad_creditos': 250,
            'precio': 59900,
            'bonificacion_creditos': 50,
            'orden': 5,
            'destacado': False
        },
    ]
    
    for data in paquetes_data:
        paquete, created = PaqueteCreditos.objects.update_or_create(
            nombre=data['nombre'],
            defaults={
                'cantidad_creditos': data['cantidad_creditos'],
                'precio': Decimal(data['precio']),
                'bonificacion_creditos': data['bonificacion_creditos'],
                'activo': True,
                'orden': data['orden'],
                'destacado': data['destacado']
            }
        )
        total = paquete.cantidad_creditos + paquete.bonificacion_creditos
        precio_por_cr = paquete.precio / total if total > 0 else 0
        print(f"   - {'✅ Creado' if created else '🔄 Actualizado'}: {paquete.nombre:15} | {total:3} CR | ${paquete.precio:6,.0f} | (${precio_por_cr:,.1f}/cr)")

    print("\n--- [FIN] Actualización completada con éxito ---")

if __name__ == '__main__':
    run_update()
