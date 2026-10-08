from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('omnichannel', '0004_token_expires_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='providerchannelconnection',
            name='alta_modo',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='providerchannelconnection',
            name='numero_solicitado',
            field=models.CharField(blank=True, default='', max_length=30),
        ),
        migrations.AddField(
            model_name='providerchannelconnection',
            name='registro_pin',
            field=models.CharField(blank=True, default='', max_length=6),
        ),
    ]
