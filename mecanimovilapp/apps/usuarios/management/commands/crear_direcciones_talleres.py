from django.core.management.base import BaseCommand
from mecanimovilapp.apps.usuarios.models import Taller, TallerDireccion


class Command(BaseCommand):
    help = 'Crear direcciones de ejemplo para talleres existentes'

    def handle(self, *args, **options):
        self.stdout.write('🔧 Creando direcciones de ejemplo para talleres...')
        
        # Obtener todos los talleres
        talleres = Taller.objects.all()
        
        for taller in talleres:
            # Verificar si ya tiene dirección
            if hasattr(taller, 'direccion_fisica'):
                self.stdout.write(f'✅ {taller.nombre} ya tiene dirección')
                continue
            
            # Crear dirección de ejemplo basada en el nombre del taller
            if 'Alison' in taller.nombre:
                direccion = TallerDireccion.objects.create(
                    taller=taller,
                    calle='Avenida Vitacura',
                    numero='9518',
                    comuna='Las Condes',
                    ciudad='Santiago',
                    region='Región Metropolitana',
                    detalles_adicionales='Edificio comercial, primer piso'
                )
            elif 'Centro' in taller.nombre:
                direccion = TallerDireccion.objects.create(
                    taller=taller,
                    calle='Avenida Providencia',
                    numero='1234',
                    comuna='Providencia',
                    ciudad='Santiago',
                    region='Región Metropolitana',
                    detalles_adicionales='Local comercial, esquina'
                )
            else:
                # Dirección genérica para otros talleres
                direccion = TallerDireccion.objects.create(
                    taller=taller,
                    calle='Calle Principal',
                    numero='100',
                    comuna='Santiago',
                    ciudad='Santiago',
                    region='Región Metropolitana',
                    detalles_adicionales='Local comercial'
                )
            
            self.stdout.write(f'✅ Dirección creada para {taller.nombre}: {direccion.direccion_completa}')
        
        self.stdout.write(self.style.SUCCESS('🎉 Direcciones de talleres creadas exitosamente'))
