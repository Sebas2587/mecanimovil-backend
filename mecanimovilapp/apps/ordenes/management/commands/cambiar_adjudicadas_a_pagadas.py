"""
Comando de Django para cambiar las solicitudes públicas adjudicadas a estado 'pagada'.

Este comando actualiza las solicitudes públicas que están en estado 'adjudicada' 
a estado 'pagada', junto con sus ofertas asociadas.

Uso:
    python manage.py cambiar_adjudicadas_a_pagadas
    python manage.py cambiar_adjudicadas_a_pagadas --dry-run  # Para ver qué se haría sin hacer cambios
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from mecanimovilapp.apps.ordenes.models import SolicitudServicioPublica, OfertaProveedor
from django.utils import timezone


class Command(BaseCommand):
    help = 'Cambia las solicitudes públicas adjudicadas a estado pagada'

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
        
        self.stdout.write('🔍 Buscando solicitudes adjudicadas que necesitan actualización...')
        
        # Buscar todas las SolicitudServicioPublica que:
        # 1. Tienen estado 'adjudicada'
        # 2. Tienen una oferta seleccionada
        solicitudes = SolicitudServicioPublica.objects.filter(
            estado='adjudicada',
            oferta_seleccionada__isnull=False
        ).select_related('cliente', 'vehiculo', 'oferta_seleccionada')
        
        total_encontradas = solicitudes.count()
        self.stdout.write(f'📊 Encontradas {total_encontradas} solicitudes adjudicadas')
        
        if total_encontradas == 0:
            self.stdout.write(self.style.SUCCESS('✅ No hay solicitudes adjudicadas que actualizar'))
            return
        
        # Mostrar detalles de las solicitudes
        self.stdout.write('\n📋 Detalle de solicitudes a actualizar:')
        for solicitud in solicitudes:
            oferta = solicitud.oferta_seleccionada
            proveedor_nombre = oferta.nombre_proveedor if oferta else 'Sin proveedor'
            monto = oferta.precio_total_ofrecido if oferta else 0
            
            self.stdout.write(
                f'  • Solicitud #{solicitud.id} - '
                f'Proveedor: {proveedor_nombre} - '
                f'Monto: ${int(monto):,} - '
                f'Fecha: {solicitud.fecha_creacion.strftime("%Y-%m-%d %H:%M")}'
            )
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\n⚠️  DRY RUN: No se realizaron cambios'))
            return
        
        # Confirmar antes de continuar
        if not force:
            self.stdout.write(f'\n⚠️  Se van a actualizar {total_encontradas} solicitudes a estado "pagada"')
            self.stdout.write('⚠️  También se actualizarán las ofertas asociadas a estado "pagada"')
            respuesta = input('¿Deseas continuar? (s/n): ')
            
            if respuesta.lower() != 's':
                self.stdout.write(self.style.WARNING('❌ Operación cancelada'))
                return
        
        # Actualizar las solicitudes y ofertas
        self.stdout.write('\n🔄 Actualizando solicitudes y ofertas...')
        
        actualizadas = 0
        ofertas_actualizadas = 0
        errores = 0
        
        with transaction.atomic():
            for solicitud in solicitudes:
                try:
                    # Actualizar estado de la solicitud a 'pagada'
                    solicitud.estado = 'pagada'
                    solicitud.save(update_fields=['estado'])
                    
                    # Actualizar estado de la oferta seleccionada a 'pagada'
                    if solicitud.oferta_seleccionada:
                        oferta = solicitud.oferta_seleccionada
                        oferta.estado = 'pagada'
                        oferta.save(update_fields=['estado'])
                        ofertas_actualizadas += 1
                    
                    actualizadas += 1
                    
                    proveedor_nombre = oferta.nombre_proveedor if oferta else 'Sin proveedor'
                    
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'  ✅ Solicitud #{solicitud.id} actualizada - Proveedor: {proveedor_nombre}'
                        )
                    )
                    
                except Exception as e:
                    errores += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f'  ❌ Error actualizando solicitud #{solicitud.id}: {str(e)}'
                        )
                    )
        
        # Resumen
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS(f'✅ Proceso completado'))
        self.stdout.write(f'📊 Solicitudes actualizadas: {actualizadas}')
        self.stdout.write(f'📊 Ofertas actualizadas: {ofertas_actualizadas}')
        if errores > 0:
            self.stdout.write(self.style.ERROR(f'❌ Errores: {errores}'))
        self.stdout.write('='*60)
        
        if actualizadas > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    '\n🎉 Las solicitudes ahora tienen estado "pagada" y están listas para iniciar el servicio.'
                )
            )

