"""
Comando para corregir compras de créditos que están marcadas como 'completada'
pero que no tienen los créditos acreditados en el saldo del proveedor.

Uso:
    python manage.py corregir_creditos_compras_completadas
    python manage.py corregir_creditos_compras_completadas --dry-run  # Solo mostrar qué se haría
    python manage.py corregir_creditos_compras_completadas --proveedor-id 123  # Solo un proveedor
"""
from django.core.management.base import BaseCommand
from django.db import transaction, models
from mecanimovilapp.apps.suscripciones.models import CompraCreditos, CreditoProveedor, ConsumoCredito
from mecanimovilapp.apps.suscripciones.creditos_services import obtener_credito_proveedor
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Corrige compras de créditos completadas que no tienen créditos acreditados'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Solo mostrar qué se haría sin hacer cambios',
        )
        parser.add_argument(
            '--proveedor-id',
            type=int,
            help='Solo procesar compras de un proveedor específico',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        proveedor_id = options.get('proveedor_id')

        if dry_run:
            self.stdout.write(self.style.WARNING('🔍 MODO DRY-RUN: No se harán cambios'))

        # Obtener todas las compras completadas
        compras_query = CompraCreditos.objects.filter(estado='completada')
        
        if proveedor_id:
            compras_query = compras_query.filter(proveedor_id=proveedor_id)
            self.stdout.write(f'📋 Procesando solo compras del proveedor {proveedor_id}')
        
        compras = compras_query.select_related('proveedor').order_by('fecha_compra')
        total_compras = compras.count()
        
        self.stdout.write(f'📊 Encontradas {total_compras} compras completadas')
        
        compras_corregidas = 0
        compras_ya_correctas = 0
        errores = 0
        
        for compra in compras:
            try:
                # Obtener el saldo actual del proveedor
                credito_proveedor = obtener_credito_proveedor(compra.proveedor)
                saldo_actual = credito_proveedor.saldo_creditos
                
                # Calcular total de créditos comprados (todas las compras completadas)
                total_creditos_comprados = CompraCreditos.objects.filter(
                    proveedor=compra.proveedor,
                    estado='completada'
                ).aggregate(
                    total=models.Sum('cantidad_creditos')
                )['total'] or 0
                
                # Calcular total de créditos consumidos
                total_creditos_consumidos = ConsumoCredito.objects.filter(
                    proveedor=compra.proveedor
                ).aggregate(
                    total=models.Sum('creditos_consumidos')
                )['total'] or 0
                
                # Saldo esperado = créditos comprados - créditos consumidos
                saldo_esperado = total_creditos_comprados - total_creditos_consumidos
                
                # Si el saldo actual es menor que el esperado, hay créditos faltantes
                diferencia = saldo_esperado - saldo_actual
                
                if diferencia > 0:
                    # Hay créditos faltantes. Verificar si esta compra específica no fue procesada
                    # Calculamos el saldo esperado sin esta compra
                    total_sin_esta_compra = total_creditos_comprados - compra.cantidad_creditos
                    saldo_esperado_sin_compra = total_sin_esta_compra - total_creditos_consumidos
                    
                    # Si el saldo actual coincide con el esperado sin esta compra,
                    # entonces esta compra NO fue procesada
                    if abs(saldo_actual - saldo_esperado_sin_compra) < 1:  # Tolerancia para errores de redondeo
                        if not dry_run:
                            # Acreditar los créditos de esta compra
                            with transaction.atomic():
                                credito_proveedor.saldo_creditos += compra.cantidad_creditos
                                if not credito_proveedor.fecha_ultima_compra or compra.fecha_compra > credito_proveedor.fecha_ultima_compra:
                                    credito_proveedor.fecha_ultima_compra = compra.fecha_compra
                                credito_proveedor.save(update_fields=['saldo_creditos', 'fecha_ultima_compra', 'fecha_actualizacion'])
                            
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f'✅ Compra {compra.id}: Acreditados {compra.cantidad_creditos} créditos '
                                    f'para proveedor {compra.proveedor.username} '
                                    f'(Saldo: {saldo_actual} → {credito_proveedor.saldo_creditos})'
                                )
                            )
                            compras_corregidas += 1
                        else:
                            self.stdout.write(
                                f'🔧 Compra {compra.id}: Se acreditarían {compra.cantidad_creditos} créditos '
                                f'para proveedor {compra.proveedor.username} '
                                f'(Saldo actual: {saldo_actual}, Esperado: {saldo_esperado}, Diferencia: {diferencia})'
                            )
                            compras_corregidas += 1
                    else:
                        # Hay diferencia pero no es de esta compra específica
                        compras_ya_correctas += 1
                else:
                    # El saldo está correcto o hay más créditos de los esperados (puede ser por migraciones)
                    compras_ya_correctas += 1
                    
            except Exception as e:
                errores += 1
                self.stdout.write(
                    self.style.ERROR(
                        f'❌ Error procesando compra {compra.id}: {str(e)}'
                    )
                )
                logger.error(f'Error procesando compra {compra.id}: {e}', exc_info=True)
        
        # Resumen
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS(f'✅ Compras corregidas: {compras_corregidas}'))
        self.stdout.write(self.style.SUCCESS(f'✓ Compras ya correctas: {compras_ya_correctas}'))
        if errores > 0:
            self.stdout.write(self.style.ERROR(f'❌ Errores: {errores}'))
        self.stdout.write('='*60)
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\n🔍 DRY-RUN completado. Ejecuta sin --dry-run para aplicar cambios.'))
