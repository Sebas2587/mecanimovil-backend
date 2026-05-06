from django.db import migrations, models


def dedup_estados_salud(apps, schema_editor):
    """
    Antes de agregar el unique constraint, eliminar filas duplicadas de
    EstadoSaludVehiculo manteniendo solo la fila más reciente por vehículo.
    """
    EstadoSaludVehiculo = apps.get_model('vehiculos', 'EstadoSaludVehiculo')
    from django.db.models import Count

    vehiculos_con_duplicados = (
        EstadoSaludVehiculo.objects
        .values('vehiculo_id')
        .annotate(cnt=Count('id'))
        .filter(cnt__gt=1)
        .values_list('vehiculo_id', flat=True)
    )

    for vehiculo_id in vehiculos_con_duplicados:
        ids_ordenados = list(
            EstadoSaludVehiculo.objects
            .filter(vehiculo_id=vehiculo_id)
            .order_by('-fecha_calculo')
            .values_list('id', flat=True)
        )
        # Mantener el primero (más reciente), borrar el resto
        EstadoSaludVehiculo.objects.filter(id__in=ids_ordenados[1:]).delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0017_vehiculo_is_certified_mecanimovil'),
    ]

    operations = [
        migrations.RunPython(dedup_estados_salud, noop),
        migrations.AddConstraint(
            model_name='estadosaludvehiculo',
            constraint=models.UniqueConstraint(
                fields=['vehiculo'],
                name='unique_estado_salud_per_vehiculo',
            ),
        ),
    ]
