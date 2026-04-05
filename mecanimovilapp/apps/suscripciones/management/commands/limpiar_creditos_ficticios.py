"""
One-time command to remove fictitious credits that were granted without
a real MercadoPago payment (e.g. 'inicial_autorizacion').
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from mecanimovilapp.apps.suscripciones.models import SuscripcionProveedor
from mecanimovilapp.apps.suscripciones.creditos_services import obtener_credito_proveedor


class Command(BaseCommand):
    help = "Reverts credits given under fake charge IDs (non-numeric) and cleans processed_charge_ids"

    def handle(self, *args, **options):
        suscripciones = SuscripcionProveedor.objects.select_related('plan', 'proveedor').all()
        total_reverted = 0

        for sus in suscripciones:
            fake_ids = [
                cid for cid in (sus.processed_charge_ids or [])
                if not str(cid).isdigit()
            ]
            if not fake_ids:
                self.stdout.write(f"  Suscripcion {sus.id}: sin IDs ficticios, OK.")
                continue

            creditos_por_cobro = sus.plan.creditos_mensuales
            creditos_a_revertir = creditos_por_cobro * len(fake_ids)

            with transaction.atomic():
                credito = obtener_credito_proveedor(sus.proveedor)
                saldo_anterior = credito.saldo_creditos
                credito.saldo_creditos = max(0, credito.saldo_creditos - creditos_a_revertir)
                credito.save(update_fields=['saldo_creditos', 'fecha_actualizacion'])

                real_ids = [cid for cid in (sus.processed_charge_ids or []) if str(cid).isdigit()]
                sus.processed_charge_ids = sorted(real_ids)
                if sus.ultimo_charge_id and not str(sus.ultimo_charge_id).isdigit():
                    sus.ultimo_charge_id = real_ids[-1] if real_ids else ''
                sus.save(update_fields=['processed_charge_ids', 'ultimo_charge_id', 'fecha_actualizacion'])

            self.stdout.write(self.style.WARNING(
                f"  Suscripcion {sus.id} (proveedor {sus.proveedor.id}): "
                f"revertidos {creditos_a_revertir} créditos ficticios "
                f"({fake_ids}). Saldo: {saldo_anterior} -> {credito.saldo_creditos}"
            ))
            total_reverted += creditos_a_revertir

        if total_reverted:
            self.stdout.write(self.style.SUCCESS(
                f"\nTotal créditos ficticios revertidos: {total_reverted}"
            ))
        else:
            self.stdout.write(self.style.SUCCESS("\nNo se encontraron créditos ficticios."))
