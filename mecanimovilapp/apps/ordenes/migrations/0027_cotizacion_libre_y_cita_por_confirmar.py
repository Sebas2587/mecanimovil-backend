# Generated manually for cotización libre + cita por confirmar

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0026_citaagendapersonal_conversation_origen'),
    ]

    operations = [
        migrations.AddField(
            model_name='citaagendapersonal',
            name='horario_por_confirmar',
            field=models.BooleanField(
                default=False,
                help_text='True si la cita se creó desde cotización pública sin horario definido.',
            ),
        ),
        migrations.AddField(
            model_name='citaagendapersonal',
            name='cotizacion_canal_origen',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='citas_generadas',
                to='ordenes.cotizacioncanal',
            ),
        ),
        migrations.AddField(
            model_name='cotizacioncanal',
            name='cliente_nombre',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
        migrations.AddField(
            model_name='cotizacioncanal',
            name='cliente_telefono',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='cotizacioncanal',
            name='es_libre',
            field=models.BooleanField(
                default=False,
                help_text='Cotización creada sin conversación omnicanal (link público).',
            ),
        ),
        migrations.AddField(
            model_name='cotizacioncanal',
            name='token',
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='cotizacioncanal',
            name='url_publica',
            field=models.URLField(blank=True, default='', max_length=500),
        ),
        migrations.AddField(
            model_name='cotizacioncanal',
            name='visto_en',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='cotizacioncanal',
            name='conversation',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='cotizaciones_canal',
                to='chat.conversation',
            ),
        ),
    ]
