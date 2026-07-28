"""Re-sincroniza chunks de catálogo (repuestos/garantía en texto)."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from mecanimovilapp.apps.agente_ia.services.rag import sincronizar_chunk_oferta_servicio
from mecanimovilapp.apps.servicios.models import OfertaServicio


class Command(BaseCommand):
    help = 'Re-sincroniza chunks RAG de OfertaServicio activas (p. ej. tras cambio de texto de catálogo).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--taller-id',
            type=int,
            default=None,
            help='Limitar a un taller específico.',
        )
        parser.add_argument(
            '--incluir-no-disponibles',
            action='store_true',
            default=False,
            help='Incluir ofertas con disponible=False.',
        )

    def handle(self, *args, **options):
        taller_id = options.get('taller_id')
        qs = OfertaServicio.objects.filter(taller_id__isnull=False)
        if taller_id:
            qs = qs.filter(taller_id=taller_id)
        if not options.get('incluir_no_disponibles'):
            qs = qs.filter(disponible=True)

        ids = list(qs.values_list('id', flat=True))
        for oferta_id in ids:
            sincronizar_chunk_oferta_servicio(oferta_id)

        self.stdout.write(
            self.style.SUCCESS(f'Re-sincronizadas {len(ids)} ofertas de servicio.')
        )
