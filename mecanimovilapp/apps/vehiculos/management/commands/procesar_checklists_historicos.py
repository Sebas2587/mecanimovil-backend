"""
Comando de management para procesar todos los checklists históricos
y actualizar métricas de salud de todos los vehículos
"""
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from mecanimovilapp.apps.vehiculos.models import Vehiculo
from mecanimovilapp.apps.vehiculos.tasks import (
    procesar_checklists_historicos_vehiculo,
    _procesar_checklists_historicos_vehiculo_interno
)
from mecanimovilapp.apps.checklists.models import ChecklistInstance
from mecanimovilapp.apps.ordenes.models import SolicitudServicio
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Procesa todos los checklists históricos completados y actualiza métricas de salud de vehículos. '
        'Útil cuando hay checklists ya finalizados cuyas métricas no se actualizaron (ej. tras un fix en el signal). '
        'Ejemplo: python manage.py procesar_checklists_historicos'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--vehicle-id',
            type=int,
            help='Procesar solo un vehículo específico por ID'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=10,
            help='Número de vehículos a procesar en cada lote (default: 10)'
        )
        parser.add_argument(
            '--async',
            action='store_true',
            help='Ejecutar procesamiento de forma asíncrona usando Celery'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Forzar procesamiento incluso si ya se procesaron anteriormente'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Mostrar qué se procesaría sin hacer cambios'
        )

    def handle(self, *args, **options):
        vehicle_id = options.get('vehicle_id')
        batch_size = options.get('batch_size', 10)
        use_async = options.get('async', False)
        force = options.get('force', False)
        dry_run = options.get('dry_run', False)

        if dry_run:
            self.stdout.write(
                self.style.WARNING('🔍 MODO DRY RUN - No se realizarán cambios')
            )

        # Determinar vehículos a procesar
        if vehicle_id:
            try:
                vehiculos = [Vehiculo.objects.get(id=vehicle_id)]
                self.stdout.write(
                    self.style.SUCCESS(f'📋 Procesando vehículo específico: ID {vehicle_id}')
                )
            except Vehiculo.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'❌ Vehículo {vehicle_id} no encontrado')
                )
                return
        else:
            # Obtener todos los vehículos que tienen checklists completados
            checklists_completados = ChecklistInstance.objects.filter(
                estado='COMPLETADO',
                orden__isnull=False
            ).values_list('orden__vehiculo_id', flat=True).distinct()

            vehiculos = Vehiculo.objects.filter(
                id__in=checklists_completados
            ).distinct()

            total_vehiculos = vehiculos.count()
            self.stdout.write(
                self.style.SUCCESS(
                    f'📋 Encontrados {total_vehiculos} vehículos con checklists completados'
                )
            )

            if total_vehiculos == 0:
                self.stdout.write(
                    self.style.WARNING('⚠️  No hay vehículos con checklists completados para procesar')
                )
                return

        # Estadísticas
        total_procesados = 0
        total_errores = 0
        total_checklists_procesados = 0
        total_componentes_actualizados = 0

        # Procesar en lotes
        for i in range(0, len(vehiculos), batch_size):
            batch = vehiculos[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(vehiculos) + batch_size - 1) // batch_size

            self.stdout.write('')
            self.stdout.write(
                self.style.SUCCESS(
                    f'📦 Procesando lote {batch_num}/{total_batches} ({len(batch)} vehículos)...'
                )
            )

            for vehiculo in batch:
                try:
                    # Contar checklists del vehículo
                    checklists_count = ChecklistInstance.objects.filter(
                        orden__vehiculo=vehiculo,
                        estado='COMPLETADO'
                    ).count()

                    if checklists_count == 0:
                        if self.verbosity >= 2:
                            self.stdout.write(
                                f'  ⏭️  Vehículo {vehiculo.id} ({vehiculo.patente}): Sin checklists completados'
                            )
                        continue

                    if dry_run:
                        self.stdout.write(
                            f'  🔍 [DRY RUN] Vehículo {vehiculo.id} ({vehiculo.patente}): '
                            f'{checklists_count} checklists a procesar'
                        )
                        continue

                    # Procesar vehículo
                    if use_async:
                        # Usar Celery si está disponible
                        try:
                            # .delay() retorna un ID de tarea, no el resultado
                            task_id = procesar_checklists_historicos_vehiculo.delay(vehiculo.id)
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f'  ✅ Vehículo {vehiculo.id} ({vehiculo.patente}): '
                                    f'Procesamiento iniciado en background (Task ID: {task_id}, {checklists_count} checklists)'
                                )
                            )
                            total_procesados += 1
                        except Exception as e:
                            # Fallback a ejecución sincrónica si Celery falla
                            logger.warning(f"Celery no disponible, ejecutando sincrónicamente: {e}")
                            resultado = _procesar_checklists_historicos_vehiculo_interno(vehiculo.id)
                            if resultado and isinstance(resultado, dict):
                                total_checklists_procesados += resultado.get('checklists_procesados', 0)
                                total_componentes_actualizados += resultado.get('componentes_actualizados', 0)
                                self.stdout.write(
                                    self.style.SUCCESS(
                                        f'  ✅ Vehículo {vehiculo.id} ({vehiculo.patente}): '
                                        f'{resultado.get("checklists_procesados", 0)} checklists procesados, '
                                        f'{resultado.get("componentes_actualizados", 0)} componentes actualizados'
                                    )
                                )
                                total_procesados += 1
                            else:
                                self.stdout.write(
                                    self.style.WARNING(
                                        f'  ⚠️  Vehículo {vehiculo.id} ({vehiculo.patente}): '
                                        f'No se pudo procesar'
                                    )
                                )
                                total_errores += 1
                    else:
                        # Ejecutar sincrónicamente usando la función interna
                        resultado = _procesar_checklists_historicos_vehiculo_interno(vehiculo.id)
                        if resultado and isinstance(resultado, dict):
                            total_checklists_procesados += resultado.get('checklists_procesados', 0)
                            total_componentes_actualizados += resultado.get('componentes_actualizados', 0)
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f'  ✅ Vehículo {vehiculo.id} ({vehiculo.patente}): '
                                    f'{resultado.get("checklists_procesados", 0)} checklists procesados, '
                                    f'{resultado.get("componentes_actualizados", 0)} componentes actualizados'
                                )
                            )
                            total_procesados += 1
                        else:
                            self.stdout.write(
                                self.style.WARNING(
                                    f'  ⚠️  Vehículo {vehiculo.id} ({vehiculo.patente}): '
                                    f'No se pudo procesar (resultado: {resultado})'
                                )
                            )
                            total_errores += 1

                except Exception as e:
                    total_errores += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f'  ❌ Error procesando vehículo {vehiculo.id} ({vehiculo.patente}): {str(e)}'
                        )
                    )
                    logger.error(f"Error procesando vehículo {vehiculo.id}: {str(e)}", exc_info=True)

        # Resumen final
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('📊 RESUMEN DEL PROCESAMIENTO'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(
            self.style.SUCCESS(f'✅ Vehículos procesados: {total_procesados}')
        )
        if not use_async:
            self.stdout.write(
                self.style.SUCCESS(f'📋 Checklists procesados: {total_checklists_procesados}')
            )
            self.stdout.write(
                self.style.SUCCESS(f'🔧 Componentes actualizados: {total_componentes_actualizados}')
            )
        if total_errores > 0:
            self.stdout.write(
                self.style.WARNING(f'⚠️  Errores: {total_errores}')
            )
        self.stdout.write(self.style.SUCCESS('=' * 60))

        if use_async:
            self.stdout.write(
                self.style.SUCCESS(
                    '✅ Procesamiento iniciado en background. '
                    'Revisa los logs de Celery para ver el progreso detallado.'
                )
            )

