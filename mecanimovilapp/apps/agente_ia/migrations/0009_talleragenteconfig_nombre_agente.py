from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agente_ia', '0008_fuente_conversacion_exitosa'),
    ]

    operations = [
        migrations.AddField(
            model_name='talleragenteconfig',
            name='nombre_agente',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Nombre con el que el agente se presenta a los clientes (ej. Carlos, Sofía).',
                max_length=80,
            ),
        ),
    ]
