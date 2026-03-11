# Intervalo por tiempo para salud (km + meses)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0013_estadosaludvehiculo_ultima_actualizacion'),
    ]

    operations = [
        migrations.AddField(
            model_name='reglamantenimientogenerica',
            name='intervalo_meses',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Meses recomendados entre servicios (ej. 6). Opcional; si null, solo aplica eje km.',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='reglamantenimientoespecifica',
            name='intervalo_meses',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Meses entre servicios para este modelo; si null, solo eje km.',
                null=True,
            ),
        ),
    ]
