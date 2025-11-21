from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from django.db.models import Count
from mecanimovilapp.apps.vehiculos.models import Vehiculo
from mecanimovilapp.apps.personalizacion.ml_engine import MotorRecomendaciones
from mecanimovilapp.apps.personalizacion.models import PerfilVehiculo, RecomendacionPersonalizada
import time


class Command(BaseCommand):
    help = 'Genera recomendaciones personalizadas usando el motor de Machine Learning'

    def add_arguments(self, parser):
        parser.add_argument(
            '--vehiculo-id',
            type=int,
            help='ID específico del vehículo para generar recomendaciones'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=10,
            help='Número de vehículos a procesar por lote (default: 10)'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Forzar regeneración de recomendaciones existentes'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Ejecutar sin hacer cambios en la base de datos'
        )

    def handle(self, *args, **options):
        self.verbosity = options['verbosity']
        self.dry_run = options['dry_run']
        
        if self.dry_run:
            self.stdout.write(
                self.style.WARNING('🔍 Modo DRY RUN - No se harán cambios en la base de datos')
            )
        
        # Inicializar motor de recomendaciones
        try:
            motor = MotorRecomendaciones()
            self.stdout.write(
                self.style.SUCCESS('✅ Motor de recomendaciones inicializado')
            )
        except Exception as e:
            raise CommandError(f'Error inicializando motor ML: {str(e)}')

        # Determinar vehículos a procesar
        if options['vehiculo_id']:
            vehiculos = self._get_vehiculo_especifico(options['vehiculo_id'])
        else:
            vehiculos = self._get_vehiculos_para_procesar(options['force'])

        if not vehiculos:
            self.stdout.write(
                self.style.WARNING('⚠️  No hay vehículos para procesar')
            )
            return

        self.stdout.write(
            self.style.SUCCESS(f'🚀 Procesando {len(vehiculos)} vehículos...')
        )

        # Procesar en lotes
        batch_size = options['batch_size']
        total_procesados = 0
        total_errores = 0
        
        for i in range(0, len(vehiculos), batch_size):
            batch = vehiculos[i:i + batch_size]
            procesados, errores = self._procesar_lote(motor, batch)
            total_procesados += procesados
            total_errores += errores
            
            if self.verbosity >= 1:
                self.stdout.write(
                    f'📊 Lote {i//batch_size + 1}: {procesados} procesados, {errores} errores'
                )

        # Resumen final
        self._mostrar_resumen(total_procesados, total_errores, len(vehiculos))

    def _get_vehiculo_especifico(self, vehiculo_id):
        """Obtiene un vehículo específico por ID"""
        try:
            vehiculo = Vehiculo.objects.get(id=vehiculo_id)
            return [vehiculo]
        except Vehiculo.DoesNotExist:
            raise CommandError(f'Vehículo con ID {vehiculo_id} no encontrado')

    def _get_vehiculos_para_procesar(self, force=False):
        """Obtiene la lista de vehículos que necesitan procesamiento"""
        if force:
            # Procesar todos los vehículos
            vehiculos = Vehiculo.objects.select_related('cliente').all()
            if self.verbosity >= 1:
                self.stdout.write('🔄 Modo FORCE: procesando todos los vehículos')
        else:
            # Solo vehículos sin recomendaciones recientes
            vehiculos_sin_recomendaciones = Vehiculo.objects.filter(
                recomendaciones__isnull=True
            ).distinct()
            
            vehiculos_recomendaciones_viejas = Vehiculo.objects.filter(
                recomendaciones__fecha_generacion__lt=timezone.now() - timedelta(days=7)
            ).distinct()
            
            vehiculos = (vehiculos_sin_recomendaciones | vehiculos_recomendaciones_viejas).select_related('cliente')
            
            if self.verbosity >= 1:
                self.stdout.write(
                    f'📋 Procesando vehículos sin recomendaciones recientes'
                )

        return list(vehiculos)

    def _procesar_lote(self, motor, vehiculos_batch):
        """Procesa un lote de vehículos"""
        procesados = 0
        errores = 0
        
        for vehiculo in vehiculos_batch:
            try:
                if not self.dry_run:
                    with transaction.atomic():
                        # Generar recomendaciones
                        motor.generar_recomendaciones_vehiculo(vehiculo)
                        
                        # Verificar que se crearon recomendaciones
                        count_recomendaciones = RecomendacionPersonalizada.objects.filter(
                            vehiculo=vehiculo,
                            activa=True
                        ).count()
                        
                        if self.verbosity >= 2:
                            self.stdout.write(
                                f'  ✅ {vehiculo.marca_nombre} {vehiculo.modelo_nombre} '
                                f'({vehiculo.year}) - {count_recomendaciones} recomendaciones'
                            )
                else:
                    # Modo dry-run: solo simular
                    if self.verbosity >= 2:
                        self.stdout.write(
                            f'  🔍 [DRY RUN] {vehiculo.marca_nombre} {vehiculo.modelo_nombre} ({vehiculo.year})'
                        )
                
                procesados += 1
                
            except Exception as e:
                errores += 1
                if self.verbosity >= 1:
                    self.stdout.write(
                        self.style.ERROR(
                            f'  ❌ Error procesando vehículo {vehiculo.id}: {str(e)}'
                        )
                    )
            
            # Pequeña pausa para no sobrecargar la base de datos
            time.sleep(0.1)
        
        return procesados, errores

    def _mostrar_resumen(self, procesados, errores, total):
        """Muestra el resumen final del procesamiento"""
        self.stdout.write('\n' + '='*50)
        self.stdout.write(
            self.style.SUCCESS(f'🎉 Procesamiento completado!')
        )
        self.stdout.write(f'📊 Estadísticas:')
        self.stdout.write(f'   • Total vehículos: {total}')
        self.stdout.write(f'   • Procesados exitosamente: {procesados}')
        self.stdout.write(f'   • Errores: {errores}')
        
        if errores > 0:
            self.stdout.write(
                self.style.WARNING(f'   • Tasa de éxito: {(procesados/total)*100:.1f}%')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f'   • Tasa de éxito: 100%')
            )
        
        if not self.dry_run and procesados > 0:
            # Mostrar estadísticas de recomendaciones generadas
            total_recomendaciones = RecomendacionPersonalizada.objects.filter(
                activa=True
            ).count()
            
            self.stdout.write(f'\n📈 Recomendaciones en el sistema:')
            self.stdout.write(f'   • Total activas: {total_recomendaciones}')
            
            # Estadísticas por tipo
            tipos_stats = RecomendacionPersonalizada.objects.filter(
                activa=True
            ).values('tipo').annotate(
                count=Count('id')
            ).order_by('-count')
            
            for stat in tipos_stats:
                self.stdout.write(f'   • {stat["tipo"]}: {stat["count"]}')
        
        self.stdout.write('='*50) 