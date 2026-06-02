# Tipos de motor alineados con app usuarios y motor de salud

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0024_vehiculo_descripcion_venta_fotovehiculomarketplace'),
    ]

    operations = [
        migrations.AlterField(
            model_name='vehiculo',
            name='tipo_motor',
            field=models.CharField(
                choices=[
                    ('Gasolina', 'Gasolina'),
                    ('GASOLINA', 'GASOLINA'),
                    ('BENCINA', 'BENCINA'),
                    ('Diésel', 'Diésel'),
                    ('DIESEL', 'DIESEL'),
                    ('Electric', 'Electric'),
                    ('ELECTRICO', 'Eléctrico'),
                    ('HIBRIDO', 'Híbrido'),
                ],
                default='Gasolina',
                max_length=20,
            ),
        ),
    ]
