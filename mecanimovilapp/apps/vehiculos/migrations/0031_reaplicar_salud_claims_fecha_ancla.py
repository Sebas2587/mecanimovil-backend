"""
Reaplica claims con fecha_servicio = now para que el desgaste por meses
no parta desde la fecha antigua del taller.
"""

from django.db import migrations


def reaplicar(apps, schema_editor):
    InformeServicioPublico = apps.get_model('checklists', 'InformeServicioPublico')
    Vehiculo = apps.get_model('vehiculos', 'Vehiculo')

    try:
        from django.utils import timezone
        from mecanimovilapp.apps.vehiculos.tasks import actualizar_salud_desde_checklist
    except Exception:
        return

    informes = InformeServicioPublico.objects.filter(
        reclamado_por_vehiculo_id__isnull=False,
        checklist_instance_id__isnull=False,
    ).order_by('reclamado_en', 'id')

    for informe in informes.iterator():
        try:
            vehiculo = Vehiculo.objects.get(id=informe.reclamado_por_vehiculo_id)
        except Vehiculo.DoesNotExist:
            continue
        km_ancla = int(vehiculo.kilometraje or 0) or None
        try:
            actualizar_salud_desde_checklist(
                informe.checklist_instance_id,
                vehiculo.id,
                km_servicio_override=km_ancla,
                fecha_servicio_override=timezone.now(),
                actualizar_odometro=False,
            )
        except Exception:
            continue


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0030_reaplicar_salud_claims_snapshot_km'),
        ('checklists', '0008_informe_publico_firma_supervisor'),
    ]

    operations = [
        migrations.RunPython(reaplicar, noop_reverse),
    ]
