from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from mecanimovilapp.apps.usuarios.models import ConnectionStatus


class Command(BaseCommand):
    help = 'Limpia conexiones WebSocket antiguas y optimiza el rendimiento'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Forzar limpieza sin confirmación',
        )

    def handle(self, *args, **options):
        self.stdout.write("🧹 Iniciando limpieza de conexiones WebSocket...")
        
        # Marcar como desconectados los proveedores que no han enviado heartbeat en 5 minutos
        cutoff_time = timezone.now() - timedelta(minutes=5)
        
        # Buscar conexiones activas que no han actualizado su heartbeat
        old_connections = ConnectionStatus.objects.filter(
            esta_conectado=True,
            ultima_conexion__lt=cutoff_time
        )
        
        self.stdout.write(f"📊 Encontradas {old_connections.count()} conexiones antiguas")
        
        if old_connections.count() > 0 and not options['force']:
            confirm = input("¿Deseas continuar con la limpieza? (y/N): ")
            if confirm.lower() != 'y':
                self.stdout.write("❌ Limpieza cancelada")
                return
        
        for connection in old_connections:
            connection.esta_conectado = False
            connection.ultima_desconexion = timezone.now()
            connection.save()
            
            provider_name = connection.nombre_proveedor
            self.stdout.write(f"🔌 Marcando como desconectado: {provider_name}")
        
        # Limpiar conexiones muy antiguas (más de 1 hora)
        very_old_cutoff = timezone.now() - timedelta(hours=1)
        very_old_connections = ConnectionStatus.objects.filter(
            ultima_conexion__lt=very_old_cutoff
        )
        
        self.stdout.write(f"🗑️ Eliminando {very_old_connections.count()} conexiones muy antiguas")
        very_old_connections.delete()
        
        self.stdout.write(self.style.SUCCESS("✅ Limpieza completada"))
        
        # Mostrar estadísticas
        total_connections = ConnectionStatus.objects.count()
        active_connections = ConnectionStatus.objects.filter(esta_conectado=True).count()
        
        self.stdout.write(f"📊 Estadísticas:")
        self.stdout.write(f"   - Total de conexiones: {total_connections}")
        self.stdout.write(f"   - Conexiones activas: {active_connections}")
        self.stdout.write(f"   - Conexiones inactivas: {total_connections - active_connections}") 