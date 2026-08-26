from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0036_cotizacioncanal_politicas_cotizacion'),
    ]

    operations = [
        migrations.AddField(
            model_name='cotizacioncanal',
            name='descuento_tipo',
            field=models.CharField(
                blank=True,
                choices=[('', 'Sin descuento'), ('monto', 'Monto en CLP'), ('porcentaje', 'Porcentaje')],
                default='',
                help_text='monto (CLP) o porcentaje. Vacío = sin descuento.',
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name='cotizacioncanal',
            name='descuento_alcance',
            field=models.CharField(
                choices=[('mano_obra', 'Mano de obra'), ('total', 'Total')],
                default='mano_obra',
                help_text='Base del descuento: mano de obra o total (repuestos + mano de obra).',
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name='cotizacioncanal',
            name='descuento_valor',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='CLP si tipo=monto; 0–100 si tipo=porcentaje.',
                max_digits=12,
            ),
        ),
        migrations.AddField(
            model_name='cotizacioncanal',
            name='descuento_clp',
            field=models.DecimalField(
                decimal_places=0,
                default=0,
                help_text='Monto de descuento aplicado (IVA incl.). Read-only, se recalcula.',
                max_digits=12,
            ),
        ),
    ]
