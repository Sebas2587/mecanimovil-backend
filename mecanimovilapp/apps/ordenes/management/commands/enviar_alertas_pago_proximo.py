"""
Comando de Django para enviar alertas de pago próximo a clientes.

Este comando busca solicitudes adjudicadas donde faltan 6 horas o menos
para la fecha límite de pago y envía notificaciones WebSocket a los clientes.

Uso:
    python manage.py enviar_alertas_pago_proximo
    python manage.py enviar_alertas_pago_proximo --dry-run  # Para ver qué se haría sin hacer cambios
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from mecanimovilapp.apps.ordenes.models import SolicitudServicioPublica
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from mecanimovilapp.apps.usuarios.tasks import send_expo_push_notification
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Envía alertas de pago próximo a clientes cuando faltan 6 horas para la fecha límite'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Ejecuta el comando sin hacer cambios reales en la base de datos',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('🔍 MODO DRY RUN: No se enviarán notificaciones'))
        
        self.stdout.write('🔍 Buscando solicitudes adjudicadas con alerta de pago próximo...')
        
        ahora = timezone.now()
        # 6 horas = 21600 segundos
        limite_inferior = ahora + timedelta(hours=5, minutes=55)  # 5h 55m
        limite_superior = ahora + timedelta(hours=6, minutes=5)   # 6h 5m
        
        # Buscar solicitudes adjudicadas donde fecha_limite_pago está entre 5h55m y 6h5m
        solicitudes_con_alerta = SolicitudServicioPublica.objects.filter(
            estado__in=['adjudicada', 'pendiente_pago'],
            fecha_limite_pago__gte=limite_inferior,
            fecha_limite_pago__lte=limite_superior
        ).select_related(
            'cliente',
            'cliente__usuario',
            'oferta_seleccionada'
        )
        
        total_encontradas = solicitudes_con_alerta.count()
        self.stdout.write(f'📊 Encontradas {total_encontradas} solicitudes con alerta activa')
        
        if total_encontradas == 0:
            self.stdout.write(self.style.SUCCESS('✅ No hay solicitudes que requieran alerta'))
            return
        
        # Mostrar detalles
        self.stdout.write('\n📋 Detalle de solicitudes a notificar:')
        for solicitud in solicitudes_con_alerta:
            cliente_nombre = solicitud.cliente.nombre if solicitud.cliente else 'Sin cliente'
            tiempo_restante = solicitud.tiempo_restante_pago()
            horas = int(tiempo_restante.total_seconds() // 3600) if tiempo_restante else 0
            minutos = int((tiempo_restante.total_seconds() % 3600) // 60) if tiempo_restante else 0
            
            self.stdout.write(
                f'  • Solicitud #{solicitud.id} - '
                f'Cliente: {cliente_nombre} - '
                f'Tiempo restante: {horas}h {minutos}m'
            )
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\n⚠️  DRY RUN: No se enviaron notificaciones'))
            return
        
        # Enviar notificaciones
        self.stdout.write('\n📤 Enviando notificaciones WebSocket...')
        
        enviadas = 0
        errores = 0
        channel_layer = get_channel_layer()
        
        for solicitud in solicitudes_con_alerta:
            try:
                if not solicitud.cliente or not solicitud.cliente.usuario:
                    logger.warning(f"Solicitud {solicitud.id} sin cliente o usuario asociado")
                    continue
                
                tiempo_restante = solicitud.tiempo_restante_pago()
                if not tiempo_restante:
                    continue
                
                horas = int(tiempo_restante.total_seconds() // 3600)
                minutos = int((tiempo_restante.total_seconds() % 3600) // 60)
                
                # Enviar notificación WebSocket al cliente
                if channel_layer:
                    async_to_sync(channel_layer.group_send)(
                        f"cliente_{solicitud.cliente.usuario.id}",
                        {
                            'type': 'alerta_pago_proximo',
                            'solicitud_id': str(solicitud.id),
                            'oferta_id': str(solicitud.oferta_seleccionada.id) if solicitud.oferta_seleccionada else None,
                            'mensaje': f'Quedan {horas}h {minutos}m para pagar esta solicitud. No olvides completar el pago antes de la fecha del servicio.',
                            'tiempo_restante_horas': horas,
                            'tiempo_restante_minutos': minutos,
                            'fecha_limite_pago': solicitud.fecha_limite_pago.isoformat() if solicitud.fecha_limite_pago else None,
                            'timestamp': ahora.isoformat()
                        }
                    )
                
                # Enviar notificación PUSH al dispositivo del cliente
                send_expo_push_notification.delay(
                    solicitud.cliente.usuario.id,
                    f"⏰ Pago Pendiente",
                    f"Quedan {horas}h {minutos}m para pagar tu servicio. No olvides completar el pago.",
                    {
                        'type': 'payment_reminder',
                        'solicitud_id': str(solicitud.id),
                        'horas_restantes': horas,
                        'minutos_restantes': minutos
                    }
                )
                
                # Crear notificación in-app
                from mecanimovilapp.apps.usuarios.models import Notificacion
                Notificacion.objects.create(
                    usuario=solicitud.cliente.usuario,
                    tipo='payment_reminder',
                    titulo=f"⏰ Pago Pendiente",
                    mensaje=f"Quedan {horas}h {minutos}m para pagar tu servicio. No olvides completar el pago.",
                    data={
                        'solicitud_id': str(solicitud.id),
                        'horas_restantes': horas,
                        'minutos_restantes': minutos
                    }
                )
                
                enviadas += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  ✅ Notificación enviada - Solicitud #{solicitud.id} - '
                        f'Cliente: {solicitud.cliente.nombre if solicitud.cliente else "N/A"}'
                    )
                )
                
            except Exception as e:
                errores += 1
                logger.error(f"Error enviando notificación para solicitud {solicitud.id}: {e}", exc_info=True)
                self.stdout.write(
                    self.style.ERROR(
                        f'  ❌ Error enviando notificación para solicitud #{solicitud.id}: {str(e)}'
                    )
                )
        
        # Resumen
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS(f'✅ Proceso completado'))
        self.stdout.write(f'📊 Notificaciones enviadas: {enviadas}')
        if errores > 0:
            self.stdout.write(self.style.ERROR(f'❌ Errores: {errores}'))
        self.stdout.write('='*60)
