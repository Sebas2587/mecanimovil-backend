from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('omnichannel', '0003_externalcontact_rol'),
    ]

    operations = [
        migrations.AddField(
            model_name='providerchannelconnection',
            name='token_expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='providerchannelconnection',
            name='token_no_expira',
            field=models.BooleanField(default=False),
        ),
    ]
