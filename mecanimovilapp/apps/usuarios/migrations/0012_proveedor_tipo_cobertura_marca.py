from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0011_resena_aspectos_kpi'),
    ]

    operations = [
        migrations.AddField(
            model_name='taller',
            name='tipo_cobertura_marca',
            field=models.CharField(
                choices=[
                    ('especialista', 'Especialista en marcas'),
                    ('multimarca', 'Multimarca'),
                ],
                default='especialista',
                help_text='Especialista: marcas concretas. Multimarca: atiende cualquier marca.',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='mecanicodomicilio',
            name='tipo_cobertura_marca',
            field=models.CharField(
                choices=[
                    ('especialista', 'Especialista en marcas'),
                    ('multimarca', 'Multimarca'),
                ],
                default='especialista',
                help_text='Especialista: marcas concretas. Multimarca: atiende cualquier marca.',
                max_length=20,
            ),
        ),
    ]
