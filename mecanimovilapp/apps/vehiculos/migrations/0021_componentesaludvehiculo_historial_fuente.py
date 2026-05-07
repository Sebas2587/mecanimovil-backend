from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0020_eventosaludvehiculo'),
    ]

    operations = [
        migrations.AddField(
            model_name='componentesaludvehiculo',
            name='historial_fuente',
            field=models.CharField(
                choices=[
                    ('ENGINE',            'Estimado automáticamente'),
                    ('CHECKLIST',         'Confirmado por checklist de taller'),
                    ('USUARIO_DECLARADO', 'Declarado por el usuario (retroactivo)'),
                    ('REGISTRO_INICIAL',  'Informado al registrar el vehículo'),
                ],
                default='ENGINE',
                help_text='Origen del último dato de km/fecha de servicio.',
                max_length=20,
            ),
        ),
    ]
