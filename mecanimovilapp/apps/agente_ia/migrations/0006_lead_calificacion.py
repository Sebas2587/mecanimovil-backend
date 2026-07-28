from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('agente_ia', '0005_agente_activo_por_defecto'),
    ]

    operations = [
        migrations.CreateModel(
            name='LeadCalificacion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('categoria', models.CharField(
                    choices=[
                        ('sin_calificar', 'Sin calificar'),
                        ('curioso', 'Curioso'),
                        ('comparando', 'Comparando'),
                        ('sin_presupuesto', 'Sin presupuesto'),
                        ('interesado_calificado', 'Interesado calificado'),
                        ('listo_agendar', 'Listo para agendar'),
                        ('no_automotriz', 'No automotriz'),
                    ],
                    db_index=True,
                    default='sin_calificar',
                    max_length=30,
                )),
                ('score', models.PositiveSmallIntegerField(default=0)),
                ('senal_llm', models.CharField(blank=True, default='', max_length=30)),
                ('senales', models.JSONField(blank=True, default=dict)),
                ('actualizado_en', models.DateTimeField(auto_now=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('conversation', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='lead_calificacion',
                    to='chat.conversation',
                )),
                ('taller', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='leads_calificados',
                    to='usuarios.taller',
                )),
            ],
            options={
                'verbose_name': 'Calificación de lead',
                'verbose_name_plural': 'Calificaciones de leads',
            },
        ),
        migrations.AddIndex(
            model_name='leadcalificacion',
            index=models.Index(fields=['taller', 'categoria'], name='agente_ia_lead_taller_cat'),
        ),
        migrations.AddIndex(
            model_name='leadcalificacion',
            index=models.Index(fields=['taller', '-score'], name='agente_ia_lead_taller_score'),
        ),
    ]
