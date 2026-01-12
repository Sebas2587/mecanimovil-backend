"""
Comando de Django para procesar solicitudes adjudicadas expiradas sin pago.

Este comando busca solicitudes adjudicadas donde la fecha_limite_pago ya pasó
y no se ha realizado el pago, cancelándolas automáticamente.

Uso:
    python manage.py procesar_solicitudes_expiradas
    python manage.py procesar_solicitudes_expiradas --dry-run  # Para ver qué se haría sin hacer cambios
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from mecanimovilapp.apps.ordenes.models import SolicitudServicioPublica, OfertaProveedor
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Procesa solicitudes adjudicadas expiradas sin pago y las cancela automáticamente'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Ejecuta el comando sin hacer cambios reales en la base de datos',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Ejecuta sin pedir confirmación',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options['force']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('🔍 MODO DRY RUN: No se harán cambios reales'))
        
        self.stdout.write('🔍 Buscando solicitudes adjudicadas expiradas sin pago...')
        
        ahora = timezone.now()
        
        # ✅ FIX: Buscar solicitudes adjudicadas O pendientes de pago donde fecha_limite_pago ya pasó
        # Cuando el cliente acepta la oferta, el estado cambia de 'adjudicada' a 'pendiente_pago',
        # por lo que debemos incluir ambos estados para cancelar correctamente las expiradas
        solicitudes_expiradas = SolicitudServicioPublica.objects.filter(
            estado__in=['adjudicada', 'pendiente_pago'],
            fecha_limite_pago__lt=ahora,
            oferta_seleccionada__isnull=False
        ).select_related(
            'cliente',
            'cliente__usuario',
            'oferta_seleccionada',
            'oferta_seleccionada__proveedor'
        )
        
        total_encontradas = solicitudes_expiradas.count()
        self.stdout.write(f'📊 Encontradas {total_encontradas} solicitudes expiradas sin pago')
        
        if total_encontradas == 0:
            self.stdout.write(self.style.SUCCESS('✅ No hay solicitudes expiradas que procesar'))
            return
        
        # Mostrar detalles
        self.stdout.write('\n📋 Detalle de solicitudes a procesar:')
        for solicitud in solicitudes_expiradas:
            oferta = solicitud.oferta_seleccionada
            proveedor_nombre = oferta.proveedor.username if oferta else 'Sin proveedor'
            cliente_nombre = solicitud.cliente.nombre if solicitud.cliente else 'Sin cliente'
            
            self.stdout.write(
                f'  • Solicitud #{solicitud.id} - '
                f'Cliente: {cliente_nombre} - '
                f'Proveedor: {proveedor_nombre} - '
                f'Fecha límite: {solicitud.fecha_limite_pago.strftime("%Y-%m-%d %H:%M") if solicitud.fecha_limite_pago else "N/A"}'
            )
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\n⚠️  DRY RUN: No se realizaron cambios'))
            return
        
        # Confirmar antes de continuar
        if not force:
            self.stdout.write(f'\n⚠️  Se van a cancelar {total_encontradas} solicitudes expiradas')
            self.stdout.write('⚠️  NOTA: Los créditos NO se devolverán automáticamente (prevenir gaming)')
            respuesta = input('¿Deseas continuar? (s/n): ')
            
            if respuesta.lower() != 's':
                self.stdout.write(self.style.WARNING('❌ Operación cancelada'))
                return
        
        # Procesar las solicitudes expiradas
        self.stdout.write('\n🔄 Procesando solicitudes expiradas...')
        
        procesadas = 0
        errores = 0
        channel_layer = get_channel_layer()
        
        for solicitud in solicitudes_expiradas:
            try:
                with transaction.atomic():
                    oferta = solicitud.oferta_seleccionada
                    
                    # Cambiar estado de solicitud a cancelada
                    solicitud.estado = 'cancelada'
                    solicitud.save(update_fields=['estado'])
                    
                    # Rechazar oferta seleccionada
                    if oferta:
                        oferta.estado = 'rechazada'
                        oferta.fecha_respuesta_cliente = ahora
                        oferta.save(update_fields=['estado', 'fecha_respuesta_cliente'])
                    
                    # ✅ Rechazar TODAS las ofertas pendientes de esta solicitud
                    OfertaProveedor.objects.filter(
                        solicitud=solicitud,
                        estado__in=['enviada', 'vista', 'en_chat', 'aceptada', 'pendiente_pago']
                    ).exclude(id=oferta.id if oferta else None).update(
                        estado='rechazada',
                        fecha_respuesta_cliente=ahora
                    )
                    
                    procesadas += 1
                    
                    # Notificar al cliente vía WebSocket
                    try:
                        if channel_layer and solicitud.cliente and solicitud.cliente.usuario:
                            async_to_sync(channel_layer.group_send)(
                                f"cliente_{solicitud.cliente.usuario.id}",
                                {
                                    'type': 'pago_expirado',
                                    'solicitud_id': str(solicitud.id),
                                    'oferta_id': str(oferta.id) if oferta else None,
                                    'mensaje': 'El plazo para pagar esta solicitud ha expirado. La solicitud ha sido cancelada automáticamente.',
                                    'fecha_limite_pago': solicitud.fecha_limite_pago.isoformat() if solicitud.fecha_limite_pago else None,
                                    'timestamp': ahora.isoformat()
                                }
                            )
                    except Exception as e:
                        logger.error(f"Error enviando notificación WebSocket al cliente: {e}", exc_info=True)
                    
                    # Notificar al proveedor vía WebSocket
                    try:
                        if channel_layer and oferta and oferta.proveedor:
                            async_to_sync(channel_layer.group_send)(
                                f"proveedor_{oferta.proveedor.id}",
                                {
                                    'type': 'pago_expirado',
                                    'oferta_id': str(oferta.id),
                                    'solicitud_id': str(solicitud.id),
                                    'mensaje': 'El cliente no pagó a tiempo. La solicitud ha sido cancelada automáticamente. Los créditos no se devuelven por expiración automática.',
                                    'fecha_limite_pago': solicitud.fecha_limite_pago.isoformat() if solicitud.fecha_limite_pago else None,
                                    'creditos_devueltos': False,
                                    'timestamp': ahora.isoformat()
                                }
                            )
                    except Exception as e:
                        logger.error(f"Error enviando notificación WebSocket al proveedor: {e}", exc_info=True)
                    
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'  ✅ Solicitud #{solicitud.id} cancelada - '
                            f'Cliente: {solicitud.cliente.nombre if solicitud.cliente else "N/A"} - '
                            f'Proveedor: {oferta.proveedor.username if oferta else "N/A"}'
                        )
                    )
                    
            except Exception as e:
                errores += 1
                logger.error(f"Error procesando solicitud {solicitud.id}: {e}", exc_info=True)
                self.stdout.write(
                    self.style.ERROR(
                        f'  ❌ Error procesando solicitud #{solicitud.id}: {str(e)}'
                    )
                )
        
        # Resumen
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS(f'✅ Proceso completado'))
        self.stdout.write(f'📊 Solicitudes procesadas: {procesadas}')
        if errores > 0:
            self.stdout.write(self.style.ERROR(f'❌ Errores: {errores}'))
        self.stdout.write('='*60)
        
        if procesadas > 0:
            self.stdout.write(
                self.style.WARNING(
                    '\n⚠️  NOTA: Los créditos NO se devolvieron automáticamente para prevenir gaming.'
                )
            )
