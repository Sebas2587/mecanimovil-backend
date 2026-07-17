from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('servicios', '0009_ofertaservicio_modelo_vehiculo_seleccionado'),
    ]

    operations = [
        migrations.AddField(
            model_name='categoriaservicio',
            name='imagen',
            field=models.ImageField(
                blank=True,
                help_text='Imagen del ícono (reemplaza el círculo con Lucide en la app)',
                null=True,
                upload_to='categorias/',
            ),
        ),
        migrations.AlterField(
            model_name='categoriaservicio',
            name='icono',
            field=models.CharField(
                blank=True,
                help_text='Nombre del ícono Lucide/legacy (fallback si no hay imagen)',
                max_length=50,
                null=True,
            ),
        ),
    ]
