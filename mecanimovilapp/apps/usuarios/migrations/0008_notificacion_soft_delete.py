from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0007_resena_solicitud_resenafoto'),
    ]

    operations = [
        migrations.AddField(
            model_name='notificacion',
            name='eliminada',
            field=models.BooleanField(
                default=False,
                help_text='Soft-delete: el usuario la descartó; no se muestra pero evita que Celery la recree',
            ),
        ),
        migrations.AddField(
            model_name='notificacion',
            name='fecha_eliminada',
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text='Fecha en que el usuario la eliminó',
            ),
        ),
        migrations.AddIndex(
            model_name='notificacion',
            index=models.Index(
                fields=['usuario', 'eliminada'],
                name='usuarios_no_usuario_elimina_idx',
            ),
        ),
    ]
