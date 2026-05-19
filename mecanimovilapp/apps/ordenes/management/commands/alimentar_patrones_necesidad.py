"""
Bootstrap de PatronAprendizajeNecesidad desde solicitudes ya confirmadas/creadas.
"""
from django.core.management.base import BaseCommand
from django.db.models import Count

from mecanimovilapp.apps.ordenes.models import SolicitudServicioPublica
from mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_aprendizaje import (
    contar_patrones_activos,
    registrar_aprendizaje_desde_solicitud,
)


class Command(BaseCommand):
    help = 'Alimenta patrones semánticos desde descripciones de solicitudes existentes'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=500,
            help='Máximo de solicitudes a procesar (más recientes primero)',
        )

    def handle(self, *args, **options):
        limit = max(1, int(options['limit']))
        antes = contar_patrones_activos()
        total_registros = 0
        procesadas = 0

        qs = (
            SolicitudServicioPublica.objects.exclude(descripcion_problema='')
            .annotate(_n_servicios=Count('servicios_solicitados'))
            .filter(_n_servicios__gt=0)
            .order_by('-fecha_publicacion')[:limit]
        )

        for solicitud in qs.prefetch_related('servicios_solicitados', 'vehiculo'):
            componentes = None
            if isinstance(solicitud.metadata_ia_entrada, dict):
                componentes = solicitud.metadata_ia_entrada.get('componentes_salud')
            n = registrar_aprendizaje_desde_solicitud(
                solicitud,
                componentes_salud=componentes,
            )
            total_registros += n
            procesadas += 1

        despues = contar_patrones_activos()
        self.stdout.write(
            self.style.SUCCESS(
                f'Procesadas {procesadas} solicitudes; '
                f'patrones {antes} → {despues} (+{despues - antes} filas, {total_registros} upserts)'
            )
        )
