# Generated manually for valoracion_mercado

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('valoracion_mercado', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='MercadoLibreOAuthToken',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('singleton_id', models.PositiveSmallIntegerField(default=1, editable=False, unique=True)),
                ('access_token', models.CharField(blank=True, default='', max_length=255)),
                ('refresh_token', models.CharField(blank=True, default='', max_length=255)),
                ('token_type', models.CharField(blank=True, default='', max_length=32)),
                ('scope', models.CharField(blank=True, default='', max_length=255)),
                ('ml_user_id', models.BigIntegerField(blank=True, null=True)),
                ('expires_at', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'token OAuth MercadoLibre',
                'verbose_name_plural': 'token OAuth MercadoLibre',
            },
        ),
    ]
