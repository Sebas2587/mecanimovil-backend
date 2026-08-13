from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0033_cotizacioncanal_cita_origen'),
    ]

    operations = [
        migrations.AddField(
            model_name='cotizacioncanal',
            name='ejecucion_adicional',
            field=models.CharField(
                choices=[
                    ('misma_visita', 'Misma visita'),
                    ('nueva_fecha', 'Nueva fecha'),
                ],
                default='misma_visita',
                help_text='Cómo se ejecuta el trabajo adicional: en la visita en curso o en una fecha posterior.',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='cotizacioncanal',
            name='fecha_propuesta',
            field=models.DateField(
                blank=True,
                help_text='Fecha acordada con el cliente cuando ejecucion_adicional=nueva_fecha.',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='cotizacioncanal',
            name='hora_propuesta',
            field=models.TimeField(
                blank=True,
                help_text='Hora acordada con el cliente cuando ejecucion_adicional=nueva_fecha.',
                null=True,
            ),
        ),
    ]
