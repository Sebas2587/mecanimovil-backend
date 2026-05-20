# Generated manually — permite una oferta por (proveedor, servicio, marca)

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('servicios', '0002_initial'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='ofertaservicio',
            unique_together={
                ('taller', 'servicio', 'marca_vehiculo_seleccionada'),
                ('mecanico', 'servicio', 'marca_vehiculo_seleccionada'),
            },
        ),
    ]
