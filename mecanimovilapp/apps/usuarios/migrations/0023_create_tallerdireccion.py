# Generated manually on 2025-08-28

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0022_remove_direccion_field'),
    ]

    operations = [
        migrations.CreateModel(
            name='TallerDireccion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('calle', models.CharField(help_text='Nombre de la calle', max_length=255)),
                ('numero', models.CharField(help_text='Número de la casa/edificio', max_length=20)),
                ('comuna', models.CharField(help_text='Comuna', max_length=100)),
                ('ciudad', models.CharField(help_text='Ciudad', max_length=100)),
                ('region', models.CharField(help_text='Región', max_length=100)),
                ('codigo_postal', models.CharField(blank=True, help_text='Código postal', max_length=10, null=True)),
                ('detalles_adicionales', models.TextField(blank=True, help_text='Detalles adicionales de ubicación', null=True)),
                ('fecha_creacion', models.DateTimeField(auto_now_add=True)),
                ('fecha_actualizacion', models.DateTimeField(auto_now=True)),
                ('taller', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='direccion_fisica', to='usuarios.taller')),
            ],
            options={
                'verbose_name': 'dirección de taller',
                'verbose_name_plural': 'direcciones de talleres',
            },
        ),
    ]
