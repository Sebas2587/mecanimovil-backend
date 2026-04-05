from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('suscripciones', '0004_alter_compracreditos_paquete'),
    ]

    operations = [
        migrations.AddField(
            model_name='suscripcionproveedor',
            name='processed_charge_ids',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='Lista de todos los charge_ids ya acreditados (idempotencia robusta)',
                verbose_name='IDs de Cobros Procesados',
            ),
        ),
    ]
