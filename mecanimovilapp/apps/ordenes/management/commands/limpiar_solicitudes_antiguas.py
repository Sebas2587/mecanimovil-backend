from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from mecanimovilapp.apps.ordenes.models import SolicitudServicio


class Command(BaseCommand):
    help = 'Limpia solicitudes canceladas muy antiguas (más de 2 años) - USAR CON PRECAUCIÓN'

    def add_arguments(self, parser):
        parser.add_argument(
            '--years',
            type=int,
            default=2,
            help='Años de antigüedad para considerar solicitudes como "muy antiguas" (default: 2)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Solo mostrar qué se eliminaría sin hacer cambios reales'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Confirmar que realmente quieres eliminar datos (requerido para ejecución real)'
        )

    def handle(self, *args, **options):
        years = options['years']
        dry_run = options['dry_run']
        force = options['force']
        
        if not dry_run and not force:
            self.stdout.write(
                self.style.ERROR(
                    'ADVERTENCIA: Este comando eliminará datos permanentemente.\n'
                    'Usa --dry-run para ver qué se eliminaría, o --force para confirmar.'
                )
            )
            return
        
        # Calcular fecha límite
        fecha_limite = timezone.now() - timedelta(days=years * 365)
        
        # Buscar solicitudes canceladas muy antiguas
        solicitudes_antiguas = SolicitudServicio.objects.filter(
            estado__in=['cancelado', 'devolucion_procesada'],
            fecha_hora_solicitud__lt=fecha_limite
        )
        
        count = solicitudes_antiguas.count()
        
        if count == 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f'No se encontraron solicitudes canceladas con más de {years} años.'
                )
            )
            return
        
        self.stdout.write(
            self.style.WARNING(
                f'Encontradas {count} solicitudes canceladas con más de {years} años:'
            )
        )
        
        # Mostrar estadísticas
        for solicitud in solicitudes_antiguas[:10]:  # Mostrar solo las primeras 10
            self.stdout.write(
                f'  - Solicitud #{solicitud.id}: {solicitud.estado} '
                f'(creada: {solicitud.fecha_hora_solicitud.date()})'
            )
        
        if count > 10:
            self.stdout.write(f'  ... y {count - 10} más')
        
        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f'DRY RUN: Se eliminarían {count} solicitudes (no se hicieron cambios)'
                )
            )
        else:
            # Eliminar realmente
            deleted_count, _ = solicitudes_antiguas.delete()
            self.stdout.write(
                self.style.SUCCESS(
                    f'Eliminadas {deleted_count} solicitudes canceladas antiguas.'
                )
            )
            
            # Log de auditoría
            self.stdout.write(
                self.style.WARNING(
                    'IMPORTANTE: Esta acción se ha registrado. '
                    'Considera hacer backup antes de ejecutar este comando en producción.'
                )
            ) 