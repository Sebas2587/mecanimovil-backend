# OfertaServicio.tipo_motor — precio/configuración opcional por motor

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('servicios', '0007_tipos_motor_compatibles'),
    ]

    operations = [
        migrations.AddField(
            model_name='ofertaservicio',
            name='tipo_motor',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Vacío: aplica a todos los motores compatibles del servicio. Ej. GASOLINA o DIESEL para precio/repuestos distintos por motor.',
                max_length=20,
                verbose_name='tipo de motor',
            ),
        ),
        migrations.AlterUniqueTogether(
            name='ofertaservicio',
            unique_together={
                ('taller', 'servicio', 'marca_vehiculo_seleccionada', 'tipo_motor'),
                ('mecanico', 'servicio', 'marca_vehiculo_seleccionada', 'tipo_motor'),
            },
        ),
    ]
