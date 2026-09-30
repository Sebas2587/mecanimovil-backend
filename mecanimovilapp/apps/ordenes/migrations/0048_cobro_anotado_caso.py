from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0047_rol_casa_consulta_repuesto'),
    ]

    operations = [
        migrations.AddField(
            model_name='citaagendapersonal',
            name='cobro_estado',
            field=models.CharField(
                choices=[('pendiente', 'Pendiente'), ('anotado', 'Anotado')],
                default='pendiente',
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name='citaagendapersonal',
            name='cobro_medio',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
        migrations.AddField(
            model_name='citaagendapersonal',
            name='cobro_monto_clp',
            field=models.DecimalField(blank=True, decimal_places=0, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='citaagendapersonal',
            name='cobro_anotado_en',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='solicitudservicio',
            name='cobro_estado',
            field=models.CharField(
                choices=[('pendiente', 'Pendiente'), ('anotado', 'Anotado')],
                default='pendiente',
                help_text='Anotación del taller. No reemplaza el pago del marketplace.',
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name='solicitudservicio',
            name='cobro_medio',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
        migrations.AddField(
            model_name='solicitudservicio',
            name='cobro_monto_clp',
            field=models.DecimalField(blank=True, decimal_places=0, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='solicitudservicio',
            name='cobro_anotado_en',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
