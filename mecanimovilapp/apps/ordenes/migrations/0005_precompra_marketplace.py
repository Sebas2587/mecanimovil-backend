import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0004_add_fecha_alternativa_oferta'),
        ('vehiculos', '0017_vehiculo_is_certified_mecanimovil'),
    ]

    operations = [
        migrations.AddField(
            model_name='solicitudservicio',
            name='oferta_marketplace',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='solicitudes_inspeccion',
                to='vehiculos.ofertavehiculo',
                help_text='Oferta de compra marketplace que originó esta inspección pre-compra',
                verbose_name='Oferta Marketplace',
            ),
        ),
        migrations.AddField(
            model_name='carritoagendamiento',
            name='oferta_marketplace',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='carritos_inspeccion',
                to='vehiculos.ofertavehiculo',
                help_text='Oferta de compra marketplace (inspección pre-compra)',
            ),
        ),
    ]
