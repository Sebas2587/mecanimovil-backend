"""Estado agendando + recargo domicilio en config agente."""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('agente_ia', '0003_sesion_por_chat_y_pausa'),
        ('ordenes', '0027_cotizacion_libre_y_cita_por_confirmar'),
    ]

    operations = [
        migrations.AddField(
            model_name='talleragenteconfig',
            name='recargo_domicilio_clp',
            field=models.PositiveIntegerField(
                default=5000,
                help_text='Recargo fijo (CLP) que se suma a la mano de obra cuando la modalidad es a domicilio.',
            ),
        ),
        migrations.AddField(
            model_name='agenteconversacionsesion',
            name='cita_en_negociacion',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='agente_sesiones_negociacion',
                to='ordenes.citaagendapersonal',
            ),
        ),
        migrations.AlterField(
            model_name='agenteconversacionsesion',
            name='estado',
            field=models.CharField(
                choices=[
                    ('capturando', 'Capturando información'),
                    ('listo_para_cotizar', 'Listo para cotizar'),
                    ('esperando_revision_taller', 'Esperando revisión del taller'),
                    ('agendando', 'Agendando cita'),
                    ('pausado_por_taller', 'Pausado por taller'),
                    ('cerrado', 'Cerrado'),
                ],
                db_index=True,
                default='capturando',
                max_length=30,
            ),
        ),
    ]
