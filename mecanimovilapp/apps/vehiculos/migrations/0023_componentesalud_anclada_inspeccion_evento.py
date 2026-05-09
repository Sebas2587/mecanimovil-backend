"""
Anclaje Weibull desde inspección de checklist.

- Agrega ComponenteSaludVehiculo.salud_anclada_pct para que HealthEngine
  proyecte la curva Weibull desde el porcentaje declarado por un técnico.
- Agrega INSPECCION_DECLARADA a EventoSaludVehiculo.TIPO_EVENTO_CHOICES
  para que el dataset ML diferencie reemplazos de inspecciones.
"""
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0022_rename_evt_salud_comp_tipo_idx_vehiculos_e_compone_d77ded_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='componentesaludvehiculo',
            name='salud_anclada_pct',
            field=models.FloatField(
                blank=True,
                help_text=(
                    'Porcentaje de vida útil declarado en la última inspección de checklist. '
                    'Si no es null, el HealthEngine ancla la curva Weibull en este punto. '
                    'Se limpia (None) cuando el componente se reemplaza.'
                ),
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(0),
                    django.core.validators.MaxValueValidator(100),
                ],
            ),
        ),
        migrations.AlterField(
            model_name='eventosaludvehiculo',
            name='tipo_evento',
            field=models.CharField(
                choices=[
                    ('SERVICIO_REALIZADO',   'Servicio realizado (checklist completado)'),
                    ('INSPECCION_DECLARADA', 'Inspección con porcentaje declarado por técnico'),
                    ('FALLA_REPORTADA',      'Componente reportó falla / 0 % salud'),
                    ('NIVEL_CRITICO',        'Componente alcanzó nivel CRÍTICO'),
                    ('VIAJE_KM',             'Acumulación de km por viaje GPS'),
                    ('CHECKLIST_KM',         'Lectura de odómetro desde checklist'),
                    ('REGISTRO_INICIAL',     'Vehículo registrado con historial inicial'),
                ],
                max_length=30,
            ),
        ),
    ]
