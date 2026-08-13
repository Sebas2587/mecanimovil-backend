from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0032_preciorepuestoweb'),
    ]

    operations = [
        migrations.AddField(
            model_name='cotizacioncanal',
            name='cita_origen',
            field=models.ForeignKey(
                blank=True,
                help_text='Cita principal en curso cuando esta cotización es un trabajo adicional.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='cotizaciones_adicionales',
                to='ordenes.citaagendapersonal',
            ),
        ),
        migrations.AddIndex(
            model_name='cotizacioncanal',
            index=models.Index(fields=['cita_origen', 'estado'], name='ordenes_cot_cita_or_estado_idx'),
        ),
    ]
