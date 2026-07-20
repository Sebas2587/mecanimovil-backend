from django.db import migrations


# CotizacionCanal, CotizacionCanalPlantilla y GuiaReparacionGuardada quedaron
# con índices sin `name=` explícito en `Meta.indexes`, mientras que la
# migración que los creó (0023/0024) sí les dio nombre. Eso hace que Django
# recalcule un nombre autogenerado distinto en cada `makemigrations` y
# proponga un `RenameIndex` fantasma que puede fallar con `UndefinedTable`
# si el índice legacy nunca existió con ese nombre exacto en algún entorno.
RENAMES = [
    ('cotizacioncanal', 'ordenes_cot_conv_est_idx', 'ordenes_cot_convers_fbf312_idx'),
    ('cotizacioncanal', 'ordenes_cot_taller_idx', 'ordenes_cot_taller__12b798_idx'),
    ('cotizacioncanalplantilla', 'ordenes_cot_pl_taller_idx', 'ordenes_cot_taller__2ff310_idx'),
    ('guiareparacionguardada', 'ordenes_gui_miembro_7a8b2c_idx', 'ordenes_gui_miembro_0ea153_idx'),
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
        for _model, old_name, new_name in RENAMES:
            cursor.execute(
                RENAME_SQL_TEMPLATE.format(old_name=old_name, new_name=new_name)
            )


def _noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0024_cotizacioncanal'),
    ]

    operations = [
        migrations.RunPython(_rename_legacy_indexes, _noop),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameIndex(
                    model_name=model_name,
                    old_name=old_name,
                    new_name=new_name,
                )
                for model_name, old_name, new_name in RENAMES
            ],
        ),
    ]
