# Generated manually for agendamiento IA asistido

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('servicios', '0002_initial'),
        ('ordenes', '0009_fotos_necesidad_solicitud_publica'),
    ]

    operations = [
        migrations.AddField(
            model_name='ofertaproveedor',
            name='metadata_ia',
            field=models.JSONField(
                blank=True,
                help_text='Resumen IA, temperatura, ids sugeridos (sin texto crudo de consultas efímeras)',
                null=True,
                verbose_name='Metadata IA',
            ),
        ),
        migrations.AddField(
            model_name='ofertaproveedor',
            name='oferta_servicio',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='ofertas_proveedor_generadas',
                to='servicios.ofertaservicio',
                verbose_name='Oferta de catálogo origen',
            ),
        ),
        migrations.AddField(
            model_name='ofertaproveedor',
            name='origen',
            field=models.CharField(
                choices=[
                    ('manual', 'Creada manualmente por proveedor'),
                    ('catalogo', 'Generada desde catálogo OfertaServicio'),
                    ('secundaria', 'Oferta secundaria en ejecución'),
                ],
                db_index=True,
                default='manual',
                max_length=20,
                verbose_name='Origen de la oferta',
            ),
        ),
        migrations.AddField(
            model_name='solicitudserviciopublica',
            name='metadata_ia_entrada',
            field=models.JSONField(
                blank=True,
                help_text='Entrada del asistente al crear (temperatura, origen texto/salud)',
                null=True,
                verbose_name='Metadata IA entrada',
            ),
        ),
    ]
