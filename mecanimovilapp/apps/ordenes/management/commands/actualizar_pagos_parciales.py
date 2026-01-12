"""
Comando de Django para actualizar ofertas con pago parcial que tienen estado 'pagada'
a estado 'pagada_parcialmente'.

Uso:
    python manage.py actualizar_pagos_parciales
    python manage.py actualizar_pagos_parciales --dry-run  # Para ver qué se haría sin hacer cambios
"""
from django.core.management.base import BaseCommand
from mecanimovilapp.apps.ordenes.models import OfertaProveedor


class Command(BaseCommand):
    help = 'Actualiza ofertas con pago parcial de estado "pagada" a "pagada_parcialmente"'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Muestra qué se haría sin hacer cambios reales',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        # Buscar ofertas que tienen:
        # - estado = 'pagada'
        # - estado_pago_repuestos = 'pagado'
        # - estado_pago_servicio = 'pendiente'
        ofertas_a_actualizar = OfertaProveedor.objects.filter(
            estado='pagada',
            estado_pago_repuestos='pagado',
            estado_pago_servicio='pendiente'
        )
        
        total_encontradas = ofertas_a_actualizar.count()
        
        if total_encontradas == 0:
            self.stdout.write(self.style.SUCCESS('\n✅ No hay ofertas que actualizar.'))
            return
        
        if dry_run:
            self.stdout.write(self.style.WARNING(f'\n🔍 MODO DRY-RUN: Se actualizarían {total_encontradas} ofertas'))
            self.stdout.write('\nOfertas que se actualizarían:')
            for oferta in ofertas_a_actualizar[:10]:
                self.stdout.write(f'  - {oferta.id}: {oferta.nombre_proveedor} (Solicitud: {oferta.solicitud.id})')
            if total_encontradas > 10:
                self.stdout.write(f'  ... y {total_encontradas - 10} más')
        else:
            self.stdout.write(f'\n⚠️  Se van a actualizar {total_encontradas} ofertas a estado "pagada_parcialmente"')
            
            actualizadas = 0
            for oferta in ofertas_a_actualizar:
                oferta.estado = 'pagada_parcialmente'
                oferta.save(update_fields=['estado'])
                actualizadas += 1
                self.stdout.write(f'  ✅ {oferta.id}: {oferta.nombre_proveedor}')
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n🎉 Se actualizaron {actualizadas} ofertas a estado "pagada_parcialmente".'
                )
            )

