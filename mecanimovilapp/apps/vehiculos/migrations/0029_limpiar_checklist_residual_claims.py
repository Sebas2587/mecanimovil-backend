"""
Limpieza residual: componentes que quedaron con historial_fuente=CHECKLIST
tras el claim retroactivo (p.ej. si un worker reaplicó el ancla durante 0028).
"""

from django.db import migrations


def limpiar_residual(apps, schema_editor):
    InformeServicioPublico = apps.get_model('checklists', 'InformeServicioPublico')
    ComponenteSaludVehiculo = apps.get_model('vehiculos', 'ComponenteSaludVehiculo')

    vehiculo_ids = list(
        InformeServicioPublico.objects.filter(
            reclamado_por_vehiculo_id__isnull=False,
        )
        .values_list('reclamado_por_vehiculo_id', flat=True)
        .distinct()
    )
    if not vehiculo_ids:
        return

    ComponenteSaludVehiculo.objects.filter(
        vehiculo_id__in=vehiculo_ids,
        historial_fuente='CHECKLIST',
    ).update(
        historial_conocido=False,
        historial_fuente='ENGINE',
        km_ultimo_servicio=0,
        salud_anclada_pct=None,
        fecha_ultimo_servicio=None,
        mensaje_alerta='',
        requiere_servicio_inmediato=False,
    )

    try:
        from mecanimovilapp.apps.vehiculos.services.health_engine import HealthEngine
        from mecanimovilapp.apps.vehiculos.tasks import invalidate_vehicle_health_cache

        for vehiculo_id in vehiculo_ids:
            try:
                invalidate_vehicle_health_cache(vehiculo_id)
            except Exception:
                pass
            try:
                HealthEngine.calcular_salud_vehiculo(vehiculo_id)
            except Exception:
                pass
    except Exception:
        pass


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0028_revertir_salud_claims_retroactivos'),
        ('checklists', '0008_informe_publico_firma_supervisor'),
    ]

    operations = [
        migrations.RunPython(limpiar_residual, noop_reverse),
    ]
