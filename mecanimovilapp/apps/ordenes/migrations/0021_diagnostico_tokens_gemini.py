from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0020_diagnosticoasistidocitapersonal'),
    ]

    operations = [
        migrations.AddField(
            model_name='diagnosticoasistidoorden',
            name='modelo',
            field=models.CharField(blank=True, default='', max_length=80),
        ),
        migrations.AddField(
            model_name='diagnosticoasistidoorden',
            name='tokens_entrada',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='diagnosticoasistidoorden',
            name='tokens_salida',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='diagnosticoasistidoorden',
            name='tokens_total',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='diagnosticoasistidocitapersonal',
            name='modelo',
            field=models.CharField(blank=True, default='', max_length=80),
        ),
        migrations.AddField(
            model_name='diagnosticoasistidocitapersonal',
            name='tokens_entrada',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='diagnosticoasistidocitapersonal',
            name='tokens_salida',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='diagnosticoasistidocitapersonal',
            name='tokens_total',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
