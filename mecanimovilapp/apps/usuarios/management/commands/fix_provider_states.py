from django.core.management.base import BaseCommand
from django.db import transaction, models
from mecanimovilapp.apps.usuarios.models import Taller, MecanicoDomicilio


class Command(BaseCommand):
    help = 'Corrige los estados inconsistentes de los proveedores de servicios'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Ejecutar sin hacer cambios reales (solo mostrar qué se haría)',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Forzar la corrección sin confirmación',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options['force']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('MODO DRY-RUN: No se harán cambios reales'))
        
        # Contadores
        talleres_corregidos = 0
        mecanicos_corregidos = 0
        
        try:
            with transaction.atomic():
                # Corregir Talleres
                self.stdout.write('\n🔧 Analizando Talleres...')
                talleres_problematicos = Taller.objects.filter(
                    models.Q(verificado=True, estado_verificacion__in=['pendiente', 'en_revision', 'rechazado']) |
                    models.Q(verificado=False, estado_verificacion='aprobado') |
                    models.Q(activo=True, verificado=False)
                )
                
                for taller in talleres_problematicos:
                    problema = self.analizar_problema_taller(taller)
                    self.stdout.write(f"  - {taller.nombre}: {problema}")
                    
                    if not dry_run:
                        self.corregir_taller(taller)
                        talleres_corregidos += 1
                
                # Corregir Mecánicos
                self.stdout.write('\n🔧 Analizando Mecánicos...')
                mecanicos_problematicos = MecanicoDomicilio.objects.filter(
                    models.Q(verificado=True, estado_verificacion__in=['pendiente', 'en_revision', 'rechazado']) |
                    models.Q(verificado=False, estado_verificacion='aprobado') |
                    models.Q(activo=True, verificado=False)
                )
                
                for mecanico in mecanicos_problematicos:
                    problema = self.analizar_problema_mecanico(mecanico)
                    self.stdout.write(f"  - {mecanico.nombre}: {problema}")
                    
                    if not dry_run:
                        self.corregir_mecanico(mecanico)
                        mecanicos_corregidos += 1
                
                # Mostrar resumen
                self.stdout.write('\n📊 RESUMEN:')
                self.stdout.write(f"  Talleres {'que se corregirían' if dry_run else 'corregidos'}: {talleres_corregidos}")
                self.stdout.write(f"  Mecánicos {'que se corregirían' if dry_run else 'corregidos'}: {mecanicos_corregidos}")
                
                if dry_run:
                    self.stdout.write(self.style.WARNING('\nPara aplicar los cambios, ejecuta sin --dry-run'))
                    # Hacer rollback en dry-run
                    transaction.set_rollback(True)
                else:
                    self.stdout.write(self.style.SUCCESS('\n✅ Correcciones aplicadas exitosamente'))
                    
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\n❌ Error durante la corrección: {str(e)}'))
            raise

    def analizar_problema_taller(self, taller):
        """Analiza qué problema específico tiene el taller"""
        if taller.verificado and taller.estado_verificacion != 'aprobado':
            return f"verificado=True pero estado='{taller.estado_verificacion}'"
        elif not taller.verificado and taller.estado_verificacion == 'aprobado':
            return f"verificado=False pero estado='aprobado'"
        elif taller.activo and not taller.verificado:
            return f"activo=True pero verificado=False"
        return "estado inconsistente"

    def analizar_problema_mecanico(self, mecanico):
        """Analiza qué problema específico tiene el mecánico"""
        if mecanico.verificado and mecanico.estado_verificacion != 'aprobado':
            return f"verificado=True pero estado='{mecanico.estado_verificacion}'"
        elif not mecanico.verificado and mecanico.estado_verificacion == 'aprobado':
            return f"verificado=False pero estado='aprobado'"
        elif mecanico.activo and not mecanico.verificado:
            return f"activo=True pero verificado=False"
        return "estado inconsistente"

    def corregir_taller(self, taller):
        """Corrige el estado del taller según las reglas de negocio"""
        # Regla: Solo pueden estar activos y verificados si estado_verificacion='aprobado'
        if taller.estado_verificacion == 'aprobado':
            taller.verificado = True
            taller.activo = True
        else:
            taller.verificado = False
            # Solo mantener activo=True si completó onboarding (para que puedan hacer onboarding)
            if not taller.onboarding_completado:
                taller.activo = False
        
        taller.save(update_fields=['verificado', 'activo'])

    def corregir_mecanico(self, mecanico):
        """Corrige el estado del mecánico según las reglas de negocio"""
        # Regla: Solo pueden estar activos y verificados si estado_verificacion='aprobado'
        if mecanico.estado_verificacion == 'aprobado':
            mecanico.verificado = True
            mecanico.activo = True
        else:
            mecanico.verificado = False
            # Solo mantener activo=True si completó onboarding (para que puedan hacer onboarding)
            if not mecanico.onboarding_completado:
                mecanico.activo = False
        
        mecanico.save(update_fields=['verificado', 'activo']) 