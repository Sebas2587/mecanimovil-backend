from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0019_miembrotaller_foto'),
    ]

    operations = [
        migrations.AddField(
            model_name='webpushsubscription',
            name='app_origen',
            field=models.CharField(
                choices=[('usuario', 'App Usuarios'), ('proveedor', 'App Proveedores')],
                default='usuario',
                help_text='App desde la cual se registró la suscripción web',
                max_length=20,
            ),
        ),
    ]
