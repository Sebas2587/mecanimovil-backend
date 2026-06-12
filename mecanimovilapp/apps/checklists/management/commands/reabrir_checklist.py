"""
Reabre un checklist finalizado (COMPLETADO o PENDIENTE_FIRMA_CLIENTE) para que el
proveedor pueda completarlo de nuevo —útil cuando las fotos de evidencia no se
subieron correctamente al primer intento.

Operaciones:
  - ChecklistInstance.estado          → EN_PROGRESO
  - ChecklistInstance.firma_tecnico   → None
  - ChecklistInstance.firma_cliente   → None
  - ChecklistInstance.fecha_finalizacion → None
  - ChecklistInstance.progreso_porcentaje → recalculado desde respuestas existentes
  - SolicitudServicio.estado          → checklist_en_progreso
  - ChecklistItemResponse de ítems PHOTO: completado=False, respuesta_texto=''
  - ChecklistPhoto de esa instancia: eliminadas (para re-subir limpias)

Uso:
    python manage.py reabrir_checklist --orden-id <id> [--dry-run]
    python manage.py reabrir_checklist --orden-id 15
    python manage.py reabrir_checklist --orden-id 15 --dry-run
"""
import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

logger = logging.getLogger(__name__)

FOTO_TEXT_PATTERNS = ['foto(s) de evidencia', 'fotos de evidencia', 'foto de evidencia']


def _es_texto_foto(texto):
    if not texto:
        return False
    t = str(texto).lower().strip()
    return any(p in t for p in FOTO_TEXT_PATTERNS) and t[:5].strip().isdigit() or (
        t.split()[0].isdigit() if t.split() else False
    )


class Command(BaseCommand):
    help = 'Reabre un checklist completado/pendiente-firma para que el proveedor lo vuelva a llenar'

    def add_arguments(self, parser):
        parser.add_argument(
            '--orden-id',
            required=True,
            type=int,
            help='ID de la SolicitudServicio (orden) cuyo checklist se quiere reabrir',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Mostrar qué cambios se harían sin aplicarlos',
        )
        parser.add_argument(
            '--reset-todas-respuestas',
            action='store_true',
            help='Además de las fotos, marcar TODAS las respuestas como incompletas (rellenado completo)',
        )

    def handle(self, *args, **options):
        from mecanimovilapp.apps.checklists.models import ChecklistInstance, ChecklistPhoto

        orden_id = options['orden_id']
        dry_run = options['dry_run']
        reset_todas = options['reset_todas_respuestas']

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

        if instance.estado not in ('COMPLETADO', 'PENDIENTE_FIRMA_CLIENTE', 'EN_PROGRESO', 'PAUSADO'):
            raise CommandError(
                f'Estado "{instance.estado}" no es reabriblemente (debe ser COMPLETADO o PENDIENTE_FIRMA_CLIENTE).'
            )

        # Contar fotos y respuestas afectadas
        respuestas = list(instance.respuestas.all())
        fotos = ChecklistPhoto.objects.filter(response__checklist_instance=instance)
        fotos_count = fotos.count()

        respuestas_foto = [
            r for r in respuestas
            if r.item_template.catalog_item.tipo_pregunta == 'PHOTO'
            or _es_texto_foto(r.respuesta_texto)
        ]
        respuestas_todas = respuestas

        self.stdout.write(self.style.NOTICE(f'\n🔍 Análisis:'))
        self.stdout.write(f'  Respuestas totales:   {len(respuestas_todas)}')
        self.stdout.write(f'  Respuestas de fotos:  {len(respuestas_foto)}')
        self.stdout.write(f'  Fotos en BD:          {fotos_count}')

        if dry_run:
            self.stdout.write(self.style.WARNING('\n[DRY-RUN] Se aplicaría:'))
            self.stdout.write(f'  ChecklistInstance #{instance.id}.estado → EN_PROGRESO')
            self.stdout.write(f'  ChecklistInstance #{instance.id}.firma_tecnico → None')
            self.stdout.write(f'  ChecklistInstance #{instance.id}.firma_cliente  → None')
            self.stdout.write(f'  ChecklistInstance #{instance.id}.fecha_finalizacion → None')
            self.stdout.write(f'  SolicitudServicio #{orden.id}.estado → checklist_en_progreso')
            self.stdout.write(f'  Eliminar {fotos_count} foto(s) de BD')
            if reset_todas:
                self.stdout.write(f'  Resetear {len(respuestas_todas)} respuestas (todas)')
            else:
                self.stdout.write(f'  Resetear {len(respuestas_foto)} respuestas de fotos')
            self.stdout.write(self.style.WARNING('\n[DRY-RUN] Sin cambios aplicados.'))
            return

        with transaction.atomic():
            # 1. Resetear la instancia de checklist
            instance.estado = 'EN_PROGRESO'
            instance.firma_tecnico = None
            instance.firma_cliente = None
            instance.fecha_finalizacion = None

            # 2. Resetear respuestas
            if reset_todas:
                targets = respuestas_todas
            else:
                targets = respuestas_foto

            for r in targets:
                r.completado = False
                if _es_texto_foto(r.respuesta_texto):
                    r.respuesta_texto = ''
                r.save(update_fields=['completado', 'respuesta_texto'])

            # 3. Recalcular progreso
            total = len(respuestas_todas)
            completadas = sum(1 for r in respuestas_todas if r.completado)
            progreso = int((completadas / total) * 100) if total > 0 else 0
            instance.progreso_porcentaje = progreso

            instance.save(update_fields=[
                'estado', 'firma_tecnico', 'firma_cliente',
                'fecha_finalizacion', 'progreso_porcentaje',
            ])

            # 4. Eliminar fotos existentes (para re-subir limpias)
            eliminadas, _ = fotos.delete()

            # 5. Revertir estado de la orden
            orden.estado = 'checklist_en_progreso'
            orden.save(update_fields=['estado'])

        self.stdout.write(self.style.SUCCESS(
            f'\n✅ Checklist #{instance.id} reabierto correctamente:\n'
            f'   Estado → EN_PROGRESO | Progreso → {progreso}% ({completadas}/{total})\n'
            f'   Orden #{orden.id}.estado → checklist_en_progreso\n'
            f'   Fotos eliminadas: {eliminadas}\n'
            f'   Respuestas reseteadas: {len(targets)}'
        ))
        self.stdout.write(self.style.NOTICE(
            '\n👉 El proveedor puede ahora abrir la app, ir al checklist y volver a subir las fotos.'
        ))
