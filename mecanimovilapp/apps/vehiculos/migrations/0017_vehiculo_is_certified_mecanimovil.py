from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0016_viajeregistrado'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehiculo',
            name='is_certified_mecanimovil',
            field=models.BooleanField(
                default=False,
                help_text='Se activa al completar inspección pre-compra',
                verbose_name='certificado MecaniMóvil',
            ),
        ),
    ]
