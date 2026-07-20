from django.db import migrations


# Los índices de CobroSuscripcion se crearon con nombre explícito en 0006
# (suscripcion_charge__idx, suscripcion_paymen_idx), pero el modelo quedó sin
# `name=` en `Meta.indexes`, por lo que Django recalcula un nombre
# autogenerado distinto en cada `makemigrations`, proponiendo un
# `RenameIndex` fantasma que puede fallar con `UndefinedTable` si el índice
# legacy nunca existió con ese nombre exacto en algún entorno.
RENAMES = [
    ('suscripcion_charge__idx', 'suscripcion_charge__f5c1c7_idx'),
    ('suscripcion_paymen_idx', 'suscripcion_payment_6cf9a3_idx'),
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


def _rename_legacy_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        for old_name, new_name in RENAMES:
            cursor.execute(
                RENAME_SQL_TEMPLATE.format(old_name=old_name, new_name=new_name)
            )


def _noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('suscripciones', '0006_cobrosuscripcion'),
    ]

    operations = [
        migrations.RunPython(_rename_legacy_indexes, _noop),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameIndex(
                    model_name='cobrosuscripcion',
                    old_name=old_name,
                    new_name=new_name,
                )
                for old_name, new_name in RENAMES
            ],
        ),
    ]
