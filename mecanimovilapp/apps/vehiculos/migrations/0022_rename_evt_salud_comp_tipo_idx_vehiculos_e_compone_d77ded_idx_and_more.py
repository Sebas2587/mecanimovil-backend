from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0021_componentesaludvehiculo_historial_fuente'),
    ]

    operations = [
        # Render/Prod hotfix:
        # En algunos entornos existe una migración histórica que intenta renombrar un índice
        # legacy (`evt_salud_comp_tipo_idx`) y falla si ese índice nunca fue creado.
        #
        # Esta operación es idempotente:
        # - Si el índice antiguo existe y el nuevo NO existe → renombra.
        # - Si el índice antiguo NO existe → no hace nada.
        # - Si el nuevo ya existe → no hace nada.
        migrations.RunSQL(
            sql="""
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind = 'i'
      AND n.nspname = 'public'
      AND c.relname = 'evt_salud_comp_tipo_idx'
  ) AND NOT EXISTS (
    SELECT 1
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind = 'i'
      AND n.nspname = 'public'
      AND c.relname = 'vehiculos_e_compone_d77ded_idx'
  ) THEN
    ALTER INDEX evt_salud_comp_tipo_idx RENAME TO vehiculos_e_compone_d77ded_idx;
  END IF;
END $$;
""",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

