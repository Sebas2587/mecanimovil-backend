"""
Comando de management para inicializar el sistema completo de créditos.
Ejecutar: python manage.py init_sistema_creditos
"""
from django.core.management.base import BaseCommand
from decimal import Decimal, ROUND_HALF_UP
from mecanimovilapp.apps.suscripciones.models import (
    ConfiguracionCreditos,
    PaqueteCreditos
)


class Command(BaseCommand):
    help = 'Inicializa el sistema completo de créditos: configuración global y paquetes'

    def handle(self, *args, **options):
        self.stdout.write('Inicializando sistema de créditos...')
        
        # 1. Crear configuración global
        self.stdout.write('\n1. Creando configuración global...')
        config, created = ConfiguracionCreditos.objects.get_or_create(
            activo=True,
            defaults={
                'aov_promedio': Decimal('150000'),
                'tasa_comision': Decimal('0.10'),
                'k_promedio': 3,
                'creditos_expiracion_meses': 12,
                'activo': True
            }
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS('✓ Configuración global creada'))
            self.stdout.write(f'  - AOV Promedio: ${config.aov_promedio:,.0f} CLP')
            self.stdout.write(f'  - Tasa de Comisión: {config.tasa_comision*100:.1f}%')
            self.stdout.write(f'  - K Promedio: {config.k_promedio} créditos')
            self.stdout.write(f'  - Precio Crédito Base: ${config.precio_credito_base:,.0f} CLP')
            self.stdout.write(f'  - Expiración: {config.creditos_expiracion_meses} meses')
        else:
            self.stdout.write('Configuración global ya existe')
        
        # 2. Crear paquetes de créditos para pruebas
        self.stdout.write('\n2. Creando paquetes de créditos...')
        
        # Calcular precio base por crédito según la fórmula
        precio_credito_base = config.precio_credito_base
        
        # Función helper para redondear a 2 decimales
        def redondear_precio(precio):
            return precio.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        paquetes = [
            {
                'nombre': 'Paquete Prueba - Pequeño',
                'cantidad_creditos': 5,
                'precio': redondear_precio(precio_credito_base * 5),  # 5 créditos
                'bonificacion_creditos': 0,
                'orden': 1,
                'destacado': False
            },
            {
                'nombre': 'Paquete Prueba - Mediano',
                'cantidad_creditos': 10,
                'precio': redondear_precio(precio_credito_base * 10 * Decimal('0.95')),  # 5% descuento
                'bonificacion_creditos': 1,
                'orden': 2,
                'destacado': True
            },
            {
                'nombre': 'Paquete Prueba - Grande',
                'cantidad_creditos': 20,
                'precio': redondear_precio(precio_credito_base * 20 * Decimal('0.90')),  # 10% descuento
                'bonificacion_creditos': 3,
                'orden': 3,
                'destacado': False
            },
            {
                'nombre': 'Paquete Estándar',
                'cantidad_creditos': 25,
                'precio': redondear_precio(precio_credito_base * 25 * Decimal('0.88')),  # 12% descuento
                'bonificacion_creditos': 5,
                'orden': 4,
                'destacado': False
            },
            {
                'nombre': 'Paquete Premium',
                'cantidad_creditos': 50,
                'precio': redondear_precio(precio_credito_base * 50 * Decimal('0.85')),  # 15% descuento
                'bonificacion_creditos': 10,
                'orden': 5,
                'destacado': False
            },
        ]
        
        paquetes_creados = 0
        for paquete_data in paquetes:
            paquete, created = PaqueteCreditos.objects.get_or_create(
                nombre=paquete_data['nombre'],
                defaults={
                    'cantidad_creditos': paquete_data['cantidad_creditos'],
                    'precio': paquete_data['precio'],
                    'bonificacion_creditos': paquete_data['bonificacion_creditos'],
                    'activo': True,
                    'orden': paquete_data['orden'],
                    'destacado': paquete_data['destacado']
                }
            )
            
            if created:
                paquetes_creados += 1
                total_creditos = paquete.total_creditos
                precio_por_credito = paquete.precio_por_credito
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✓ {paquete.nombre} creado:\n'
                        f'    - Créditos: {paquete.cantidad_creditos} (+ {paquete.bonificacion_creditos} bonificación) = {total_creditos} total\n'
                        f'    - Precio: ${paquete.precio:,.0f} CLP\n'
                        f'    - Precio por crédito: ${precio_por_credito:,.0f} CLP'
                    )
                )
            else:
                self.stdout.write(f'{paquete.nombre} ya existe')
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\n✓ Sistema de créditos inicializado correctamente:\n'
                f'  - Configuración global: {"Creada" if created else "Existente"}\n'
                f'  - Paquetes creados: {paquetes_creados}\n'
                f'  - Total de paquetes: {len(paquetes)}'
            )
        )

