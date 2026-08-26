from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0023_taller_politicas_cotizacion'),
    ]

    operations = [
        migrations.AddField(
            model_name='taller',
            name='dias_validez_cotizacion',
            field=models.PositiveSmallIntegerField(
                default=30,
                help_text='Días de vigencia de las cotizaciones públicas (1–90). Default 30.',
                validators=[MinValueValidator(1), MaxValueValidator(90)],
            ),
        ),
        migrations.AddField(
            model_name='mecanicodomicilio',
            name='dias_validez_cotizacion',
            field=models.PositiveSmallIntegerField(
                default=30,
                help_text='Días de vigencia de las cotizaciones públicas (1–90). Default 30.',
                validators=[MinValueValidator(1), MaxValueValidator(90)],
            ),
        ),
    ]
