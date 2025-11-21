from django.db import migrations

def consolidate_especialidad_references(apps, schema_editor):
    """
    Este método se encarga de transferir cualquier dato de 'especialidad' a 'categoriaservicio'
    y actualizar las referencias en otros modelos.
    """
    # No necesitamos hacer nada aquí porque Especialidad ya era un alias de CategoriaServicio,
    # por lo que todos los datos ya estaban en el mismo modelo.
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('servicios', '0001_initial'),  # Ajustar esta dependencia según tu proyecto
    ]

    operations = [
        migrations.RunPython(consolidate_especialidad_references),
    ] 