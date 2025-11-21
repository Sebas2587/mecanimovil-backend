# Generated manually to fix carrito unique constraint - SQL DIRECT VERSION
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0020_remove_slotdisponibilidad_disponibilidad_and_more'),
    ]

    operations = [
        # Limpiar carritos duplicados con SQL directo
        migrations.RunSQL(
            sql="""
                -- Limpiar carritos duplicados antes de cambiar restricción
                WITH carritos_duplicados AS (
                    SELECT 
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY cliente_id, activo 
                            ORDER BY fecha_creacion DESC, id DESC
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
        
        # Eliminar restricción única existente de forma segura
        migrations.RunSQL(
            sql="""
                DO $$ 
                DECLARE
                    constraint_name TEXT;
                BEGIN
                    -- Buscar el nombre exacto de la restricción única
                    SELECT conname INTO constraint_name
                    FROM pg_constraint 
                    WHERE conrelid = 'ordenes_carritoagendamiento'::regclass
                    AND contype = 'u'
                    AND array_to_string(
                        ARRAY(
                            SELECT attname 
                            FROM pg_attribute 
                            WHERE attrelid = conrelid 
                            AND attnum = ANY(conkey)
                            ORDER BY attnum
                        ), 
                        ','
                    ) LIKE '%cliente_id%vehiculo_id%activo%';
                    
                    -- Eliminar la restricción si existe
                    IF constraint_name IS NOT NULL THEN
                        EXECUTE 'ALTER TABLE ordenes_carritoagendamiento DROP CONSTRAINT ' || constraint_name;
                    END IF;
                    
                EXCEPTION 
                    WHEN OTHERS THEN
                        -- Ignorar errores
                        NULL;
                END $$;
            """,
            reverse_sql=""
        ),
        
        # Crear nueva restricción única
        migrations.RunSQL(
            sql="""
                -- Crear nueva restricción única para cliente + activo
                ALTER TABLE ordenes_carritoagendamiento 
                ADD CONSTRAINT ordenes_carritoagendamiento_cliente_activo_unique 
                UNIQUE (cliente_id, activo);
            """,
            reverse_sql="""
                ALTER TABLE ordenes_carritoagendamiento 
                DROP CONSTRAINT IF EXISTS ordenes_carritoagendamiento_cliente_activo_unique;
            """
        ),
    ] 