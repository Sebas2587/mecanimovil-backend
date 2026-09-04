from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0005_omnichannel_fields'),
        ('usuarios', '0024_dias_validez_cotizacion'),
        ('ordenes', '0043_calidad_imagen_repuesto'),
    ]

    operations = [
        migrations.CreateModel(
            name='VitrinaRepuestos',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(db_index=True, max_length=64, unique=True)),
                ('lineas', models.JSONField(blank=True, default=list)),
                ('seleccion', models.JSONField(blank=True, default=list)),
                ('estado', models.CharField(choices=[('enviada', 'Enviada'), ('abierta', 'Abierta'), ('respondida', 'Respondida'), ('expirada', 'Expirada')], db_index=True, default='enviada', max_length=16)),
                ('expira_en', models.DateTimeField(db_index=True)),
                ('enviada_en', models.DateTimeField(blank=True, null=True)),
                ('abierta_en', models.DateTimeField(blank=True, null=True)),
                ('respondida_en', models.DateTimeField(blank=True, null=True)),
                ('recordatorio_enviado', models.BooleanField(default=False)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('actualizado_en', models.DateTimeField(auto_now=True)),
                ('conversation', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='vitrinas_repuestos', to='chat.conversation')),
                ('cotizacion', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='vitrinas_repuestos', to='ordenes.cotizacioncanal')),
                ('taller', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='vitrinas_repuestos', to='usuarios.taller')),
            ],
            options={
                'verbose_name': 'vitrina de repuestos',
                'verbose_name_plural': 'vitrinas de repuestos',
            },
        ),
        migrations.CreateModel(
            name='SeleccionRepuestoEvento',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('linea_id', models.CharField(blank=True, default='', max_length=64)),
                ('familia', models.CharField(blank=True, default='', max_length=40)),
                ('propuesta_ia_calidad', models.CharField(blank=True, default='', max_length=16)),
                ('cliente_calidad', models.CharField(blank=True, default='', max_length=16)),
                ('taller_calidad', models.CharField(blank=True, default='', max_length=16)),
                ('propuesta_ia_opcion_id', models.CharField(blank=True, default='', max_length=64)),
                ('cliente_opcion_id', models.CharField(blank=True, default='', max_length=64)),
                ('taller_opcion_id', models.CharField(blank=True, default='', max_length=64)),
                ('cambio_calidad', models.BooleanField(default=False)),
                ('delta_precio_pct', models.FloatField(blank=True, null=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('cotizacion', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='eventos_seleccion_repuesto', to='ordenes.cotizacioncanal')),
                ('taller', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='eventos_seleccion_repuesto', to='usuarios.taller')),
            ],
            options={
                'verbose_name': 'evento selección repuesto',
                'verbose_name_plural': 'eventos selección repuesto',
            },
        ),
        migrations.CreateModel(
            name='VehiculoPreferenciaRepuesto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('patente', models.CharField(max_length=12)),
                ('calidad_preferida', models.CharField(blank=True, default='', max_length=16)),
                ('muestras', models.PositiveIntegerField(default=0)),
                ('por_familia', models.JSONField(blank=True, default=dict)),
                ('actualizado_en', models.DateTimeField(auto_now=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('taller', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='preferencias_repuesto_vehiculo', to='usuarios.taller')),
            ],
            options={
                'verbose_name': 'preferencia repuesto vehículo',
                'verbose_name_plural': 'preferencias repuesto vehículo',
            },
        ),
        migrations.AddIndex(
            model_name='vitrinarepuestos',
            index=models.Index(fields=['taller', '-creado_en'], name='ordenes_vitrina_taller_idx'),
        ),
        migrations.AddIndex(
            model_name='vitrinarepuestos',
            index=models.Index(fields=['estado', 'expira_en'], name='ordenes_vitrina_estado_idx'),
        ),
        migrations.AddIndex(
            model_name='seleccionrepuestoevento',
            index=models.Index(fields=['taller', 'familia', '-creado_en'], name='ordenes_selrep_fam_idx'),
        ),
        migrations.AddConstraint(
            model_name='vehiculopreferenciarepuesto',
            constraint=models.UniqueConstraint(fields=('taller', 'patente'), name='ordenes_vehpref_taller_patente_uniq'),
        ),
    ]
