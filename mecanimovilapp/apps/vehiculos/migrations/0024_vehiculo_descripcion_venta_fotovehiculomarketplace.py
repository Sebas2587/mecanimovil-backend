from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0023_componentesalud_anclada_inspeccion_evento'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehiculo',
            name='descripcion_venta',
            field=models.TextField(
                blank=True,
                null=True,
                verbose_name='descripción de venta',
                help_text='Descripción libre del vehículo para el marketplace',
            ),
        ),
        migrations.CreateModel(
            name='FotoVehiculoMarketplace',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('foto', models.ImageField(upload_to='marketplace/fotos/')),
                ('orden', models.PositiveSmallIntegerField(default=0, help_text='Posición en el carrusel')),
                ('fecha_creacion', models.DateTimeField(auto_now_add=True)),
                ('vehiculo', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='fotos_marketplace',
                    to='vehiculos.vehiculo',
                )),
            ],
            options={
                'verbose_name': 'foto de marketplace',
                'verbose_name_plural': 'fotos de marketplace',
                'ordering': ['orden', 'fecha_creacion'],
            },
        ),
    ]
