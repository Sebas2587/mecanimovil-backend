# Generated manually on 2025-05-27 to fix unique constraint issue

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0008_solicitudservicio_comprobante_validado'),
    ]

    operations = [
        # Primero eliminar la restricción única existente
        migrations.AlterUniqueTogether(
            name='carritoagendamiento',
            unique_together=set(),
        ),
        
        # Agregar una nueva restricción única solo para carritos activos
        # Esto se hace a nivel de base de datos con un índice parcial
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX ordenes_carritoagendamiento_cliente_vehiculo_activo_unique 
                ON ordenes_carritoagendamiento (cliente_id, vehiculo_id) 
                WHERE activo = true;
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS ordenes_carritoagendamiento_cliente_vehiculo_activo_unique;
            """
        ),
    ] 