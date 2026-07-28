from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agente_ia', '0009_talleragenteconfig_nombre_agente'),
    ]

    operations = [
        migrations.AddField(
            model_name='talleragenteconfig',
            name='nivel_insistencia',
            field=models.CharField(
                choices=[('bajo', 'Bajo'), ('medio', 'Medio'), ('alto', 'Alto')],
                default='medio',
                help_text='Qué tan insistente es el agente al empujar cotización/agenda.',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='talleragenteconfig',
            name='permite_estimados_historicos',
            field=models.BooleanField(
                default=True,
                help_text='Si está activo, el agente puede citar referencias históricas cuando no hay tarifa de catálogo.',
            ),
        ),
        migrations.AddField(
            model_name='talleragenteconfig',
            name='tono_ventas',
            field=models.CharField(
                choices=[
                    ('conservador', 'Conservador'),
                    ('balanceado', 'Balanceado'),
                    ('proactivo', 'Proactivo'),
                ],
                default='balanceado',
                help_text='Estilo comercial del agente (asesoría vs cierre).',
                max_length=15,
            ),
        ),
        migrations.AddField(
            model_name='talleragenteconfig',
            name='requiere_direccion_antes_de_cotizar',
            field=models.BooleanField(
                default=False,
                help_text='Si está activo, el agente debe pedir dirección del cliente antes de armar borrador.',
            ),
        ),
    ]
