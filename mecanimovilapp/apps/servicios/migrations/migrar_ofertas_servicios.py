from django.db import migrations

def migrar_datos_precios(apps, schema_editor):
    """
    Esta migración fue diseñada para migrar datos de modelos antiguos.
    Los modelos originales ya no existen, y en una base de datos nueva
    no hay datos que migrar, así que esta función es un no-op.
    """
    # Los modelos OfertaServicio, PrecioServicioTaller, PrecioServicioMecanico
    # ya no existen en el esquema actual.
    # En producción (base de datos nueva), no hay datos que migrar.
    pass

def actualizar_lineas_servicio(apps, schema_editor):
    """
    Esta migración fue diseñada para actualizar líneas de servicio existentes.
    En una base de datos nueva no hay datos que actualizar.
    """
    # No hay datos que migrar en una base de datos nueva.
    pass

class Migration(migrations.Migration):
    """
    Migración de datos legacy - ahora es un no-op porque los modelos
    originales ya no existen y la base de datos de producción está vacía.
    """
    dependencies = [
        ('servicios', '0001_initial'),
        ('ordenes', '0001_initial'),
    ]
    
    operations = [
        migrations.RunPython(migrar_datos_precios, migrations.RunPython.noop),
        migrations.RunPython(actualizar_lineas_servicio, migrations.RunPython.noop),
    ]
