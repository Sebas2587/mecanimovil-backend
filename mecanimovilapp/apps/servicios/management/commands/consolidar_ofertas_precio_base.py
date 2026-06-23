"""
Consolida ofertas duplicadas por marca (mismo servicio y precio) en una oferta precio base.

Ocurre cuando un proveedor multimarca publica con «Todas mis marcas» en la pestaña
Por marca: se crea una OfertaServicio por cada marca en lugar de una con marca=null.

Uso:
  python manage.py consolidar_ofertas_precio_base --dry-run
  python manage.py consolidar_ofertas_precio_base --force --taller-id 26
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from mecanimovilapp.apps.servicios.models import OfertaServicio


def _proveedor_key(oferta: OfertaServicio) -> tuple:
    return (oferta.taller_id, oferta.mecanico_id)


def _proveedor_label(oferta: OfertaServicio) -> str:
    if oferta.mecanico_id:
        return f"mecánico #{oferta.mecanico_id} ({oferta.mecanico.nombre})"
    if oferta.taller_id:
        return f"taller #{oferta.taller_id} ({oferta.taller.nombre})"
    return "proveedor desconocido"


class Command(BaseCommand):
    help = (
        "Une ofertas repetidas por marca (mismo precio) en una sola oferta precio base (marca null)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Solo muestra qué se consolidaría, sin modificar la base.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Requerido para ejecutar cambios reales (sin --dry-run).",
        )
        parser.add_argument(
            "--min-marcas",
            type=int,
            default=5,
            help="Mínimo de ofertas por marca distintas para consolidar (default: 5).",
        )
        parser.add_argument("--taller-id", type=int, help="Limitar a un taller.")
        parser.add_argument("--mecanico-id", type=int, help="Limitar a un mecánico.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        if not dry_run and not options["force"]:
            self.stderr.write(
                self.style.ERROR("Use --dry-run para simular o --force para aplicar cambios.")
            )
            return

        qs = OfertaServicio.objects.select_related(
            "servicio", "taller", "mecanico", "marca_vehiculo_seleccionada"
        )
        if options["taller_id"]:
            qs = qs.filter(taller_id=options["taller_id"])
        if options["mecanico_id"]:
            qs = qs.filter(mecanico_id=options["mecanico_id"])

        min_marcas = options["min_marcas"]
        combos: dict[tuple, list[OfertaServicio]] = defaultdict(list)

        for oferta in qs:
            combos[
                (
                    _proveedor_key(oferta),
                    oferta.servicio_id,
                    oferta.modelo_vehiculo_seleccionado_id,
                    oferta.tipo_motor or "",
                )
            ].append(oferta)

        total_consolidados = 0
        total_eliminados = 0

        for combo_key, ofertas in combos.items():
            servicio_id = combo_key[1]
            per_marca = [o for o in ofertas if o.marca_vehiculo_seleccionada_id]
            bases = [o for o in ofertas if o.marca_vehiculo_seleccionada_id is None]

            if len(per_marca) < min_marcas:
                continue

            marcas_distintas = {
                o.marca_vehiculo_seleccionada_id for o in per_marca
            }
            if len(marcas_distintas) < min_marcas:
                continue

            por_precio: dict[tuple[Decimal, Decimal], list[OfertaServicio]] = defaultdict(list)
            for o in per_marca:
                por_precio[(o.costo_mano_de_obra_sin_iva, o.costo_repuestos_sin_iva)].append(o)

            def _grupo_score(items: list[OfertaServicio]) -> tuple:
                return (len(items), max(o.fecha_creacion for o in items))

            best_price_key = max(por_precio.keys(), key=lambda k: _grupo_score(por_precio[k]))
            template = max(
                por_precio[best_price_key],
                key=lambda o: o.fecha_creacion,
            )
            ref = ofertas[0]
            servicio_nombre = ref.servicio.nombre
            prov = _proveedor_label(ref)

            ids_per_marca = [o.id for o in per_marca]
            extra_bases = [o.id for o in bases[1:]] if len(bases) > 1 else []

            self.stdout.write(
                f"• {prov} | {servicio_nombre} | "
                f"{len(marcas_distintas)} marcas → 1 precio base "
                f"(MO ${template.costo_mano_de_obra_sin_iva}, "
                f"rep ${template.costo_repuestos_sin_iva})"
            )

            if dry_run:
                total_consolidados += 1
                total_eliminados += len(ids_per_marca) - (0 if bases else 1)
                total_eliminados += len(extra_bases)
                continue

            with transaction.atomic():
                if bases:
                    base = bases[0]
                    base.costo_mano_de_obra_sin_iva = template.costo_mano_de_obra_sin_iva
                    base.costo_repuestos_sin_iva = template.costo_repuestos_sin_iva
                    base.disponible = template.disponible
                    base.save()
                    eliminar_ids = [
                        oid for oid in ids_per_marca if oid != base.id
                    ] + extra_bases
                else:
                    template.marca_vehiculo_seleccionada = None
                    template.save(update_fields=["marca_vehiculo_seleccionada"])
                    eliminar_ids = [oid for oid in ids_per_marca if oid != template.id]

                if eliminar_ids:
                    OfertaServicio.objects.filter(id__in=eliminar_ids).delete()

            total_consolidados += 1
            total_eliminados += len(eliminar_ids)

        suffix = " (dry-run)" if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"Listo: {total_consolidados} servicio(s) consolidados, "
                f"{total_eliminados} oferta(s) eliminadas{suffix}."
            )
        )
