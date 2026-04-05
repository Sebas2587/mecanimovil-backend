from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('suscripciones', '0005_suscripcionproveedor_processed_charge_ids'),
    ]

    operations = [
        migrations.CreateModel(
            name='CobroSuscripcion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('charge_id', models.CharField(help_text='ID del authorized_payment en MP', max_length=50, verbose_name='Authorized Payment ID')),
                ('payment_id', models.CharField(help_text='ID del payment real en MP (/v1/payments/{id})', max_length=50, verbose_name='Payment ID')),
                ('status', models.CharField(max_length=30, verbose_name='Estado del cobro en MP')),
                ('status_detail', models.CharField(max_length=50, verbose_name='Detalle del estado')),
                ('transaction_amount', models.DecimalField(decimal_places=2, max_digits=12, verbose_name='Monto cobrado')),
                ('net_received_amount', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name='Monto neto recibido')),
                ('currency_id', models.CharField(default='CLP', max_length=5)),
                ('collector_id', models.BigIntegerField(help_text='Debe coincidir con la cuenta de Mecanimovil', verbose_name='ID de cuenta receptora')),
                ('payer_email', models.EmailField(blank=True, default='', max_length=254)),
                ('payer_id', models.CharField(blank=True, default='', max_length=50)),
                ('card_last_four', models.CharField(blank=True, default='', max_length=4)),
                ('payment_method', models.CharField(blank=True, default='', max_length=30)),
                ('date_approved', models.DateTimeField(blank=True, null=True, verbose_name='Fecha aprobación MP')),
                ('creditos_otorgados', models.IntegerField(default=0, verbose_name='Créditos otorgados')),
                ('fecha_registro', models.DateTimeField(auto_now_add=True)),
                ('suscripcion', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='cobros', to='suscripciones.suscripcionproveedor', verbose_name='Suscripción')),
            ],
            options={
                'verbose_name': 'Cobro de Suscripción',
                'verbose_name_plural': 'Cobros de Suscripción',
                'ordering': ['-date_approved'],
                'indexes': [
                    models.Index(fields=['charge_id'], name='suscripcion_charge__idx'),
                    models.Index(fields=['payment_id'], name='suscripcion_paymen_idx'),
                ],
                'unique_together': {('suscripcion', 'charge_id')},
            },
        ),
    ]
