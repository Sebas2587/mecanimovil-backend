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
from mecanimovilapp.apps.suscripciones.models import CompraCreditos, CreditoProveedor
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
                
                # Calcular el saldo esperado si esta compra hubiera sido procesada correctamente
                # Necesitamos verificar si los créditos de esta compra ya están incluidos
                # Para esto, verificamos si hay compras completadas anteriores a esta
                compras_anteriores = CompraCreditos.objects.filter(
                    proveedor=compra.proveedor,
                    estado='completada',
                    fecha_compra__lt=compra.fecha_compra
                ).aggregate(
                    total_creditos=models.Sum('cantidad_creditos')
                )['total_creditos'] or 0
                
                # Calcular saldo esperado: créditos de compras anteriores + créditos de esta compra
                # Menos los consumos (que no podemos calcular fácilmente aquí)
                # En su lugar, verificamos si el saldo actual es menor que el esperado mínimo
                saldo_minimo_esperado = compras_anteriores + compra.cantidad_creditos
                
                # Si el saldo actual es menor que el mínimo esperado, probablemente faltan créditos
                if saldo_actual < saldo_minimo_esperado:
                    # Verificar si esta compra específica ya fue procesada
                    # Comparando con el saldo antes de esta compra
                    saldo_antes_compra = saldo_actual - compra.cantidad_creditos
                    
                    # Si el saldo antes de esta compra es igual a las compras anteriores,
                    # entonces esta compra NO fue procesada
                    if abs(saldo_antes_compra - compras_anteriores) < 1:  # Tolerancia para errores de redondeo
                        if not dry_run:
                            # Acreditar los créditos de esta compra
                            with transaction.atomic():
                                credito_proveedor.saldo_creditos += compra.cantidad_creditos
                                credito_proveedor.fecha_ultima_compra = compra.fecha_compra
                                credito_proveedor.save(update_fields=['saldo_creditos', 'fecha_ultima_compra', 'fecha_actualizacion'])
                            
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f'✅ Compra {compra.id}: Acreditados {compra.cantidad_creditos} créditos '
                                    f'para proveedor {compra.proveedor.username} '
                                    f'(Saldo: {saldo_antes_compra} → {credito_proveedor.saldo_creditos})'
                                )
                            )
                            compras_corregidas += 1
                        else:
                            self.stdout.write(
                                f'🔧 Compra {compra.id}: Se acreditarían {compra.cantidad_creditos} créditos '
                                f'para proveedor {compra.proveedor.username} '
                                f'(Saldo actual: {saldo_actual}, Esperado mínimo: {saldo_minimo_esperado})'
                            )
                            compras_corregidas += 1
                    else:
                        # Esta compra ya fue procesada, pero hay otro problema
                        compras_ya_correctas += 1
                else:
                    # El saldo parece correcto
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
