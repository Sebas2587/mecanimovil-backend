from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0040_proveedor_repuestos_precio_taller'),
    ]

    operations = [
        migrations.AddField(
            model_name='preciorepuestoweb',
            name='especificacion',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.AddField(
            model_name='preciorepuestoweb',
            name='codigo_parte',
            field=models.CharField(blank=True, default='', max_length=60),
        ),
        migrations.AddField(
            model_name='preciorepuestoweb',
            name='tipo_motor',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='preciorepuestoweb',
            name='cilindraje',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='preciorepuestoweb',
            name='categoria',
            field=models.CharField(blank=True, default='', max_length=40),
        ),
    ]
