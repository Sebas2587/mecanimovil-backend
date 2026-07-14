"""
Amplía access_token/refresh_token a TextField: los tokens reales de
MercadoLibre superan los 255 caracteres del varchar original y el
callback de OAuth fallaba con DataError al guardarlos.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('valoracion_mercado', '0002_mercadolibreoauthtoken'),
    ]

    operations = [
        migrations.AlterField(
            model_name='mercadolibreoauthtoken',
            name='access_token',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AlterField(
            model_name='mercadolibreoauthtoken',
            name='refresh_token',
            field=models.TextField(blank=True, default=''),
        ),
    ]
