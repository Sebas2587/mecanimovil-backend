# Generated manually for cotizacion canal IA

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0005_omnichannel_fields'),
        ('usuarios', '0020_webpushsubscription_app_origen'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('ordenes', '0023_guiareparacionguardada'),
    ]

    operations = [
        migrations.CreateModel(
            name='CotizacionCanal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('estado', models.CharField(choices=[('borrador', 'Borrador'), ('enviada', 'Enviada'), ('aceptada', 'Aceptada'), ('rechazada', 'Rechazada'), ('expirada', 'Expirada'), ('cancelada', 'Cancelada')], db_index=True, default='borrador', max_length=20)),
                ('modalidad', models.CharField(choices=[('taller', 'En taller'), ('domicilio', 'A domicilio')], default='taller', max_length=20)),
                ('vehiculo_marca', models.CharField(blank=True, default='', max_length=100)),
                ('vehiculo_modelo', models.CharField(blank=True, default='', max_length=100)),
                ('vehiculo_anio', models.PositiveIntegerField(blank=True, null=True)),
                ('vehiculo_patente', models.CharField(blank=True, default='', max_length=20)),
                ('vehiculo_cilindraje', models.CharField(blank=True, default='', max_length=50)),
                ('vehiculo_vin', models.CharField(blank=True, default='', max_length=50)),
                ('tipo_motor', models.CharField(blank=True, default='', max_length=20)),
                ('tipo_motor_label', models.CharField(blank=True, default='', max_length=80)),
                ('aviso_motor', models.TextField(blank=True, default='')),
                ('servicio_nombre', models.CharField(blank=True, default='', max_length=255)),
                ('descripcion_problema', models.TextField(blank=True, default='')),
                ('repuestos', models.JSONField(blank=True, default=list)),
                ('mano_obra_clp', models.DecimalField(decimal_places=0, default=0, max_digits=12)),
                ('costo_repuestos_clp', models.DecimalField(decimal_places=0, default=0, max_digits=12)),
                ('total_clp', models.DecimalField(decimal_places=0, default=0, max_digits=12)),
                ('duracion_minutos_estimada', models.PositiveIntegerField(blank=True, null=True)),
                ('advertencias', models.JSONField(blank=True, default=list)),
                ('contenido_ia', models.JSONField(blank=True, default=dict)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('tokens_entrada', models.PositiveIntegerField(default=0)),
                ('tokens_salida', models.PositiveIntegerField(default=0)),
                ('modelo_ia', models.CharField(blank=True, default='', max_length=80)),
                ('enviada_en', models.DateTimeField(blank=True, null=True)),
                ('aceptada_en', models.DateTimeField(blank=True, null=True)),
                ('rechazada_en', models.DateTimeField(blank=True, null=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('actualizado_en', models.DateTimeField(auto_now=True)),
                ('conversation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='cotizaciones_canal', to='chat.conversation')),
                ('creado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='cotizaciones_canal_creadas', to=settings.AUTH_USER_MODEL)),
                ('message_envio', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='cotizacion_canal_enviada', to='chat.message')),
                ('taller', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='cotizaciones_canal', to='usuarios.taller')),
            ],
            options={
                'verbose_name': 'cotización canal',
                'verbose_name_plural': 'cotizaciones canal',
                'ordering': ['-creado_en'],
            },
        ),
        migrations.CreateModel(
            name='CotizacionCanalPlantilla',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('titulo', models.CharField(max_length=255)),
                ('snapshot', models.JSONField(blank=True, default=dict)),
                ('uso_count', models.PositiveIntegerField(default=0)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('actualizado_en', models.DateTimeField(auto_now=True)),
                ('creado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='plantillas_cotizacion_canal', to=settings.AUTH_USER_MODEL)),
                ('taller', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='plantillas_cotizacion_canal', to='usuarios.taller')),
            ],
            options={
                'verbose_name': 'plantilla cotización canal',
                'verbose_name_plural': 'plantillas cotización canal',
                'ordering': ['-actualizado_en'],
            },
        ),
        migrations.AddIndex(
            model_name='cotizacioncanal',
            index=models.Index(fields=['conversation', 'estado'], name='ordenes_cot_conv_est_idx'),
        ),
        migrations.AddIndex(
            model_name='cotizacioncanal',
            index=models.Index(fields=['taller', '-creado_en'], name='ordenes_cot_taller_idx'),
        ),
        migrations.AddIndex(
            model_name='cotizacioncanalplantilla',
            index=models.Index(fields=['taller', '-actualizado_en'], name='ordenes_cot_pl_taller_idx'),
        ),
    ]
