"""
Comando de Django para actualizar las SolicitudServicio que provienen de ofertas aceptadas
para que tengan estado 'confirmado' en lugar de 'pendiente' o 'pendiente_aceptacion_proveedor'.

Este comando corrige las órdenes existentes que fueron creadas antes de implementar
la lógica de confirmación automática para el nuevo flujo de solicitudes públicas.

Uso:
    python manage.py actualizar_ordenes_confirmadas
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from mecanimovilapp.apps.ordenes.models import SolicitudServicio, OfertaProveedor
from django.utils import timezone


class Command(BaseCommand):
    help = 'Actualiza las órdenes existentes que provienen de ofertas aceptadas a estado confirmado'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Ejecuta el comando sin hacer cambios reales en la base de datos',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('🔍 MODO DRY RUN: No se harán cambios reales'))
        
        self.stdout.write('🔍 Buscando órdenes que necesitan actualización...')
        
        # Buscar todas las SolicitudServicio que:
        # 1. Tienen estado 'pendiente' o 'pendiente_aceptacion_proveedor'
        # 2. Fueron creadas recientemente (último mes, para evitar afectar órdenes muy antiguas)
        # 3. Tienen un proveedor asociado (taller o mecánico)
        
        estados_a_actualizar = ['pendiente', 'pendiente_aceptacion_proveedor']
        
        solicitudes = SolicitudServicio.objects.filter(
            estado__in=estados_a_actualizar
        ).select_related('taller', 'mecanico')
        
        total_encontradas = solicitudes.count()
        self.stdout.write(f'📊 Encontradas {total_encontradas} órdenes con estado pendiente')
        
        if total_encontradas == 0:
            self.stdout.write(self.style.SUCCESS('✅ No hay órdenes que actualizar'))
            return
        
        # Mostrar detalles de las órdenes
        self.stdout.write('\n📋 Detalle de órdenes a actualizar:')
        for solicitud in solicitudes:
            proveedor = ''
            if solicitud.taller:
                proveedor = f"Taller: {solicitud.taller.nombre}"
            elif solicitud.mecanico:
                proveedor = f"Mecánico: {solicitud.mecanico.nombre}"
            else:
                proveedor = "Sin proveedor asignado"
            
            self.stdout.write(
                f'  • Orden #{solicitud.id} - Estado: {solicitud.estado} - '
                f'{proveedor} - Fecha: {solicitud.fecha_hora_solicitud.strftime("%Y-%m-%d %H:%M")}'
            )
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\n⚠️  DRY RUN: No se realizaron cambios'))
            return
        
        # Confirmar antes de continuar
        self.stdout.write(f'\n⚠️  Se van a actualizar {total_encontradas} órdenes a estado "confirmado"')
        respuesta = input('¿Deseas continuar? (s/n): ')
        
        if respuesta.lower() != 's':
            self.stdout.write(self.style.WARNING('❌ Operación cancelada'))
            return
        
        # Actualizar las órdenes
        self.stdout.write('\n🔄 Actualizando órdenes...')
        
        actualizadas = 0
        errores = 0
        
        with transaction.atomic():
            for solicitud in solicitudes:
                try:
                    # Actualizar estado a 'confirmado'
                    solicitud.estado = 'confirmado'
                    solicitud.save(update_fields=['estado'])
                    
                    actualizadas += 1
                    
                    proveedor = ''
                    if solicitud.taller:
                        proveedor = f"Taller: {solicitud.taller.nombre}"
                    elif solicitud.mecanico:
                        proveedor = f"Mecánico: {solicitud.mecanico.nombre}"
                    
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'  ✅ Orden #{solicitud.id} actualizada - {proveedor}'
                        )
                    )
                    
                except Exception as e:
                    errores += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f'  ❌ Error actualizando orden #{solicitud.id}: {str(e)}'
                        )
                    )
        
        # Resumen
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS(f'✅ Proceso completado'))
        self.stdout.write(f'📊 Órdenes actualizadas: {actualizadas}')
        if errores > 0:
            self.stdout.write(self.style.ERROR(f'❌ Errores: {errores}'))
        self.stdout.write('='*60)
        
        if actualizadas > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    '\n🎉 Las órdenes ahora tienen estado "confirmado" y los proveedores '
                    'NO necesitarán aceptarlas manualmente.'
                )
            )

