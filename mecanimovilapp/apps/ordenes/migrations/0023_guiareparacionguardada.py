from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0022_citaagendapersonaldetalle_vehiculo_vin'),
        ('usuarios', '0015_miembrotaller_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='GuiaReparacionGuardada',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('vehiculo_marca', models.CharField(blank=True, default='', max_length=100)),
                ('vehiculo_modelo', models.CharField(blank=True, default='', max_length=100)),
                ('vehiculo_anio', models.PositiveIntegerField(blank=True, null=True)),
                ('vehiculo_patente', models.CharField(blank=True, default='', max_length=20)),
                ('titulo', models.CharField(max_length=255)),
                ('contenido', models.JSONField(blank=True, default=dict)),
                ('origen', models.CharField(
                    choices=[('orden', 'Orden Mecanimovil'), ('cita', 'Cita personal')],
                    max_length=10,
                )),
                ('origen_id', models.PositiveIntegerField(blank=True, null=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('diagnostico_cita', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='guias_guardadas',
                    to='ordenes.diagnosticoasistidocitapersonal',
                )),
                ('diagnostico_orden', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='guias_guardadas',
                    to='ordenes.diagnosticoasistidoorden',
                )),
                ('miembro_taller', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='guias_reparacion_guardadas',
                    to='usuarios.miembrotaller',
                )),
                ('taller', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='guias_reparacion_guardadas',
                    to='usuarios.taller',
                )),
            ],
            options={
                'verbose_name': 'guía de reparación guardada',
                'verbose_name_plural': 'guías de reparación guardadas',
                'ordering': ['-creado_en'],
            },
        ),
        migrations.AddIndex(
            model_name='guiareparacionguardada',
            index=models.Index(
                fields=['miembro_taller', 'vehiculo_marca', 'vehiculo_modelo'],
                name='ordenes_gui_miembro_7a8b2c_idx',
            ),
        ),
    ]
