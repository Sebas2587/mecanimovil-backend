"""
Reaplica salud de informes reclamados anclando al km ACTUAL del vehículo.

Evita el bug de degradar por km del taller (p.ej. 63.000) vs odómetro actual.
"""

from django.db import migrations


def reaplicar_claims(apps, schema_editor):
    InformeServicioPublico = apps.get_model('checklists', 'InformeServicioPublico')
    Vehiculo = apps.get_model('vehiculos', 'Vehiculo')

    informes = (
        InformeServicioPublico.objects.filter(
            reclamado_por_vehiculo_id__isnull=False,
            checklist_instance_id__isnull=False,
        )
        .order_by('reclamado_en', 'id')
    )

    try:
        from mecanimovilapp.apps.vehiculos.tasks import actualizar_salud_desde_checklist
    except Exception:
        return

    for informe in informes.iterator():
        vehiculo_id = informe.reclamado_por_vehiculo_id
        checklist_id = informe.checklist_instance_id
        try:
            vehiculo = Vehiculo.objects.get(id=vehiculo_id)
        except Vehiculo.DoesNotExist:
            continue
        km_ancla = int(vehiculo.kilometraje or 0) or None
        try:
            actualizar_salud_desde_checklist(
                checklist_id,
                vehiculo_id,
                km_servicio_override=km_ancla,
                actualizar_odometro=False,
            )
        except Exception:
            continue


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0029_limpiar_checklist_residual_claims'),
        ('checklists', '0008_informe_publico_firma_supervisor'),
    ]

    operations = [
        migrations.RunPython(reaplicar_claims, noop_reverse),
    ]
