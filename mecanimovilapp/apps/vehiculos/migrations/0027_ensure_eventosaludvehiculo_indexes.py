from django.db import migrations


# Los 3 índices de EventoSaludVehiculo se crearon con nombre explícito en la
# migración 0020 (evt_salud_*_idx). En algún momento el modelo quedó sin
# `name=` en `Meta.indexes`, lo que hace que Django recalcule un nombre
# autogenerado distinto (vehiculos_e_*_idx) cada vez que se corre
# `makemigrations`, generando una migración `RenameIndex` fantasma que falla
# con `UndefinedTable` en entornos donde el índice antiguo nunca existió con
# ese nombre exacto (o ya fue renombrado antes).
#
# Esta migración:
# 1. Renombra en la base de datos, de forma idempotente, cualquier índice
#    legacy que todavía tenga el nombre antiguo hacia el nombre canónico.
# 2. Actualiza el *state* de Django (SeparateDatabaseAndState) para que
#    coincida con `models_health.py`, evitando que vuelva a proponerse este
#    rename en futuros `makemigrations`.
RENAMES = [
    ('evt_salud_comp_tipo_idx', 'vehiculos_e_compone_d77ded_idx'),
    ('evt_salud_marca_modelo_idx', 'vehiculos_e_marca_fab556_idx'),
    ('evt_salud_tipo_fecha_idx', 'vehiculos_e_tipo_ev_bdef42_idx'),
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
        ('vehiculos', '0026_health_notif_tracking'),
    ]

    operations = [
        migrations.RunPython(_rename_legacy_indexes, _noop),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameIndex(
                    model_name='eventosaludvehiculo',
                    old_name=old_name,
                    new_name=new_name,
                )
                for old_name, new_name in RENAMES
            ],
        ),
    ]
