# M2M ComponenteSalud -> Servicio para modal salud (ej. Bujías -> Cambio de bujías)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('servicios', '0002_initial'),
        ('vehiculos', '0014_regla_intervalo_meses'),
    ]

    operations = [
        migrations.AddField(
            model_name='componentesalud',
            name='servicios_asociados',
            field=models.ManyToManyField(
                blank=True,
                help_text='Servicios sugeridos al tocar este componente en salud del vehículo (modal en app).',
                related_name='componentes_salud',
                to='servicios.servicio',
            ),
        ),
    ]
