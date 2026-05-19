# Generated manually for agendamiento IA fase 2

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0010_agendamiento_ia_oferta_catalogo'),
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
                    ('pendiente_confirmacion', 'Pendiente confirmación proveedor (catálogo)'),
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
