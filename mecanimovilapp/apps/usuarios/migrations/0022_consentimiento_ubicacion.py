from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0021_ley21719_privacy_models'),
    ]

    operations = [
        migrations.AlterField(
            model_name='consentimientousuario',
            name='tipo',
            field=models.CharField(
                choices=[
                    ('terminos', 'Términos de uso'),
                    ('privacidad', 'Política de privacidad'),
                    ('marketing', 'Comunicaciones comerciales'),
                    ('ubicacion', 'Geolocalización'),
                ],
                db_index=True,
                max_length=20,
            ),
        ),
    ]
