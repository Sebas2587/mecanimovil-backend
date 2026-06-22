import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0019_miembrotaller_foto'),
        ('ordenes', '0016_citaagendapersonal_miembro_taller_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='solicitudserviciopublica',
            name='miembro_taller_preferido',
            field=models.ForeignKey(
                blank=True,
                help_text='Técnico del taller elegido por el cliente al agendar',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='solicitudes_preferidas',
                to='usuarios.miembrotaller',
                verbose_name='Técnico preferido',
            ),
        ),
        migrations.AddField(
            model_name='ofertaproveedor',
            name='miembro_taller_asignado',
            field=models.ForeignKey(
                blank=True,
                help_text='Técnico acordado para la oferta (preferido del cliente o propuesto por el proveedor)',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='ofertas_asignadas',
                to='usuarios.miembrotaller',
                verbose_name='Técnico asignado',
            ),
        ),
        migrations.AddField(
            model_name='ofertaproveedor',
            name='es_cambio_tecnico',
            field=models.BooleanField(
                default=False,
                help_text='True si el proveedor propuso un técnico distinto al preferido por el cliente.',
                verbose_name='Cambio de técnico',
            ),
        ),
    ]
