# Generated manually: marca cada recálculo para staleness y sync

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0012_componentesalud_reglamantenimientoespecifica_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='estadosaludvehiculo',
            name='ultima_actualizacion',
            field=models.DateTimeField(
                null=True,
                blank=True,
                help_text='Última vez que HealthEngine actualizó este snapshot',
            ),
        ),
    ]
