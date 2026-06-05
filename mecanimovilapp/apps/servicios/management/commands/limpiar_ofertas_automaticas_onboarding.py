"""
Elimina ofertas creadas por crear_ofertas_automaticas durante el onboarding
cuando el proveedor ya tenía un catálogo explícito (crear_catalogo_inicial).

Uso:
  python manage.py limpiar_ofertas_automaticas_onboarding --dry-run
  python manage.py limpiar_ofertas_automaticas_onboarding --force
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from mecanimovilapp.apps.servicios.models import OfertaServicio

AUTO_MARKER = "Oferta creada automáticamente durante el onboarding"


class Command(BaseCommand):
    help = (
        "Elimina ofertas automáticas duplicadas del onboarding cuando el proveedor "
        "ya tiene catálogo explícito. Usar --dry-run primero."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Solo listar ofertas que se eliminarían, sin borrar.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Confirmar eliminación real (requerido si no es dry-run).",
        )

    def _proveedor_label(self, oferta):
        if oferta.mecanico_id:
            return f"mecánico #{oferta.mecanico_id} ({oferta.mecanico.nombre})"
        if oferta.taller_id:
            return f"taller #{oferta.taller_id} ({oferta.taller.nombre})"
        return "sin proveedor"

    def _tiene_catalogo_explicito(self, oferta):
        """True si el proveedor tiene al menos una oferta que no es automática."""
        if oferta.mecanico_id:
            return OfertaServicio.objects.filter(mecanico_id=oferta.mecanico_id).exclude(
                Q(detalles_adicionales__icontains=AUTO_MARKER)
            ).exists()
        if oferta.taller_id:
            return OfertaServicio.objects.filter(taller_id=oferta.taller_id).exclude(
                Q(detalles_adicionales__icontains=AUTO_MARKER)
            ).exists()
        return False

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]

        if not dry_run and not force:
            self.stdout.write(
                self.style.ERROR(
                    "Usa --dry-run para revisar o --force para eliminar ofertas duplicadas."
                )
            )
            return

        candidatas = (
            OfertaServicio.objects.filter(detalles_adicionales__icontains=AUTO_MARKER)
            .select_related("servicio", "mecanico", "taller", "marca_vehiculo_seleccionada")
            .order_by("mecanico_id", "taller_id", "id")
        )

        a_eliminar = []
        omitidas = 0

        for oferta in candidatas:
            if self._tiene_catalogo_explicito(oferta):
                a_eliminar.append(oferta)
            else:
                omitidas += 1

        if not a_eliminar:
            self.stdout.write(
                self.style.SUCCESS(
                    f"No hay ofertas automáticas duplicadas para eliminar "
                    f"({omitidas} omitidas: solo catálogo legacy automático)."
                )
            )
            return

        self.stdout.write(
            self.style.WARNING(
                f"Ofertas automáticas duplicadas a eliminar: {len(a_eliminar)} "
                f"({omitidas} omitidas por ser único catálogo del proveedor)."
            )
        )

        for oferta in a_eliminar:
            marca = (
                oferta.marca_vehiculo_seleccionada.nombre
                if oferta.marca_vehiculo_seleccionada_id
                else "—"
            )
            self.stdout.write(
                f"  - #{oferta.id} {oferta.servicio.nombre} | "
                f"{self._proveedor_label(oferta)} | marca={marca} | "
                f"disponible={oferta.disponible}"
            )

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"DRY RUN: se eliminarían {len(a_eliminar)} ofertas (sin cambios)."
                )
            )
            return

        with transaction.atomic():
            ids = [o.id for o in a_eliminar]
            deleted, _ = OfertaServicio.objects.filter(id__in=ids).delete()

        self.stdout.write(
            self.style.SUCCESS(f"Eliminadas {deleted} ofertas automáticas duplicadas.")
        )
