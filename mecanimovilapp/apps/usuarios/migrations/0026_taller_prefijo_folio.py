from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0025_rename_usuarios_co_usuario_8a1f2d_idx_usuarios_co_usuario_c66b23_idx'),
    ]

    operations = [
        migrations.AddField(
            model_name='taller',
            name='prefijo_folio',
            field=models.CharField(
                blank=True,
                help_text='Sigla propia del taller para folios de cotización (ej. TR).',
                max_length=6,
                null=True,
                unique=True,
            ),
        ),
    ]
