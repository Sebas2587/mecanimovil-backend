from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from mecanimovilapp.apps.usuarios.models import MecanicoDomicilio, Taller


class Command(BaseCommand):
    help = 'Limpia estados de conexión incorrectos de proveedores'

    def add_arguments(self, parser):
        parser.add_argument(
            '--minutes',
            type=int,
            default=5,
            help='Minutos de inactividad para considerar desconectado (default: 5)'
        )

    def handle(self, *args, **options):
        minutes = options['minutes']
        time_limit = timezone.now() - timedelta(minutes=minutes)
        
        self.stdout.write(
            self.style.SUCCESS(f'🧹 Limpiando estados de conexión...')
        )
        self.stdout.write(f'⏰ Tiempo límite: {time_limit}')
        
        # Limpiar mecánicos a domicilio
        mecanicos_conectados = MecanicoDomicilio.objects.filter(
            esta_conectado=True,
            ultima_conexion__lt=time_limit
        )
        
        self.stdout.write(
            f'🔧 Mecánicos conectados con última conexión > {minutes} min: {mecanicos_conectados.count()}'
        )
        
        for mecanico in mecanicos_conectados:
            self.stdout.write(f'  - {mecanico.nombre}: última conexión {mecanico.ultima_conexion}')
            mecanico.esta_conectado = False
            mecanico.save()
            self.stdout.write(self.style.SUCCESS(f'    ✅ Marcado como desconectado'))
        
        # Limpiar talleres
        talleres_conectados = Taller.objects.filter(
            esta_conectado=True,
            ultima_conexion__lt=time_limit
        )
        
        self.stdout.write(
            f'🏪 Talleres conectados con última conexión > {minutes} min: {talleres_conectados.count()}'
        )
        
        for taller in talleres_conectados:
            self.stdout.write(f'  - {taller.nombre}: última conexión {taller.ultima_conexion}')
            taller.esta_conectado = False
            taller.save()
            self.stdout.write(self.style.SUCCESS(f'    ✅ Marcado como desconectado'))
        
        self.stdout.write(self.style.SUCCESS(f'✅ Limpieza completada'))
        
        # Mostrar estado actual
        self.stdout.write(f'\n📊 Estado actual:')
        mecanicos_activos = MecanicoDomicilio.objects.filter(esta_conectado=True)
        talleres_activos = Taller.objects.filter(esta_conectado=True)
        
        self.stdout.write(f'  - Mecánicos conectados: {mecanicos_activos.count()}')
        for m in mecanicos_activos:
            self.stdout.write(f'    * {m.nombre} - última conexión: {m.ultima_conexion}')
        
        self.stdout.write(f'  - Talleres conectados: {talleres_activos.count()}')
        for t in talleres_activos:
            self.stdout.write(f'    * {t.nombre} - última conexión: {t.ultima_conexion}') 