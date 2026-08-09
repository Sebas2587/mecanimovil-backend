from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0031_cotizacioncanal_notas_internas'),
    ]

    operations = [
        migrations.CreateModel(
            name='PrecioRepuestoWeb',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('clave', models.CharField(db_index=True, help_text='Clave normalizada nombre+marca+modelo+anio del vehículo.', max_length=240)),
                ('nombre_producto', models.CharField(blank=True, default='', max_length=200)),
                ('marca_repuesto', models.CharField(blank=True, default='', max_length=100)),
                ('precio_clp', models.PositiveIntegerField(default=0)),
                ('tienda', models.CharField(blank=True, default='', max_length=200)),
                ('dominio', models.CharField(max_length=200)),
                ('url', models.URLField(blank=True, default='', max_length=500)),
                ('compatibilidad', models.CharField(blank=True, default='', max_length=20)),
                ('confianza', models.FloatField(default=0.0)),
                ('consultado_en', models.DateTimeField(auto_now=True)),
                ('expira_en', models.DateTimeField(db_index=True)),
            ],
            options={
                'verbose_name': 'precio repuesto web',
                'verbose_name_plural': 'precios repuesto web',
            },
        ),
        migrations.AddConstraint(
            model_name='preciorepuestoweb',
            constraint=models.UniqueConstraint(
                fields=('clave', 'dominio'),
                name='ordenes_preciorepuestoweb_clave_dominio_uniq',
            ),
        ),
        migrations.AddIndex(
            model_name='preciorepuestoweb',
            index=models.Index(fields=['expira_en'], name='ordenes_prw_expira_idx'),
        ),
        migrations.AddIndex(
            model_name='preciorepuestoweb',
            index=models.Index(fields=['clave', '-confianza'], name='ordenes_prw_clave_conf_idx'),
        ),
    ]
