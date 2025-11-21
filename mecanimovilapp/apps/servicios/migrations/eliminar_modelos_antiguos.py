from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [
        ('servicios', 'migrar_ofertas_servicios'),
    ]
    
    operations = [
        # Eliminar tablas intermedias con ForeignKeys a los modelos principales
        migrations.RemoveField(
            model_name='serviciotaller',
            name='servicio',
        ),
        migrations.RemoveField(
            model_name='serviciotaller',
            name='taller',
        ),
        migrations.RemoveField(
            model_name='serviciomecanico',
            name='mecanico',
        ),
        migrations.RemoveField(
            model_name='serviciomecanico',
            name='servicio',
        ),
        migrations.RemoveField(
            model_name='precioserviciotaller',
            name='servicio',
        ),
        migrations.RemoveField(
            model_name='precioserviciotaller',
            name='taller',
        ),
        migrations.RemoveField(
            model_name='precioserviciomecanico',
            name='mecanico',
        ),
        migrations.RemoveField(
            model_name='precioserviciomecanico',
            name='servicio',
        ),
        migrations.RemoveField(
            model_name='servicioasociado',
            name='servicio_asociado',
        ),
        migrations.RemoveField(
            model_name='servicioasociado',
            name='servicio_principal',
        ),
        migrations.RemoveField(
            model_name='serviciomarca',
            name='marca',
        ),
        migrations.RemoveField(
            model_name='serviciomarca',
            name='servicio',
        ),
        migrations.RemoveField(
            model_name='serviciocategoria',
            name='categoria',
        ),
        migrations.RemoveField(
            model_name='serviciocategoria',
            name='servicio',
        ),
        
        # Eliminar los modelos
        migrations.DeleteModel(
            name='ServicioTaller',
        ),
        migrations.DeleteModel(
            name='ServicioMecanico',
        ),
        migrations.DeleteModel(
            name='PrecioServicioTaller',
        ),
        migrations.DeleteModel(
            name='PrecioServicioMecanico',
        ),
        migrations.DeleteModel(
            name='ServicioAsociado',
        ),
        migrations.DeleteModel(
            name='ServicioMarca',
        ),
        migrations.DeleteModel(
            name='ServicioCategoria',
        ),
    ] 