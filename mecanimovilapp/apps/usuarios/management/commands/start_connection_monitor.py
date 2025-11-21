from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
import asyncio
import time
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from mecanimovilapp.apps.usuarios.models import ConnectionStatus
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Monitorea el estado de conexión de proveedores y envía actualizaciones en tiempo real'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('🔄 Iniciando monitor de conexiones...'))
        
        try:
            asyncio.run(self.run_monitor())
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('⏹️ Monitor detenido por el usuario'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Error en monitor: {e}'))

    async def run_monitor(self):
        """Ejecuta el monitor de conexiones"""
        channel_layer = get_channel_layer()
        
        while True:
            try:
                # Verificar proveedores que no han tenido actividad en los últimos 60 segundos
                cutoff_time = timezone.now() - timedelta(seconds=60)
                
                # Buscar proveedores que están marcados como conectados pero no han tenido actividad reciente
                stale_connections = ConnectionStatus.objects.filter(
                    esta_conectado=True,
                    ultima_conexion__lt=cutoff_time
                )
                
                for connection in stale_connections:
                    # Marcar como desconectado
                    connection.esta_conectado = False
                    connection.ultima_desconexion = timezone.now()
                    connection.save()
                    
                    # Determinar tipo de proveedor
                    if hasattr(connection, 'proveedor'):
                        proveedor = connection.proveedor
                        tipo_proveedor = 'mecanico'
                        nombre_proveedor = proveedor.nombre
                        proveedor_id = proveedor.id
                    elif hasattr(connection, 'taller'):
                        proveedor = connection.taller
                        tipo_proveedor = 'taller'
                        nombre_proveedor = proveedor.nombre
                        proveedor_id = proveedor.id
                    else:
                        continue
                    
                    logger.info(f"🔌 Proveedor {nombre_proveedor} marcado como desconectado por inactividad")
                    
                    # Enviar notificación a clientes usando sync_to_async
                    async_to_sync(channel_layer.group_send)(
                        "clientes",
                        {
                            'type': 'connection_status_update',
                            'proveedor_id': proveedor_id,
                            'tipo_proveedor': tipo_proveedor,
                            'esta_conectado': False,
                            'nombre_proveedor': nombre_proveedor,
                            'timestamp': timezone.now().isoformat()
                        }
                    )
                    
                    self.stdout.write(
                        self.style.WARNING(f"🔌 {nombre_proveedor} desconectado automáticamente")
                    )
                
                # Esperar 30 segundos antes de la siguiente verificación
                await asyncio.sleep(30)
                
            except Exception as e:
                logger.error(f"❌ Error en monitor de conexiones: {e}")
                await asyncio.sleep(30)  # Continuar después de un error 