from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0021_diagnostico_tokens_gemini'),
    ]

    operations = [
        migrations.AddField(
            model_name='citaagendapersonaldetalle',
            name='vehiculo_vin',
            field=models.CharField(blank=True, default='', max_length=30),
        ),
    ]
