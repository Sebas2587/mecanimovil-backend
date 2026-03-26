from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0015_componentesalud_servicios_asociados'),
    ]

    operations = [
        migrations.CreateModel(
            name='ViajeRegistrado',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('km_recorridos', models.FloatField(help_text='Kilómetros recorridos en el viaje')),
                ('km_odometro_anterior', models.PositiveIntegerField(help_text='Odómetro antes del viaje')),
                ('km_odometro_nuevo', models.PositiveIntegerField(help_text='Odómetro después del viaje')),
                ('duracion_segundos', models.PositiveIntegerField(default=0, help_text='Duración del viaje en segundos')),
                ('coordenadas_inicio', models.JSONField(blank=True, help_text="{'latitude': ..., 'longitude': ...}", null=True)),
                ('coordenadas_fin', models.JSONField(blank=True, help_text="{'latitude': ..., 'longitude': ...}", null=True)),
                ('velocidad_promedio_kmh', models.FloatField(default=0, help_text='Velocidad promedio en km/h')),
                ('fecha_inicio', models.DateTimeField(blank=True, help_text='Momento en que se inició el viaje', null=True)),
                ('fecha_registro', models.DateTimeField(auto_now_add=True)),
                ('vehiculo', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='viajes', to='vehiculos.vehiculo')),
            ],
            options={
                'verbose_name': 'viaje registrado',
                'verbose_name_plural': 'viajes registrados',
                'ordering': ['-fecha_registro'],
            },
        ),
    ]
