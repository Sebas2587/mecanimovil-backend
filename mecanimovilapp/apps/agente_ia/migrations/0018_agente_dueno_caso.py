from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0001_initial'),
        ('agente_ia', '0017_agente_dueno_hilo'),
    ]

    operations = [
        migrations.AddField(
            model_name='agenteduenohilo',
            name='caso_anclado',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='agenteduenohilo',
            name='ultima_tarjeta',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='agenteduenohilo',
            name='accion_pendiente',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.CreateModel(
            name='AgenteDuenoCorreccion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('caso_id', models.CharField(blank=True, default='', max_length=40)),
                ('descarta', models.CharField(
                    choices=[
                        ('cliente', 'Ese contacto no es el cliente'),
                        ('auto_desde_servicio', 'La marca del servicio no es el auto'),
                    ],
                    max_length=32,
                )),
                ('valor', models.CharField(blank=True, default='', max_length=200)),
                ('texto', models.TextField()),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('taller', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='correcciones_agente_dueno',
                    to='usuarios.taller',
                )),
            ],
            options={
                'ordering': ['-creado_en'],
                'indexes': [
                    models.Index(fields=['taller', '-creado_en'], name='agente_dueno_corr_taller'),
                ],
            },
        ),
        migrations.CreateModel(
            name='AgenteDuenoAvisoCliente',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('caso_id', models.CharField(max_length=40)),
                ('destinatario', models.CharField(blank=True, default='', max_length=200)),
                ('telefono', models.CharField(blank=True, default='', max_length=30)),
                ('texto', models.TextField()),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('taller', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='avisos_agente_dueno',
                    to='usuarios.taller',
                )),
            ],
            options={
                'ordering': ['-creado_en'],
                'indexes': [
                    models.Index(fields=['taller', 'caso_id'], name='agente_dueno_aviso_caso'),
                ],
            },
        ),
    ]
