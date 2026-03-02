# Generated manually for fecha alternativa en ofertas

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0003_preserve_service_history_on_vehicle_delete'),
    ]

    operations = [
        migrations.AddField(
            model_name='ofertaproveedor',
            name='es_fecha_alternativa',
            field=models.BooleanField(default=False, help_text='True si el proveedor propone una fecha distinta a la solicitada por el cliente.', verbose_name='Es fecha alternativa'),
        ),
        migrations.AddField(
            model_name='ofertaproveedor',
            name='motivo_fecha_alternativa',
            field=models.TextField(blank=True, help_text='Razón por la que el proveedor propone otra fecha.', null=True, verbose_name='Motivo fecha alternativa'),
        ),
    ]
