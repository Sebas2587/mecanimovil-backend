from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('agente_ia', '0006_lead_calificacion'),
    ]

    operations = [
        migrations.CreateModel(
            name='AgenteClienteMemoria',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('resumen', models.TextField(blank=True, default='')),
                (
                    'disposicion_reciente',
                    models.CharField(
                        blank=True,
                        choices=[
                            ('curioso', 'Curioso / asesoría'),
                            ('no_listo', 'No listo para cotizar'),
                            ('interesado', 'Interesado'),
                            ('listo_agendar', 'Listo para agendar'),
                        ],
                        default='',
                        max_length=30,
                    ),
                ),
                ('actualizado_en', models.DateTimeField(auto_now=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                (
                    'external_contact',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='memorias_agente',
                        to='omnichannel.externalcontact',
                    ),
                ),
                (
                    'taller',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='memorias_clientes_agente',
                        to='usuarios.taller',
                    ),
                ),
                (
                    'ultima_conversacion',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='+',
                        to='chat.conversation',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Memoria cliente agente IA',
                'verbose_name_plural': 'Memorias clientes agente IA',
            },
        ),
        migrations.AddIndex(
            model_name='agenteclientememoria',
            index=models.Index(fields=['taller', '-actualizado_en'], name='agente_ia_mem_taller_idx'),
        ),
        migrations.AddConstraint(
            model_name='agenteclientememoria',
            constraint=models.UniqueConstraint(
                fields=('taller', 'external_contact'),
                name='agente_ia_memoria_taller_contacto_unique',
            ),
        ),
    ]
