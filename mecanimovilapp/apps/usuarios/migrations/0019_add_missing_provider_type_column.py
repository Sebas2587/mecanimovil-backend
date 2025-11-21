# Generated manually to fix missing provider_type column

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0018_auto_20250802_1216'),
    ]

    operations = [
        migrations.AddField(
            model_name='review',
            name='provider_type',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('taller', 'Taller'),
                    ('mecanico', 'Mecánico a Domicilio')
                ],
                help_text="Tipo de proveedor",
                default='taller'  # Valor por defecto temporal
            ),
        ),
    ] 