from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0001_initial'),
        ('agente_ia', '0016_consulta_casas_automatica'),
    ]

    operations = [
        migrations.CreateModel(
            name='AgenteDuenoHilo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('titulo', models.CharField(default='Nueva conversación', max_length=120)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('actualizado_en', models.DateTimeField(auto_now=True)),
                ('taller', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='hilos_agente_dueno',
                    to='usuarios.taller',
                )),
            ],
            options={
                'ordering': ['-actualizado_en'],
                'indexes': [
                    models.Index(fields=['taller', '-actualizado_en'], name='agente_dueno_hilo_taller'),
                ],
            },
        ),
        migrations.CreateModel(
            name='AgenteDuenoMensaje',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rol', models.CharField(choices=[('dueno', 'Dueño'), ('agente', 'Agente')], max_length=12)),
                ('texto', models.TextField()),
                ('vista', models.JSONField(blank=True, default=dict)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('hilo', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='mensajes',
                    to='agente_ia.AgenteDuenoHilo',
                )),
            ],
            options={
                'ordering': ['creado_en'],
            },
        ),
    ]
