"""
Fuerza recálculo sync de salud para vehículos con informes reclamados,
respetando el % anclado del taller (HealthEngine snapshot fresco).
"""

from django.db import migrations


def forzar(apps, schema_editor):
    InformeServicioPublico = apps.get_model('checklists', 'InformeServicioPublico')
    Vehiculo = apps.get_model('vehiculos', 'Vehiculo')

    try:
        from django.utils import timezone
        from mecanimovilapp.apps.vehiculos.tasks import actualizar_salud_desde_checklist
        from mecanimovilapp.apps.vehiculos.services.health_engine import HealthEngine
        from mecanimovilapp.apps.vehiculos.tasks import invalidate_vehicle_health_cache
    except Exception:
        return

    vehiculo_ids = list(
        InformeServicioPublico.objects.filter(
            reclamado_por_vehiculo_id__isnull=False,
        )
        .values_list('reclamado_por_vehiculo_id', flat=True)
        .distinct()
    )

    for vehiculo_id in vehiculo_ids:
        try:
            vehiculo = Vehiculo.objects.get(id=vehiculo_id)
        except Vehiculo.DoesNotExist:
            continue

        checklist_ids = list(
            InformeServicioPublico.objects.filter(
                reclamado_por_vehiculo_id=vehiculo_id,
            ).values_list('checklist_instance_id', flat=True)
        )
        km_ancla = int(vehiculo.kilometraje or 0) or None
        for checklist_id in checklist_ids:
            if not checklist_id:
                continue
            try:
                actualizar_salud_desde_checklist(
                    checklist_id,
                    vehiculo_id,
                    km_servicio_override=km_ancla,
                    fecha_servicio_override=timezone.now(),
                    actualizar_odometro=False,
                )
            except Exception:
                continue
        try:
            invalidate_vehicle_health_cache(vehiculo_id)
            HealthEngine.calcular_salud_vehiculo(vehiculo_id)
        except Exception:
            continue


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0031_reaplicar_salud_claims_fecha_ancla'),
        ('checklists', '0008_informe_publico_firma_supervisor'),
    ]

    operations = [
        migrations.RunPython(forzar, noop_reverse),
    ]
