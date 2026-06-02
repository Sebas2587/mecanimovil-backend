# Generated manually for tipos_motor_compatibles

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('servicios', '0006_repuesto_marcas_compatibles'),
    ]

    operations = [
        migrations.AddField(
            model_name='servicio',
            name='tipos_motor_compatibles',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='Vacío = todos los motores. Ej: ["GASOLINA"] solo bencinero; ["GASOLINA","DIESEL"] ambos combustión.',
                verbose_name='tipos de motor compatibles',
            ),
        ),
        migrations.AddField(
            model_name='repuesto',
            name='tipos_motor_compatibles',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='Vacío = todos los motores. Misma semántica que en Servicio.',
                verbose_name='tipos de motor compatibles',
            ),
        ),
    ]
