"""
Estado intermedio PENDIENTE_FIRMA_CLIENTE para soportar firma diferida del
cliente desde la app del usuario (change: firma-cliente-diferida-checklist).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0004_checklist_intencion_componente_salud'),
    ]

    operations = [
        migrations.AlterField(
            model_name='checklistinstance',
            name='estado',
            field=models.CharField(
                choices=[
                    ('PENDIENTE', 'Pendiente de inicio'),
                    ('EN_PROGRESO', 'En progreso'),
                    ('PAUSADO', 'Pausado temporalmente'),
                    ('PENDIENTE_FIRMA_CLIENTE', 'Pendiente de firma del cliente'),
                    ('COMPLETADO', 'Completado'),
                    ('CANCELADO', 'Cancelado'),
                ],
                default='PENDIENTE',
                max_length=30,
            ),
        ),
    ]
