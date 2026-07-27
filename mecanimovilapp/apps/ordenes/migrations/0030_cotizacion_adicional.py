# Generated manually for cotizacion adicional fields

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0029_cotizacion_fecha_expiracion_publica'),
    ]

    operations = [
        migrations.AddField(
            model_name='cotizacioncanal',
            name='cotizacion_original',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='cotizaciones_adicionales',
                to='ordenes.cotizacioncanal',
            ),
        ),
        migrations.AddField(
            model_name='cotizacioncanal',
            name='es_cotizacion_adicional',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='cotizacioncanal',
            name='motivo_servicio_adicional',
            field=models.TextField(blank=True, default=''),
        ),
    ]
