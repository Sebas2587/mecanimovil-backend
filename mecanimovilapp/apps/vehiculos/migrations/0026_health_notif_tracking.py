from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0025_vehiculo_tipo_motor_hibrido_electrico'),
    ]

    operations = [
        # ComponenteSaludVehiculo: tracking de la última notificación enviada
        migrations.AddField(
            model_name='componentesaludvehiculo',
            name='ultimo_pct_notificado',
            field=models.FloatField(
                blank=True,
                null=True,
                help_text='Último salud_porcentaje con el que se emitió push. Null = nunca notificado.',
            ),
        ),
        migrations.AddField(
            model_name='componentesaludvehiculo',
            name='ultimo_nivel_notificado',
            field=models.CharField(
                blank=True,
                max_length=20,
                null=True,
                help_text='Último nivel_alerta (OPTIMO/ATENCION/URGENTE/CRITICO) notificado.',
            ),
        ),
        # EstadoSaludVehiculo: tracking del último % global notificado
        migrations.AddField(
            model_name='estadosaludvehiculo',
            name='ultimo_pct_global_notificado',
            field=models.FloatField(
                blank=True,
                null=True,
                help_text='Último salud_general_porcentaje notificado. Evita pushes repetitivas.',
            ),
        ),
    ]
