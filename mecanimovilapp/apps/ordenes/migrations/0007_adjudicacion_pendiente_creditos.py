# Generated manually for adjudicación post-créditos

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0006_solicitudpublica_vehiculo_inspeccion_precompra'),
    ]

    operations = [
        migrations.AddField(
            model_name='solicitudserviciopublica',
            name='fecha_limite_confirmacion_creditos',
            field=models.DateTimeField(
                blank=True,
                help_text='Plazo para que el proveedor elegido acredite créditos y confirme la adjudicación',
                null=True,
                verbose_name='Fecha límite confirmación créditos proveedor',
            ),
        ),
        migrations.AlterField(
            model_name='ofertaproveedor',
            name='estado',
            field=models.CharField(
                choices=[
                    ('enviada', 'Enviada'),
                    ('vista', 'Vista por Cliente'),
                    ('en_chat', 'En Conversación'),
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
                max_length=20,
                verbose_name='Estado',
            ),
        ),
        migrations.AlterField(
            model_name='solicitudserviciopublica',
            name='estado',
            field=models.CharField(
                choices=[
                    ('creada', 'Creada - Pendiente Servicios'),
                    ('seleccionando_servicios', 'Seleccionando Servicios'),
                    ('publicada', 'Publicada - Esperando Ofertas'),
                    ('con_ofertas', 'Con Ofertas Recibidas'),
                    ('esperando_creditos_proveedor', 'Esperando confirmación de créditos del proveedor'),
                    ('adjudicada', 'Adjudicada a Proveedor'),
                    ('pendiente_pago', 'Cliente Procesando Pago'),
                    ('pagada', 'Pago Completado - Listo para Iniciar'),
                    ('en_ejecucion', 'Servicio en Progreso'),
                    ('completada', 'Servicio Finalizado'),
                    ('expirada', 'Expirada Sin Ofertas'),
                    ('cancelada', 'Cancelada por Cliente'),
                ],
                db_index=True,
                default='creada',
                max_length=30,
                verbose_name='Estado',
            ),
        ),
    ]
