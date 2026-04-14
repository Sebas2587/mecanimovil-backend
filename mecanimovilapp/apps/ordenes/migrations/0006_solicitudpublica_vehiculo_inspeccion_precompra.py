import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0017_vehiculo_is_certified_mecanimovil'),
        ('ordenes', '0005_precompra_marketplace'),
    ]

    operations = [
        migrations.AddField(
            model_name='solicitudserviciopublica',
            name='vehiculo_inspeccion_precompra',
            field=models.ForeignKey(
                blank=True,
                help_text='Vehículo ofertado por el vendedor; permite evitar duplicados de pre-compra por comprador.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='solicitudes_publicas_inspeccion_precompra',
                to='vehiculos.vehiculo',
                verbose_name='Vehículo inspección pre-compra (marketplace)',
            ),
        ),
    ]
