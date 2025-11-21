from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django.utils import timezone
from mecanimovilapp.apps.usuarios.models import Taller, MecanicoDomicilio, DocumentoOnboarding
import base64
from PIL import Image
import io


class Command(BaseCommand):
    help = 'Crea documentos de prueba para verificar el sistema de onboarding'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Eliminar todos los documentos existentes antes de crear nuevos',
        )

    def handle(self, *args, **options):
        clear_existing = options['clear']
        
        if clear_existing:
            self.stdout.write('🗑️ Eliminando documentos existentes...')
            DocumentoOnboarding.objects.all().delete()
        
        # Crear imagen de prueba (1x1 pixel rojo)
        def crear_imagen_prueba():
            img = Image.new('RGB', (100, 100), color='red')
            img_buffer = io.BytesIO()
            img.save(img_buffer, format='JPEG')
            img_buffer.seek(0)
            return ContentFile(img_buffer.read(), name='test_document.jpg')
        
        documentos_creados = 0
        
        # Crear documentos para talleres
        self.stdout.write('\n🔧 Creando documentos para talleres...')
        talleres = Taller.objects.all()[:2]  # Solo los primeros 2 para prueba
        
        for taller in talleres:
            tipos_taller = ['dni_frontal', 'dni_trasero', 'rut_fiscal']
            
            for tipo in tipos_taller:
                doc = DocumentoOnboarding.objects.create(
                    taller=taller,
                    mecanico=None,
                    tipo_documento=tipo,
                    archivo=crear_imagen_prueba(),
                    nombre_original=f'{tipo}_taller_{taller.id}.jpg',
                    verificado=False
                )
                self.stdout.write(f'  ✅ {taller.nombre}: {doc.get_tipo_documento_display()}')
                documentos_creados += 1
        
        # Crear documentos para mecánicos
        self.stdout.write('\n🔧 Creando documentos para mecánicos...')
        mecanicos = MecanicoDomicilio.objects.all()[:2]  # Solo los primeros 2 para prueba
        
        for mecanico in mecanicos:
            tipos_mecanico = ['dni_frontal', 'dni_trasero', 'licencia_conducir']
            
            for tipo in tipos_mecanico:
                doc = DocumentoOnboarding.objects.create(
                    taller=None,
                    mecanico=mecanico,
                    tipo_documento=tipo,
                    archivo=crear_imagen_prueba(),
                    nombre_original=f'{tipo}_mecanico_{mecanico.id}.jpg',
                    verificado=False
                )
                self.stdout.write(f'  ✅ {mecanico.nombre}: {doc.get_tipo_documento_display()}')
                documentos_creados += 1
        
        # Mostrar resumen
        self.stdout.write('\n📊 RESUMEN:')
        self.stdout.write(f'  Documentos creados: {documentos_creados}')
        self.stdout.write(f'  Total documentos en DB: {DocumentoOnboarding.objects.count()}')
        
        # Verificar relaciones
        self.stdout.write('\n🔗 VERIFICANDO RELACIONES:')
        for taller in Taller.objects.all():
            docs_count = taller.documentos_onboarding.count()
            if docs_count > 0:
                self.stdout.write(f'  Taller "{taller.nombre}": {docs_count} documentos')
        
        for mecanico in MecanicoDomicilio.objects.all():
            docs_count = mecanico.documentos_onboarding.count()
            if docs_count > 0:
                self.stdout.write(f'  Mecánico "{mecanico.nombre}": {docs_count} documentos')
        
        self.stdout.write(self.style.SUCCESS('\n✅ Documentos de prueba creados exitosamente')) 