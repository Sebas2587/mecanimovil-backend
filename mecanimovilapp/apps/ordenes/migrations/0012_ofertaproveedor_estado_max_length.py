# Ampliar max_length: pendiente_confirmacion tiene 22 caracteres

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0011_pendiente_confirmacion_catalogo'),
    ]

    operations = [
        migrations.AlterField(
            model_name='ofertaproveedor',
            name='estado',
            field=models.CharField(
                choices=[
                    ('enviada', 'Enviada'),
                    ('vista', 'Vista por Cliente'),
                    ('en_chat', 'En Conversación'),
                    ('pendiente_confirmacion', 'Pendiente confirmación proveedor (catálogo)'),
                    ('pendiente_creditos', 'Pendiente créditos proveedor'),
                    ('aceptada', 'Aceptada por Cliente'),
                    ('pendiente_pago', 'Cliente Procesando Pago'),
                    ('pagada_parcialmente', 'Pagada Parcialmente - Pendiente Saldo'),
                    ('pagada', 'Pagada - Listo para Iniciar'),
                    ('en_ejecucion', 'En Ejecución - Servicio en Progreso'),
                    ('completada', 'Completada - Servicio Finalizado'),
                    ('rechazada', 'Rechazada'),
                    ('retirada', 'Retirada por Proveedor'),
                    ('expirada', 'Expirada'),
                ],
                db_index=True,
                default='enviada',
                max_length=30,
                verbose_name='Estado',
            ),
        ),
    ]
