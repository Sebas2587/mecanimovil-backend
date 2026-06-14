"""
Agrega fecha_completado_proveedor a ChecklistInstance.

Captura el momento exacto en que el técnico firma y cierra su parte del
checklist, independientemente de si el cliente ha firmado o no.
Permite calcular KPIs de tiempo real de ejecución sin incluir la espera
de firma del cliente.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0005_pendiente_firma_cliente_estado'),
    ]

    operations = [
        migrations.AddField(
            model_name='checklistinstance',
            name='fecha_completado_proveedor',
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text=(
                    'Momento en que el proveedor finaliza su parte (firma del técnico), '
                    'antes de esperar la firma del cliente. Usado en KPIs de tiempo real.'
                ),
            ),
        ),
    ]
