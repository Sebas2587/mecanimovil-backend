from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0019_componentesaludvehiculo_historial_conocido'),
    ]

    operations = [
        migrations.CreateModel(
            name='EventoSaludVehiculo',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tipo_evento', models.CharField(choices=[
                    ('SERVICIO_REALIZADO', 'Servicio realizado (checklist completado)'),
                    ('FALLA_REPORTADA', 'Componente reportó falla / 0 % salud'),
                    ('NIVEL_CRITICO', 'Componente alcanzó nivel CRÍTICO'),
                    ('VIAJE_KM', 'Acumulación de km por viaje GPS'),
                    ('CHECKLIST_KM', 'Lectura de odómetro desde checklist'),
                    ('REGISTRO_INICIAL', 'Vehículo registrado con historial inicial'),
                ], max_length=30)),
                ('marca', models.CharField(blank=True, max_length=100)),
                ('modelo', models.CharField(blank=True, max_length=100)),
                ('year', models.IntegerField(blank=True, null=True)),
                ('tipo_motor', models.CharField(blank=True, max_length=20)),
                ('transmision', models.CharField(blank=True, max_length=20)),
                ('kilometraje', models.PositiveIntegerField(default=0, help_text='Odómetro del vehículo al momento del evento.')),
                ('km_desde_ultimo_servicio', models.IntegerField(blank=True, help_text='Distancia entre el km del evento y el km del último servicio (positivo).', null=True)),
                ('meses_desde_ultimo_servicio', models.FloatField(blank=True, null=True)),
                ('vida_util_referencia_km', models.PositiveIntegerField(blank=True, help_text='eta de la regla aplicada (Weibull) al momento del evento.', null=True)),
                ('salud_porcentaje', models.FloatField(blank=True, help_text='Salud calculada al momento del evento.', null=True)),
                ('clima_condicion', models.CharField(blank=True, help_text='rain | heat | cold | normal (al momento del evento).', max_length=20)),
                ('temperatura_c', models.FloatField(blank=True, null=True)),
                ('humedad_pct', models.FloatField(blank=True, null=True)),
                ('promedio_km_dia', models.FloatField(blank=True, help_text='km/día calculado a partir de viajes recientes (si aplica).', null=True)),
                ('checklist_id', models.IntegerField(blank=True, null=True)),
                ('orden_id', models.IntegerField(blank=True, null=True)),
                ('viaje_id', models.IntegerField(blank=True, null=True)),
                ('metadata', models.JSONField(blank=True, default=dict, help_text='Datos adicionales del evento (ej. detalles_clima, geolocalización).')),
                ('fecha_evento', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('componente', models.ForeignKey(blank=True, help_text='Componente afectado. Null para eventos globales (viaje, registro).', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='eventos_salud', to='vehiculos.componentesalud')),
                ('vehiculo', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='eventos_salud', to='vehiculos.vehiculo')),
            ],
            options={
                'verbose_name': 'Evento de Salud (ML)',
                'verbose_name_plural': 'Eventos de Salud (ML)',
                'ordering': ['-fecha_evento'],
            },
        ),
        migrations.AddIndex(
            model_name='eventosaludvehiculo',
            index=models.Index(fields=['componente', 'tipo_evento'], name='evt_salud_comp_tipo_idx'),
        ),
        migrations.AddIndex(
            model_name='eventosaludvehiculo',
            index=models.Index(fields=['marca', 'modelo'], name='evt_salud_marca_modelo_idx'),
        ),
        migrations.AddIndex(
            model_name='eventosaludvehiculo',
            index=models.Index(fields=['tipo_evento', 'fecha_evento'], name='evt_salud_tipo_fecha_idx'),
        ),
    ]
