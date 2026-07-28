from django.db import migrations


# ConsumoFeatureMensual se creó en 0008 con nombres explícitos de índice
# (suscripcion_proveed_6a1b2c_idx, suscripcion_taller__7d3e4f_idx), pero el
# modelo quedó sin `name=` en `Meta.indexes`. Eso hace que `makemigrations`
# proponga un RenameIndex fantasma hacia nombres autogenerados distintos, que
# falla con UndefinedTable si el índice legacy nunca existió con ese nombre.
RENAMES = [
    ('suscripcion_proveed_6a1b2c_idx', 'suscripcion_proveed_a41041_idx'),
    ('suscripcion_taller__7d3e4f_idx', 'suscripcion_taller__24d913_idx'),
]

CANONICAL_INDEXES = [
    (
        'suscripcion_proveed_a41041_idx',
        'CREATE INDEX IF NOT EXISTS suscripcion_proveed_a41041_idx '
        'ON suscripciones_consumofeaturemensual (proveedor_id, periodo)',
    ),
    (
        'suscripcion_taller__24d913_idx',
        'CREATE INDEX IF NOT EXISTS suscripcion_taller__24d913_idx '
        'ON suscripciones_consumofeaturemensual (taller_id, periodo)',
    ),
]

RENAME_SQL_TEMPLATE = """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind = 'i'
      AND n.nspname = 'public'
      AND c.relname = '{old_name}'
  ) AND NOT EXISTS (
    SELECT 1
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind = 'i'
      AND n.nspname = 'public'
      AND c.relname = '{new_name}'
  ) THEN
    ALTER INDEX "{old_name}" RENAME TO "{new_name}";
  END IF;
END $$;
"""


def _ensure_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        for old_name, new_name in RENAMES:
            cursor.execute(
                RENAME_SQL_TEMPLATE.format(old_name=old_name, new_name=new_name)
            )
        for _name, create_sql in CANONICAL_INDEXES:
            cursor.execute(create_sql)


def _noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('suscripciones', '0010_agente_ia_plan_descripcion'),
    ]

    operations = [
        migrations.RunPython(_ensure_indexes, _noop),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameIndex(
                    model_name='consumofeaturemensual',
                    old_name=old_name,
                    new_name=new_name,
                )
                for old_name, new_name in RENAMES
            ],
        ),
    ]
