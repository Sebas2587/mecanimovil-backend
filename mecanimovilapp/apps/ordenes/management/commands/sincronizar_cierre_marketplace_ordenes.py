"""
Repara desincronización entre SolicitudServicio, OfertaProveedor y solicitud pública.

Casos:
  1. Orden `completado` pero oferta/solicitud siguen abiertas.
  2. Checklist `COMPLETADO` pero orden/oferta no cerradas (firmas registradas).

Uso en Render Shell:
    python manage.py sincronizar_cierre_marketplace_ordenes --dry-run
    python manage.py sincronizar_cierre_marketplace_ordenes
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from mecanimovilapp.apps.ordenes.models import SolicitudServicio
from mecanimovilapp.apps.ordenes.services.cierre_servicio_marketplace import (
    sincronizar_cierre_marketplace,
)


class Command(BaseCommand):
    help = 'Alinea oferta y solicitud pública con órdenes/checklists ya cerrados.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Listar IDs afectados sin escribir en la base de datos',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        ids_orden_completada = set(
            SolicitudServicio.objects.filter(
                estado='completado',
                oferta_proveedor__isnull=False,
            )
            .filter(
                oferta_proveedor__estado__in=['en_ejecucion', 'pagada', 'pagada_parcialmente']
            )
            .values_list('id', flat=True)
        )

        ids_checklist_completado = set()
        try:
            from mecanimovilapp.apps.checklists.models import ChecklistInstance

            ids_checklist_completado = set(
                ChecklistInstance.objects.filter(estado='COMPLETADO')
                .exclude(orden__estado='completado')
                .values_list('orden_id', flat=True)
            )
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f'No se pudo evaluar checklists: {exc}'))

        ids = sorted(ids_orden_completada | ids_checklist_completado)
        self.stdout.write(self.style.NOTICE(f'Órdenes candidatas: {len(ids)}'))
        for oid in ids:
            self.stdout.write(f'  - orden_id={oid}')

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry-run: sin cambios.'))
            return

        arregladas = 0
        for oid in ids:
            if oid in ids_checklist_completado and oid not in ids_orden_completada:
                with transaction.atomic():
                    orden = SolicitudServicio.objects.select_for_update().get(pk=oid)
                    if orden.estado != 'completado':
                        orden.estado = 'completado'
                        orden.save(update_fields=['estado'])
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'  orden_id={oid}: estado → completado (checklist COMPLETADO)'
                            )
                        )

            hubo, _ = sincronizar_cierre_marketplace(oid)
            if hubo:
                arregladas += 1

        self.stdout.write(self.style.SUCCESS(f'Filas actualizadas (hubo cambio): {arregladas}'))
