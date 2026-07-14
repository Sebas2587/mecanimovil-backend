"""
El callback seguía fallando con el mismo DataError después de ampliar
access_token/refresh_token: el campo que realmente excede 255 caracteres
es `scope` (MercadoLibre devuelve un string de scope más largo de lo
esperado). Se amplía también a TextField.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('valoracion_mercado', '0003_mercadolibreoauthtoken_textfields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='mercadolibreoauthtoken',
            name='scope',
            field=models.TextField(blank=True, default=''),
        ),
    ]
