# Generated manually to fix carrito unique constraint - FINAL VERSION
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0020_remove_slotdisponibilidad_disponibilidad_and_more'),
    ]

    operations = [
        # Eliminar la restricción única problemática
        migrations.RunSQL(
            sql="""
                -- Eliminar restricción única existente que causa problemas
                ALTER TABLE ordenes_carritoagendamiento 
                DROP CONSTRAINT IF EXISTS ordenes_carritoagendamiento_cliente_activo_unique;
                
                -- Eliminar también cualquier restricción de unique_together anterior
                ALTER TABLE ordenes_carritoagendamiento 
                DROP CONSTRAINT IF EXISTS ordenes_carritoagendamiento_cliente_vehiculo_activo_unique;
                
                -- Eliminar índices únicos existentes
                DROP INDEX IF EXISTS ordenes_carritoagendamiento_cliente_vehiculo_activo_unique;
                DROP INDEX IF EXISTS ordenes_carritoagendamiento_cliente_activo_unique;
            """,
            reverse_sql=""
        ),
        
        # Crear nueva restricción única PARCIAL solo para carritos activos
        migrations.RunSQL(
            sql="""
                -- Crear índice único parcial: solo un carrito activo por cliente
                CREATE UNIQUE INDEX ordenes_carritoagendamiento_cliente_activo_unique_partial
                ON ordenes_carritoagendamiento (cliente_id) 
                WHERE activo = true;
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS ordenes_carritoagendamiento_cliente_activo_unique_partial;
            """
        ),
        
        # Limpiar carritos duplicados activos si los hay
        migrations.RunSQL(
            sql="""
                -- Limpiar carritos activos duplicados, conservando el más reciente
                WITH carritos_duplicados AS (
                    SELECT 
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY cliente_id 
                            ORDER BY fecha_actualizacion DESC, id DESC
                        ) as rn
                    FROM ordenes_carritoagendamiento 
                    WHERE activo = true
                )
                DELETE FROM ordenes_carritoagendamiento 
                WHERE id IN (
                    SELECT id FROM carritos_duplicados WHERE rn > 1
                );
            """,
            reverse_sql=""
        ),
    ] 