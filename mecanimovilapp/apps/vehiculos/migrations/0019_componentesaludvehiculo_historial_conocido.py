from django.db import migrations, models


def marcar_historial_conocido_existente(apps, schema_editor):
    """
    Para filas que ya tienen km_ultimo_servicio > 0 Y fecha_ultimo_servicio definida,
    marcar historial_conocido=True (datos reales del usuario o de checklists anteriores).
    """
    ComponenteSaludVehiculo = apps.get_model('vehiculos', 'ComponenteSaludVehiculo')
    ComponenteSaludVehiculo.objects.filter(
        km_ultimo_servicio__gt=0,
        fecha_ultimo_servicio__isnull=False,
    ).update(historial_conocido=True)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0018_estadosaludvehiculo_unique_per_vehiculo'),
    ]

    operations = [
        migrations.AddField(
            model_name='componentesaludvehiculo',
            name='historial_conocido',
            field=models.BooleanField(
                default=False,
                help_text='Indica si km_ultimo_servicio proviene de datos reales (checklist/registro). '
                          'Si False, el Engine usa estimación conservadora de ~1 ciclo de mantenimiento.',
            ),
        ),
        migrations.RunPython(marcar_historial_conocido_existente, noop),
    ]
