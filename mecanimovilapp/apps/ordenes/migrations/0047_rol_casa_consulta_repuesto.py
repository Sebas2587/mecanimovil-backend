import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0005_omnichannel_fields'),
        ('omnichannel', '0003_externalcontact_rol'),
        ('ordenes', '0046_solicitudservicio_numero_publico'),
    ]

    operations = [
        migrations.AddField(
            model_name='proveedorrepuestos',
            name='telefono_norm',
            field=models.CharField(blank=True, db_index=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='proveedorrepuestos',
            name='external_contact',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='casas_repuestos',
                to='omnichannel.externalcontact',
            ),
        ),
        migrations.CreateModel(
            name='ConsultaRepuesto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('repuesto_id', models.CharField(db_index=True, max_length=64)),
                ('pieza_nombre', models.CharField(max_length=200)),
                ('vehiculo_snapshot', models.JSONField(blank=True, default=dict)),
                ('estado', models.CharField(
                    choices=[
                        ('esperando', 'Esperando'),
                        ('recordada', 'Recordada'),
                        ('respondida', 'Respondida'),
                        ('por_revisar', 'Por revisar'),
                        ('sin_respuesta', 'Sin respuesta'),
                        ('sin_stock', 'Sin stock'),
                        ('fallida', 'No se pudo enviar'),
                        ('cancelada', 'Cancelada'),
                    ],
                    db_index=True,
                    default='esperando',
                    max_length=20,
                )),
                ('origen', models.CharField(default='manual', max_length=16)),
                ('unica', models.BooleanField(default=False)),
                ('extraccion', models.JSONField(blank=True, default=dict)),
                ('confianza', models.FloatField(default=0)),
                ('recordatorio_en', models.DateTimeField(blank=True, null=True)),
                ('cierra_en', models.DateTimeField(blank=True, null=True)),
                ('recordatorio_enviado', models.BooleanField(default=False)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('actualizado_en', models.DateTimeField(auto_now=True)),
                ('conversation', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='consultas_repuesto', to='chat.conversation')),
                ('cotizacion', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='consultas_repuesto', to='ordenes.cotizacioncanal')),
                ('mensaje_respuesta', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='consultas_repuesto_respuesta', to='chat.message')),
                ('mensaje_saliente', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='consultas_repuesto_salida', to='chat.message')),
                ('proveedor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='consultas', to='ordenes.proveedorrepuestos')),
                ('taller', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='consultas_repuesto', to='usuarios.taller')),
            ],
            options={
                'verbose_name': 'consulta de repuesto',
                'verbose_name_plural': 'consultas de repuesto',
            },
        ),
        migrations.AddIndex(
            model_name='consultarepuesto',
            index=models.Index(fields=['estado', 'cierra_en'], name='ordenes_consulta_cierre_idx'),
        ),
        migrations.AddConstraint(
            model_name='consultarepuesto',
            constraint=models.UniqueConstraint(
                condition=models.Q(estado__in=['esperando', 'recordada']),
                fields=('cotizacion', 'repuesto_id', 'proveedor'),
                name='ordenes_consulta_repuesto_abierta_uniq',
            ),
        ),
    ]
