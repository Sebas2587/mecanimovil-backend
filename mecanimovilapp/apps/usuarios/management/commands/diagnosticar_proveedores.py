from django.core.management.base import BaseCommand
from django.db import models
from mecanimovilapp.apps.usuarios.models import Taller, MecanicoDomicilio, DocumentoOnboarding
from mecanimovilapp.apps.servicios.models import CategoriaServicio
from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo

class Command(BaseCommand):
    help = 'Diagnostica el estado actual de los proveedores, especialidades y marcas'

    def add_arguments(self, parser):
        parser.add_argument(
            '--proveedor',
            type=str,
            help='Diagnosticar un proveedor específico por nombre'
        )
        parser.add_argument(
            '--tipo',
            type=str,
            choices=['taller', 'mecanico'],
            help='Filtrar por tipo de proveedor'
        )
        parser.add_argument(
            '--detallado',
            action='store_true',
            help='Mostrar información detallada de cada proveedor'
        )

    def handle(self, *args, **options):
        proveedor_nombre = options.get('proveedor')
        tipo_filtro = options.get('tipo')
        detallado = options.get('detallado', False)
        
        self.stdout.write(self.style.SUCCESS('🔍 DIAGNÓSTICO DE PROVEEDORES'))
        self.stdout.write('=' * 50)
        
        # Estadísticas generales
        self.mostrar_estadisticas_generales()
        
        # Diagnosticar talleres
        if not tipo_filtro or tipo_filtro == 'taller':
            self.diagnosticar_talleres(proveedor_nombre, detallado)
        
        # Diagnosticar mecánicos
        if not tipo_filtro or tipo_filtro == 'mecanico':
            self.diagnosticar_mecanicos(proveedor_nombre, detallado)
        
        # Verificar catálogos
        self.verificar_catalogos()

    def mostrar_estadisticas_generales(self):
        """Mostrar estadísticas generales del sistema"""
        self.stdout.write('\n📊 ESTADÍSTICAS GENERALES')
        self.stdout.write('-' * 30)
        
        # Talleres
        talleres_total = Taller.objects.count()
        talleres_verificados = Taller.objects.filter(verificado=True).count()
        talleres_onboarding = Taller.objects.filter(onboarding_completado=True).count()
        
        self.stdout.write(f'🏪 Talleres:')
        self.stdout.write(f'  Total: {talleres_total}')
        self.stdout.write(f'  Verificados: {talleres_verificados}')
        self.stdout.write(f'  Onboarding completado: {talleres_onboarding}')
        
        # Mecánicos
        mecanicos_total = MecanicoDomicilio.objects.count()
        mecanicos_verificados = MecanicoDomicilio.objects.filter(verificado=True).count()
        mecanicos_onboarding = MecanicoDomicilio.objects.filter(onboarding_completado=True).count()
        
        self.stdout.write(f'🔧 Mecánicos:')
        self.stdout.write(f'  Total: {mecanicos_total}')
        self.stdout.write(f'  Verificados: {mecanicos_verificados}')
        self.stdout.write(f'  Onboarding completado: {mecanicos_onboarding}')
        
        # Documentos
        documentos_total = DocumentoOnboarding.objects.count()
        self.stdout.write(f'📄 Documentos de onboarding: {documentos_total}')

    def diagnosticar_talleres(self, nombre_filtro=None, detallado=False):
        """Diagnosticar estado de talleres"""
        self.stdout.write('\n🏪 TALLERES')
        self.stdout.write('-' * 30)
        
        talleres = Taller.objects.all()
        if nombre_filtro:
            talleres = talleres.filter(nombre__icontains=nombre_filtro)
        
        for taller in talleres:
            self.mostrar_diagnostico_taller(taller, detallado)

    def diagnosticar_mecanicos(self, nombre_filtro=None, detallado=False):
        """Diagnosticar estado de mecánicos"""
        self.stdout.write('\n🔧 MECÁNICOS')
        self.stdout.write('-' * 30)
        
        mecanicos = MecanicoDomicilio.objects.all()
        if nombre_filtro:
            mecanicos = mecanicos.filter(nombre__icontains=nombre_filtro)
        
        for mecanico in mecanicos:
            self.mostrar_diagnostico_mecanico(mecanico, detallado)

    def mostrar_diagnostico_taller(self, taller, detallado=False):
        """Mostrar diagnóstico detallado de un taller"""
        # Obtener counts
        especialidades_count = taller.especialidades.count()
        marcas_count = taller.marcas_atendidas.count()
        documentos_count = DocumentoOnboarding.objects.filter(taller=taller).count()
        
        # Determinar estado
        estado_icono = self.get_estado_icono(taller.verificado, taller.estado_verificacion)
        
        # Mostrar información básica
        self.stdout.write(f'\n{estado_icono} {taller.nombre} (ID: {taller.id})')
        self.stdout.write(f'  Estado: {taller.estado_verificacion} | Verificado: {taller.verificado} | Activo: {taller.activo}')
        self.stdout.write(f'  Onboarding: Iniciado={taller.onboarding_iniciado}, Completado={taller.onboarding_completado}')
        self.stdout.write(f'  Especialidades: {especialidades_count} | Marcas: {marcas_count} | Documentos: {documentos_count}')
        
        # Información detallada
        if detallado:
            self.stdout.write(f'  Teléfono: {taller.telefono or "N/A"}')
            self.stdout.write(f'  Dirección: {taller.direccion or "N/A"}')
            self.stdout.write(f'  RUT: {taller.rut or "N/A"}')
            self.stdout.write(f'  Descripción: {taller.descripcion or "N/A"}')
            
            # Mostrar especialidades
            if especialidades_count > 0:
                especialidades = list(taller.especialidades.values_list('nombre', flat=True))
                self.stdout.write(f'  Especialidades: {", ".join(especialidades)}')
            
            # Mostrar marcas
            if marcas_count > 0:
                marcas = list(taller.marcas_atendidas.values_list('nombre', flat=True))
                self.stdout.write(f'  Marcas: {", ".join(marcas)}')
        
        # Alertas
        alertas = []
        if taller.onboarding_completado and especialidades_count == 0:
            alertas.append("⚠️ Sin especialidades")
        if taller.onboarding_completado and marcas_count == 0:
            alertas.append("⚠️ Sin marcas")
        if taller.verificado and taller.estado_verificacion != 'aprobado':
            alertas.append("⚠️ Estado inconsistente")
        
        if alertas:
            self.stdout.write(f'  ALERTAS: {" | ".join(alertas)}')

    def mostrar_diagnostico_mecanico(self, mecanico, detallado=False):
        """Mostrar diagnóstico detallado de un mecánico"""
        # Obtener counts
        especialidades_count = mecanico.especialidades.count()
        marcas_count = mecanico.marcas_atendidas.count()
        documentos_count = DocumentoOnboarding.objects.filter(mecanico=mecanico).count()
        
        # Determinar estado
        estado_icono = self.get_estado_icono(mecanico.verificado, mecanico.estado_verificacion)
        
        # Mostrar información básica
        self.stdout.write(f'\n{estado_icono} {mecanico.nombre} (ID: {mecanico.id})')
        self.stdout.write(f'  Estado: {mecanico.estado_verificacion} | Verificado: {mecanico.verificado} | Activo: {mecanico.activo}')
        self.stdout.write(f'  Onboarding: Iniciado={mecanico.onboarding_iniciado}, Completado={mecanico.onboarding_completado}')
        self.stdout.write(f'  Especialidades: {especialidades_count} | Marcas: {marcas_count} | Documentos: {documentos_count}')
        
        # Información detallada
        if detallado:
            self.stdout.write(f'  Teléfono: {mecanico.telefono or "N/A"}')
            self.stdout.write(f'  DNI: {mecanico.dni or "N/A"}')
            self.stdout.write(f'  Experiencia: {mecanico.experiencia_anos or "N/A"} años')
            self.stdout.write(f'  Descripción: {mecanico.descripcion or "N/A"}')
            
            # Mostrar especialidades
            if especialidades_count > 0:
                especialidades = list(mecanico.especialidades.values_list('nombre', flat=True))
                self.stdout.write(f'  Especialidades: {", ".join(especialidades)}')
            
            # Mostrar marcas
            if marcas_count > 0:
                marcas = list(mecanico.marcas_atendidas.values_list('nombre', flat=True))
                self.stdout.write(f'  Marcas: {", ".join(marcas)}')
        
        # Alertas
        alertas = []
        if mecanico.onboarding_completado and especialidades_count == 0:
            alertas.append("⚠️ Sin especialidades")
        if mecanico.onboarding_completado and marcas_count == 0:
            alertas.append("⚠️ Sin marcas")
        if mecanico.verificado and mecanico.estado_verificacion != 'aprobado':
            alertas.append("⚠️ Estado inconsistente")
        
        if alertas:
            self.stdout.write(f'  ALERTAS: {" | ".join(alertas)}')

    def get_estado_icono(self, verificado, estado_verificacion):
        """Obtener ícono según el estado del proveedor"""
        if verificado and estado_verificacion == 'aprobado':
            return '✅'
        elif estado_verificacion == 'en_revision':
            return '⏳'
        elif estado_verificacion == 'rechazado':
            return '❌'
        else:
            return '⚠️'

    def verificar_catalogos(self):
        """Verificar catálogos de especialidades y marcas"""
        self.stdout.write('\n📋 CATÁLOGOS')
        self.stdout.write('-' * 30)
        
        # Especialidades
        especialidades_count = CategoriaServicio.objects.count()
        self.stdout.write(f'🔧 Especialidades disponibles: {especialidades_count}')
        
        # Marcas
        marcas_count = MarcaVehiculo.objects.count()
        self.stdout.write(f'🚗 Marcas de vehículos: {marcas_count}')
        
        # Mostrar algunas especialidades
        if especialidades_count > 0:
            especialidades = list(CategoriaServicio.objects.values_list('nombre', flat=True)[:5])
            self.stdout.write(f'  Ejemplos de especialidades: {", ".join(especialidades)}')
        
        # Mostrar algunas marcas
        if marcas_count > 0:
            marcas = list(MarcaVehiculo.objects.values_list('nombre', flat=True)[:5])
            self.stdout.write(f'  Ejemplos de marcas: {", ".join(marcas)}')

        self.stdout.write('\n' + '=' * 50)
        self.stdout.write('🎯 RECOMENDACIONES:')
        self.stdout.write('1. Ejecuta: python manage.py verificar_proveedores_onboarding --dry-run')
        self.stdout.write('2. Revisa proveedores con alertas')
        self.stdout.write('3. Verifica en Django Admin si las especialidades se guardaron correctamente')
        self.stdout.write('4. Si hay problemas, contacta con el desarrollador') 