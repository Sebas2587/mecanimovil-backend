from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0018_miembrotaller_permisos'),
    ]

    operations = [
        migrations.AddField(
            model_name='miembrotaller',
            name='foto',
            field=models.ImageField(
                blank=True,
                help_text='Foto de perfil del mecánico (visible en la app de usuarios)',
                null=True,
                upload_to='equipo/mecanicos/',
            ),
        ),
    ]
