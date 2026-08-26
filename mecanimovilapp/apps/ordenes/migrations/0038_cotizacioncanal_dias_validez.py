from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0037_cotizacioncanal_descuento'),
    ]

    operations = [
        migrations.AddField(
            model_name='cotizacioncanal',
            name='dias_validez',
            field=models.PositiveSmallIntegerField(
                default=30,
                help_text='Vigencia en días (snapshot del taller). Se usa al emitir fecha_expiracion_publica.',
                validators=[MinValueValidator(1), MaxValueValidator(90)],
            ),
        ),
    ]
