from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('agente_ia', '0012_leadcalificacion_motivo_perdida_and_more'),
        ('ordenes', '0044_vitrina_seleccion_repuesto'),
    ]

    operations = [
        migrations.AddField(
            model_name='talleragenteconfig',
            name='preguntar_calidad_repuestos',
            field=models.BooleanField(default=True, help_text='Si está activo, el agente puede preguntar calidad (original/OEM/alternativo).'),
        ),
        migrations.AddField(
            model_name='talleragenteconfig',
            name='vitrina_repuestos_habilitada',
            field=models.BooleanField(default=True, help_text='Si el agente está activo, puede enviar la vitrina pública de opciones.'),
        ),
        migrations.AddField(
            model_name='talleragenteconfig',
            name='vitrina_muestra_bandas',
            field=models.BooleanField(default=True, help_text='Si hay ≥2 fuentes, mostrar banda de referencia en la vitrina.'),
        ),
        migrations.AddField(
            model_name='agenteconversacionsesion',
            name='vitrina_activa',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sesiones_agente', to='ordenes.vitrinarepuestos'),
        ),
        migrations.AlterField(
            model_name='agenteconversacionsesion',
            name='estado',
            field=models.CharField(
                choices=[
                    ('capturando', 'Capturando información'),
                    ('listo_para_cotizar', 'Listo para cotizar'),
                    ('eligiendo_repuestos', 'Eligiendo repuestos'),
                    ('esperando_revision_taller', 'Esperando revisión del taller'),
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
        migrations.AddField(
            model_name='agenteclientememoria',
            name='calidad_preferida',
            field=models.CharField(blank=True, default='', max_length=16),
        ),
        migrations.AddField(
            model_name='agenteclientememoria',
            name='preferencias_repuestos',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name='agenteaprendizajediario',
            name='tipo_hallazgo',
            field=models.CharField(
                choices=[
                    ('lead_perdido', 'Lead perdido'),
                    ('respuesta_insuficiente', 'Respuesta insuficiente'),
                    ('correccion_sistematica', 'Corrección sistemática'),
                    ('patron_alta_confianza', 'Patrón alta confianza'),
                    ('seleccion_repuesto', 'Selección de repuesto'),
                ],
                db_index=True,
                max_length=40,
            ),
        ),
    ]
