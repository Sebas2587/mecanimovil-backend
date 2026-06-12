"""
Reabre un checklist para que el proveedor pueda completarlo de nuevo.

Uso:
    python manage.py reabrir_checklist --orden-id 15
    python manage.py reabrir_checklist --orden-id 15 --dry-run
    python manage.py reabrir_checklist --orden-id 15 --reset-todas-respuestas
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from mecanimovilapp.apps.checklists.reopen_utils import (
    ESTADOS_CHECKLIST_REABRIR,
    es_texto_foto_evidencia,
    puede_reabrir_checklist,
    reabrir_checklist_instance,
)


class Command(BaseCommand):
    help = 'Reabre un checklist para que el proveedor lo vuelva a llenar'

    def add_arguments(self, parser):
        parser.add_argument('--orden-id', required=True, type=int)
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument(
            '--reset-todas-respuestas',
            action='store_true',
            help='Marcar TODAS las respuestas como incompletas (rellenado completo)',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Forzar reapertura aunque el estado no sea el habitual',
        )

    def handle(self, *args, **options):
        from mecanimovilapp.apps.checklists.models import ChecklistInstance, ChecklistPhoto

        orden_id = options['orden_id']
        dry_run = options['dry_run']
        reset_todas = options['reset_todas_respuestas']
        forzar = options['force']

        try:
            instance = ChecklistInstance.objects.select_related('orden').get(orden_id=orden_id)
        except ChecklistInstance.DoesNotExist:
            raise CommandError(f'No existe ChecklistInstance para orden_id={orden_id}')

        orden = instance.orden

        self.stdout.write(self.style.NOTICE('\n📋 Estado actual:'))
        self.stdout.write(f'  ChecklistInstance #{instance.id}: {instance.estado}')
        self.stdout.write(f'  SolicitudServicio #{orden.id}: {orden.estado}')
        self.stdout.write(f'  Progreso: {instance.progreso_porcentaje}%')
        self.stdout.write(f'  Firma técnico: {"✓" if instance.firma_tecnico else "—"}')
        self.stdout.write(f'  Firma cliente:  {"✓" if instance.firma_cliente else "—"}')

        ok, motivo = puede_reabrir_checklist(instance, orden)
        if not ok and not forzar:
            raise CommandError(
                f'{motivo} Estados válidos: {", ".join(ESTADOS_CHECKLIST_REABRIR)}. '
                f'Use --force si necesita forzar.'
            )

        if instance.estado == 'PENDIENTE' and orden.estado == 'pendiente_firma_cliente':
            self.stdout.write(self.style.WARNING(
                '\n⚠️  Desincronización detectada: checklist PENDIENTE pero orden '
                'pendiente_firma_cliente. Se alineará a checklist_en_progreso.'
            ))

        respuestas = list(instance.respuestas.select_related('item_template__catalog_item').all())
        fotos_count = ChecklistPhoto.objects.filter(response__checklist_instance=instance).count()
        respuestas_foto = [
            r for r in respuestas
            if r.item_template.catalog_item.tipo_pregunta == 'PHOTO'
            or es_texto_foto_evidencia(r.respuesta_texto)
        ]

        self.stdout.write(self.style.NOTICE('\n🔍 Análisis:'))
        self.stdout.write(f'  Respuestas totales:   {len(respuestas)}')
        self.stdout.write(f'  Respuestas de fotos:  {len(respuestas_foto)}')
        self.stdout.write(f'  Fotos en BD:          {fotos_count}')

        if dry_run:
            self.stdout.write(self.style.WARNING('\n[DRY-RUN] Se aplicaría:'))
            self.stdout.write(f'  ChecklistInstance #{instance.id}.estado → EN_PROGRESO')
            self.stdout.write(f'  SolicitudServicio #{orden.id}.estado → checklist_en_progreso')
            self.stdout.write(f'  Eliminar {fotos_count} foto(s)')
            n = len(respuestas) if reset_todas else len(respuestas_foto)
            self.stdout.write(f'  Resetear {n} respuesta(s)')
            return

        with transaction.atomic():
            result = reabrir_checklist_instance(
                instance,
                reset_todas_respuestas=reset_todas,
                forzar=forzar,
            )

        self.stdout.write(self.style.SUCCESS(
            f'\n✅ Checklist #{instance.id} reabierto:\n'
            f'   Estado → EN_PROGRESO | Progreso → {result["progreso"]}% '
            f'({result["completadas"]}/{result["total_respuestas"]})\n'
            f'   Orden #{orden.id}.estado → {result["orden_estado_nuevo"]}\n'
            f'   Fotos eliminadas: {result["fotos_eliminadas"]}\n'
            f'   Respuestas reseteadas: {result["respuestas_reseteadas"]}'
        ))
        self.stdout.write(self.style.NOTICE(
            '\n👉 El proveedor puede abrir la app y volver a completar el checklist.'
        ))
