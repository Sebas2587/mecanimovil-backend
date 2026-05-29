# Generated manually — marcas_compatibles en catálogo maestro

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0023_componentesalud_anclada_inspeccion_evento'),
        ('servicios', '0004_ofertaservicio_duracion_min_max'),
    ]

    operations = [
        migrations.AddField(
            model_name='servicio',
            name='marcas_compatibles',
            field=models.ManyToManyField(
                blank=True,
                help_text='Marcas de vehículos con las que este servicio es compatible. Si no se restringen modelos, aplica a todos los modelos de la marca.',
                related_name='servicios_compatibles',
                to='vehiculos.marcavehiculo',
                verbose_name='marcas compatibles',
            ),
        ),
        migrations.AlterField(
            model_name='servicio',
            name='modelos_compatibles',
            field=models.ManyToManyField(
                blank=True,
                help_text='Opcional: limita el servicio a modelos concretos de las marcas asociadas. Si está vacío, aplica a todos los modelos de las marcas compatibles.',
                related_name='servicios_compatibles',
                to='vehiculos.modelo',
                verbose_name='modelos compatibles',
            ),
        ),
    ]
