# Generated manually for dirección en cotización a domicilio

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0027_cotizacion_libre_y_cita_por_confirmar'),
    ]

    operations = [
        migrations.AddField(
            model_name='cotizacioncanal',
            name='direccion_servicio',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Dirección del cliente cuando modalidad es a domicilio.',
                max_length=500,
            ),
        ),
    ]
