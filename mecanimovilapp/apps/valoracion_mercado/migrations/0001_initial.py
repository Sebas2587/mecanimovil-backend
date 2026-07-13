# Generated manually for valoracion_mercado

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('vehiculos', '0026_health_notif_tracking'),
    ]

    operations = [
        migrations.CreateModel(
            name='CurvaDepreciacionSegmento',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tipo_vehiculo', models.CharField(max_length=40, unique=True)),
                ('tasa_anual_pct', models.DecimalField(decimal_places=2, default=7.0, max_digits=5)),
                ('activo', models.BooleanField(default=True)),
            ],
            options={
                'verbose_name': 'curva de depreciación',
                'verbose_name_plural': 'curvas de depreciación',
            },
        ),
        migrations.CreateModel(
            name='AvisoExternoVehiculo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fuente', models.CharField(choices=[('mercadolibre', 'MercadoLibre'), ('chileautos', 'Chileautos')], max_length=32)),
                ('external_id', models.CharField(max_length=128)),
                ('url', models.URLField(blank=True, default='', max_length=512)),
                ('marca_texto', models.CharField(blank=True, default='', max_length=80)),
                ('modelo_texto', models.CharField(blank=True, default='', max_length=120)),
                ('year', models.PositiveIntegerField(blank=True, null=True)),
                ('kilometraje', models.PositiveIntegerField(blank=True, null=True)),
                ('precio', models.PositiveIntegerField()),
                ('region', models.CharField(blank=True, default='', max_length=80)),
                ('titulo_raw', models.TextField(blank=True, default='')),
                ('fecha_primera_vista', models.DateTimeField(auto_now_add=True)),
                ('fecha_ultima_vista', models.DateTimeField(auto_now=True)),
                ('activo', models.BooleanField(default=True)),
                ('fecha_removido', models.DateTimeField(blank=True, null=True)),
                ('marca', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='avisos_externos', to='vehiculos.marcavehiculo')),
                ('modelo', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='avisos_externos', to='vehiculos.modelo')),
            ],
            options={
                'verbose_name': 'aviso externo de vehículo',
                'verbose_name_plural': 'avisos externos de vehículos',
                'unique_together': {('fuente', 'external_id')},
            },
        ),
        migrations.AddIndex(
            model_name='avisoexternovehiculo',
            index=models.Index(fields=['marca', 'modelo', 'year', 'activo'], name='valoracion__marca_i_8a3f2d_idx'),
        ),
        migrations.AddIndex(
            model_name='avisoexternovehiculo',
            index=models.Index(fields=['fecha_ultima_vista'], name='valoracion__fecha_u_4b1c9e_idx'),
        ),
        migrations.CreateModel(
            name='SegmentoValorHistorial',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('year_bucket', models.PositiveIntegerField(help_text='Año representativo del segmento')),
                ('year_min', models.PositiveIntegerField()),
                ('year_max', models.PositiveIntegerField()),
                ('fecha_snapshot', models.DateField()),
                ('n_anuncios_activos', models.PositiveIntegerField(default=0)),
                ('precio_mediana', models.PositiveIntegerField(default=0)),
                ('precio_p25', models.PositiveIntegerField(default=0)),
                ('precio_p75', models.PositiveIntegerField(default=0)),
                ('tasa_rotacion_30d_pct', models.DecimalField(blank=True, decimal_places=2, help_text='Porcentaje de avisos removidos en ~30 días', max_digits=5, null=True)),
                ('marca', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='segmentos_valor', to='vehiculos.marcavehiculo')),
                ('modelo', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='segmentos_valor', to='vehiculos.modelo')),
            ],
            options={
                'verbose_name': 'histórico de segmento',
                'verbose_name_plural': 'históricos de segmentos',
                'ordering': ['-fecha_snapshot'],
                'unique_together': {('marca', 'modelo', 'year_bucket', 'fecha_snapshot')},
            },
        ),
        migrations.CreateModel(
            name='TasacionHistorial',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha', models.DateField()),
                ('precio_mercado_promedio', models.PositiveIntegerField(default=0)),
                ('banda_min', models.PositiveIntegerField(default=0)),
                ('banda_max', models.PositiveIntegerField(default=0)),
                ('tasacion_fiscal', models.PositiveIntegerField(default=0)),
                ('mileage', models.PositiveIntegerField(blank=True, null=True)),
                ('vehiculo', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tasaciones_historial', to='vehiculos.vehiculo')),
            ],
            options={
                'verbose_name': 'histórico de tasación',
                'verbose_name_plural': 'históricos de tasación',
                'ordering': ['-fecha'],
                'unique_together': {('vehiculo', 'fecha')},
            },
        ),
        migrations.CreateModel(
            name='ValoracionVehiculo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('valor_real_hoy', models.PositiveIntegerField(default=0)),
                ('valor_real_rango_min', models.PositiveIntegerField(default=0)),
                ('valor_real_rango_max', models.PositiveIntegerField(default=0)),
                ('confianza', models.CharField(choices=[('alta', 'Alta'), ('media', 'Media'), ('estimado', 'Estimado')], default='estimado', max_length=16)),
                ('liquidez_score', models.PositiveSmallIntegerField(default=0)),
                ('liquidez_label', models.CharField(choices=[('facil', 'Fácil'), ('moderado', 'Moderado'), ('dificil', 'Difícil'), ('calculando', 'Calculando')], default='calculando', max_length=16)),
                ('liquidez_razones', models.JSONField(blank=True, default=list)),
                ('proyeccion', models.JSONField(blank=True, default=list)),
                ('histograma', models.JSONField(blank=True, default=list)),
                ('meta', models.JSONField(blank=True, default=dict)),
                ('fecha_calculo', models.DateTimeField(auto_now=True)),
                ('vehiculo', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='valoracion_mercado', to='vehiculos.vehiculo')),
            ],
            options={
                'verbose_name': 'valoración de vehículo',
                'verbose_name_plural': 'valoraciones de vehículos',
            },
        ),
    ]
