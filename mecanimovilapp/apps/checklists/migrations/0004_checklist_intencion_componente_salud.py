"""
Granularidad de salud en checklists:

- Catálogo: nuevo tipo de pregunta COMPONENT_HEALTH (slider 0–100%).
- ChecklistTemplate: tipo_intencion_default (REPARACION / INSPECCION / PRECOMPRA / MIXTO).
- ChecklistItemTemplate: tipo_actualizacion + componente_salud_asociado (FK a vehiculos.ComponenteSalud).

Reemplaza el dict mapeo_componentes hardcoded por una asociación explícita.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0003_initial'),
        # Solo se necesita ComponenteSalud, que llegó en 0001_initial de vehiculos.
        ('vehiculos', '0022_rename_evt_salud_comp_tipo_idx_vehiculos_e_compone_d77ded_idx_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='checklistitemcatalog',
            name='tipo_pregunta',
            field=models.CharField(
                choices=[
                    ('TEXT', 'Texto libre'),
                    ('NUMBER', 'Número'),
                    ('BOOLEAN', 'Sí/No (Booleano)'),
                    ('SELECT', 'Selección única'),
                    ('MULTISELECT', 'Selección múltiple'),
                    ('PHOTO', 'Fotografía'),
                    ('SIGNATURE', 'Firma digital'),
                    ('LOCATION', 'Ubicación GPS'),
                    ('DATETIME', 'Fecha y hora'),
                    ('RATING', 'Calificación (1-5 estrellas)'),
                    ('KILOMETER_INPUT', 'Entrada de kilometraje'),
                    ('FUEL_GAUGE', 'Medidor de combustible'),
                    ('FLUID_LEVEL', 'Nivel de fluidos'),
                    ('COMPONENT_HEALTH', 'Vida útil de componente (slider 0–100%)'),
                    ('INVENTORY_CHECKLIST', 'Lista de inventario'),
                    ('SERVICE_SELECTION', 'Selección de servicios'),
                    ('VEHICLE_CONDITION', 'Estado del vehículo'),
                    ('VEHICLE_DIAGRAM', 'Diagrama de vehículo'),
                    ('DAMAGE_REPORT', 'Reporte de daños'),
                    ('EXTERIOR_INSPECTION', 'Inspección exterior'),
                    ('INTERIOR_INSPECTION', 'Inspección interior'),
                    ('ENGINE_INSPECTION', 'Inspección del motor'),
                    ('ELECTRICAL_CHECK', 'Verificación eléctrica'),
                    ('BRAKE_CHECK', 'Verificación de frenos'),
                    ('SUSPENSION_CHECK', 'Verificación de suspensión'),
                    ('TIRE_CONDITION', 'Estado de neumáticos'),
                    ('FINAL_NOTES', 'Notas finales'),
                    ('CLIENT_CONFIRMATION', 'Confirmación del cliente'),
                    ('WORK_SUMMARY', 'Resumen del trabajo'),
                ],
                help_text='Tipo de pregunta/input para este item',
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name='checklisttemplate',
            name='tipo_intencion_default',
            field=models.CharField(
                choices=[
                    ('REPARACION', 'Reparación / reemplazo de componentes'),
                    ('INSPECCION', 'Inspección / diagnóstico'),
                    ('PRECOMPRA', 'Inspección pre-compra (no afecta salud)'),
                    ('MIXTO', 'Mixto (definido a nivel de ítem)'),
                ],
                default='MIXTO',
                help_text=(
                    'Intención por defecto del checklist sobre la salud del vehículo. '
                    'Cada ítem puede sobrescribirla con su propio tipo_actualizacion.'
                ),
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='checklistitemtemplate',
            name='tipo_actualizacion',
            field=models.CharField(
                blank=True,
                choices=[
                    ('REEMPLAZA', 'Reemplaza el componente (resetea salud a 100%)'),
                    ('INSPECCIONA', 'Inspecciona y declara estado actual del componente'),
                    ('INFORMATIVO', 'No afecta métricas de salud'),
                ],
                help_text=(
                    'Si null, hereda de checklist_template.tipo_intencion_default. '
                    'REEMPLAZA: setea salud=100. INSPECCIONA: usa el valor declarado. '
                    'INFORMATIVO: no toca métricas.'
                ),
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='checklistitemtemplate',
            name='componente_salud_asociado',
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    'Componente cuya salud se actualiza con la respuesta a este ítem. '
                    'Sustituye al antiguo mapeo_componentes por substring.'
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='checklist_item_templates',
                to='vehiculos.componentesalud',
            ),
        ),
    ]
