# Generated manually — marcas_compatibles en Repuesto

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0024_vehiculo_descripcion_venta_fotovehiculomarketplace'),
        ('servicios', '0005_servicio_marcas_compatibles'),
    ]

    operations = [
        migrations.AddField(
            model_name='repuesto',
            name='marcas_compatibles',
            field=models.ManyToManyField(
                blank=True,
                help_text='Marcas de vehículo con las que este repuesto es compatible. Si no se restringen modelos, aplica a todos los modelos de la marca.',
                related_name='repuestos_compatibles_marca',
                to='vehiculos.marcavehiculo',
                verbose_name='marcas de vehículo compatibles',
            ),
        ),
        migrations.AlterField(
            model_name='repuesto',
            name='modelos_compatibles',
            field=models.ManyToManyField(
                blank=True,
                help_text='Opcional: limita el repuesto a modelos concretos de las marcas asociadas.',
                related_name='repuestos_compatibles',
                to='vehiculos.modelo',
                verbose_name='modelos compatibles',
            ),
        ),
    ]
