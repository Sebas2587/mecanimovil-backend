from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0042_tienda_especialista_marca'),
    ]

    operations = [
        migrations.AddField(
            model_name='preciorepuestoweb',
            name='calidad',
            field=models.CharField(blank=True, default='', max_length=16),
        ),
        migrations.AddField(
            model_name='preciorepuestoweb',
            name='imagen_url',
            field=models.URLField(blank=True, default='', max_length=500),
        ),
        migrations.AddField(
            model_name='preciorepuestoweb',
            name='imagen_estado',
            field=models.CharField(blank=True, default='pendiente', max_length=16),
        ),
        migrations.AddField(
            model_name='precioproveedortaller',
            name='calidad',
            field=models.CharField(blank=True, default='', max_length=16),
        ),
        migrations.AddField(
            model_name='precioproveedortaller',
            name='imagen_url',
            field=models.URLField(blank=True, default='', max_length=500),
        ),
    ]
