# OfertaServicio.modelo_vehiculo_seleccionado — precio/config por modelo

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0001_initial'),
        ('servicios', '0008_ofertaservicio_tipo_motor'),
    ]

    operations = [
        migrations.AddField(
            model_name='ofertaservicio',
            name='modelo_vehiculo_seleccionado',
            field=models.ForeignKey(
                blank=True,
                help_text='Modelo específico. Null = todos los modelos de la marca.',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='ofertas_servicio',
                to='vehiculos.modelo',
            ),
        ),
        migrations.AlterUniqueTogether(
            name='ofertaservicio',
            unique_together={
                (
                    'taller',
                    'servicio',
                    'marca_vehiculo_seleccionada',
                    'modelo_vehiculo_seleccionado',
                    'tipo_motor',
                ),
                (
                    'mecanico',
                    'servicio',
                    'marca_vehiculo_seleccionada',
                    'modelo_vehiculo_seleccionado',
                    'tipo_motor',
                ),
            },
        ),
    ]
