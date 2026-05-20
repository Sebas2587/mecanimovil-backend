# Generated manually for agendamiento disponibilidad por duración

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('servicios', '0003_ofertaservicio_unique_por_marca'),
    ]

    operations = [
        migrations.AddField(
            model_name='ofertaservicio',
            name='duracion_minima_minutos',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Tiempo mínimo estimado para realizar el servicio (minutos)',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='ofertaservicio',
            name='duracion_maxima_minutos',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Tiempo máximo estimado para bloquear agenda y calcular ventanas libres',
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='ofertaservicio',
            name='duracion_estimada',
            field=models.TimeField(
                blank=True,
                help_text='Legacy: hora estimada (HH:MM). Preferir duracion_minima/maxima_minutos.',
                null=True,
            ),
        ),
    ]
