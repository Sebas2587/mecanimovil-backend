from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agente_ia', '0007_agente_cliente_memoria'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tallerconocimientochunk',
            name='fuente',
            field=models.CharField(
                choices=[
                    ('DOCUMENTO_TALLER', 'Documento del taller'),
                    ('CATALOGO_SERVICIO', 'Catálogo de servicios'),
                    ('HISTORICO_SERVICIO', 'Histórico de servicios'),
                    ('INSTRUCCION', 'Instrucciones personalizadas'),
                    ('CONVERSACION_EXITOSA', 'Conversación exitosa'),
                ],
                db_index=True,
                max_length=30,
            ),
        ),
    ]
