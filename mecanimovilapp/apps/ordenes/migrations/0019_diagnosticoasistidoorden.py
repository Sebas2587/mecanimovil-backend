# Generated manually for asistente-diagnostico-ia change

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0018_solicitud_fecha_pendiente_aceptacion'),
        ('usuarios', '0015_miembrotaller_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='DiagnosticoAsistidoOrden',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('contenido', models.JSONField(blank=True, default=dict)),
                ('estado', models.CharField(
                    choices=[
                        ('completado', 'Completado'),
                        ('error', 'Error'),
                        ('deshabilitado', 'Deshabilitado'),
                    ],
                    default='completado',
                    max_length=20,
                )),
                ('error', models.CharField(blank=True, default='', max_length=500)),
                ('latencia_ms', models.PositiveIntegerField(default=0)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('generado_por', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='diagnosticos_generados',
                    to='usuarios.miembrotaller',
                )),
                ('orden', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='diagnosticos_asistidos',
                    to='ordenes.solicitudservicio',
                )),
            ],
            options={
                'verbose_name': 'diagnóstico asistido de orden',
                'verbose_name_plural': 'diagnósticos asistidos de orden',
                'ordering': ['-creado_en'],
            },
        ),
    ]
