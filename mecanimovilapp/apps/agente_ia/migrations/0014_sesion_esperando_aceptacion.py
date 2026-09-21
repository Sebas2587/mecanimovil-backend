from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agente_ia', '0013_calidad_vitrina_aprendizaje'),
    ]

    operations = [
        migrations.AlterField(
            model_name='agenteconversacionsesion',
            name='estado',
            field=models.CharField(
                choices=[
                    ('capturando', 'Capturando información'),
                    ('listo_para_cotizar', 'Listo para cotizar'),
                    ('eligiendo_repuestos', 'Eligiendo repuestos'),
                    ('esperando_revision_taller', 'Esperando revisión del taller'),
                    ('esperando_aceptacion', 'Esperando aceptación de cotización'),
                    ('agendando', 'Agendando cita'),
                    ('coordinacion_terreno', 'Coordinación en terreno / en sitio'),
                    ('pausado_por_taller', 'Pausado por taller'),
                    ('cerrado', 'Cerrado'),
                ],
                db_index=True,
                default='capturando',
                max_length=30,
            ),
        ),
    ]
