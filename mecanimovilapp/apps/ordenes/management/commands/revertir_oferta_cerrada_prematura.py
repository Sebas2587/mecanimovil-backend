"""
Revierte una oferta cerrada prematuramente (p. ej. terminar-servicio sin checklist)
al estado en_ejecucion para que el proveedor complete el checklist.

Uso:
    python manage.py revertir_oferta_cerrada_prematura --oferta-id <uuid> --dry-run
    python manage.py revertir_oferta_cerrada_prematura --oferta-id <uuid>
"""
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.db import transaction

from mecanimovilapp.apps.ordenes.models import OfertaProveedor, SolicitudServicio


class Command(BaseCommand):
    help = 'Revierte oferta/solicitud/orden a en_ejecucion y asegura checklist pendiente'

    def add_arguments(self, parser):
        parser.add_argument('--oferta-id', required=True, help='UUID de la OfertaProveedor')
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Mostrar cambios sin aplicarlos',
        )

    def handle(self, *args, **options):
        oferta_id = options['oferta_id']
        dry_run = options['dry_run']

        try:
            oferta = OfertaProveedor.objects.select_related('solicitud').get(pk=oferta_id)
        except OfertaProveedor.DoesNotExist:
            self.stderr.write(self.style.ERROR(f'Oferta no encontrada: {oferta_id}'))
            return

        solicitud = oferta.solicitud
        orden = SolicitudServicio.objects.filter(oferta_proveedor=oferta).first()

        self.stdout.write(self.style.NOTICE('\nEstado actual:'))
        self.stdout.write(f'  Oferta {oferta.id}: {oferta.estado}')
        self.stdout.write(f'  Solicitud pública {solicitud.id}: {solicitud.estado}')
        if orden:
            self.stdout.write(f'  Orden {orden.id}: {orden.estado}')
        else:
            self.stdout.write('  Orden: (no existe)')

        if oferta.estado not in ('completada', 'en_ejecucion'):
            self.stdout.write(
                self.style.WARNING(
                    f'Oferta en "{oferta.estado}" — no requiere corrección.'
                )
            )
            return

        if oferta.estado == 'completada':
            self.stdout.write(
                self.style.WARNING(
                    'Oferta ya está completada. Este comando no revierte servicios cerrados.'
                )
            )
            return

        if not orden:
            self.stderr.write(self.style.ERROR('No hay SolicitudServicio asociada a esta oferta.'))
            return

        ya_en_flujo = (
            oferta.estado == 'en_ejecucion'
            and solicitud.estado == 'en_ejecucion'
            and orden.estado in ('confirmado', 'checklist_en_progreso', 'pendiente_firma_cliente')
        )

        detalles = list(oferta.detalles_servicios.select_related('servicio').all())
        if not detalles:
            self.stderr.write(self.style.ERROR('La oferta no tiene detalles de servicios.'))
            return

        servicios = [d.servicio for d in detalles]
        self.stdout.write('\nServicios en la oferta:')
        for s in servicios:
            self.stdout.write(f'  - {s.nombre} (id={s.id})')

        if dry_run:
            self.stdout.write(self.style.WARNING('\n[DRY-RUN] Se aplicaría:'))
            self.stdout.write('  oferta.estado → en_ejecucion')
            self.stdout.write('  solicitud.estado → en_ejecucion')
            self.stdout.write('  orden.estado → confirmado')
            self.stdout.write('  populate_checklists_por_servicio (si falta template)')
            self.stdout.write('  ChecklistInstance PENDIENTE (si no existe)')
            return

        with transaction.atomic():
            if not ya_en_flujo:
                oferta.estado = 'en_ejecucion'
                oferta.save(update_fields=['estado'])

                solicitud.estado = 'en_ejecucion'
                solicitud.save(update_fields=['estado'])

                orden.estado = 'confirmado'
                orden.save(update_fields=['estado'])

                self.stdout.write(self.style.SUCCESS('\n✅ Estados revertidos a en_ejecucion / confirmado'))
            else:
                self.stdout.write(self.style.SUCCESS('\nℹ️ Estados ya en flujo de ejecución; verificando checklist…'))

            # Asegurar templates de checklist para los servicios de la oferta
            self.stdout.write('\n📋 Verificando templates de checklist...')
            call_command('populate_checklists_por_servicio')

            from mecanimovilapp.apps.checklists.models import ChecklistTemplate, ChecklistInstance

            checklist_creado = False
            for servicio in servicios:
                template = ChecklistTemplate.objects.filter(servicio=servicio, activo=True).first()
                if not template:
                    self.stdout.write(
                        self.style.WARNING(f'  ⚠️ Sin template activo para: {servicio.nombre}')
                    )
                    continue

                existing = ChecklistInstance.objects.filter(orden=orden).first()
                if existing:
                    if existing.estado in ('COMPLETADO', 'PENDIENTE_FIRMA_CLIENTE'):
                        existing.estado = 'PENDIENTE'
                        existing.firma_tecnico = None
                        existing.firma_cliente = None
                        existing.fecha_finalizacion = None
                        existing.progreso_porcentaje = 0
                        existing.save(
                            update_fields=[
                                'estado',
                                'firma_tecnico',
                                'firma_cliente',
                                'fecha_finalizacion',
                                'progreso_porcentaje',
                            ]
                        )
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'  ✅ Checklist {existing.id} reseteado a PENDIENTE '
                                f'(template: {template.nombre})'
                            )
                        )
                    else:
                        self.stdout.write(
                            f'  ℹ️ Checklist existente {existing.id} en estado {existing.estado}'
                        )
                    checklist_creado = True
                    break

                instance = ChecklistInstance.objects.create(
                    orden=orden,
                    checklist_template=template,
                    estado='PENDIENTE',
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  ✅ ChecklistInstance {instance.id} creado '
                        f'(template: {template.nombre})'
                    )
                )
                checklist_creado = True
                break

            if not checklist_creado:
                self.stdout.write(
                    self.style.WARNING(
                        '\n⚠️ No se creó checklist. El proveedor podrá terminar manualmente '
                        'si no hay template configurado.'
                    )
                )

        self.stdout.write(self.style.SUCCESS('\n🎉 Corrección aplicada. El proveedor puede completar el checklist.\n'))
