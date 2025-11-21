from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from mecanimovilapp.apps.usuarios.models import Taller, MecanicoDomicilio, DocumentoOnboarding

class Command(BaseCommand):
    help = 'Verifica y aprueba automáticamente proveedores que han completado el onboarding correctamente'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Mostrar qué proveedores serían verificados sin realizar cambios'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Forzar la verificación incluso si faltan algunos datos'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options['force']
        
        self.stdout.write(self.style.SUCCESS('🔍 Verificando proveedores que completaron onboarding...'))
        
        if dry_run:
            self.stdout.write(self.style.WARNING('⚠️  MODO DRY-RUN: No se realizarán cambios'))
        
        talleres_verificados = 0
        mecanicos_verificados = 0
        talleres_problemas = 0
        mecanicos_problemas = 0
        
        try:
            with transaction.atomic():
                # Procesar talleres
                self.stdout.write('\n🏪 Procesando talleres...')
                talleres = Taller.objects.filter(
                    onboarding_completado=True,
                    verificado=False
                )
                
                for taller in talleres:
                    resultado = self.verificar_taller(taller, force)
                    
                    if resultado['puede_verificar']:
                        if not dry_run:
                            taller.aprobar_verificacion()
                            talleres_verificados += 1
                        
                        self.stdout.write(
                            self.style.SUCCESS(f'  ✅ {taller.nombre}: {resultado["mensaje"]}')
                        )
                    else:
                        talleres_problemas += 1
                        self.stdout.write(
                            self.style.WARNING(f'  ⚠️  {taller.nombre}: {resultado["mensaje"]}')
                        )
                
                # Procesar mecánicos
                self.stdout.write('\n🔧 Procesando mecánicos...')
                mecanicos = MecanicoDomicilio.objects.filter(
                    onboarding_completado=True,
                    verificado=False
                )
                
                for mecanico in mecanicos:
                    resultado = self.verificar_mecanico(mecanico, force)
                    
                    if resultado['puede_verificar']:
                        if not dry_run:
                            mecanico.aprobar_verificacion()
                            mecanicos_verificados += 1
                        
                        self.stdout.write(
                            self.style.SUCCESS(f'  ✅ {mecanico.nombre}: {resultado["mensaje"]}')
                        )
                    else:
                        mecanicos_problemas += 1
                        self.stdout.write(
                            self.style.WARNING(f'  ⚠️  {mecanico.nombre}: {resultado["mensaje"]}')
                        )
                
                # Resumen
                self.stdout.write('\n📊 RESUMEN:')
                self.stdout.write(f'  Talleres {"que se verificarían" if dry_run else "verificados"}: {talleres_verificados}')
                self.stdout.write(f'  Mecánicos {"que se verificarían" if dry_run else "verificados"}: {mecanicos_verificados}')
                self.stdout.write(f'  Talleres con problemas: {talleres_problemas}')
                self.stdout.write(f'  Mecánicos con problemas: {mecanicos_problemas}')
                
                if dry_run:
                    self.stdout.write(self.style.WARNING('\n⚠️  Para aplicar los cambios, ejecuta sin --dry-run'))
                    transaction.set_rollback(True)
                else:
                    self.stdout.write(self.style.SUCCESS('\n✅ Verificaciones aplicadas exitosamente'))
                    
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\n❌ Error durante la verificación: {str(e)}'))
            raise

    def verificar_taller(self, taller, force=False):
        """Verifica si un taller puede ser aprobado automáticamente"""
        problemas = []
        
        # Verificar datos básicos
        if not taller.nombre:
            problemas.append('falta nombre')
        if not taller.telefono:
            problemas.append('falta teléfono')
        if not taller.descripcion:
            problemas.append('falta descripción')
        if not taller.direccion:
            problemas.append('falta dirección')
        
        # Verificar especialidades
        especialidades_count = taller.especialidades.count()
        if especialidades_count == 0:
            problemas.append('sin especialidades')
        
        # Verificar marcas atendidas
        marcas_count = taller.marcas_atendidas.count()
        if marcas_count == 0:
            problemas.append('sin marcas atendidas')
        
        # Verificar documentos (opcional)
        documentos_count = DocumentoOnboarding.objects.filter(taller=taller).count()
        if documentos_count == 0:
            problemas.append('sin documentos')
        
        # Determinar si puede verificar
        puede_verificar = len(problemas) == 0 or force
        
        if puede_verificar:
            mensaje = f'Aprobado - {especialidades_count} especialidades, {marcas_count} marcas, {documentos_count} documentos'
        else:
            mensaje = f'Problemas: {", ".join(problemas)}'
        
        return {
            'puede_verificar': puede_verificar,
            'mensaje': mensaje,
            'problemas': problemas
        }

    def verificar_mecanico(self, mecanico, force=False):
        """Verifica si un mecánico puede ser aprobado automáticamente"""
        problemas = []
        
        # Verificar datos básicos
        if not mecanico.nombre:
            problemas.append('falta nombre')
        if not mecanico.telefono:
            problemas.append('falta teléfono')
        if not mecanico.descripcion:
            problemas.append('falta descripción')
        if not mecanico.dni:
            problemas.append('falta DNI')
        if not mecanico.experiencia_anos:
            problemas.append('falta experiencia')
        
        # Verificar especialidades
        especialidades_count = mecanico.especialidades.count()
        if especialidades_count == 0:
            problemas.append('sin especialidades')
        
        # Verificar marcas atendidas
        marcas_count = mecanico.marcas_atendidas.count()
        if marcas_count == 0:
            problemas.append('sin marcas atendidas')
        
        # Verificar documentos (opcional)
        documentos_count = DocumentoOnboarding.objects.filter(mecanico=mecanico).count()
        if documentos_count == 0:
            problemas.append('sin documentos')
        
        # Determinar si puede verificar
        puede_verificar = len(problemas) == 0 or force
        
        if puede_verificar:
            mensaje = f'Aprobado - {especialidades_count} especialidades, {marcas_count} marcas, {documentos_count} documentos'
        else:
            mensaje = f'Problemas: {", ".join(problemas)}'
        
        return {
            'puede_verificar': puede_verificar,
            'mensaje': mensaje,
            'problemas': problemas
        } 